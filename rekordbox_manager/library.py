"""Read-only connections; staged installation for grids and memory cues."""
from __future__ import annotations

import struct
import sqlite3
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .models import Cue, Grid, Track
from .playlist_structure import ordered_playlist_nodes
from .guards import SafetyError, ensure_clean_database
from .backups import digest
from .cue_writer import compatibility_problem, write_staged


def read_grid(path: Path) -> Grid:
    data = path.read_bytes()
    if len(data) < 28 or data[:4] != b"PMAI":
        raise ValueError("Unrecognised analysis file.")
    offset, total = struct.unpack_from(">II", data, 4)
    if total != len(data) or not 28 <= offset <= total:
        raise ValueError("Invalid analysis file length.")
    while offset < total:
        if offset + 12 > total:
            raise ValueError("Truncated analysis tag.")
        tag, header, length = struct.unpack_from(">4sII", data, offset)
        if not 12 <= header <= length or offset + length > total:
            raise ValueError("Invalid analysis tag length.")
        if tag == b"PQTZ":
            if header != 24:
                raise ValueError("Unsupported beat-grid tag version.")
            count = struct.unpack_from(">I", data, offset + 20)[0]
            if 24 + count * 8 != length:
                raise ValueError("Invalid beat-grid entry count.")
            entries = [struct.unpack_from(">HHI", data, offset + 24 + i * 8) for i in range(count)]
            grid = Grid([e[2] / 1000 for e in entries], [e[0] for e in entries])
            grid.validate()
            return grid
        offset += length
    raise ValueError("No analysed beat grid found.")


class RekordboxLibrary:
    writable = False
    demo = False
    write_reason = "Direct updates are locked in this preview. Compatibility must be verified on the target Rekordbox installation first."

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.root = self.path.parent
        ensure_clean_database(self.path)
        self.fingerprint = digest(self.path)
        self.fingerprints = {self.path.name: self.fingerprint}
        self.audio_stamps = {}
        self.loaded_ids = set()
        self.name = "Rekordbox library · read-only preview"
        self.playlists: dict[str, str] = {}
        self.playlist_paths: dict[str, tuple[tuple[str, str], ...]] = {}
        with self.connect() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"djmdContent", "djmdPlaylist", "djmdSongPlaylist", "djmdCue"} <= tables:
                raise ValueError("This is not a supported Rekordbox 6/7 master library.")
            self.write_reason = compatibility_problem(db)
            self.writable = not self.write_reason
            if self.writable:
                self.name = "Rekordbox library · memory cue import"
                self.write_reason = "Grid and memory cue import enabled. Constant-tempo local MP3/WAV only; existing hot cues and saved loops are preserved."
            rows = [dict(r) for r in db.execute("SELECT ID, Name, ParentID, Attribute, Seq FROM djmdPlaylist ORDER BY Seq")]
            self.playlist_nodes = ordered_playlist_nodes(rows)
            paths = {}
            for node in self.playlist_nodes:
                parts = paths.get(node.parent_id, ()) + ((node.identity, node.name),)
                paths[node.identity] = parts
                # Smart playlists require their rule engine; display them in the
                # browser, but never pretend they are empty regular playlists.
                if node.attribute == 0:
                    self.playlist_paths[node.identity] = parts
                    self.playlists[node.identity] = " / ".join(name for _, name in parts)

    @contextmanager
    def connect(self):
        ensure_clean_database(self.path)
        # immutable prevents sidecar creation; only used after refusing outstanding journals.
        uri = self.path.as_uri() + "?mode=ro&immutable=1"
        with self.path.open("rb") as f:
            plain = f.read(16) == b"SQLite format 3\0"
        if plain:
            db = sqlite3.connect(uri, uri=True)
        else:
            from sqlcipher3 import dbapi2 as cipher
            from pyrekordbox.masterdb.database import BLOB
            from pyrekordbox.utils import deobfuscate
            db = cipher.connect(uri, uri=True)
            key = deobfuscate(BLOB).replace("'", "''")
            db.execute("PRAGMA key='" + key + "'")
        if plain:
            db.row_factory = sqlite3.Row
        else:
            db.row_factory = cipher.Row
        db.execute("PRAGMA query_only=ON")
        try:
            yield db
        finally:
            db.close()

    def tracks(self, playlist: str) -> list[Track]:
        query = """SELECT c.*, a.Name AS ArtistName, g.Name AS GenreName
            FROM djmdSongPlaylist s JOIN djmdContent c ON c.ID=s.ContentID
            LEFT JOIN djmdArtist a ON a.ID=c.ArtistID
            LEFT JOIN djmdGenre g ON g.ID=c.GenreID
            WHERE s.PlaylistID=? ORDER BY s.TrackNo"""
        return self._read_tracks(query, (playlist,))

    def tracks_by_ids(self, identities):
        if not identities:
            return []
        query = """SELECT c.*, a.Name AS ArtistName, g.Name AS GenreName
            FROM djmdContent c LEFT JOIN djmdArtist a ON a.ID=c.ArtistID
            LEFT JOIN djmdGenre g ON g.ID=c.GenreID WHERE c.ID IN ("""
        query += ','.join('?' for _ in identities) + ') ORDER BY c.ID'
        return self._read_tracks(query, tuple(identities))

    def _read_tracks(self, query, parameters):
        result = []
        with self.connect() as db:
            seen = set()
            for row in db.execute(query, parameters):
                r = dict(row)
                identity = str(r["ID"])
                if identity in seen:
                    continue
                seen.add(identity)
                issues, paths, grid = [], [], Grid([], [])
                rel = str(r.get("AnalysisDataPath") or "").replace("\\", "/").lstrip("/")
                if rel:
                    dat = (self.root / "share" / rel).resolve()
                    if dat.is_relative_to((self.root / "share").resolve()) and dat.is_file():
                        paths = [p for p in dat.parent.iterdir() if p.suffix.upper() in {".DAT", ".EXT", ".2EX", ".3EX"}]
                        for path in paths:
                            self.fingerprints[str(path.relative_to(self.root))] = digest(path)
                        try:
                            grid = read_grid(dat)
                        except ValueError as exc:
                            issues.append(str(exc))
                    else:
                        issues.append("Analysis files are missing or outside the library's share folder.")
                else:
                    issues.append("Track has no analysis file.")
                cues = []
                for cue in db.execute("SELECT * FROM djmdCue WHERE ContentID=?", (identity,)):
                    c = dict(cue)
                    start = max(0, c.get("InMsec") or 0) / 1000
                    out = c.get("OutMsec")
                    end = out / 1000 if out is not None and 0 < out < 0xFFFFFF00 and out / 1000 > start else None
                    kind = "memory" if c.get("Kind") == 0 else "hot"
                    if end is not None:
                        kind += "_loop"
                    cues.append(Cue(start, c.get("Comment") or kind.replace("_", " ").title(), kind, end))
                audio = Path(r.get("FolderPath") or "")
                if not audio.is_file():
                    issues.append("Local audio file is missing or unavailable.")
                else:
                    stat = audio.stat()
                    self.audio_stamps[str(audio)] = (stat.st_size, stat.st_mtime_ns)
                self.loaded_ids.add(identity)
                result.append(Track(identity, r.get("Title") or audio.stem, r.get("ArtistName") or "Unknown artist",
                                    r.get("GenreName") or "", audio, float(r.get("Length") or 0),
                                    float(r.get("BPM") or 0) / 100, grid, cues, paths, issues))
        if digest(self.path) != self.fingerprint:
            raise SafetyError("Library changed while reading. Close Rekordbox and reload.")
        return result

    def apply(self, proposals, backups=None):
        if not self.writable:
            raise SafetyError(self.write_reason)
        if backups is None or not proposals:
            raise SafetyError("A verified backup and at least one track are required.")
        if any(p.track.id not in self.loaded_ids for p in proposals):
            raise SafetyError("Reload and analyse the selected playlist before importing cues.")
        def guard():
            ensure_clean_database(self.path)
            with self.connect() as db:
                problem = compatibility_problem(db)
                if problem:
                    raise SafetyError(problem)
            for p in proposals:
                stat = p.track.path.stat()
                if self.audio_stamps.get(str(p.track.path)) != (stat.st_size, stat.st_mtime_ns):
                    raise SafetyError("Audio changed since analysis. Reload the playlist.")
        guard()
        with tempfile.TemporaryDirectory(prefix="rekordbox-cue-stage-") as temp:
            staged = Path(temp) / self.path.name
            shutil.copy2(self.path, staged)
            if digest(staged) != self.fingerprint:
                raise SafetyError("Library changed since loading. Reload and analyse again.")
            from .grid_writer import stage_grid
            replacements = {}
            grid_updates = {}
            for p in proposals:
                if p.options.fix_grid:
                    if not p.can_apply:
                        raise SafetyError("Review the grid and rebuild cues before importing.")
                    with self.connect() as db:
                        rows = db.execute('SELECT ID FROM djmdContent WHERE AnalysisDataPath = '
                                          '(SELECT AnalysisDataPath FROM djmdContent WHERE ID=?)', (p.track.id,)).fetchall()
                        if len(rows) != 1:
                            raise SafetyError("Shared analysis files are not supported for grid writing.")
                    changes, bpm = stage_grid(p, self.root, Path(temp))
                    if set(changes) & set(replacements):
                        raise SafetyError("Multiple tracks reference the same analysis files.")
                    replacements.update(changes)
                    grid_updates[p.track.id] = bpm
            write_staged(staged, proposals, grid_updates=grid_updates)
            ensure_clean_database(staged)
            replacements[self.path.name] = staged
            expected_hashes = {name: digest(path) for name, path in replacements.items()}
            def verify():
                guard()
                if any(digest(self.root / name) != sha for name, sha in expected_hashes.items()):
                    raise SafetyError("Installed files do not match the verified staged copies.")
                with self.connect() as db:
                    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise SafetyError("Installed database failed its integrity check.")
            backup = backups.install(self.root, replacements, self.fingerprints,
                                     guard, verify, f"Rekordbox grids/cues: {len(proposals)} track(s)")
        self.reload()
        return backup

    def reload(self):
        self.__init__(self.path)

    def restore(self, backups, folder):
        # Restoration only replaces files produced by this adapter. It does not
        # depend on the installed app version, so recovery survives an upgrade.
        allowed = {self.path.name, "masterPlaylists6.xml"}
        with self.connect() as db:
            for row in db.execute('SELECT AnalysisDataPath FROM djmdContent'):
                relative = str(row[0] or '').replace('\\', '/').lstrip('/')
                dat = (self.root / 'share' / relative).resolve()
                if relative and dat.is_relative_to(self.root / 'share') and dat.suffix.upper() == '.DAT' and dat.parent.is_dir():
                    allowed.update(str(p.relative_to(self.root)) for p in dat.parent.iterdir()
                                   if p.is_file() and p.suffix.upper() in {'.DAT', '.EXT', '.2EX', '.3EX'})
        backups.restore(folder, self.root, lambda: ensure_clean_database(self.path), allowed)
        self.reload()
