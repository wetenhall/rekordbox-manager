"""Heuristic low-frequency attack candidates; these are not isolated kick stems."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
from scipy import signal
from scipy.ndimage import uniform_filter1d

from .models import Grid


@dataclass(frozen=True)
class Attack:
    time: float
    strength: float


@dataclass(frozen=True)
class AttackMatch:
    time: float | None
    note: str
    needs_review: bool = False


def kick_attacks(y: np.ndarray, sr: int) -> list[Attack]:
    """Locate sharp bass-band rises, then backtrack to the attack's leading edge.

    Zero-phase filtering avoids a causal filter delay. The leading edge is checked
    against the unfiltered audio envelope to limit pre-ringing timestamps. Smooth
    bass swells are excluded by requiring a fast rise and a short attack time.
    """
    if len(y) < sr // 2 or sr < 1000:
        return []
    hop = max(1, round(sr * .002))
    low = signal.sosfiltfilt(signal.butter(3, [35, 180], btype='bandpass', fs=sr, output='sos'), y)
    window = max(1, round(sr * .024))
    envelope = np.sqrt(np.maximum(uniform_filter1d(low * low, size=window, mode='constant')[::hop], 0))
    del low
    raw_window = max(1, round(sr * .002))
    raw = np.sqrt(np.maximum(uniform_filter1d(y * y, size=raw_window, mode='constant')[::hop], 0))
    step = hop / sr
    lag = max(1, round(.012 / step))
    rise = np.maximum(envelope - np.r_[np.repeat(envelope[0], lag), envelope[:-lag]], 0)
    scale = float(np.max(rise))
    if scale < 1e-7:
        return []
    indices, _ = signal.find_peaks(rise, distance=max(1, round(.080 / step)),
                                  prominence=max(scale * .035, float(np.median(rise)) * 4))
    attacks = []
    audible_floor = float(np.percentile(envelope, 99)) * .08
    for peak in indices:
        begin = max(0, peak - round(.050 / step))
        end = min(len(envelope), peak + round(.020 / step) + 1)
        baseline = float(np.min(envelope[begin:peak + 1]))
        top = float(np.max(envelope[peak:end]))
        if top <= max(audible_floor, 1e-7) or (top - baseline) / top < .35 or rise[peak] / max(top - baseline, 1e-9) < .30:
            continue
        # Backtrack the bass rise, not its later amplitude maximum.
        threshold = baseline + (top - baseline) * .18
        crossings = np.flatnonzero(envelope[begin:peak + 1] <= threshold)
        at = begin + int(crossings[-1]) if len(crossings) else begin
        if (peak - at) * step > .040:
            continue
        # A filtered bass signal can ring before a real attack. If the raw audio
        # has a clear leading edge nearby, use that instead of pre-ringing.
        left, right = max(0, at - 3), min(len(raw), peak + 3)
        floor, ceiling = float(np.min(raw[left:right])), float(np.max(raw[left:right]))
        if ceiling > max(floor * 2, 1e-7):
            above = np.flatnonzero(raw[left:right] > floor + .12 * (ceiling - floor))
            if len(above):
                at = left + int(above[0])
        attacks.append(Attack(round(float(at * step), 3), min(1., float(rise[peak] / scale))))
    return attacks


def match_attack(attacks: list[Attack], target: float, grid: Grid, duration: float,
                 *, lower: float = -1., upper: float | None = None) -> AttackMatch:
    """A local adjustment only: at most 0.6 beat / 250 ms from the marker."""
    grid.validate()
    beat = float(np.median(np.diff(grid.times)))
    radius = min(.250, beat * .6)
    upper = duration if upper is None else min(duration, upper)
    candidates = [a for a in attacks if lower < a.time < upper and 0 <= a.time < duration
                  and abs(a.time - target) <= radius and a.strength >= .05]
    if not candidates:
        return AttackMatch(None, "No distinct kick-like attack nearby. Listen, move the marker closer to the intended kick, then try again.", True)
    candidates.sort(key=lambda a: abs(a.time - target))
    chosen = candidates[0]
    if len(candidates) > 1:
        other = candidates[1]
        if abs(abs(other.time - target) - abs(chosen.time - target)) < beat * .12 and other.strength >= chosen.strength * .65:
            return AttackMatch(None, "Two nearby attacks are plausible. Move the marker closer to the intended kick and try again.", True)
    # Check a local pulse, allowing eighth-note syncopation. Do not assume one
    # kick on every quarter note, particularly for drum and bass.
    def residual(time):
        coordinate = float(np.interp(time, grid.times, np.arange(len(grid.times))))
        return (coordinate - round(coordinate * 2) / 2) * beat
    nearby = [a for a in attacks if abs(a.time - chosen.time) <= beat * 8
              and grid.times[0] <= a.time <= grid.times[-1] and a.strength >= .05]
    phase = residual(chosen.time)
    support = sum(abs(residual(a.time) - phase) <= .030 for a in nearby)
    nearest = min(grid.times, key=lambda t: abs(t - chosen.time))
    offset = chosen.time - nearest
    needs_review = support < 3 or abs(offset) > .035
    note = "Matched a nearby kick-like attack; listen to confirm."
    if support < 3:
        note += " Limited support from surrounding drum hits; review required."
    if abs(offset) > .035:
        note += f" Attack is {offset * 1000:+.0f} ms from the nearest grid beat. Check grid timing/bar alignment; the grid was not moved."
    return AttackMatch(chosen.time, note, needs_review)


def refine_drop(y: np.ndarray, sr: int, attacks: list[Attack], target: float,
                grid: Grid, duration: float, *, lower: float = -1.,
                upper: float | None = None) -> AttackMatch:
    """Refine a broad structural candidate within one bar, using sustained bass
    contrast across the attack. Manual snap remains a much narrower operation.
    """
    beat = float(np.median(np.diff(grid.times)))
    upper = duration if upper is None else min(duration, upper)
    candidates = [a for a in attacks if abs(a.time-target) <= beat*4
                  and lower < a.time < upper and 0 <= a.time < duration]
    if not candidates:
        return match_attack(attacks, target, grid, duration, lower=lower, upper=upper)
    start = max(0., target-beat*13)
    end = min(duration, target+beat*13)
    sample_start = int(start*sr)
    segment = y[sample_start:int(end*sr)]
    if len(segment) < sr*.1:
        return match_attack(attacks, target, grid, duration, lower=lower, upper=upper)
    low = signal.sosfiltfilt(signal.butter(3, [35,180], btype='bandpass', fs=sr, output='sos'), segment)
    integral = np.r_[0., np.cumsum(low*low)]
    def energy(a,b):
        left = max(0,min(len(low),round(a*sr)-sample_start))
        right = max(0,min(len(low),round(b*sr)-sample_start))
        return float((integral[right]-integral[left])/max(1,right-left)) if right>left else 0.
    strongest = max(a.strength for a in candidates)
    scored = []
    for attack in candidates:
        if attack.strength < strongest*.15:
            continue
        at = attack.time
        before = energy(at-beat*4,at)
        after = energy(at,at+beat*4)
        sustained = energy(at,at+beat*8)
        # Absolute contrast avoids favouring a tiny attack before the real drop
        # simply because the preceding passage was close to silent.
        score = .65*(after-before) + .35*(sustained-energy(at-beat*8,at))
        if after > before*1.25 and sustained > before*1.15 and score>0:
            scored.append((score,attack))
    if not scored:
        match = match_attack(attacks,target,grid,duration,lower=lower,upper=upper)
        return AttackMatch(match.time, match.note + " No clear local bass transition; confirm this is the intended drop.", True)
    best = max(score for score,_ in scored)
    # Long bass windows can give a quiet pickup just before the main attack
    # almost the same structural score. Do not let the earliest-window tie-break
    # anchor the grid to that pickup. Only suppress a much weaker predecessor
    # within half a beat when the stronger attack also fits the same transition;
    # a comparable leading kick or a distant louder hit must not be displaced.
    plausible = [a for score,a in scored if score>=best*.92]
    onset_radius = min(.250, beat*.5)
    leading = [a for a in plausible if not any(
        0 < b.time-a.time <= onset_radius and a.strength < b.strength*.35
        for b in plausible)]
    chosen = min(leading,key=lambda a:a.time)
    match = match_attack(attacks,chosen.time,grid,duration,lower=lower,upper=upper)
    if any(abs(a.time-chosen.time)>beat*.75 for a in plausible):
        return AttackMatch(match.time, match.note + " Several nearby attacks fit the transition; confirm the drop by listening.", True)
    if abs(chosen.time-target)>beat*3.6:
        return AttackMatch(match.time, match.note + " Match is at the edge of the search region; confirm the drop by listening.", True)
    return match
