from dataclasses import replace
import xml.etree.ElementTree as ET

import pytest

from rekordbox_manager.backups import digest
from rekordbox_manager.guards import SafetyError
from rekordbox_manager.organiser_queue import OrganiserQueue, XML_NAME
from rekordbox_manager.organiser_writer import apply_plan
from rekordbox_manager.cue_writer import staged_connection, insert_row
from rekordbox_manager.usage import scan_usage
from test_cue_writer import fixture_library, rows, supported_install


def queued(lib):
    q = OrganiserQueue()
    folder = q.create(lib, 'Rediscovered', folder=True)
    nested = q.create(lib, 'November', parent=folder.identity, folder=True)
    playlist = q.create(lib, 'To play', parent=nested.identity)
    scan = scan_usage(lib)
    q.add(lib, scan.tracks, [playlist.identity], scan.fingerprint)
    q.add(lib, scan.tracks, [playlist.identity], scan.fingerprint)
    return q, playlist


@pytest.mark.parametrize('encrypted', [False, True])
@pytest.mark.parametrize('with_xml', [False, True])
def test_drafts_import_hierarchy_memberships_preservation_and_restore(tmp_path, encrypted, with_xml):
    lib, proposal, store = fixture_library(tmp_path, encrypted)
    xml = lib.root / XML_NAME
    if with_xml:
        xml.write_text('<MASTER Version="1"><PRODUCT Name="rekordbox"/><PLAYLISTS><NODE Id="ABC" ParentId="0" Attribute="0" Timestamp="1" Lib_Type="0" CheckType="0"/></PLAYLISTS></MASTER>')
    originals = {t: rows(lib, t) for t in ('djmdContent', 'djmdCue', 'contentCue', 'djmdPlaylist', 'djmdSongPlaylist')}
    before = digest(lib.path)
    xml_before = xml.read_bytes() if with_xml else None
    audio = digest(proposal.track.path)
    analysis = {p: digest(p) for p in proposal.track.analysis_paths}
    q, playlist = queued(lib)
    assert digest(lib.path) == before and not store.list()
    assert len(q.assignments[playlist.identity]) == 2
    assert q.view().playlist_paths[playlist.identity][-1] == (playlist.identity, 'To play')
    backup = apply_plan(lib, q.snapshot(), store)
    imported = {r['ID']: r for r in rows(lib, 'djmdPlaylist')}
    assert imported[playlist.identity]['ParentID'] == q.nodes[1].identity
    assert imported[q.nodes[1].identity]['ParentID'] == q.nodes[0].identity
    assert imported[q.nodes[0].identity]['ParentID'] == 'root'
    added = [r for r in rows(lib, 'djmdSongPlaylist') if r['PlaylistID'] == playlist.identity]
    assert {r['ContentID'] for r in added} == {'t', 'unrelated'}
    assert [r['TrackNo'] for r in added] == [1, 2]
    assert all(r in rows(lib, 'djmdPlaylist') for r in originals['djmdPlaylist'])
    assert all(r in rows(lib, 'djmdSongPlaylist') for r in originals['djmdSongPlaylist'])
    for t in ('djmdContent', 'djmdCue', 'contentCue'):
        assert rows(lib, t) == originals[t]
    assert rows(lib, 'agentRegistry')[0]['int_1'] == 28  # Two events per node, one per song.
    assert digest(proposal.track.path) == audio and all(digest(p) == sha for p, sha in analysis.items())
    if with_xml:
        nodes = ET.parse(xml).getroot().find('PLAYLISTS')
        assert len(nodes) == 4 and nodes[0].get('Id') == 'ABC'
        assert nodes[-1].get('ParentId') == f'{int(q.nodes[1].identity):X}'
    assert lib.playlist_paths[playlist.identity][-1][1] == 'To play'
    with pytest.raises(SafetyError, match='changed'):
        apply_plan(lib, q.snapshot(), store)
    lib.restore(store, backup)
    assert digest(lib.path) == before
    assert (xml.read_bytes() if xml.exists() else None) == xml_before


def test_existing_memberships_deduplicate_and_append_without_removal(tmp_path):
    lib, _, store = fixture_library(tmp_path)
    scan = scan_usage(lib)
    q = OrganiserQueue()
    q.add(lib, scan.tracks, ['p'], scan.fingerprint)
    assert list(q.assignments['p']) == ['unrelated']
    apply_plan(lib, q.snapshot(), store)
    assert [(r['ContentID'], r['TrackNo']) for r in rows(lib, 'djmdSongPlaylist')] == [('t', 1), ('unrelated', 2)]


@pytest.mark.parametrize('change', ['database', 'xml', 'parent_deleted', 'track_synced', 'trigger', 'duplicate_id'])
def test_invalid_or_stale_draft_never_installs(tmp_path, change):
    lib, _, store = fixture_library(tmp_path)
    xml = lib.root / XML_NAME
    xml.write_text('<MASTER><PLAYLISTS/></MASTER>')
    q, playlist = queued(lib)
    plan = q.snapshot()
    if change == 'database':
        with staged_connection(lib.path) as db:
            db.execute("UPDATE djmdContent SET Title='later'")
            db.commit()
    elif change == 'xml':
        xml.write_text('<MASTER Version="2"><PLAYLISTS/></MASTER>')
    elif change == 'duplicate_id':
        plan = replace(plan, nodes=(replace(plan.nodes[0], identity='p'),) + plan.nodes[1:])
    elif change == 'parent_deleted':
        plan = replace(plan, nodes=(replace(plan.nodes[0], parent_id='missing'),) + plan.nodes[1:])
    else:
        with staged_connection(lib.path) as db:
            if change == 'track_synced':
                db.execute("UPDATE djmdContent SET rb_local_synced=1")
            else:
                db.execute('CREATE TRIGGER surprise AFTER INSERT ON djmdPlaylist BEGIN UPDATE djmdContent SET Title="oops"; END')
            db.commit()
        lib.reload()
        plan = replace(plan, fingerprint=lib.fingerprint)
    before = digest(lib.path), xml.read_bytes()
    with pytest.raises(SafetyError):
        apply_plan(lib, plan, store)
    assert (digest(lib.path), xml.read_bytes()) == before and not store.list()


def test_verification_failure_restores_database_and_playlist_xml(tmp_path, monkeypatch):
    lib, _, store = fixture_library(tmp_path)
    xml = lib.root / XML_NAME
    xml.write_text('<MASTER><PLAYLISTS/></MASTER>')
    q, _ = queued(lib)
    before = digest(lib.path), xml.read_bytes()
    install = store.install
    def broken(root, replacements, expected, guard, validate, description):
        def fail():
            raise SafetyError('verification failed')
        return install(root, replacements, expected, guard, fail, description)
    monkeypatch.setattr(store, 'install', broken)
    with pytest.raises(SafetyError, match='verification failed'):
        apply_plan(lib, q.snapshot(), store)
    assert (digest(lib.path), xml.read_bytes()) == before
    assert store.list()[0][1]['state'] == 'rolled_back'
    assert q.pending()


def test_queue_invalid_names_parents_duplicates_and_rebase(tmp_path):
    lib, _, _ = fixture_library(tmp_path)
    q, playlist = queued(lib)
    for name, parent in [('', None), ('line\nbreak', None), ('a' * 256, None), ('REDISCOVERED', None), ('wrong', playlist.identity)]:
        with pytest.raises(SafetyError):
            q.create(lib, name, parent=parent)
    old = q.fingerprint
    with staged_connection(lib.path) as db:
        db.execute("UPDATE djmdContent SET CueUpdated='new'")
        db.commit()
    lib.reload()
    with pytest.raises(SafetyError, match='changed'):
        q.bind(lib)
    q.rebase('wrong', lib)
    assert q.fingerprint == old
    q.rebase(old, lib)
    q.bind(lib)
    assert q.fingerprint == lib.fingerprint
