"""Append unfiled content to regular playlists, using a private database copy.

The membership row format follows pyrekordbox 0.5.0's add_to_playlist and
registry counter handling. This is separate from grid/cue compatibility: only
local records on the supported macOS version are accepted. No audio or analysis
file is opened, moved, renamed or rewritten by this module.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

from . import cue_writer
from .backups import digest
from .guards import SafetyError, ensure_clean_database


@dataclass(frozen=True)
class PlaylistAddition:
    fingerprint: str
    tracks: tuple[tuple[str, str, str], ...]
    playlists: tuple[tuple[str, str], ...]


def schema_problem(db):
    required = {
        'djmdSongPlaylist': {'ID', 'PlaylistID', 'ContentID', 'TrackNo'} | cue_writer.STATS,
        'djmdPlaylist': {'ID', 'Name', 'Attribute', 'ParentID', 'Seq'} | cue_writer.STATS,
        'djmdContent': {'ID', 'Title', 'ArtistID', 'ServiceID', 'FolderPath'} | cue_writer.STATS,
        'djmdArtist': {'ID', 'Name'},
        'agentRegistry': {'registry_id', 'int_1'},
        'djmdProperty': {'DBVersion'},
    }
    for table, columns in required.items():
        actual = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
        if not columns <= actual:
            return f'Unsupported {table} schema; playlist additions are locked.'
    if [r[0] for r in db.execute('SELECT DBVersion FROM djmdProperty')] != ['6000']:
        return 'Unsupported database version; playlist additions are locked.'
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND lower(tbl_name) "
                  "IN ('djmdsongplaylist', 'agentregistry')").fetchone():
        return 'Unexpected database triggers; playlist additions are locked.'
    counter = db.execute("SELECT int_1 FROM agentRegistry WHERE registry_id='localUpdateCount'").fetchone()
    if counter is None or not isinstance(counter[0], int) or counter[0] < 0:
        return 'Missing update counter; playlist additions are locked.'
    return ''


def compatibility_problem(db):
    if cue_writer.installed_version() != cue_writer.TESTED_VERSION:
        return f'Playlist additions require Rekordbox {cue_writer.TESTED_VERSION} on macOS. Scanning remains available.'
    return schema_problem(db)


def _local(row):
    return not any(row[k] for k in ('rb_local_deleted', 'rb_local_synced', 'rb_data_status'))


def _validate_selection(db, track_ids, playlist_ids):
    if not track_ids or not playlist_ids or len(set(track_ids)) != len(track_ids) or len(set(playlist_ids)) != len(playlist_ids):
        raise SafetyError('Select unique tracks and at least one destination playlist.')
    tracks = []
    for identity in track_ids:
        row = db.execute('SELECT c.*, a.Name AS ArtistName FROM djmdContent c '
                         'LEFT JOIN djmdArtist a ON a.ID=c.ArtistID WHERE c.ID=?', (identity,)).fetchone()
        if row is None or not _local(row) or row['ServiceID'] not in (None, 0):
            raise SafetyError('A selected track is unavailable, deleted, streaming or cloud-synced. No changes applied.')
        if db.execute('SELECT 1 FROM djmdSongPlaylist s JOIN djmdPlaylist p ON p.ID=s.PlaylistID '
                      'WHERE s.ContentID=? AND COALESCE(s.rb_local_deleted,0)=0 '
                      'AND COALESCE(p.rb_local_deleted,0)=0 AND COALESCE(p.Attribute,0)=0 LIMIT 1', (identity,)).fetchone():
            raise SafetyError('A selected track already belongs to a regular playlist. Scan the library again.')
        tracks.append((identity, row['Title'] or 'Untitled track', row['ArtistName'] or 'Unknown artist'))
    for identity in playlist_ids:
        row = db.execute('SELECT * FROM djmdPlaylist WHERE ID=?', (identity,)).fetchone()
        if row is None or row['Attribute'] != 0 or not _local(row):
            raise SafetyError('Choose active local regular playlists; folders, smart and cloud-synced playlists cannot be edited.')
        rows = db.execute('SELECT * FROM djmdSongPlaylist WHERE PlaylistID=?', (identity,)).fetchall()
        if any(r['rb_local_synced'] or r['rb_data_status'] for r in rows):
            raise SafetyError('Cloud-synced playlist entries are not supported.')
        active = [r['TrackNo'] for r in rows if not r['rb_local_deleted']]
        if any(not isinstance(n, int) or n < 1 for n in active) or len(set(active)) != len(active):
            raise SafetyError('The destination playlist has inconsistent track order. Repair it in Rekordbox first.')
    return tuple(tracks)


def plan_additions(library, track_ids, playlist_ids, fingerprint):
    ensure_clean_database(library.path)
    if not fingerprint or fingerprint != library.fingerprint or digest(library.path) != fingerprint:
        raise SafetyError('Library changed since the scan. Reconnect and scan again.')
    track_ids, playlist_ids = tuple(track_ids), tuple(playlist_ids)
    with library.connect() as db:
        problem = compatibility_problem(db)
        if problem:
            raise SafetyError(problem)
        tracks = _validate_selection(db, track_ids, playlist_ids)
    if digest(library.path) != fingerprint:
        raise SafetyError('Library changed while preparing the playlist additions. Reconnect and scan again.')
    return PlaylistAddition(fingerprint, tracks, tuple((key, library.playlists[key]) for key in playlist_ids))


def write_staged(path, plan):
    """Append only; existing membership rows and every content row stay intact."""
    with cue_writer.staged_connection(path) as db:
        problem = schema_problem(db)
        if problem:
            raise SafetyError(problem)
        track_ids = tuple(t[0] for t in plan.tracks)
        playlist_ids = tuple(p[0] for p in plan.playlists)
        if _validate_selection(db, track_ids, playlist_ids) != plan.tracks:
            raise SafetyError('Selected track details changed. Review the additions again.')
        journal = db.execute('PRAGMA journal_mode').fetchone()[0]
        db.execute('PRAGMA journal_mode=DELETE').fetchall()
        db.execute('PRAGMA synchronous=FULL')
        counter = db.execute("SELECT int_1 FROM agentRegistry WHERE registry_id='localUpdateCount'").fetchone()[0]
        before = {r['ID']: dict(r) for r in db.execute('SELECT * FROM djmdSongPlaylist')}
        expected = {}
        now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('T', ' ').replace('+00:00', ' +00:00')
        try:
            db.execute('BEGIN IMMEDIATE')
            for playlist_id in playlist_ids:
                # Include tombstones when choosing the append position; never reuse or reorder them.
                numbers = [r['TrackNo'] for r in before.values() if r['PlaylistID'] == playlist_id]
                position = max([0] + [n for n in numbers if isinstance(n, int)])
                for track_id in track_ids:
                    counter += 1
                    position += 1
                    identity = str(uuid4())
                    values = dict(ID=identity, PlaylistID=playlist_id, ContentID=track_id,
                                  TrackNo=position, UUID=str(uuid4()), rb_local_usn=counter,
                                  rb_data_status=0, rb_local_data_status=0, rb_local_deleted=0,
                                  rb_local_synced=0, created_at=now, updated_at=now)
                    cue_writer.insert_row(db, 'djmdSongPlaylist', values)
                    expected[identity] = values
            db.execute("UPDATE agentRegistry SET int_1=? WHERE registry_id='localUpdateCount'", (counter,))
            after = {r['ID']: dict(r) for r in db.execute('SELECT * FROM djmdSongPlaylist')}
            if (set(after) != set(before) | set(expected) or any(after[k] != v for k, v in before.items())
                    or any(any(after[k][field] != value for field, value in values.items()) for k, values in expected.items())):
                raise SafetyError('Playlist read-back differs from the reviewed additions.')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SafetyError('Staged database integrity check failed.')
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            if journal == 'wal':
                db.execute('PRAGMA journal_mode=WAL').fetchall()


def apply_additions(library, plan, backups):
    if backups is None:
        raise SafetyError('A verified backup is required for playlist additions.')

    def guard():
        ensure_clean_database(library.path)
        with library.connect() as db:
            problem = compatibility_problem(db)
            if problem:
                raise SafetyError(problem)

    guard()
    if library.fingerprint != plan.fingerprint or digest(library.path) != plan.fingerprint:
        raise SafetyError('Library changed since the scan. Reconnect and scan again.')
    with tempfile.TemporaryDirectory(prefix='rekordbox-playlist-stage-') as temp:
        staged = Path(temp) / library.path.name
        shutil.copy2(library.path, staged)
        if digest(staged) != plan.fingerprint:
            raise SafetyError('Library changed while staging. Reconnect and scan again.')
        write_staged(staged, plan)
        ensure_clean_database(staged)
        installed_hash = digest(staged)

        def verify():
            guard()
            if digest(library.path) != installed_hash:
                raise SafetyError('Installed database differs from the validated playlist additions.')
            with library.connect() as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise SafetyError('Installed database integrity check failed.')

        backup = backups.install(library.root, {library.path.name: staged},
                                 {library.path.name: plan.fingerprint}, guard, verify,
                                 f'Organiser: {len(plan.tracks)} track(s) added to {len(plan.playlists)} playlist(s)')
    # Only membership rows changed. Retain loaded cue/grid baselines and audio stamps.
    library.fingerprint = installed_hash
    library.fingerprints[library.path.name] = installed_hash
    return backup
