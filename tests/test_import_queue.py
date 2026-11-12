from dataclasses import replace
from contextlib import closing
import sqlite3

import pytest

from rekordbox_manager.cue_writer import insert_row
from rekordbox_manager.guards import SafetyError
from rekordbox_manager.import_queue import ImportQueue, import_snapshot
from rekordbox_manager.models import Cue, Options, Proposal
from test_cue_writer import fixture_library, rows, supported_install


def five_playlists(tmp_path):
    lib, original, backups = fixture_library(tmp_path)
    stamp = '2026-01-01 00:00:00.000 +00:00'
    with closing(sqlite3.connect(lib.path)) as db, db:
        for i in range(2, 6):
            insert_row(db, 'djmdPlaylist', dict(ID=f'p{i}', Name=f'Playlist {i}', Attribute=0, Seq=i,
                       ParentID='p', created_at=stamp, updated_at=stamp))
            insert_row(db, 'djmdSongPlaylist', dict(ID=f'song{i}', PlaylistID=f'p{i}',
                       ContentID='t' if i < 5 else 'unrelated', TrackNo=7,
                       created_at=stamp, updated_at=stamp))
    lib.reload()
    queue = ImportQueue()
    for playlist in lib.playlists:
        tracks = lib.tracks(playlist)
        proposals = [Proposal(t, Options(False, True), t.grid,
                    t.cues + [Cue(10, 'DROP 1'), Cue(20, 'DROP 2')], 10, 20) for t in tracks]
        queue.capture(lib, proposals, {playlist: (lib.playlists[playlist], frozenset(t.id for t in tracks))})
    return lib, queue, backups


def test_five_playlists_deduplicate_and_keep_all_membership_and_order(tmp_path):
    lib, queue, backups = five_playlists(tmp_path)
    playlists_before = rows(lib, 'djmdPlaylist')
    members_before = rows(lib, 'djmdSongPlaylist')
    ids_before = [r['ID'] for r in rows(lib, 'djmdContent')]
    assert len(queue.ready()) == 2
    assert set(queue.entries['t'].sources) == {'p','p2','p3','p4'}
    assert len(queue.breakdown()) == 5
    queue.validate(lib)
    confirmed = [replace(import_snapshot(e.proposal), reviewed=True) for e in queue.ready()]
    lib.apply(confirmed, backups)
    queue.complete([p.track.id for p in confirmed], lib)
    assert not queue.pending()
    assert rows(lib, 'djmdPlaylist') == playlists_before
    assert rows(lib, 'djmdSongPlaylist') == members_before
    assert [r['ID'] for r in rows(lib, 'djmdContent')] == ids_before
    for playlist in lib.playlists:
        assert any(c.label == 'DROP 1' for c in lib.tracks(playlist)[0].cues)
    assert len(backups.list()) == 1


def test_pending_tracks_can_be_imported_after_earlier_batch_reloads_adapter(tmp_path):
    lib, queue, backups = five_playlists(tmp_path)
    pending = queue.entries['unrelated'].proposal
    pending.cues_dirty = True
    ready = [replace(e.proposal, reviewed=True) for e in queue.ready()]
    queue.validate(lib)
    lib.apply(ready, backups)
    queue.complete([p.track.id for p in ready], lib)
    assert [e.proposal.track.id for e in queue.pending()] == ['unrelated']
    pending.cues_dirty = False
    queue.validate(lib)
    lib.tracks_by_ids(['unrelated'])
    queue.validate(lib)
    lib.apply([replace(pending, reviewed=True)], backups)
    queue.complete(['unrelated'], lib)
    assert not queue.ready() and len(backups.list()) == 2


@pytest.mark.parametrize('change', ['audio', 'analysis', 'database'])
def test_queue_keeps_original_baselines_even_after_browsing(tmp_path, change):
    lib, queue, backups = five_playlists(tmp_path)
    entry = queue.entries['t']
    if change == 'audio':
        entry.audio_path.write_bytes(b'changed audio')
        lib.tracks('p')  # Re-reading must not bless the old preparation.
    elif change == 'analysis':
        path = next(iter(entry.analysis_hashes))
        path.write_bytes(path.read_bytes() + b'changed')
        lib.tracks('p')
    else:
        with closing(sqlite3.connect(lib.path)) as db, db:
            db.execute("UPDATE djmdContent SET Title='Changed'")
    with pytest.raises(SafetyError, match='changed'):
        queue.validate(lib)
    assert not backups.list()


def test_reprepare_replaces_shared_track_without_duplicate_or_lost_sources(tmp_path):
    lib, queue, _ = five_playlists(tmp_path)
    original = queue.entries['t'].proposal
    updated = replace(original, cues=original.cues + [Cue(30, 'Later edit')])
    queue.forget(['t'])
    queue.capture(lib, [updated], {'p2': ('Playlist 2', frozenset(['t']))})
    assert len(queue.ready()) == 2
    assert queue.entries['t'].proposal is updated
    assert set(queue.entries['t'].sources) == {'p','p2','p3','p4'}
    updated.cues_dirty = True
    assert [e.proposal.track.id for e in queue.ready()] == ['unrelated']


def test_queue_rejects_wrong_library_identity_and_invalid_scope(tmp_path):
    lib, queue, _ = five_playlists(tmp_path)
    with pytest.raises(SafetyError, match='connected library'):
        queue.validate(object())
    proposal = queue.entries['t'].proposal
    with pytest.raises(SafetyError, match='scanned playlists'):
        queue.capture(lib, [proposal, proposal], {'p': ('Test', frozenset(['t']))})
    proposal.track = replace(proposal.track, id='unrelated')
    with pytest.raises(SafetyError, match='identity changed'):
        queue.validate(lib)


@pytest.mark.parametrize('encrypted', [False, True])
def test_shared_track_grid_and_cue_import_keeps_playlist_structure(tmp_path, encrypted):
    from rekordbox_manager.cue_writer import staged_connection
    from test_grid_writer import prepared
    lib, proposal, backups = prepared(tmp_path, encrypted)
    stamp = '2026-01-01 00:00:00.000 +00:00'
    with staged_connection(lib.path) as db:
        for i in range(2, 6):
            insert_row(db, 'djmdPlaylist', dict(ID=f'p{i}', Name=f'Playlist {i}', Attribute=0, Seq=i,
                       created_at=stamp, updated_at=stamp))
            insert_row(db, 'djmdSongPlaylist', dict(ID=f'm{i}', PlaylistID=f'p{i}', ContentID='t',
                       TrackNo=i, created_at=stamp, updated_at=stamp))
        db.commit()
    lib.reload()
    queue = ImportQueue()
    for playlist in lib.playlists:
        track = lib.tracks(playlist)[0]
        queue.capture(lib, [replace(proposal, track=track)], {playlist: (playlist, frozenset(['t']))})
    before = {table: rows(lib, table) for table in ('djmdPlaylist', 'djmdSongPlaylist')}
    queue.validate(lib)
    assert len(queue.ready()) == 1
    lib.apply([entry.proposal for entry in queue.ready()], backups)
    queue.complete(['t'], lib)
    assert {table: rows(lib, table) for table in before} == before
    for playlist in lib.playlists:
        saved = lib.tracks(playlist)[0]
        assert saved.grid == proposal.grid and any(c.label == 'DROP 1' for c in saved.cues)
    assert len(backups.list()) == 1
