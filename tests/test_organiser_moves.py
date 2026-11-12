from dataclasses import replace
import xml.etree.ElementTree as ET

import pytest

from rekordbox_manager.backups import digest
from rekordbox_manager.cue_writer import staged_connection, insert_row
from rekordbox_manager.guards import SafetyError
from rekordbox_manager.organiser_queue import OrganiserQueue, XML_NAME
from rekordbox_manager.organiser_writer import apply_plan
from test_cue_writer import fixture_library, rows, supported_install


def hierarchy(tmp_path, encrypted=False):
    lib, proposal, store = fixture_library(tmp_path, encrypted)
    with staged_connection(lib.path) as db:
        db.execute("UPDATE djmdPlaylist SET ID='10',ParentID='root',Seq=3")
        db.execute("UPDATE djmdSongPlaylist SET PlaylistID='10'")
        base = dict(db.execute('SELECT * FROM djmdPlaylist').fetchone())
        for identity, name, parent, attr, seq in [('100','Folder A','root',1,1), ('200','Folder B','root',1,2),
                ('110','Playlist A','100',0,1), ('120','Nested','100',1,2), ('121','Deep playlist','120',0,1), ('210','Playlist B','200',0,1)]:
            insert_row(db, 'djmdPlaylist', dict(base, ID=identity, Name=name, ParentID=parent, Attribute=attr, Seq=seq))
        db.commit()
    root = ET.Element('MASTER', Version='1')
    xml = ET.SubElement(root, 'PLAYLISTS')
    for row in rows(lib, 'djmdPlaylist'):
        ET.SubElement(xml, 'NODE', Id=f"{int(row['ID']):X}", ParentId='0' if row['ParentID'] == 'root' else f"{int(row['ParentID']):X}",
                      Attribute=str(row['Attribute']), Timestamp='1', Lib_Type='0', CheckType='0')
    ET.ElementTree(root).write(lib.root / XML_NAME)
    lib.reload()
    return lib, proposal, store


def children(q, parent):
    return [n.identity for n in q.view().playlist_nodes if n.parent_id == parent]


@pytest.mark.parametrize('encrypted', [False, True])
def test_move_folders_playlists_reorder_import_and_restore(tmp_path, encrypted):
    lib, proposal, store = hierarchy(tmp_path, encrypted)
    q = OrganiserQueue()
    originals = {t: rows(lib, t) for t in ('djmdContent', 'djmdCue', 'contentCue', 'djmdSongPlaylist')}
    before = digest(lib.path), (lib.root / XML_NAME).read_bytes()
    q.move(lib, '110', '200', '210')
    q.move(lib, '120', '200')
    q.move(lib, '200', None, '100')
    assert children(q, None) == ['200', '100', '10']
    assert children(q, '200') == ['110', '210', '120']
    assert children(q, '120') == ['121']
    assert digest(lib.path) == before[0] and not store.list()
    backup = apply_plan(lib, q.snapshot(), store)
    after = {r['ID']: r for r in rows(lib, 'djmdPlaylist')}
    assert (after['110']['ParentID'], after['110']['Seq']) == ('200', 1)
    assert (after['120']['ParentID'], after['120']['Seq']) == ('200', 3)
    assert (after['121']['ParentID'], after['121']['Seq']) == ('120', 1)
    assert (after['200']['ParentID'], after['200']['Seq']) == ('root', 1)
    assert after['100']['Seq'] == 2
    for table, original in originals.items():
        assert rows(lib, table) == original
    xml = ET.parse(lib.root / XML_NAME).getroot().find('PLAYLISTS')
    changed = next(n for n in xml if n.get('Id') == f'{110:X}')
    assert changed.get('ParentId') == f'{200:X}'
    lib.restore(store, backup)
    assert (digest(lib.path), (lib.root / XML_NAME).read_bytes()) == before



def test_new_drafts_can_move_then_create_more_and_move_existing_into_draft(tmp_path):
    lib, _, store = hierarchy(tmp_path)
    q = OrganiserQueue()
    folder = q.create(lib, 'Draft folder', parent='100', folder=True)
    q.move(lib, folder.identity, None, '100')
    q.move(lib, '100', folder.identity)
    playlist = q.create(lib, 'After moving', parent='100')
    q.move(lib, playlist.identity, '200', '210')
    apply_plan(lib, q.snapshot(), store)
    after = {r['ID']: r for r in rows(lib, 'djmdPlaylist')}
    assert after[folder.identity]['ParentID'] == 'root'
    assert after['100']['ParentID'] == folder.identity
    assert after[playlist.identity]['ParentID'] == '200'
    assert after['210']['Seq'] == 2


def test_move_back_to_original_is_noop_and_create_after_drag_is_in_snapshot(tmp_path):
    lib, _, store = hierarchy(tmp_path)
    q = OrganiserQueue()
    q.move(lib, '110', '200')
    q.move(lib, '110', '100', '120')
    assert not q.pending() and not q.snapshot().structure
    q.move(lib, '110', '200')
    new = q.create(lib, 'Added later', parent='100')
    assert new.identity in {n.identity for n in q.snapshot().structure}
    apply_plan(lib, q.snapshot(), store)
    assert new.identity in lib.playlists


@pytest.mark.parametrize('identity,parent,before', [('100','100',None), ('100','120',None), ('120','121',None),
                                                   ('110','210',None), ('110',None,'missing')])
def test_invalid_drop_keeps_drafts_and_source_unchanged(tmp_path, identity, parent, before):
    lib, _, _ = hierarchy(tmp_path)
    q = OrganiserQueue()
    fingerprint = digest(lib.path)
    with pytest.raises(SafetyError):
        q.move(lib, identity, parent, before)
    assert not q.pending() and digest(lib.path) == fingerprint


@pytest.mark.parametrize('change', ['cycle', 'missing', 'rename', 'cloud', 'stale_xml'])
def test_invalid_plan_never_installs(tmp_path, change):
    lib, _, store = hierarchy(tmp_path)
    if change == 'cloud':
        with staged_connection(lib.path) as db:
            db.execute("UPDATE djmdPlaylist SET rb_local_synced=1 WHERE ID='210'")
            db.commit()
        lib.reload()
    q = OrganiserQueue()
    q.move(lib, '110', '200', '210')
    plan = q.snapshot()
    if change == 'cycle':
        plan = replace(plan, structure=tuple(replace(n, parent_id='120') if n.identity == '100' else n for n in plan.structure))
    elif change == 'missing':
        plan = replace(plan, structure=plan.structure[:-1])
    elif change == 'rename':
        plan = replace(plan, structure=tuple(replace(n, name='renamed') if n.identity == '110' else n for n in plan.structure))
    elif change == 'stale_xml':
        (lib.root / XML_NAME).write_text('<MASTER><PLAYLISTS/></MASTER>')
    before = digest(lib.path), (lib.root / XML_NAME).read_bytes()
    with pytest.raises(SafetyError):
        apply_plan(lib, plan, store)
    assert (digest(lib.path), (lib.root / XML_NAME).read_bytes()) == before and not store.list()


def test_failed_move_install_restores_both_files(tmp_path, monkeypatch):
    lib, _, store = hierarchy(tmp_path)
    q = OrganiserQueue()
    q.move(lib, '110', '200')
    before = digest(lib.path), (lib.root / XML_NAME).read_bytes()
    install = store.install
    def fail_install(root, replacements, expected, guard, validate, description):
        def fail():
            raise SafetyError('verification failed')
        return install(root, replacements, expected, guard, fail, description)
    monkeypatch.setattr(store, 'install', fail_install)
    with pytest.raises(SafetyError, match='verification failed'):
        apply_plan(lib, q.snapshot(), store)
    assert (digest(lib.path), (lib.root / XML_NAME).read_bytes()) == before
    assert q.pending()
