import numpy as np
import pytest
from rekordbox_manager.audio_timing import saved_audio_offset, shift_samples


def sample():
    rng=np.random.default_rng(17)
    heights=rng.uniform(.05,1,9000)
    return np.repeat(heights,20),3000,heights**2


@pytest.mark.parametrize('bins',[-12,0,8,17])
def test_timeline_translation_requires_matching_regions(bins):
    y,sr,heights=sample()
    saved=shift_samples(heights,150,bins/150)
    assert saved_audio_offset(y,sr,saved)==pytest.approx(bins/150)
    shifted=shift_samples(y,sr,bins/150)
    assert len(shifted)==len(y)+bins*20


def test_unrelated_silent_and_drifting_waveforms_abstain():
    y,sr,heights=sample()
    assert saved_audio_offset(y,sr,np.ones(9000)) is None
    assert saved_audio_offset(np.zeros_like(y),sr,heights) is None
    assert saved_audio_offset(y,sr,heights[::-1]) is None
    drifting=np.concatenate([shift_samples(heights[i:i+1800],150,n/150)[:1800]
                             for n,i in zip([0,5,10,15,20],range(0,9000,1800))])
    assert saved_audio_offset(y,sr,drifting) is None
