import struct
from array import array

import numpy as np
import pytest

from rekordbox_manager.waveform_data import rekordbox_waveforms, track_waveforms, WaveformData


def anlz(path, *tags):
    body=b''.join(tags)
    path.write_bytes(struct.pack('>4s6I',b'PMAI',28,28+len(body),0,0,0,0)+body)
    return path


def tag(kind, payload, size):
    return struct.pack('>4s5I',kind,24,24+len(payload),size,len(payload)//size,0)+payload


def saved_files(tmp_path, duration=2):
    count=round(duration*150)
    heights=np.zeros(count,dtype='>u2');heights[150]=(31<<2)|(7<<13)
    ext=anlz(tmp_path/'track.EXT',tag(b'PWV5',heights.tobytes(),2))
    bands=np.tile(np.array([64,32,255],dtype=np.uint8),(count,1))
    two=anlz(tmp_path/'track.2EX',tag(b'PWV7',bands.tobytes(),3))
    return [ext,two]


def test_saved_detail_decodes_heights_band_order_and_clock_without_writes(tmp_path):
    paths=saved_files(tmp_path)
    original=[p.read_bytes() for p in paths]
    data=rekordbox_waveforms(paths,2.04)
    assert data.source=='Rekordbox saved waveform'
    assert data.sample_rate==data.band_rate==150
    assert len(data.peaks)==300 and data.peaks[150]==1
    assert np.argmax(data.peaks)/data.sample_rate==1  # never stretch to 2.04 s
    assert [b[0] for b in data.bands]==pytest.approx([64/255,32/255,1])
    assert not data.channels  # ANLZ has no stereo channels
    assert [p.read_bytes() for p in paths]==original


def test_saved_detail_is_used_without_audio_regeneration(tmp_path,monkeypatch):
    from types import SimpleNamespace
    track=SimpleNamespace(analysis_paths=saved_files(tmp_path),duration=2.,path=tmp_path/'not-opened.wav')
    def forbidden(*args):raise AssertionError('Audio waveform was unnecessarily regenerated')
    monkeypatch.setattr('rekordbox_manager.waveform_data.audio_waveforms',forbidden)
    assert track_waveforms(track).sample_rate==150


def test_monochrome_detail_and_band_only_files_supported(tmp_path):
    ext=anlz(tmp_path/'mono.EXT',tag(b'PWV3',bytes([255])*300,1))
    data=rekordbox_waveforms([ext],2)
    assert list(data.peaks)==[1]*300 and not any(data.bands)
    two=saved_files(tmp_path)[1]
    data=rekordbox_waveforms([two],2)
    assert list(data.peaks)==[1]*300 and data.band_rate==150


def test_invalid_or_stale_detail_does_not_get_stretched_or_block_good_file(tmp_path):
    paths=saved_files(tmp_path)
    assert rekordbox_waveforms(paths,3) is None
    bad=anlz(tmp_path/'bad.EXT',struct.pack('>4sII',b'PWV5',24,0))
    assert rekordbox_waveforms([bad],2) is None
    assert rekordbox_waveforms([bad,*paths],2).sample_rate==150
    bad.write_bytes(paths[0].read_bytes()[:-1])
    assert rekordbox_waveforms([bad],2) is None
    # Other containers and an overview alone cannot replace detailed timing.
    unknown=tmp_path/'track.3EX';unknown.write_bytes(b'not a PMAI container')
    dat=anlz(tmp_path/'overview.DAT',struct.pack('>4sII',b'PWAV',12,12))
    assert rekordbox_waveforms([unknown,dat,tmp_path/'missing.EXT'],2) is None


@pytest.mark.parametrize('has_mono',[False,True])
def test_missing_data_falls_back_explicitly_and_keeps_saved_amplitude(tmp_path,monkeypatch,has_mono):
    from types import SimpleNamespace
    mono=anlz(tmp_path/'mono.EXT',tag(b'PWV3',bytes([31])*300,1))
    generated=WaveformData(array('f',[.3]*2000),tuple(array('f',[.2]*2000) for _ in range(3)),(array('f',[.4]*2000),))
    calls=[]
    monkeypatch.setattr('rekordbox_manager.waveform_data.audio_waveforms',lambda path:(calls.append(path) or generated))
    track=SimpleNamespace(analysis_paths=[mono] if has_mono else [],duration=2.,path=tmp_path/'audio.wav')
    data=track_waveforms(track)
    assert calls==[track.path] and data.bands==generated.bands and data.channels==generated.channels
    assert 'audio' in data.source.lower()
    assert data.sample_rate==(150 if has_mono else 0)
    assert len(data.peaks)==(300 if has_mono else 2000)
