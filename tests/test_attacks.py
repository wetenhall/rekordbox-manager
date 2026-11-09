import numpy as np
import pytest

from rekordbox_manager.attacks import Attack, kick_attacks, match_attack, refine_drop
from rekordbox_manager.models import Grid


def drums(bpm=172, syncopated=False):
    sr=11025
    beat=60/bpm
    y=np.zeros(sr*24,dtype=np.float32)
    times=[]
    t=np.arange(round(.18*sr))/sr
    kick=np.sin(2*np.pi*(80*t-70*t*t))*np.exp(-t*22)*np.minimum(t/.002,1)
    for i in range(48):
        if syncopated and i%4 not in (0,2):continue
        onset=1+i*beat+(beat/2 if syncopated and i%4==2 else 0)
        start=round(onset*sr)
        y[start:start+len(kick)]+=kick
        times.append(onset)
    g=Grid([1+i*beat for i in range(60)],[i%4+1 for i in range(60)])
    return y,sr,g,times


@pytest.mark.parametrize('bpm,syncopated',[(125,False),(140,False),(172,True)])
def test_attack_leading_edges_and_syncopated_pulse(bpm,syncopated):
    y,sr,g,times=drums(bpm,syncopated)
    attacks=kick_attacks(y,sr)
    assert len(attacks)>=len(times)*.9
    for expected in times[2:-2]:
        assert min(abs(a.time-expected) for a in attacks)<.015
    match=match_attack(attacks,times[4]+.08,g,len(y)/sr)
    assert match.time==pytest.approx(times[4],abs=.015)
    assert not match.needs_review


def test_louder_high_frequency_hit_does_not_replace_nearby_kick():
    y,sr,g,times=drums()
    expected=times[12]
    t=np.arange(round(.08*sr))/sr
    start=round((expected+.09)*sr)
    y[start:start+len(t)]+=3*np.sin(2*np.pi*2400*t)*np.exp(-t*45)
    match=match_attack(kick_attacks(y,sr),expected+.07,g,len(y)/sr)
    assert match.time==pytest.approx(expected,abs=.015)


def test_silence_and_slow_bass_swell_do_not_supply_a_kick():
    sr=11025;t=np.arange(sr*4)/sr
    assert kick_attacks(np.zeros_like(t),sr)==[]
    swell=np.sin(2*np.pi*60*t)*np.exp(-((t-2)/.6)**2)
    assert kick_attacks(swell,sr)==[]


def test_local_matching_refuses_ambiguous_distant_and_crossed_markers():
    g=Grid([i*.5 for i in range(100)],[i%4+1 for i in range(100)])
    ambiguous=match_attack([Attack(9.9,1),Attack(10.1,1)],10,g,50)
    assert ambiguous.time is None and 'Two nearby' in ambiguous.note
    assert match_attack([Attack(12,1)],10,g,50).time is None
    assert match_attack([Attack(10.1,1)],10,g,50,upper=10.05).time is None
    assert match_attack([Attack(9.9,1)],10,g,50,lower=9.95).time is None


def test_uncertain_pulse_and_grid_offset_are_flagged_without_changing_grid():
    g=Grid([i*.5 for i in range(100)],[i%4+1 for i in range(100)])
    before=g.times.copy()
    match=match_attack([Attack(10.08,1)],10,g,50)
    assert match.time==10.08 and match.needs_review
    assert 'Limited support' in match.note and 'grid was not moved' in match.note
    assert g.times==before


@pytest.mark.parametrize('bpm', [128, 175])
@pytest.mark.parametrize('precursor_gain', [.2, .8])
def test_drop_refinement_distinguishes_weak_pickup_from_real_leading_kick(bpm,precursor_gain):
    sr=11025;beat=60/bpm;drop=12.
    y=np.zeros(sr*24,dtype=np.float32)
    t=np.arange(round(.18*sr))/sr
    kick=np.sin(2*np.pi*(80*t-70*t*t))*np.exp(-t*22)*np.minimum(t/.002,1)
    for i in range(-20,24):
        at=round((drop+i*beat)*sr)
        y[at:at+len(kick)]+=kick*(.08 if i<0 else 1.)
    precursor=drop-.1
    at=round(precursor*sr)
    y[at:at+len(kick)]+=kick*precursor_gain
    grid=Grid([round(.06+i*beat,3) for i in range(int(24/beat))],
              [i%4+1 for i in range(int(24/beat))])
    attacks=kick_attacks(y,sr)
    assert any(abs(a.time-precursor)<.015 for a in attacks)
    assert any(abs(a.time-drop)<.015 for a in attacks)
    match=refine_drop(y,sr,attacks,drop+.06,grid,24)
    expected=drop if precursor_gain==.2 else precursor
    assert match.time==pytest.approx(expected,abs=.015)
