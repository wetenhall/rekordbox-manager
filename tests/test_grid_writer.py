import struct
from dataclasses import replace

import numpy as np
import pytest
import soundfile as sf

from rekordbox_manager.backups import digest
from rekordbox_manager.cue_writer import staged_connection
from rekordbox_manager.grid_writer import align_downbeat, patch_analysis, tags, tempo
from rekordbox_manager.guards import SafetyError
from rekordbox_manager.library import RekordboxLibrary, read_grid
from rekordbox_manager.models import Grid, Options
from test_cue_writer import fixture_library, rows, supported_install


def extended():
    # Native PQT2 shape, plus an unrelated opaque tag that must not change.
    raw = struct.pack('>4sIIIIIHHIHHIIII', b'PQT2',56,456,0,0x01000002,0,
                      1,12000,0,4,12000,99500,200,1770000,0) + bytes(4) + b'\x01\x54'*200
    assert len(raw)==456
    opaque=struct.pack('>4sII',b'TEST',12,18)+b'opaque'
    return struct.pack('>4sII',b'PMAI',28,28+len(raw)+len(opaque))+bytes(16)+raw+opaque


def prepared(tmp_path, encrypted=False):
    lib,p,store=fixture_library(tmp_path,encrypted)
    with staged_connection(lib.path) as db:
        db.execute("UPDATE djmdContent SET AnalysisDataPath=NULL WHERE ID='unrelated'")
        db.commit()
    sf.write(str(p.track.path),np.zeros(44100*100,dtype=np.int16),44100)
    ext=p.track.analysis_paths[0].with_suffix('.EXT');ext.write_bytes(extended())
    lib=RekordboxLibrary(lib.path)
    track=lib.tracks('p')[0]
    grid=Grid([round(.02+t*.999,3) for t in track.grid.times],[(i+1)%4+1 for i in range(len(track.grid.times))])
    p=replace(p,track=track,grid=grid,options=Options(True,True),grid_approved=True)
    return lib,p,store


@pytest.mark.parametrize('encrypted',[False,True])
def test_grid_and_cues_round_trip_with_exact_multifile_restore(tmp_path,encrypted):
    lib,p,store=prepared(tmp_path,encrypted)
    original={path:digest(path) for path in [lib.path,*p.track.analysis_paths]}
    hot=rows(lib,'djmdCue',"WHERE ID IN ('h','l','m')")
    backup=lib.apply([p],store)
    assert lib.tracks('p')[0].grid==p.grid
    assert len(lib.tracks('p')[0].cues)==5
    assert rows(lib,'djmdCue',"WHERE ID IN ('h','l','m')")==hot
    assert rows(lib,'djmdContent',"WHERE ID='t'")[0]['BPM']==tempo(p.grid)
    ext=next(x for x in p.track.analysis_paths if x.suffix=='.EXT')
    after=tags(ext.read_bytes())[1]
    assert after[0][2][24:]==bytes(32) and len(after[0][2])==56
    assert after[1]==tags(extended())[1][1]
    assert len(store.validate(backup,lib.root)['files'])==3
    lib.restore(store,backup)
    assert {path:digest(path) for path in original}==original


def test_grid_only_preserves_cue_tables_exactly(tmp_path):
    lib,p,store=prepared(tmp_path)
    before={t:rows(lib,t) for t in ('djmdCue','contentCue')}
    p.options=Options(True,False);p.cues=p.track.cues.copy()
    lib.apply([p],store)
    assert {t:rows(lib,t) for t in before}==before


@pytest.mark.parametrize('offset',[float('nan'),.3,-.3])
def test_invalid_audio_timeline_offset_cannot_be_imported(tmp_path,offset):
    lib,p,store=prepared(tmp_path)
    p.track.audio_offset=offset
    before={path:digest(path) for path in [lib.path,*p.track.analysis_paths]}
    with pytest.raises(SafetyError,match='timeline offset'):
        lib.apply([p],store)
    assert {path:digest(path) for path in before}==before


def test_grid_failure_rolls_back_every_file(tmp_path,monkeypatch):
    lib,p,store=prepared(tmp_path)
    before={path:digest(path) for path in [lib.path,*p.track.analysis_paths]}
    actual=store.install
    def failing(root,replacements,expected,guard,verify,description):
        def bad():raise RuntimeError('simulated installed validation failure')
        return actual(root,replacements,expected,guard,bad,description)
    monkeypatch.setattr(store,'install',failing)
    with pytest.raises(RuntimeError):lib.apply([p],store)
    assert {path:digest(path) for path in before}==before


@pytest.mark.parametrize('change',['stale','missing_ext','variable','shared','unapproved','bad_tag'])
def test_unsafe_grid_change_does_not_touch_database(tmp_path,change):
    lib,p,store=prepared(tmp_path)
    ext=next(x for x in p.track.analysis_paths if x.suffix=='.EXT')
    if change=='stale':ext.write_bytes(ext.read_bytes()+b'x')
    elif change=='missing_ext':p.track.analysis_paths.remove(ext)
    elif change=='variable':p.grid.times[30]+=.05
    elif change=='shared':
        with staged_connection(lib.path) as db:
            db.execute("UPDATE djmdContent SET AnalysisDataPath=(SELECT AnalysisDataPath FROM djmdContent WHERE ID='t') WHERE ID='unrelated'")
            db.commit()
    elif change=='unapproved':p.grid_approved=False
    elif change=='bad_tag':ext.write_bytes(ext.read_bytes().replace(b'PQT2',b'PQT3'))
    before=digest(lib.path)
    with pytest.raises((SafetyError,ValueError)):lib.apply([p],store)
    assert digest(lib.path)==before


def test_manual_anchor_sets_bar_start_without_changing_tempo():
    grid=Grid([.2+i*.5 for i in range(200)],[i%4+1 for i in range(200)])
    result,anchor=align_downbeat(grid,20.72,101)
    assert anchor==20.72 and result.positions[41]==1
    assert tempo(result)==tempo(grid)
    assert result.times[0]==.22
    with pytest.raises((SafetyError,ValueError)):align_downbeat(grid,0,99)


def test_malformed_tag_is_rejected():
    with pytest.raises(SafetyError):patch_analysis(b'PMAI',Grid([0,.5],[1,2]),12000)


@pytest.mark.parametrize('trim_start',[True,False])
def test_drop_aligned_boundary_trim_round_trip_and_restore(tmp_path,trim_start):
    from rekordbox_manager.analysis import rebuild_proposal
    lib,p,store=prepared(tmp_path,encrypted=True)
    # The fixture starts at zero and ends at 99.5; use an audio end that
    # requires removing the last beat for a +100 ms translation.
    if not trim_start:
        sf.write(str(p.track.path),np.zeros(round(44100*99.55),dtype=np.int16),44100)
        p.track=lib.tracks('p')[0]
        p.track.duration=99.55
    shift=-.1 if trim_start else .1
    p.first_drop,p.second_drop=32+shift,80+shift
    p.options=Options(True,True,True)
    rebuild_proposal(p)
    assert p.ready_to_apply and len(p.grid.times)==len(p.track.grid.times)-1
    p.reviewed=p.grid_approved=True
    original={path:digest(path) for path in [lib.path,*p.track.analysis_paths]}
    backup=lib.apply([p],store)
    saved=lib.tracks('p')[0]
    assert saved.grid==p.grid and tempo(saved.grid)==12000
    assert all(c.time in saved.grid.times for c in saved.cues if c.kind=='memory')
    assert any(c.kind=='hot' for c in saved.cues)
    lib.restore(store,backup)
    assert all(digest(path)==value for path,value in original.items())


def test_arbitrary_missing_beat_is_refused(tmp_path):
    lib,p,store=prepared(tmp_path)
    p.grid=Grid(p.track.grid.times[:-1],p.track.grid.positions[:-1])
    before=digest(lib.path)
    with pytest.raises(SafetyError,match='boundary trim'):
        lib.apply([p],store)
    assert digest(lib.path)==before
