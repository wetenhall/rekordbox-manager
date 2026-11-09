from array import array
import numpy as np
import pytest
from rekordbox_manager.waveform_data import peak_envelope, pixel_peaks


def test_five_minute_track_preserves_transient_time_at_high_zoom():
    sr=8000;duration=300;at=264.872
    y=np.zeros(sr*duration,dtype=np.float32)
    y[round(at*sr)]=1
    peaks=peak_envelope(y,sr)
    assert isinstance(peaks,array) and len(peaks)==300000
    peak_time=int(np.argmax(peaks))/len(peaks)*duration
    assert abs(peak_time-at)<=.001
    start,end,width=262.5,267.5,1200
    columns=pixel_peaks(peaks,duration,start,end,width)
    drawn_time=start+int(np.argmax(columns))/width*(end-start)
    assert abs(drawn_time-at)<=.001+(end-start)/width
    # The old 12,000-bin envelope put this attack visibly early.
    coarse=peak_envelope(y,sr,12000)
    old_bin_time=int(np.argmax(coarse))/len(coarse)*duration
    assert at-old_bin_time>.015


def test_zoomed_view_excludes_loud_audio_outside_view():
    peaks=array('f',[0]*1000)
    peaks[450]=.3;peaks[800]=1
    columns=pixel_peaks(peaks,10,4,5,100)
    assert max(columns)==pytest.approx(.3)
    assert int(np.argmax(columns))==50


def test_reduction_keeps_peaks_at_both_track_edges_and_sparse_zoom():
    peaks=array('f',[1,0,0,0,.5])
    assert pixel_peaks(peaks,5,0,5,1)[0]==1
    assert pixel_peaks(peaks,5,0,5,10)[-1]==.5
    assert max(pixel_peaks(peaks,5,4.1,4.2,100))==.5


@pytest.mark.parametrize('frequency,expected', [(70, 0), (1000, 1), (8000, 2)])
def test_frequency_bands_follow_audio_and_preserve_native_highs(tmp_path, frequency, expected):
    import soundfile as sf
    from rekordbox_manager.waveform_data import audio_waveforms
    sr = 44100
    y = .7 * np.sin(2 * np.pi * frequency * np.arange(sr) / sr)
    path = tmp_path / 'tone.wav'
    sf.write(path, y, sr, subtype='FLOAT')
    data = audio_waveforms(path)
    strengths = [np.mean(band[100:900]) for band in data.bands]
    assert np.argmax(strengths) == expected
    assert strengths[expected] > 5 * max(v for i, v in enumerate(strengths) if i != expected)
    assert len(data.peaks) == 1000 and len(data.channels) == 1


def test_stereo_keeps_channel_balance_and_chunk_boundary_timing(tmp_path):
    import soundfile as sf
    from rekordbox_manager.waveform_data import audio_waveforms
    sr = 8000
    y = np.zeros((sr * 11, 2), dtype=np.float32)
    for at in (9.999, 10, 10.001):
        y[round(at * sr)] = [1, .2]
    path = tmp_path / 'stereo.wav'
    sf.write(path, y, sr, subtype='FLOAT')
    data = audio_waveforms(path)
    assert len(data.peaks) == 11000
    assert np.flatnonzero(data.peaks).tolist() == [9999, 10000, 10001]
    assert max(data.channels[0]) == 1
    assert max(data.channels[1]) == pytest.approx(.2)
    assert all(len(envelope) == 11000 for envelope in (*data.channels, *data.bands))


def test_mono_and_short_silent_audio_have_finite_envelopes(tmp_path):
    import soundfile as sf
    from rekordbox_manager.waveform_data import audio_waveforms
    path = tmp_path / 'short.wav'
    sf.write(path, np.zeros(1), 44100)
    data = audio_waveforms(path)
    assert len(data.channels) == 1
    assert all(list(envelope) == [0] for envelope in (data.peaks, *data.channels, *data.bands))
