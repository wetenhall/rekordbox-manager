"""Conservative signal-based suggestions, always requiring listening/review.

This is not a trained structural model. Unusual arrangements, syncopation and
half-time interpretations need human review. We never claim calibrated confidence.
"""
from __future__ import annotations

import math
import numpy as np
import soundfile as sf
from scipy import signal

from .models import Grid, Options, Proposal, Track
from .cues import plan_cues


def load_audio(track: Track) -> tuple[np.ndarray, int]:
    info = sf.info(str(track.path))
    if info.duration > 1800:
        raise ValueError("Tracks longer than 30 minutes are not supported in this preview.")
    if info.frames == 0 or info.channels > 8:
        raise ValueError("Unsupported audio stream.")
    # Decode in chunks so a high-resolution file doesn't allocate gigabytes.
    target = 11025
    divisor = math.gcd(info.samplerate, target)
    chunks = []
    with sf.SoundFile(str(track.path)) as file:
        while True:
            block = file.read(info.samplerate * 10, dtype="float32", always_2d=True)
            if not len(block):
                break
            mono = block.mean(axis=1)
            chunks.append(signal.resample_poly(mono, target // divisor, info.samplerate // divisor))
    y = np.concatenate(chunks)
    if not np.isfinite(y).all():
        raise ValueError("Audio contains non-finite samples.")
    if np.max(np.abs(y)) < 1e-5:
        raise ValueError("Audio is silent; drop and grid analysis cannot run.")
    return y, target


def waveform(y: np.ndarray, points: int = 12000) -> list[float]:
    edges = np.linspace(0, len(y), min(points, len(y)) + 1).astype(int)
    peaks = np.array([np.max(np.abs(y[a:b])) for a, b in zip(edges[:-1], edges[1:])])
    return (peaks / max(float(np.max(peaks)), 1e-6)).tolist()


def render_metronome(track: Track, grid: Grid, destination) -> None:
    """Offline mix keeps clicks sample-aligned; never writes to source audio."""
    y, sr = load_audio(track)
    y *= .6
    for time, position in zip(grid.times, grid.positions):
        at = int(round(time * sr))
        size = min(int(.025 * sr), len(y) - at)
        if size <= 0:
            continue
        t = np.arange(size) / sr
        click = .25 * np.sin(2 * np.pi * (1500 if position == 1 else 1000) * t) * np.exp(-t * 160)
        y[at:at + size] += click
    sf.write(str(destination), np.clip(y, -1, 1), sr, subtype="PCM_16")


def grid_suggestion(y: np.ndarray, sr: int, grid: Grid) -> tuple[Grid, str]:
    grid.validate()
    times = np.array(grid.times)
    intervals = np.diff(times)
    median = np.median(intervals)
    if np.percentile(np.abs(intervals - median), 95) > median * .015:
        return grid, "Variable-tempo grid retained. Automatic correction is unsupported; review in Rekordbox."
    _, frame_times, spectrum = signal.stft(y, sr, nperseg=512, noverlap=384)
    strength = np.maximum(np.diff(np.abs(spectrum), axis=1), 0).sum(axis=0)
    frame_times = frame_times[1:]
    peak_indices, props = signal.find_peaks(strength, distance=max(1, int(.12 * sr / 128)),
                                          prominence=max(float(np.percentile(strength, 70)), 1e-8))
    peaks = frame_times[peak_indices]
    if len(peaks) < 32:
        return grid, "Insufficient clear transients. Existing grid retained; listen before using cues."
    near = np.searchsorted(times, peaks).clip(1, len(times) - 1)
    near -= (np.abs(times[near - 1] - peaks) < np.abs(times[near] - peaks)).astype(int)
    errors = peaks - times[near]
    mask = np.abs(errors) < min(.12, median * .28)
    if mask.sum() < 32 or np.ptp(times[near[mask]]) < times[-1] * .65:
        return grid, "Beat evidence does not cover enough of the track. Existing grid retained."
    x, e = times[near[mask]], errors[mask]
    fit = np.polyfit(x, e, 1)
    residual = e - np.polyval(fit, x)
    threshold = max(.012, float(np.median(np.abs(residual))) * 2.5)
    good = np.abs(residual) < threshold
    if good.sum() < 24:
        return grid, "Ambiguous timing evidence. Existing grid retained."
    fit = np.polyfit(x[good], e[good], 1)
    drift, offset = float(fit[0]), float(fit[1])
    spread = float(np.median(np.abs(e[good] - np.polyval(fit, x[good]))))
    if spread > .035 or abs(drift) > .002 or abs(offset) > .1:
        return grid, "Timing evidence is inconsistent. Existing grid retained; manual review required."
    if abs(offset) < .012 and abs(drift * times[-1]) < .020:
        return grid, "No clear timing correction found. Existing grid retained; downbeat/half-time still need review."
    adjusted = times * (1 + drift) + offset
    if adjusted[0] < 0 or adjusted[-1] >= len(y) / sr:
        return grid, "Suggested adjustment crosses an audio boundary. Existing grid retained."
    proposed = Grid(adjusted.tolist(), grid.positions.copy())
    return proposed, f"Timing suggestion: {offset * 1000:+.0f} ms at start, {drift * times[-1] * 1000:+.0f} ms drift. Audition before approving."


def drop_suggestions(y: np.ndarray, sr: int, grid: Grid) -> tuple[float | None, float | None]:
    downbeats = np.array([t for t, p in zip(grid.times, grid.positions) if p == 1])
    if len(downbeats) < 48:
        return None, None
    low = signal.sosfilt(signal.butter(3, 180, fs=sr, output="sos"), y)
    energy = []
    for a, b in zip(downbeats[:-1], downbeats[1:]):
        part = low[int(a * sr):int(b * sr)]
        energy.append(float(np.mean(part * part)) if len(part) else 0)
    values = np.array(energy)
    scores = []
    for i in range(8, len(values) - 8):
        before, after = np.mean(values[i - 8:i]), np.mean(values[i:i + 8])
        # Avoid identifying a tiny change in a near-silent passage as a big drop.
        score = (after - before) / max(float(np.max(values)), 1e-9)
        if after > before * 1.4 and score > .06:
            scores.append((score, i))
    selected = []
    for score, index in sorted(scores, reverse=True):
        if all(abs(index - other) >= 32 for other in selected):
            selected.append(index)
        if len(selected) == 2:
            break
    selected.sort()
    if len(selected) < 2:
        return (float(downbeats[selected[0]]) if selected else None), None
    return float(downbeats[selected[0]]), float(downbeats[selected[1]])


def analyse(track: Track, options: Options) -> Proposal:
    proposal = Proposal(track, options, track.grid, track.cues.copy(), warnings=track.issues.copy())
    try:
        if not options.fix_grid and not options.set_cues:
            raise ValueError("Select at least one operation.")
        track.grid.validate()
        if not track.path.is_file():
            raise ValueError("Local audio file is unavailable.")
        y, sr = load_audio(track)
        duration = len(y) / sr
        track.duration = duration
        if track.grid.times[-1] > duration + .25:
            raise ValueError("Beat grid extends beyond the audio. Check the file association in Rekordbox.")
        proposal.peaks = waveform(y)
        candidate, assessment = grid_suggestion(y, sr, track.grid)
        if options.fix_grid:
            from .grid_writer import tempo, rounded_grid
            tempo(track.grid)  # Do not silently flatten a variable-tempo grid.
            proposal.grid, proposal.grid_note = rounded_grid(candidate), assessment
            proposal.warnings.append("Check the metronome and bar starts before import. Use Set drop 1 / bar 1 here if the bar alignment is wrong.")
        else:
            proposal.grid_note = "Existing grid retained. " + assessment
            if candidate is not track.grid:
                proposal.warnings.append("Possible grid timing error. Grid correction is off; cues will use the original grid.")
        if "bass" in track.genre.lower() and track.bpm < 120:
            proposal.warnings.append("Possible half-time drum and bass grid. Confirm BPM in Rekordbox before placing cues.")
        if options.set_cues:
            proposal.first_drop, proposal.second_drop = drop_suggestions(y, sr, proposal.grid)
            if proposal.first_drop is not None and proposal.second_drop is not None:
                proposal.cues, warnings = plan_cues(proposal.grid, proposal.first_drop, proposal.second_drop,
                                                    duration, track.cues, options.replace_memory)
                proposal.warnings += warnings
            else:
                proposal.cues_dirty = True
                proposal.warnings.append("Could not identify both drops. Set the drop anchors manually and rebuild cues.")
            proposal.warnings.append("Drop suggestions use energy changes, not a trained model. Listen and confirm both anchors.")
    except Exception as exc:
        proposal.error = str(exc)
    return proposal
