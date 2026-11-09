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
from .attacks import kick_attacks, refine_drop
from .drop_grid import align_drops, rhythm_issue
from .guards import SafetyError


def rebuild_proposal(proposal: Proposal, *, manual: bool = False) -> None:
    """Use edited anchors, retaining the original tempo on every rebuild."""
    p = proposal
    p.review_note = ""
    p.preserve_drop_positions = False
    p.cues_dirty = True
    p.reviewed = p.grid_approved = False
    first, second = p.first_drop, p.second_drop
    if first is None or second is None:
        raise ValueError("Set both drop markers before rebuilding.")
    before = (first, second)
    grid = p.grid
    issue = ""
    review_note = ""
    if p.options.fix_grid:
        try:
            grid, first, second, issue = align_drops(p.track.grid, first, second, p.track.duration,
                                                       reference=p.grid_anchor, first_edited=manual or p.first_drop_edited,
                                                       second_edited=manual or p.second_drop_edited)
            if manual and issue:
                # A valid translated grid can coexist with an intentionally
                # off-grid cue. Only an explicit manual rebuild offers this.
                other = second if p.grid_anchor == 1 else first
                offset = other - grid.times[grid.nearest_downbeat(other)]
                review_note = (f"Drop {3 - p.grid_anchor} is {offset * 1000:+.0f} ms from a bar start. "
                               "Your marker positions are kept; BPM is unchanged. Listen and confirm review to accept these timings.")
                p.preserve_drop_positions = True
                issue = ""
        except (ValueError, SafetyError) as exc:
            issue = f"Cannot shift the grid: {exc} Import is blocked."
    if issue:
        p.grid = grid
        p.grid_issue = issue
        p.drop_notes = []
        p.warnings = p.track.issues.copy()
        p.grid_note = issue
        p.cues_dirty = True
        p.reviewed = p.grid_approved = False
        return
    cues, warnings = plan_cues(grid, first, second, p.track.duration, p.track.cues,
                               p.options.replace_memory, preserve_anchors=not p.options.fix_grid or p.preserve_drop_positions)
    p.grid, p.first_drop, p.second_drop, p.cues = grid, first, second, cues
    p.grid_issue = ""
    p.cues_dirty = False
    p.reviewed = p.grid_approved = False
    p.drop_notes = []
    p.warnings = p.track.issues + warnings + ["Listen to both drop anchors before importing."]
    if manual:
        rebuilt = "Cues and grid rebuilt." if p.options.fix_grid else "Cues rebuilt; existing grid kept."
        p.review_note = review_note or rebuilt + " Check the result, then confirm review to make this track ready for import."
    if p.options.fix_grid:
        anchor = first if p.grid_anchor == 1 else second
        original_index = min(range(len(p.track.grid.times)), key=lambda i: abs(p.track.grid.times[i] - anchor))
        offset = anchor - p.track.grid.times[original_index]
        other = 2 if p.grid_anchor == 1 else 1
        adjustment = (first, second)[other - 1] - before[other - 1]
        p.grid_note = (f"Grid shifted {offset * 1000:+.0f} ms to Drop {p.grid_anchor}; BPM unchanged. "
                       + ("Cue markers retain your chosen positions. " if p.preserve_drop_positions else "Cues use exact grid bar starts. ")
                       + "Check the metronome throughout the track.")
        if abs(adjustment) >= .0005:
            p.grid_note += f" Automatic Drop {other} adjusted {adjustment * 1000:+.0f} ms to the same grid."
        if len(grid.times) < len(p.track.grid.times):
            p.grid_note += " One beat outside the audio was removed."


def load_audio(track: Track, display=None) -> tuple[np.ndarray, int]:
    info = sf.info(str(track.path))
    if info.duration > 1800:
        raise ValueError("Tracks longer than 30 minutes are not supported in this preview.")
    if info.frames == 0 or info.channels > 8:
        raise ValueError("Unsupported audio stream.")
    # Decode in chunks so a high-resolution file doesn't allocate gigabytes.
    target = 11025
    divisor = math.gcd(info.samplerate, target)
    chunks = []
    # Reuse this decode for stereo display: ANLZ waveforms do not contain
    # separate L/R envelopes. No extra decode or band filtering is needed.
    channels = None
    if display is not None and not display.channels:
        from array import array
        channels = tuple(array('f') for _ in range(min(2, info.channels)))
        channel_scale = 1e-6
    with sf.SoundFile(str(track.path)) as file:
        while True:
            block = file.read(info.samplerate * 10, dtype="float32", always_2d=True)
            if not len(block):
                break
            if channels is not None:
                channel_scale = max(channel_scale, float(np.max(np.abs(block))))
                for index, envelope in enumerate(channels):
                    # Keep one common scale across blocks and both channels.
                    values = np.abs(block[:, index])
                    count = math.ceil(len(values) / info.samplerate * 1000)
                    edges = np.linspace(0, len(values), count + 1, dtype=np.int64)[:-1]
                    envelope.frombytes(np.maximum.reduceat(values, edges).astype(np.float32).tobytes())
            mono = block.mean(axis=1)
            chunks.append(signal.resample_poly(mono, target // divisor, info.samplerate // divisor))
    y = np.concatenate(chunks)
    if not np.isfinite(y).all():
        raise ValueError("Audio contains non-finite samples.")
    if np.max(np.abs(y)) < 1e-5:
        raise ValueError("Audio is silent; drop and grid analysis cannot run.")
    if channels is not None:
        for envelope in channels:
            np.frombuffer(envelope, dtype=np.float32)[:] /= channel_scale
        display.channels, display.channel_rate = channels, 1000.
    if track.audio_offset:
        from .audio_timing import shift_samples
        y = shift_samples(y, target, track.audio_offset)
    return y, target


def waveform(y: np.ndarray, points: int | None = None, *, sr: int = 11025):
    from .waveform_data import peak_envelope
    return peak_envelope(y, sr, points)


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


def drop_suggestions(y: np.ndarray, sr: int, grid: Grid, attacks=None) -> tuple[float | None, float | None]:
    downbeats = np.array([t for t, p in zip(grid.times, grid.positions) if p == 1])
    if len(downbeats) < 48:
        return None, None
    low = signal.sosfilt(signal.butter(3, 180, fs=sr, output="sos"), y)
    energy = []
    for a, b in zip(downbeats[:-1], downbeats[1:]):
        part = low[int(a * sr):int(b * sr)]
        energy.append(float(np.mean(part * part)) if len(part) else 0)
    values = np.array(energy)
    attacks = kick_attacks(y, sr) if attacks is None else attacks
    activity = np.zeros(len(values))
    for attack in attacks:
        index = int(np.searchsorted(downbeats, attack.time, side='right') - 1)
        if 0 <= index < len(activity):
            activity[index] += attack.strength
    activity_scale = max(float(np.max(activity)), 1e-9)
    scores = []
    for i in range(8, len(values) - 8):
        before, after = np.mean(values[i - 8:i]), np.mean(values[i:i + 8])
        # Avoid identifying a tiny change in a near-silent passage as a big drop.
        score = (after - before) / max(float(np.max(values)), 1e-9)
        drum_after = float(np.mean(activity[i:i + 8])) / activity_scale
        drum_change = (float(np.mean(activity[i:i + 8])) - float(np.mean(activity[i - 8:i]))) / activity_scale
        if after > before * 1.4 and score > .06 and drum_after > .08:
            scores.append((score + .20 * max(0., drum_change), i))
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
        # Read the exact audio duration as metadata, then prefer existing
        # Rekordbox display data. Decode once for the drop/grid timing check.
        track.audio_offset = 0.
        track.duration = sf.info(str(track.path)).duration
        from .waveform_data import track_waveforms
        proposal.waveform_data = track_waveforms(track)
        proposal.peaks = proposal.waveform_data.peaks
        y, sr = load_audio(track, display=proposal.waveform_data)
        timing_issue = ''
        display = proposal.waveform_data
        if display.sample_rate:
            from .audio_timing import saved_audio_offset, shift_samples
            from .waveform_data import _floats
            offset = saved_audio_offset(y, sr, display.peaks, display.sample_rate)
            if offset is None:
                timing_issue = 'Saved waveform and decoded audio timing could not be matched reliably. Check drop positions on the saved waveform, then align and rebuild manually before import.'
            else:
                track.audio_offset = offset
                y = shift_samples(y, sr, offset)
                display.channels = tuple(_floats(shift_samples(np.asarray(c), 1000, offset)) for c in display.channels)
                display.channel_rate = 1000.
                if not display.band_rate:
                    display.bands = tuple(_floats(shift_samples(np.asarray(b), 1000, offset)) for b in display.bands)
                    display.band_rate = 1000.
        duration = len(y) / sr
        track.duration = duration
        if track.grid.times[-1] > duration + .25:
            raise ValueError("Beat grid extends beyond the audio. Check the file association in Rekordbox.")
        candidate, assessment = ((track.grid, "Using Rekordbox analysis; checking drop placement.") if options.set_cues
                                 else grid_suggestion(y, sr, track.grid))
        if options.fix_grid:
            from .grid_writer import tempo, rounded_grid
            tempo(track.grid)  # Do not silently flatten a variable-tempo grid.
            # For cue analysis the drops determine a translation only. Do not
            # first change BPM with the independent spectral-flux suggestion.
            proposal.grid, proposal.grid_note = rounded_grid(track.grid if options.set_cues else candidate), assessment
            proposal.warnings.append("Check the metronome and bar starts before import. Use Set drop 1 / bar 1 here if the bar alignment is wrong.")
        else:
            proposal.grid_note = "Existing grid retained. " + assessment
            if candidate is not track.grid:
                proposal.warnings.append("Possible grid timing error. Grid correction is off; cues will use the original grid.")
        if "bass" in track.genre.lower() and track.bpm < 120:
            proposal.warnings.append("Possible half-time drum and bass grid. Confirm BPM in Rekordbox before placing cues.")
        if options.set_cues:
            proposal.attacks = kick_attacks(y, sr)
            proposal.first_drop, proposal.second_drop = drop_suggestions(y, sr, proposal.grid, proposal.attacks)
            for number, name in ((1, "first_drop"), (2, "second_drop")):
                target = getattr(proposal, name)
                if target is None:
                    continue
                match = refine_drop(y, sr, proposal.attacks, target, proposal.grid, duration,
                                     lower=proposal.first_drop if number == 2 else -1.,
                                     upper=proposal.second_drop if number == 1 else duration)
                if match.time is not None:
                    setattr(proposal, name, match.time)
                if match.time is None or match.needs_review:
                    proposal.review_note = "Listen and check the suggested drop markers."
                    proposal.drop_notes.append(f"Drop {number}: {match.note}")
            if proposal.first_drop is not None and proposal.second_drop is not None:
                if options.fix_grid:
                    rebuild_proposal(proposal)
                    if not proposal.grid_issue:
                        # Reassess uncertainty against the shifted grid, so a
                        # resolved old-grid offset does not remain a false alarm.
                        for number, target in ((1, proposal.first_drop), (2, proposal.second_drop)):
                            match = refine_drop(y, sr, proposal.attacks, target, proposal.grid, duration,
                                                lower=proposal.first_drop if number == 2 else -1.,
                                                upper=proposal.second_drop if number == 1 else duration)
                            if match.time is None or match.needs_review or abs(match.time - target) > .025:
                                proposal.review_note = "Listen and check the suggested drop markers."
                                proposal.drop_notes.append(f"Drop {number}: {match.note}")
                        rhythm_warning = rhythm_issue(proposal.grid, proposal.attacks,
                                                       proposal.first_drop, proposal.second_drop)
                        if rhythm_warning:
                            proposal.review_note = "Automatic timing check inconclusive. Listen to the track and check the grid and both drops, then confirm review."
                else:
                    proposal.cues, warnings = plan_cues(proposal.grid, proposal.first_drop, proposal.second_drop,
                                                        duration, track.cues, options.replace_memory, preserve_anchors=True)
                    proposal.warnings += warnings
            else:
                proposal.cues_dirty = True
                proposal.warnings.append("Could not identify both drops. Set the drop anchors manually and rebuild cues.")
            proposal.warnings += proposal.drop_notes
            proposal.warnings.append("Drop suggestions combine bass changes and drum attacks. These are heuristic matches; listen and confirm both anchors.")
        if timing_issue:
            proposal.grid_issue = timing_issue
            proposal.cues_dirty = True
    except Exception as exc:
        proposal.error = str(exc)
    return proposal


def review_confirmation_error(p: Proposal) -> str:
    """Human review may accept uncertain detection, never incomplete changes."""
    if p.applied:
        return "This track has already been imported."
    if p.error or p.grid_issue:
        return p.error or p.grid_issue
    if p.cues_dirty:
        return "Rebuild cues after changing the markers before confirming review."
    if not (p.options.set_cues or p.options.fix_grid):
        return "Prepare cues / grid first."
    try:
        p.grid.validate()
        if p.options.set_cues:
            first, second = p.first_drop, p.second_drop
            if first is None or second is None or not 0 <= first < second < p.track.duration:
                return "Set both drop markers inside the track, then rebuild cues."
            anchors = ((first if p.grid_anchor == 1 else second),) if p.preserve_drop_positions else (first, second)
            if p.options.fix_grid and any(abs(p.grid.times[p.grid.nearest_downbeat(t)] - t) > .0005 for t in anchors):
                return "Both drops must align with bar starts. Check the markers and rebuild."
            expected, _ = plan_cues(p.grid, first, second, p.track.duration, p.track.cues,
                                    p.options.replace_memory, preserve_anchors=not p.options.fix_grid or p.preserve_drop_positions)
            if p.cues != expected:
                return "Rebuild cues to match the current markers before confirming review."
    except (ValueError, SafetyError) as exc:
        return str(exc)
    return ""


def confirm_proposal_review(p: Proposal) -> None:
    reason = review_confirmation_error(p)
    if reason:
        raise ValueError(reason)
    p.warnings = [w for w in p.warnings if w not in p.drop_notes]
    p.drop_notes = []
    p.review_note = ""
    p.reviewed = True
    p.grid_approved = p.options.fix_grid
