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


def test_grid_correction_precedes_drop_detection(tmp_path, monkeypatch):
    track = make_track(tmp_path)
    corrected = Grid([.2 + i*.5 for i in range(120)],track.grid.positions.copy())
    monkeypatch.setattr('rekordbox_manager.analysis.grid_suggestion',lambda y,sr,g:(corrected,'Adjusted'))
    seen=[]
    def drops(y,sr,g):
        seen.append(g)
        return None,None
    monkeypatch.setattr('rekordbox_manager.analysis.drop_suggestions',drops)
    proposal=analyse(track,Options(True,True))
    assert not proposal.error and seen==[corrected]
    assert proposal.grid==corrected
