import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from array import array
from dataclasses import replace
import time
import threading
import numpy as np
import pytest
import soundfile as sf
from PySide6.QtWidgets import QApplication
from rekordbox_manager.models import Track, Grid, Cue
from rekordbox_manager.overview_loader import load_overview, overview_key, OverviewData
from rekordbox_manager.waveform_data import WaveformData


def track_at(path):
    return Track('one', 'First', 'Artist', '', path, 2, 120, Grid([0, .5], [1, 2]), [Cue(.5, 'Cue')])


def test_bass_preview_distinguishes_low_and_high_frequencies_and_is_readonly(tmp_path):
    path = tmp_path / 'tone.wav'
    sr = 16000
    t = np.arange(sr) / sr
    sf.write(path, np.r_[.8*np.sin(2*np.pi*80*t), .8*np.sin(2*np.pi*4000*t)], sr)
    before = path.read_bytes()
    track = track_at(path)
    data = load_overview(track, lambda: False)
    assert len(data.peaks) == len(data.bass) == 512
    assert np.median(data.bass[20:230]) > .8
    assert np.median(data.bass[280:490]) < .05
    assert np.median(data.peaks[280:490]) > .8
    assert path.read_bytes() == before and track.cues == [Cue(.5, 'Cue')]


def test_saved_bass_needs_no_audio_decode(tmp_path, monkeypatch):
    saved = WaveformData(peaks=array('f', [.2, .8]), bands=tuple(array('f', [.1, .6]) for _ in range(3)))
    monkeypatch.setattr('rekordbox_manager.overview_loader.rekordbox_waveforms', lambda *args: saved)
    def forbidden(*args, **kwargs):
        raise AssertionError('Saved bass should not decode audio')
    monkeypatch.setattr('rekordbox_manager.overview_loader.audio_waveforms', forbidden)
    data = load_overview(track_at(tmp_path/'offline.wav'), lambda: False)
    assert len(data.bass) and not data.error


def test_unavailable_bass_retains_saved_amplitude_and_reports_fallback(tmp_path, monkeypatch):
    saved = WaveformData(peaks=array('f', [.2, .8]))
    monkeypatch.setattr('rekordbox_manager.overview_loader.rekordbox_waveforms', lambda *args: saved)
    data = load_overview(track_at(tmp_path/'offline.wav'), lambda: False)
    assert len(data.peaks) and not len(data.bass)
    assert 'Bass preview unavailable' in data.error


def test_cancel_during_audio_loading(tmp_path):
    path = tmp_path/'tone.wav'
    sf.write(path, np.zeros(16000), 16000)
    with pytest.raises(InterruptedError):
        load_overview(track_at(path), lambda: True)


def test_cache_key_changes_when_source_changes(tmp_path):
    path = tmp_path/'audio.wav'
    path.write_bytes(b'first')
    track = track_at(path)
    key = overview_key(track)
    path.write_bytes(b'changed audio')
    assert overview_key(track) != key


def pump_until(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def test_all_rows_load_without_selection_and_old_playlist_cannot_overwrite(tmp_path, monkeypatch):
    from rekordbox_manager.ui import MainWindow
    monkeypatch.setenv('REKORDBOX_MANAGER_DATA_DIR', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    entered, release = threading.Event(), threading.Event()
    calls = []
    def load(track, cancelled):
        calls.append(track.id)
        if track.id == 'old':
            entered.set()
            release.wait(3)
        return OverviewData(2, [.7]*512, [.3 if track.id == 'old' else .6]*512)
    monkeypatch.setattr('rekordbox_manager.overview_loader.load_overview', load)
    window = MainWindow()
    try:
        old = replace(track_at(tmp_path/'old.wav'), id='old')
        window.tracks = [old]
        window.populate_table()
        assert entered.wait(2)
        window.tracks = [replace(old, id=str(i), path=tmp_path/f'{i}.wav') for i in range(3)]
        window.populate_table()
        release.set()
        pump_until(app, lambda: window.overview_worker is None)
        assert all(p.bass == [.6]*512 for p in window.row_previews)
        assert window.table.currentRow() == 0
        assert set(calls) == {'old', '0', '1', '2'}
        row = window.table._buttons[0].layout().itemAt(0).widget().layout()
        assert row.itemAt(1).widget() is window.row_previews[0]
        assert row.itemAt(2).widget().full_text == 'First'
        window.populate_table()
        assert window.overview_worker is None  # All previews reused from compact cache.
        assert all(p.bass == [.6]*512 for p in window.row_previews)
    finally:
        release.set()
        window.close()
        app.processEvents()
