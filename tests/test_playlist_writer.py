import sqlite3
from dataclasses import replace

import pytest

from rekordbox_manager.backups import digest
from rekordbox_manager.cue_writer import insert_row, staged_connection
from rekordbox_manager.guards import SafetyError
from rekordbox_manager.playlist_writer import plan_additions, apply_additions
from rekordbox_manager.usage import scan_usage
from test_cue_writer import fixture_library, rows, supported_install


def plan(lib, tracks=('unrelated',), playlists=('p',)):
    return plan_additions(lib, tracks, playlists, scan_usage(lib).fingerprint)


def edit(lib, statement, values=()):
    with staged_connection(lib.path) as db:
        db.execute(statement, values)
        db.commit()
    lib.reload()


@pytest.mark.parametrize('encrypted', [False, True])
def test_add_unfiled_preserves_all_other_tables_files_order_and_restores(tmp_path, encrypted):
    lib, proposal, backups = fixture_library(tmp_path, encrypted)
    with staged_connection(lib.path) as db:
        row = dict(db.execute('SELECT * FROM djmdPlaylist').fetchone())
        row.update(ID='p2', Name='Second')
        insert_row(db, 'djmdPlaylist', row)
        db.execute('UPDATE djmdSongPlaylist SET TrackNo=7')
        db.commit()
    lib.reload()
    before = digest(lib.path)
    audio = digest(proposal.track.path)
    analysis = {p: digest(p) for p in proposal.track.analysis_paths}
    with lib.connect() as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if r[0] not in ('djmdSongPlaylist', 'agentRegistry')]
    originals = {table: rows(lib, table) for table in tables}
    old_memberships = rows(lib, 'djmdSongPlaylist')
    addition = plan(lib, playlists=('p', 'p2'))
    backup = apply_additions(lib, addition, backups)
    assert {table: rows(lib, table) for table in tables} == originals
    memberships = rows(lib, 'djmdSongPlaylist')
    assert all(row in memberships for row in old_memberships)
    added = [r for r in memberships if r['ContentID'] == 'unrelated']
    assert {(r['PlaylistID'], r['TrackNo']) for r in added} == {('p', 8), ('p2', 1)}
    assert {r['rb_local_usn'] for r in added} == {21, 22}
    assert rows(lib, 'agentRegistry')[0]['int_1'] == 22
    assert next(t.playlists for t in scan_usage(lib).tracks if t.id == 'unrelated') == 2
    assert digest(proposal.track.path) == audio
    assert all(digest(p) == sha for p, sha in analysis.items())
    assert (lib.path.read_bytes()[:16] != b'SQLite format 3\0') == encrypted
    assert [r['path'] for r in backups.validate(backup, lib.root)['files']] == ['master.db']
    assert lib.fingerprint == digest(lib.path)
    lib.restore(backups, backup)
    assert digest(lib.path) == before


@pytest.mark.parametrize('change', ['filed', 'missing', 'duplicate', 'empty', 'deleted', 'streaming', 'synced',
                                  'smart', 'folder', 'deleted_playlist', 'synced_playlist', 'bad_order', 'trigger'])
def test_invalid_selection_never_writes_source(tmp_path, change):
    lib, _, backups = fixture_library(tmp_path)
    tracks = ('unrelated',)
    if change == 'filed': tracks = ('t',)
    elif change == 'missing': tracks = ('missing',)
    elif change == 'duplicate': tracks = ('unrelated', 'unrelated')
    elif change == 'empty': tracks = ()
    elif change == 'deleted': edit(lib, "UPDATE djmdContent SET rb_local_deleted=1 WHERE ID='unrelated'")
    elif change == 'streaming': edit(lib, "UPDATE djmdContent SET ServiceID=1 WHERE ID='unrelated'")
    elif change == 'synced': edit(lib, "UPDATE djmdContent SET rb_local_synced=1 WHERE ID='unrelated'")
    elif change == 'smart': edit(lib, 'UPDATE djmdPlaylist SET Attribute=4')
    elif change == 'folder': edit(lib, 'UPDATE djmdPlaylist SET Attribute=1')
    elif change == 'deleted_playlist': edit(lib, 'UPDATE djmdPlaylist SET rb_local_deleted=1')
    elif change == 'synced_playlist': edit(lib, 'UPDATE djmdPlaylist SET rb_local_synced=1')
    elif change == 'bad_order': edit(lib, 'UPDATE djmdSongPlaylist SET TrackNo=NULL')
    elif change == 'trigger': edit(lib, 'CREATE TRIGGER surprise AFTER INSERT ON djmdSongPlaylist BEGIN UPDATE djmdContent SET Title="oops"; END')
    before = digest(lib.path)
    with pytest.raises(SafetyError):
        apply_additions(lib, plan(lib, tracks), backups)
    assert digest(lib.path) == before and not backups.list()


def test_unsupported_version_can_scan_but_cannot_add(tmp_path, monkeypatch):
    lib, _, _ = fixture_library(tmp_path)
    monkeypatch.setattr('rekordbox_manager.cue_writer.installed_version', lambda: 'other')
    assert scan_usage(lib).tracks
    with pytest.raises(SafetyError, match='require Rekordbox'):
        plan(lib)


def test_changed_database_after_review_and_repeated_apply_blocked(tmp_path):
    lib, _, backups = fixture_library(tmp_path)
    addition = plan(lib)
    apply_additions(lib, addition, backups)
    before = digest(lib.path)
    with pytest.raises(SafetyError, match='changed'):
        apply_additions(lib, addition, backups)
    with pytest.raises(SafetyError, match='already belongs'):
        plan(lib)
    assert digest(lib.path) == before and len(backups.list()) == 1


def test_external_change_after_scan_or_confirmation_blocks_write(tmp_path):
    lib, _, backups = fixture_library(tmp_path)
    addition = plan(lib)
    with staged_connection(lib.path) as db:
        db.execute("UPDATE djmdContent SET Title='later'")
        db.commit()
    before = digest(lib.path)
    with pytest.raises(SafetyError, match='changed'):
        plan_additions(lib, ('unrelated',), ('p',), addition.fingerprint)
    with pytest.raises(SafetyError, match='changed'):
        apply_additions(lib, addition, backups)
    assert digest(lib.path) == before and not backups.list()


def test_failed_verification_rolls_back_playlist_additions(tmp_path, monkeypatch):
    lib, _, backups = fixture_library(tmp_path)
    before = digest(lib.path)
    install = backups.install
    def broken(root, replacements, expected, guard, validate, description):
        def fail(): raise SafetyError('verification failed')
        return install(root, replacements, expected, guard, fail, description)
    monkeypatch.setattr(backups, 'install', broken)
    with pytest.raises(SafetyError, match='verification failed'):
        apply_additions(lib, plan(lib), backups)
    assert digest(lib.path) == before and lib.fingerprint == before
    assert backups.list()[0][1]['state'] == 'rolled_back'


def test_missing_audio_is_still_fileable_and_no_audio_is_created(tmp_path):
    lib, proposal, backups = fixture_library(tmp_path)
    proposal.track.path.unlink()
    apply_additions(lib, plan(lib), backups)
    assert not proposal.track.path.exists()
    assert next(t.playlists for t in scan_usage(lib).tracks if t.id == 'unrelated') == 1


def test_invalid_second_track_cancels_batch_before_install(tmp_path):
    lib, _, backups = fixture_library(tmp_path)
    addition = plan(lib)
    addition = replace(addition, tracks=addition.tracks + (('missing', 'Missing', 'Unknown'),))
    before = digest(lib.path)
    with pytest.raises(SafetyError):
        apply_additions(lib, addition, backups)
    assert digest(lib.path) == before and not backups.list()
