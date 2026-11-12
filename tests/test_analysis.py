import numpy as np
import pytest
import soundfile as sf
from pathlib import Path
from rekordbox_manager.analysis import analyse, render_metronome, grid_suggestion
from rekordbox_manager.models import Track, Grid, Options, Cue


def make_track(tmp_path, silent=False):
    sr = 11025
    y = np.zeros(sr * 64, dtype=np.float32)
    for i in range(120):
        start = int((.2 + i * .5) * sr)
        t = np.arange(300) / sr
        if not silent:
            y[start:start + 300] += .6 * np.exp(-t * 100) * np.sin(2 * np.pi * 65 * t)
    path = tmp_path / 'track.wav'
    sf.write(path, y, sr)
    grid = Grid([.25 + i * .5 for i in range(120)], [i % 4 + 1 for i in range(120)])
    return Track('t', 'Test', 'Artist', 'House', path, 64, 120, grid, [Cue(1, 'Hot A', 'hot')])


def test_missing_audio_is_reported(tmp_path):
    track = make_track(tmp_path)
    track.path.unlink()
    p = analyse(track, Options(True, True))
    assert 'unavailable' in p.error and not p.can_apply


def test_silent_audio_cannot_be_approved(tmp_path):
    p = analyse(make_track(tmp_path, True), Options(False, True))
    assert 'silent' in p.error


def test_cues_only_never_changes_grid(tmp_path):
    track = make_track(tmp_path)
    p = analyse(track, Options(False, True))
    assert p.grid == track.grid
    assert not p.can_apply


@pytest.mark.parametrize('fix_grid,uncertain_drop', [(False, True), (True, True), (True, False)])
def test_detection_uncertainty_can_be_confirmed_without_rebuilding(tmp_path, monkeypatch, fix_grid, uncertain_drop):
    from copy import deepcopy
    from rekordbox_manager.analysis import confirm_proposal_review
    from rekordbox_manager.attacks import AttackMatch
    track = make_track(tmp_path)
    monkeypatch.setattr('rekordbox_manager.analysis.drop_suggestions', lambda *args: (16.25, 48.25))
    monkeypatch.setattr('rekordbox_manager.analysis.refine_drop',
                        lambda y, sr, attacks, target, *args, **kwargs: AttackMatch(target, 'Check the attack', uncertain_drop))
    monkeypatch.setattr('rekordbox_manager.analysis.rhythm_issue', lambda *args: 'Not enough drum evidence' if not uncertain_drop else '')
    p = analyse(track, Options(fix_grid, True))
    assert p.review_note and not p.error and not p.grid_issue and not p.cues_dirty
    assert not p.ready_to_apply
    before = deepcopy((p.grid, p.cues, p.first_drop, p.second_drop))
    confirm_proposal_review(p)
    assert p.ready_to_apply and p.can_apply
    assert (p.grid, p.cues, p.first_drop, p.second_drop) == before


def test_grid_only_keeps_every_cue(tmp_path):
    track = make_track(tmp_path)
    p = analyse(track, Options(True, False))
    assert p.cues == track.cues
    assert p.first_drop is None and p.second_drop is None
    assert not p.can_apply


def test_metronome_render_preserves_source_and_duration(tmp_path):
    from rekordbox_manager.backups import digest
    track = make_track(tmp_path)
    before = digest(track.path)
    out = tmp_path / 'preview.wav'
    render_metronome(track, track.grid, out)
    assert sf.info(out).duration == pytest.approx(64, abs=.01)
    assert digest(track.path) == before
    assert digest(out) != before


def test_large_grid_discontinuity_is_not_flattened():
    g = Grid([i * .5 if i < 200 else 100 + (i - 200) * .4 for i in range(400)], [i % 4 + 1 for i in range(400)])
    proposed, note = grid_suggestion(np.ones(2000), 100, g)
    assert proposed is g and 'Variable-tempo' in note


def test_missing_drop_detection_cannot_import_unchanged_cue_list(tmp_path):
    p = analyse(make_track(tmp_path), Options(False, True))
    assert not p.error and (p.first_drop is None or p.second_drop is None)
    assert p.cues_dirty and not p.ready_to_apply


def test_drop_alignment_uses_original_tempo_not_flux_drift(tmp_path, monkeypatch):
    track = make_track(tmp_path)
    corrected = Grid([.2 + i*.5 for i in range(120)],track.grid.positions.copy())
    monkeypatch.setattr('rekordbox_manager.analysis.grid_suggestion',lambda y,sr,g:(corrected,'Adjusted'))
    seen=[]
    def drops(y,sr,g,attacks):
        seen.append(g)
        return None,None
    monkeypatch.setattr('rekordbox_manager.analysis.drop_suggestions',drops)
    proposal=analyse(track,Options(True,True))
    assert not proposal.error and seen==[track.grid]
    assert proposal.grid==track.grid


@pytest.mark.parametrize('fix_grid',[False,True])
def test_cue_workflow_reuses_rekordbox_waveforms_and_skips_general_tempo_analysis(tmp_path,monkeypatch,fix_grid):
    from test_rekordbox_waveforms import saved_files
    from rekordbox_manager.waveform_data import rekordbox_waveforms
    track=make_track(tmp_path)
    track.analysis_paths=saved_files(tmp_path,64)
    saved=rekordbox_waveforms(track.analysis_paths,64)
    def forbidden(*args):raise AssertionError('Existing analysis was recomputed')
    monkeypatch.setattr('rekordbox_manager.waveform_data.audio_waveforms',forbidden)
    monkeypatch.setattr('rekordbox_manager.analysis.grid_suggestion',forbidden)
    proposal=analyse(track,Options(fix_grid,True))
    assert not proposal.error
    data=proposal.waveform_data
    assert data.source=='Rekordbox saved waveform' and data.peaks==saved.peaks and data.bands==saved.bands
    assert data.sample_rate==150 and data.channel_rate==1000
    assert len(data.channels)==1 and len(data.channels[0])==64000
    assert proposal.track.bpm==120 and proposal.track.grid==track.grid


def test_saved_waveform_offset_applies_to_drop_audio_stereo_and_metronome(tmp_path):
    from test_rekordbox_waveforms import anlz,tag
    from rekordbox_manager.analysis import load_audio
    track=make_track(tmp_path)
    y,sr=load_audio(track)
    count=int(len(y)/sr*150)
    edges=(np.arange(count)*sr/150).astype(int)
    heights=np.maximum.reduceat(np.abs(y),edges)
    heights=np.pad(heights/np.max(heights),(8,0))
    words=(np.round(heights**2*31).astype('>u2')<<2).astype('>u2')
    ext=anlz(tmp_path/'offset.EXT',tag(b'PWV5',words.tobytes(),2))
    bands=np.repeat(np.round(heights*127).astype(np.uint8)[:,None],3,axis=1)
    two=anlz(tmp_path/'offset.2EX',tag(b'PWV7',bands.tobytes(),3))
    track.analysis_paths=[ext,two]
    proposal=analyse(track,Options(True,True))
    assert not proposal.error and track.audio_offset==pytest.approx(8/150)
    shifted,_=load_audio(track)  # same clock used to render metronome audio
    assert len(shifted)==len(y)+round(8/150*sr)
    assert np.argmax(np.abs(shifted))==np.argmax(np.abs(y))+round(8/150*sr)
    assert len(proposal.waveform_data.channels[0])==64000+round(8/150*1000)
    first=track.audio_offset
    analyse(track,Options(True,True))
    assert track.audio_offset==first  # preparing again must not compound the shift


@pytest.mark.parametrize('fix_grid',[False,True])
@pytest.mark.parametrize('bpm,syncopated',[(128,False),(138,False),(174,True)])
@pytest.mark.parametrize('weak_pickup',[False,True])
def test_structural_drops_and_grid_alignment(tmp_path,bpm,syncopated,fix_grid,weak_pickup):
    sr=8000;beat=60/bpm;lead=.4;bars=120
    y=np.zeros(round((lead+bars*4*beat)*sr),dtype=np.float32)
    t=np.arange(round(.18*sr))/sr
    kick=np.sin(2*np.pi*(80*t-70*t*t))*np.exp(-t*22)*np.minimum(t/.002,1)
    for i in range(bars*4):
        if syncopated and i%4 not in (0,2):continue
        onset=lead+i*beat+(beat/2 if syncopated and i%4==2 else 0)
        gain=.8 if 32<=i//4<64 or i//4>=96 else .08
        start=round(onset*sr);size=min(len(kick),len(y)-start)
        y[start:start+size]+=kick[:size]*gain
    if weak_pickup:
        # A weak hit before the real Drop 1 must not move either the grid or cue
        # off the main attack, even though the long bass windows score similarly.
        start=round((lead+32*4*beat-.1)*sr)
        y[start:start+len(kick)]+=kick*.16
    path=tmp_path/'structured.wav';sf.write(path,y,sr)
    g=Grid([lead+i*beat+.06 for i in range(bars*4)],[i%4+1 for i in range(bars*4)])
    original=g.times.copy()
    track=Track('structured','Structured test','','',path,len(y)/sr,bpm,g)
    p=analyse(track,Options(fix_grid,True))
    assert not p.error
    assert p.first_drop==pytest.approx(lead+32*4*beat,abs=.015)
    assert p.second_drop==pytest.approx(lead+96*4*beat,abs=.015)
    assert next(c.time for c in p.cues if c.label=='DROP 1')==p.first_drop
    assert next(c.time for c in p.cues if c.label=='DROP 2')==p.second_drop
    assert g.times==original
    if fix_grid:
        assert not p.grid_issue, p.grid_issue
        assert p.ready_to_apply, p.drop_notes
        assert all(c.time in p.grid.times for c in p.cues)
        assert p.grid.times[128]==p.first_drop and p.grid.positions[128]==1
    else:
        assert p.grid is g
        assert p.review_note and not p.cues_dirty and any('grid was not moved' in note for note in p.drop_notes)


@pytest.mark.parametrize('off_grid,unmatched_audio', [(True, False), (False, True), (True, True)])
def test_complete_uncertain_proposal_can_be_confirmed_without_regeneration(tmp_path, monkeypatch, off_grid, unmatched_audio):
    from copy import deepcopy
    from rekordbox_manager.analysis import confirm_proposal_review, review_confirmation_error
    from rekordbox_manager.attacks import AttackMatch
    from test_rekordbox_waveforms import saved_files
    track = make_track(tmp_path)
    if unmatched_audio:
        track.analysis_paths = saved_files(tmp_path, 64)
        monkeypatch.setattr('rekordbox_manager.audio_timing.saved_audio_offset', lambda *args: None)
    second = 48.343 if off_grid else 48.25
    monkeypatch.setattr('rekordbox_manager.analysis.drop_suggestions', lambda *args: (16.25, second))
    monkeypatch.setattr('rekordbox_manager.analysis.refine_drop',
                        lambda y, sr, attacks, target, *args, **kwargs: AttackMatch(target, 'Clear attack', False))
    monkeypatch.setattr('rekordbox_manager.analysis.rhythm_issue', lambda *args: '')
    p = analyse(track, Options(True, True))
    assert not p.error and not p.grid_issue and not p.cues_dirty
    assert p.review_note and not p.ready_to_apply and not p.can_apply
    assert not review_confirmation_error(p)
    assert next(c.time for c in p.cues if c.label == 'DROP 2') == second
    if off_grid:
        assert '+93 ms' in p.review_note and p.preserve_drop_positions
    if unmatched_audio:
        assert 'could not be matched' in p.review_note
    before = deepcopy((p.grid, p.cues, p.first_drop, p.second_drop, track.grid))
    def forbidden(*args, **kwargs):
        pytest.fail('Confirmation must not analyse or rebuild')
    monkeypatch.setattr('rekordbox_manager.analysis.rebuild_proposal', forbidden)
    monkeypatch.setattr('rekordbox_manager.analysis.load_audio', forbidden)
    confirm_proposal_review(p)
    assert p.ready_to_apply and p.can_apply
    assert (p.grid, p.cues, p.first_drop, p.second_drop, track.grid) == before


def test_audio_uncertainty_does_not_allow_missing_cues_to_be_confirmed(tmp_path, monkeypatch):
    from test_rekordbox_waveforms import saved_files
    from rekordbox_manager.analysis import review_confirmation_error
    track = make_track(tmp_path)
    track.analysis_paths = saved_files(tmp_path, 64)
    monkeypatch.setattr('rekordbox_manager.audio_timing.saved_audio_offset', lambda *args: None)
    monkeypatch.setattr('rekordbox_manager.analysis.drop_suggestions', lambda *args: (None, None))
    p = analyse(track, Options(True, True))
    assert p.review_note and p.cues_dirty
    assert review_confirmation_error(p) and not p.can_apply
