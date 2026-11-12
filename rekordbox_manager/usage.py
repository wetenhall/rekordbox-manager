"""Lightweight, read-only usage metadata; never load audio or analysis files."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .backups import digest
from .guards import SafetyError, ensure_clean_database


@dataclass(frozen=True)
class TrackUsage:
    id: str
    title: str
    artist: str
    genre: str
    path: str
    plays: int | None
    history_entries: int | None
    playlists: int | None
    playlist_ids: tuple[str, ...] = ()

    @property
    def play_status(self):
        if (self.plays or 0) > 0 or (self.history_entries or 0) > 0:
            return "Played"
        return "No recorded plays" if self.plays == 0 else "Unknown"


@dataclass(frozen=True)
class UsageScan:
    tracks: tuple[TrackUsage, ...]
    notes: tuple[str, ...]
    scanned_at: str
    fingerprint: str = ''


def play_count(value):
    # NULL, negative and malformed values are not evidence of zero plays.
    text = str(value).strip()
    return int(text) if text.isascii() and text.isdecimal() else None


def scan_usage(library, cancelled=lambda: False):
    if cancelled():
        raise InterruptedError("Scan cancelled.")
    before = digest(library.path)
    if before != library.fingerprint:
        raise SafetyError("Library changed since connecting. Reconnect it in Settings before scanning.")
    notes = []
    with library.connect() as db:
        db.set_progress_handler(lambda: int(cancelled()), 1000)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        def columns(table):
            return {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')} if table in tables else set()

        def active(alias, cols):
            return f'COALESCE({alias}.rb_local_deleted, 0)=0' if 'rb_local_deleted' in cols else '1=1'

        content = columns('djmdContent')
        song_history, history = columns('djmdSongHistory'), columns('djmdHistory')
        songs, playlists = columns('djmdSongPlaylist'), columns('djmdPlaylist')
        history_counts = None
        if {'ContentID', 'HistoryID'} <= song_history and 'ID' in history:
            history_counts = dict(db.execute(f"""SELECT s.ContentID, COUNT(*)
                FROM djmdSongHistory s JOIN djmdHistory h ON h.ID=s.HistoryID
                WHERE {active('s', song_history)} AND {active('h', history)} GROUP BY s.ContentID"""))
        else:
            notes.append("Saved history is unavailable; play status uses the recorded play count only.")
        playlist_counts = None
        memberships = {}
        if {'ContentID', 'PlaylistID'} <= songs and {'ID', 'Attribute'} <= playlists:
            membership_rows = db.execute(f"""SELECT DISTINCT s.ContentID, s.PlaylistID
                FROM djmdSongPlaylist s JOIN djmdPlaylist p ON p.ID=s.PlaylistID
                WHERE COALESCE(p.Attribute, 0)=0 AND {active('s', songs)} AND {active('p', playlists)}
                """)
            for content_id, playlist_id in membership_rows:
                memberships.setdefault(content_id, []).append(str(playlist_id))
            playlist_counts = {identity: len(ids) for identity, ids in memberships.items()}
        else:
            notes.append("Regular-playlist membership is unavailable in this database.")
        if 'DJPlayCount' not in content:
            notes.append("Play counts are unavailable; tracks without history are marked unknown.")
        tracks = []
        try:
            query = f"""SELECT c.*, a.Name AS ArtistName, g.Name AS GenreName FROM djmdContent c
                LEFT JOIN djmdArtist a ON a.ID=c.ArtistID LEFT JOIN djmdGenre g ON g.ID=c.GenreID
                WHERE {active('c', content)}"""
            for row in db.execute(query):
                if cancelled():
                    raise InterruptedError("Scan cancelled.")
                r = dict(row)
                identity = r['ID']
                tracks.append(TrackUsage(str(identity), r.get('Title') or 'Untitled track',
                    r.get('ArtistName') or 'Unknown artist', r.get('GenreName') or '', r.get('FolderPath') or '',
                    play_count(r.get('DJPlayCount')),
                    history_counts.get(identity, 0) if history_counts is not None else None,
                    playlist_counts.get(identity, 0) if playlist_counts is not None else None,
                    tuple(memberships.get(identity, ()))))
        finally:
            db.set_progress_handler(None, 0)
    if cancelled():
        raise InterruptedError("Scan cancelled.")
    ensure_clean_database(library.path)
    if digest(library.path) != before:
        raise SafetyError("Library changed during the scan. Reconnect it in Settings and scan again.")
    return UsageScan(tuple(tracks), tuple(notes), datetime.now().astimezone().strftime('%d %b %Y, %H:%M:%S %Z'), before)
