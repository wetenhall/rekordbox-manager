"""Compact millisecond peak data, reduced to pixels only at display time."""
from array import array
import math
import struct
import numpy as np
from dataclasses import dataclass, field
import soundfile as sf
from scipy import signal


@dataclass
class WaveformData:
    peaks: array = field(default_factory=lambda: array('f'))
    bands: tuple[array, ...] = field(default_factory=lambda: tuple(array('f') for _ in range(3)))
    channels: tuple[array, ...] = field(default_factory=tuple)
    source: str = 'Audio preview'
    sample_rate: float = 0.
    band_rate: float = 0.
    channel_rate: float = 0.


def _floats(values):
    result = array('f')
    result.frombytes(np.asarray(values, dtype=np.float32).tobytes())
    return result


def rekordbox_waveforms(paths, duration):
    """Read detailed ANLZ waveforms without modifying any analysis file.

    PWV3/PWV5/PWV7 have a fixed 150 entries/s clock, not a duration-scaled
    overview. PWV7 detail stores low, mid, high in the supported native files.
    Its display heights are compressed
    frequency summaries, not raw PCM or exact isolated band amplitudes.
    Format: https://djl-analysis.deepsymmetry.org/rekordbox-export-analysis/anlz.html
    """
    tags = {}
    for path in sorted(paths, key=str):
        if path.suffix.upper() not in ('.DAT', '.EXT', '.2EX'):
            continue
        try:
            if path.stat().st_size > 20_000_000:
                continue
            blob = path.read_bytes()
            if len(blob) < 28 or blob[:4] != b'PMAI':
                continue
            offset, total = struct.unpack_from('>II', blob, 4)
            if total != len(blob) or not 28 <= offset <= total:
                continue
            found = {}
            while offset < total:
                if offset + 12 > total:
                    raise ValueError('Truncated analysis tag')
                kind, header, length = struct.unpack_from('>4sII', blob, offset)
                if not 12 <= header <= length or offset + length > total:
                    raise ValueError('Invalid analysis tag length')
                if kind in (b'PWV3', b'PWV5', b'PWV7'):
                    if header != 24:
                        raise ValueError('Unsupported waveform header')
                    size, count = struct.unpack_from('>II', blob, offset + 12)
                    expected = {b'PWV3': 1, b'PWV5': 2, b'PWV7': 3}[kind]
                    if size != expected or count == 0 or header + size * count != length:
                        raise ValueError('Invalid waveform entries')
                    # Refuse stale/incompatible lengths instead of stretching
                    # their samples and visually moving attacks off the grid.
                    if abs(count / 150 - duration) <= .1:
                        found[kind] = blob[offset + header:offset + length]
                offset += length
            tags.update(found)
        except (OSError, ValueError, struct.error):
            continue
    data = WaveformData(source='Rekordbox saved waveform', sample_rate=150.)
    if b'PWV5' in tags:
        words = np.frombuffer(tags[b'PWV5'], dtype='>u2')
        data.peaks = _floats(((words >> 2) & 31) / 31.)
    elif b'PWV3' in tags:
        data.peaks = _floats((np.frombuffer(tags[b'PWV3'], dtype=np.uint8) & 31) / 31.)
    if b'PWV7' in tags:
        heights = np.frombuffer(tags[b'PWV7'], dtype=np.uint8).reshape(-1, 3).astype(float)
        # Shared display scaling preserves relative band heights. These are
        # Rekordbox display values, not calibrated audio amplitudes.
        heights /= max(float(heights.max()), 1.)
        data.bands = tuple(_floats(heights[:, index]) for index in (0, 1, 2))
        data.band_rate = 150.
        if not data.peaks:
            data.peaks = _floats(heights.max(axis=1))
    return data if data.peaks else None


def track_waveforms(track):
    saved = rekordbox_waveforms(track.analysis_paths, track.duration)
    if saved is not None and all(len(band) for band in saved.bands):
        return saved
    generated = audio_waveforms(track.path)
    if saved is None:
        generated.source = 'Audio fallback: no usable saved detailed waveform'
        return generated
    saved.bands, saved.channels = generated.bands, generated.channels
    saved.source = 'Rekordbox saved waveform; missing bands from audio'
    return saved


def audio_waveforms(path):
    """Native-rate, channel-preserving envelopes with a shared amplitude scale.

    Process ten seconds at a time with filter overlap, retaining only 1 ms
    peaks. Zero-phase filters avoid adding delay to the displayed transients.
    Mono has one channel; multichannel sources display their first two channels.
    """
    with sf.SoundFile(str(path)) as source:
        sr = source.samplerate
        if source.frames == 0 or source.channels > 8 or source.frames / sr > 1800:
            raise ValueError('Unsupported audio stream for waveform display.')
        data = WaveformData(channels=tuple(array('f') for _ in range(min(2, source.channels))))
        # On low sample-rate sources keep both cutoffs below Nyquist.
        high = min(2500, sr * .4)
        low = min(250, high / 4)
        filters = [signal.butter(4, cutoff, btype=kind, fs=sr, output='sos')
                   for cutoff, kind in ((low, 'lowpass'), ((low, high), 'bandpass'), (high, 'highpass'))]
        overlap = round(sr * .1)
        for start in range(0, source.frames, sr * 10):
            stop = min(source.frames, start + sr * 10)
            read_start = max(0, start - overlap)
            source.seek(read_start)
            block = source.read(min(source.frames, stop + overlap) - read_start,
                                dtype='float32', always_2d=True)
            if not np.isfinite(block).all():
                raise ValueError('Audio contains non-finite samples.')
            central = slice(start - read_start, stop - read_start)
            raw = block[central]
            count = math.ceil(len(raw) / sr * 1000)
            edges = np.linspace(0, len(raw), count + 1, dtype=np.int64)[:-1]

            def append(destination, samples):
                peaks = np.maximum.reduceat(np.abs(samples), edges).astype(np.float32)
                destination.frombytes(peaks.tobytes())

            append(data.peaks, np.max(np.abs(raw), axis=1))
            for index, destination in enumerate(data.channels):
                append(destination, raw[:, index])
            for sos, destination in zip(filters, data.bands):
                filtered = signal.sosfiltfilt(sos, block, axis=0, padlen=min(27, len(block) - 1))
                append(destination, np.max(np.abs(filtered[central]), axis=1))
        scale = max(max(data.peaks, default=0), 1e-6)
        for envelope in (data.peaks, *data.bands, *data.channels):
            values = np.frombuffer(envelope, dtype=np.float32)
            values /= scale
            np.clip(values, 0, 1, out=values)
        return data


def peak_envelope(y, sr, points=None):
    if not len(y):
        return array('f')
    count = min(len(y), points if points is not None else math.ceil(len(y) / sr * 1000))
    edges = np.linspace(0, len(y), count + 1, dtype=np.int64)
    peaks = np.maximum.reduceat(np.abs(y), edges[:-1])
    peaks = (peaks / max(float(np.max(peaks)), 1e-6)).astype(np.float32)
    result = array('f')
    result.frombytes(peaks.tobytes())
    return result


def pixel_peaks(peaks, duration, start, end, width):
    """Draw each screen pixel once; never widen a peak around its timestamp."""
    if not len(peaks) or width <= 0 or end <= start or duration <= 0:
        return np.zeros(max(0, width), dtype=np.float32)
    values = np.frombuffer(peaks, dtype=np.float32) if isinstance(peaks, array) else np.asarray(peaks, dtype=np.float32)
    edges = np.floor(np.linspace(start, end, width + 1) / duration * len(values)).astype(np.int64)
    edges = np.clip(edges, 0, len(values))
    left, right = int(edges[0]), int(edges[-1])
    # Include a sample for pixels narrower than a stored bin. A sentinel permits
    # an exact end-of-track boundary without scanning audio outside the viewport.
    right = min(len(values), max(right, left + 1))
    segment = np.r_[values[left:right], np.float32(0)]
    return np.maximum.reduceat(segment, edges - left)[:-1]
