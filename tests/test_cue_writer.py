import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from rekordbox_manager import cue_writer
from rekordbox_manager.backups import BackupStore, digest
from rekordbox_manager.cue_writer import cache_entry, insert_row
from rekordbox_manager.guards import SafetyError
from rekordbox_manager.library import RekordboxLibrary
from rekordbox_manager.models import Cue, Options, Proposal
from test_library import anlz_bytes


@pytest.fixture(autouse=True)
def supported_install(monkeypatch):
    monkeypatch.setattr('psutil.process_iter', lambda attrs: [])
    monkeypatch.setattr(cue_writer, 'installed_version', lambda: cue_writer.TESTED_VERSION)


def fixture_library(tmp_path, encrypted=False):
    path=tmp_path/'master.db'
    if encrypted:
        from sqlcipher3 import dbapi2 as cipher
        from pyrekordbox.masterdb.database import BLOB
        from pyrekordbox.utils import deobfuscate
        db=cipher.connect(str(path))
        db.execute("PRAGMA key='"+deobfuscate(BLOB).replace("'", "''")+"'")
    else:
        db=sqlite3.connect(path)
    db.executescript((Path(__file__).parent/'fixtures/rekordbox-7.2.19-schema.sql').read_text())
    stamp='2026-01-01 00:00:00.000 +00:00'
    date=dict(created_at=stamp,updated_at=stamp)
    insert_row(db,'djmdProperty',dict(DBID='db',DBVersion='6000',**date))
    insert_row(db,'agentRegistry',dict(registry_id='localUpdateCount',int_1=20,**date))
    insert_row(db,'djmdPlaylist',dict(ID='p',Name='Test',Attribute=0,Seq=0,**date))
    audio=tmp_path/'audio.wav';audio.write_bytes(b'test audio untouched')
    dat=tmp_path/'share/PIONEER/USBANLZ/a/ANLZ0000.DAT';dat.parent.mkdir(parents=True);dat.write_bytes(anlz_bytes())
    for identity in ['t','unrelated']:
        insert_row(db,'djmdContent',dict(ID=identity,UUID=identity+'-uuid',Title=identity,
            FolderPath=str(audio),AnalysisDataPath='/PIONEER/USBANLZ/a/ANLZ0000.DAT',
            Length=100, BPM=12000,FileType=11,SampleRate=44100,ServiceID=0,**date))
    insert_row(db,'djmdSongPlaylist',dict(ID='song',PlaylistID='p',ContentID='t',TrackNo=1,**date))
    entries=[]
    # A normal memory cue, hot cue with unknown metadata, and saved memory loop.
    for identity,kind,start,end,comment in [('m',0,2000,-1,'Existing'),('h',5,3000,-1,'Hot D'),('l',0,5000,7000,'Loop')]:
        row=dict(ID=identity,ContentID='t',ContentUUID='t-uuid',UUID=identity+'-uuid',
                 InMsec=start,InFrame=start*150//1000,InMpegFrame=0,InMpegAbs=0,
                 OutMsec=end,OutFrame=0,OutMpegFrame=0,OutMpegAbs=0,Kind=kind,Color=-1,Comment=comment,**date)
        if identity=='h':row['InPointSeekInfo']='preserve-opaque-seek-data'
        insert_row(db,'djmdCue',row)
        entries.append(cache_entry(row))
    insert_row(db,'contentCue',dict(ID='t-uuid',ContentID='t',UUID='cache-uuid',
              Cues=json.dumps(entries),rb_cue_count=3,rb_local_usn=19,**date))
    db.commit()
    db.execute('PRAGMA journal_mode=WAL').fetchall()
    db.close()
    lib=RekordboxLibrary(path)
    track=lib.tracks('p')[0]
    proposal=Proposal(track,Options(False,True),track.grid,track.cues+[Cue(10,'DROP 1'),Cue(20,'DROP 2')],reviewed=True)
    return lib,proposal,BackupStore(tmp_path/'backups')


def rows(lib,table,where='',params=()):
    with lib.connect() as db:
        return [dict(r) for r in db.execute(f'SELECT * FROM {table} '+where,params)]


@pytest.mark.parametrize('encrypted',[False,True])
def test_apply_preserves_other_data_and_restore_is_byte_exact(tmp_path,encrypted):
    lib,p,store=fixture_library(tmp_path,encrypted)
    before=digest(lib.path)
    hot=rows(lib,'djmdCue',"WHERE ID IN ('h','l','m')")
    unrelated=rows(lib,'djmdContent',"WHERE ID='unrelated'")
    analysis=digest(p.track.analysis_paths[0]);audio=digest(p.track.path)
    backup=lib.apply([p],store)
    assert len(lib.tracks('p')[0].cues)==5
    assert rows(lib,'djmdCue',"WHERE ID IN ('h','l','m')")==hot
    assert rows(lib,'djmdContent',"WHERE ID='unrelated'")==unrelated
    assert digest(p.track.path)==audio and digest(p.track.analysis_paths[0])==analysis
    cache=rows(lib,'contentCue')[0]
    assert cache['rb_cue_count']==5
    assert rows(lib,'agentRegistry')[0]['int_1']==22
    assert (lib.path.read_bytes()[:16]!=b'SQLite format 3\0')==encrypted
    assert [e['path'] for e in store.validate(backup,lib.root)['files']]==['master.db']
    lib.restore(store,backup)
    assert digest(lib.path)==before


def test_replace_only_removes_ordinary_memory_cues(tmp_path):
    lib,p,store=fixture_library(tmp_path)
    p.options=Options(False,True,True)
    p.cues=[c for c in p.cues if c.label!='Existing']
    lib.apply([p],store)
    assert {r['ID'] for r in rows(lib,'djmdCue')} >= {'h','l'}
    assert not rows(lib,'djmdCue',"WHERE ID='m'")


@pytest.mark.parametrize("manual", [False, True])
def test_confirmed_off_grid_cue_imports_exact_timings_with_grid(tmp_path, manual):
    from rekordbox_manager.analysis import rebuild_proposal, confirm_proposal_review
    from rekordbox_manager.grid_writer import tempo
    lib, p, store = fixture_library(tmp_path)
    # Give this fixture a dedicated analysis file, as real grid imports require.
    with closing(sqlite3.connect(lib.path)) as db, db:
        db.execute("UPDATE djmdContent SET AnalysisDataPath=NULL WHERE ID='unrelated'")
    import numpy as np
    import soundfile as sf
    sf.write(p.track.path, np.zeros(8000 * 100, dtype=np.float32), 8000)
    lib = RekordboxLibrary(lib.path)
    p.track = lib.tracks('p')[0]
    p.grid = p.track.grid
    p.options = Options(True, True)
    p.first_drop, p.second_drop = 16, 63.948
    rebuild_proposal(p, manual=manual)
    assert p.review_note and not p.can_apply and not p.cues_dirty
    before = digest(lib.path)
    with pytest.raises(SafetyError):
        lib.apply([p], store)
    assert digest(lib.path) == before
    confirm_proposal_review(p)
    lib.apply([p], store)
    track = lib.tracks('p')[0]
    assert next(c.time for c in track.cues if c.label == 'DROP 2') == 63.948
    assert track.grid == p.grid and tempo(track.grid) == tempo(p.track.grid)


@pytest.mark.parametrize('change', ['hot','loop','memory','too_many','nan','duplicate','grid','dirty','unreviewed','range'])
def test_invalid_proposals_never_touch_live_files(tmp_path,change):
    lib,p,store=fixture_library(tmp_path)
    before=digest(lib.path)
    if change in ('hot','loop','memory'):
        label={'hot':'Hot D','loop':'Loop','memory':'Existing'}[change]
        p.cues=[c for c in p.cues if c.label!=label]
    elif change=='too_many':p.cues += [Cue(i,'extra') for i in range(30,41)]
    elif change=='nan':p.cues.append(Cue(float('nan'),'bad'))
    elif change=='duplicate':p.cues.append(Cue(10,'duplicate'))
    elif change=='grid':p.options=Options(True,True);p.grid_approved=True
    elif change=='dirty':p.cues_dirty=True
    elif change=='unreviewed':p.reviewed=False
    elif change=='range':p.cues.append(Cue(101,'outside audio'))
    with pytest.raises(SafetyError):lib.apply([p],store)
    assert digest(lib.path)==before and not store.list()


@pytest.mark.parametrize('source',['database','audio','analysis'])
def test_stale_inputs_block_apply(tmp_path,source):
    lib,p,store=fixture_library(tmp_path)
    if source=='database':
        with closing(sqlite3.connect(lib.path)) as db, db:db.execute("UPDATE djmdContent SET Title='new' WHERE ID='unrelated'")
    elif source=='audio':p.track.path.write_bytes(b'changed audio')
    else:p.track.analysis_paths[0].write_bytes(anlz_bytes(210))
    before=digest(lib.path)
    with pytest.raises(SafetyError,match='changed|Audio'):lib.apply([p],store)
    assert digest(lib.path)==before


def test_inconsistent_cache_is_rejected(tmp_path):
    lib,p,store=fixture_library(tmp_path)
    with closing(sqlite3.connect(lib.path)) as db, db:db.execute("UPDATE contentCue SET Cues='[]'")
    lib.reload();p.track=lib.tracks('p')[0]
    before=digest(lib.path)
    with pytest.raises(SafetyError,match='cache'):lib.apply([p],store)
    assert digest(lib.path)==before


def test_unverified_installation_is_read_only(tmp_path,monkeypatch):
    lib,p,store=fixture_library(tmp_path)
    monkeypatch.setattr(cue_writer,'installed_version',lambda:'7.0.9.0007')
    with pytest.raises(SafetyError,match='read-only'):lib.apply([p],store)
    lib.reload()
    assert not lib.writable


def test_failed_installed_verification_rolls_back(tmp_path,monkeypatch):
    lib,p,store=fixture_library(tmp_path)
    original=digest(lib.path)
    install=store.install
    def broken(root,replacements,expected,guard,validate,description):
        def fail():raise SafetyError('verification failed')
        return install(root,replacements,expected,guard,fail,description)
    monkeypatch.setattr(store,'install',broken)
    with pytest.raises(SafetyError,match='verification failed'):lib.apply([p],store)
    assert digest(lib.path)==original
    assert store.list()[0][1]['state']=='rolled_back'


def test_newer_library_changes_block_restore(tmp_path):
    lib,p,store=fixture_library(tmp_path)
    backup=lib.apply([p],store)
    with closing(sqlite3.connect(lib.path)) as db, db:db.execute("UPDATE djmdContent SET Title='later edit' WHERE ID='unrelated'")
    before=digest(lib.path)
    with pytest.raises(SafetyError,match='newer changes'):lib.restore(store,backup)
    assert digest(lib.path)==before


def test_first_cues_create_cache_and_repeat_import_does_not_duplicate(tmp_path):
    lib,p,store=fixture_library(tmp_path)
    with closing(sqlite3.connect(lib.path)) as db, db:
        db.execute('DELETE FROM djmdCue');db.execute('DELETE FROM contentCue')
    lib.reload();p.track=lib.tracks('p')[0];p.cues=[Cue(10,'DROP 1'),Cue(20,'DROP 2')]
    lib.apply([p],store)
    first=rows(lib,'djmdCue')
    p.track=lib.tracks('p')[0]
    lib.apply([p],store)
    assert rows(lib,'djmdCue')==first
    assert rows(lib,'contentCue')[0]['rb_cue_count']==2


def test_invalid_second_track_cancels_entire_batch(tmp_path):
    lib,p,store=fixture_library(tmp_path)
    other=lib.tracks_by_ids(['unrelated'])[0]
    invalid=Proposal(other,Options(True,True),other.grid,[Cue(10,'drop')],reviewed=True,grid_approved=True)
    before=digest(lib.path)
    with pytest.raises(SafetyError):lib.apply([p,invalid],store)
    assert digest(lib.path)==before and not store.list()


@pytest.mark.parametrize('column,value',[('FileType',99),('ServiceID',1),('rb_local_synced',1),('SampleRate',96000)])
def test_unsupported_content_blocks_write(tmp_path,column,value):
    lib,p,store=fixture_library(tmp_path)
    with closing(sqlite3.connect(lib.path)) as db, db:
        db.execute(f'UPDATE djmdContent SET {column}=? WHERE ID=?',(value,'t'))
    lib.reload();p.track=lib.tracks('p')[0]
    before=digest(lib.path)
    with pytest.raises(SafetyError):lib.apply([p],store)
    assert digest(lib.path)==before and not store.list()
