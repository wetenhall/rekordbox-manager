"""Match decoded audio to the saved ANLZ clock without changing tempo."""
import numpy as np


def saved_audio_offset(y, sr, peaks, rate=150):
    """Require agreeing waveform matches in independent regions.

    MP3 decoders can trim encoder padding differently from Rekordbox. Estimate
    a translation only, to the saved waveform's 1/150-second resolution. Sparse,
    ambiguous or inconsistent evidence abstains instead of guessing a grid shift.
    """
    count = min(int(len(y) / sr * rate), len(peaks))
    if count < rate * 6:
        return None
    edges = (np.arange(count) * sr / rate).astype(np.int64)
    audio = np.maximum.reduceat(np.abs(y), edges).astype(float)
    saved = np.sqrt(np.asarray(peaks, dtype=float))
    radius = round(rate * .25)
    width = min(round(rate * 12), (count - 2 * radius) // 5)
    offsets = []
    for start in np.linspace(radius, count-radius-width, 5, dtype=int):
        a = audio[start:start+width]
        a = a-a.mean()
        norm = np.linalg.norm(a)
        if norm < 1e-5:
            continue
        scores = []
        for lag in range(-radius, radius+1):
            b = saved[start+lag:start+lag+width]
            b = b-b.mean()
            scores.append(float(a @ b / max(norm*np.linalg.norm(b), 1e-12)))
        winner = int(np.argmax(scores))
        alternative = max(s for i,s in enumerate(scores) if abs(i-winner)>2)
        if scores[winner] >= .65 and scores[winner]-alternative >= .03 and winner not in (0,2*radius):
            offsets.append(winner-radius)
    if len(offsets) < 3 or max(offsets)-min(offsets) > 1:
        return None
    return round(float(np.median(offsets))) / rate


def shift_samples(samples, rate, offset):
    count = round(offset * rate)
    return np.pad(samples, (count,0)) if count >= 0 else samples[-count:]
