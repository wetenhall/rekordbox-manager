import pytest
from rekordbox_manager.models import Grid, Track, Proposal, Options
from rekordbox_manager.analysis import rebuild_proposal
from rekordbox_manager.drop_grid import align_drops, rhythm_issue
from rekordbox_manager.attacks import Attack
from rekordbox_manager.grid_writer import tempo, patch_analysis


def grid(bpm=174):
    return Grid([round(.3+i*60/bpm,3) for i in range(1000)], [i%4+1 for i in range(1000)])


@pytest.mark.parametrize('bpm', [128, 138, 174])
@pytest.mark.parametrize('shift', [-.060, .080])
def test_shift_keeps_tempo_count_and_aligns_both_drops(bpm,shift):
    original=grid(bpm)
    first,second=original.times[128]+shift,original.times[640]+shift+.010
    changed,a,b,issue=align_drops(original,first,second,500)
    assert not issue
    assert a==changed.times[128] and b==changed.times[640]
    assert changed.positions[128]==changed.positions[640]==1
    assert len(changed.times)==len(original.times) and tempo(changed)==tempo(original)
    assert all(new-old==pytest.approx(shift,abs=.001) for new,old in zip(changed.times,original.times))
    assert original==grid(bpm)


def test_wrong_tempo_and_wrong_bar_cannot_be_fixed_by_translation():
    g=grid()
    for error in (.040,60/174,4*60/174-.1):
        shifted,a,b,issue=align_drops(g,g.times[128]+.05,g.times[640]+.05+error,500)
        assert issue and 'import is blocked' in issue
        assert tempo(shifted)==tempo(g)


def test_manual_rebuild_rechecks_second_drop_and_does_not_accumulate_shift(tmp_path):
    g=grid();track=Track('x','x','','',tmp_path/'x.wav',500,174,g)
    p=Proposal(track,Options(True,True),g,[],g.times[128]+.05,g.times[640]+.05)
    rebuild_proposal(p)
    assert p.ready_to_apply and not p.grid_issue
    once=p.grid
    rebuild_proposal(p)
    assert p.grid==once
    assert all(c.time in p.grid.times for c in p.cues)
    p.second_drop+=.1
    rebuild_proposal(p)
    assert not p.ready_to_apply and p.grid_issue and p.cues_dirty
    p.first_drop+=.1
    rebuild_proposal(p)
    assert p.ready_to_apply and p.grid.times[128]==p.first_drop
    assert tempo(p.grid)==tempo(g)


def test_shift_trims_only_out_of_audio_boundary_beat(tmp_path):
    g=Grid([i*.5 for i in range(1000)],[i%4+1 for i in range(1000)])
    t=Track('x','x','','',tmp_path/'x.wav',500,120,g)
    p=Proposal(t,Options(True,True),g,[],63.94,319.94)
    rebuild_proposal(p)
    assert not p.grid_issue and p.ready_to_apply
    assert len(p.grid.times)==len(g.times)-1 and p.grid.times[0]==.44
    assert all(c.time in p.grid.times for c in p.cues)
    p.first_drop,p.second_drop=64.6,320.6
    # The later first beat is labelled 1; the second marker must share that bar phase.
    rebuild_proposal(p)
    assert p.ready_to_apply and p.grid.positions[129]==1


def test_independent_rhythm_evidence_rejects_drift_and_sparse_hits():
    g=grid()
    attacks=[Attack(t,1) for t in g.times]
    assert not rhythm_issue(g,attacks,g.times[128],g.times[640])
    assert rhythm_issue(g,attacks[:3],g.times[128],g.times[640])
    drifted=[Attack(t+.0004*t,1) for t in g.times]
    assert rhythm_issue(g,drifted,g.times[128],g.times[640])
