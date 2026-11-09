"""Cue placement is in beats, never a fixed BPM-to-seconds approximation."""
from __future__ import annotations

from bisect import bisect_right
import math

from .models import Cue, Grid


def plan_cues(grid: Grid, first: float, second: float, duration: float,
              existing: list[Cue], replace: bool, *, preserve_anchors: bool = False) -> tuple[list[Cue], list[str]]:
    grid.validate()
    if not 0 <= first < second < duration:
        raise ValueError("Drop 1 must precede drop 2, and both must be inside the track.")
    def coordinate(time):
        index = max(0, min(len(grid.times) - 2, bisect_right(grid.times, time) - 1))
        return index + (time - grid.times[index]) / (grid.times[index + 1] - grid.times[index])

    def timestamp(index):
        lower = max(0, min(len(grid.times) - 2, math.floor(index)))
        return grid.times[lower] + (index - lower) * (grid.times[lower + 1] - grid.times[lower])

    a, b = ((coordinate(first), coordinate(second)) if preserve_anchors else
            (grid.nearest_downbeat(first), grid.nearest_downbeat(second)))
    if a >= b:
        raise ValueError("Choose two distinct drop downbeats.")
    warnings = []
    # Saved memory loops consume the same ten-slot budget and are never replaced.
    keep = [c for c in existing if c.kind != "memory" or not replace]
    memory = [c for c in keep if c.kind in ("memory", "memory_loop")]
    if len(memory) > 10:
        raise ValueError("Existing memory points exceed the ten-slot budget.")
    def countdown(anchor, lower, inclusive):
        result = [anchor]
        index = anchor - 64
        while (index >= lower if inclusive else index > lower):
            result.append(index)
            index -= 64
        return result

    first_indices = countdown(a, 0, True)
    second_indices = countdown(b, a, False)
    if preserve_anchors:
        for number, time in ((1, first), (2, second)):
            nearest = grid.times[grid.nearest_downbeat(time)]
            if abs(nearest - time) > .002:
                warnings.append(f"Drop {number} is not on a grid bar start. Your chosen position is preserved; check bar alignment.")
    if len(second_indices) < 4:
        warnings.append("Less than 48 bars between drops: the second countdown stops before drop 1.")
    chosen: dict[float, Cue] = {}
    free = 10 - len(memory)

    def add(index: float, anchor: float, number: int) -> bool:
        nonlocal free
        bars = round((anchor - index) / 4)
        t = (first if number == 1 else second) if preserve_anchors and bars == 0 else timestamp(index)
        key = round(t, 3)
        tolerance = .0005 if preserve_anchors else .025
        if any(abs(c.time - t) < tolerance for c in memory):
            return True
        if key in chosen:
            return True
        if free <= 0:
            return False
        label = f"DROP {number}" if not bars else f"DROP {number} −{bars}"
        chosen[key] = Cue(t, label)
        free -= 1
        return True

    # Both anchors, then the minimum second-drop countdown, then the intro.
    for index, anchor, number in [(a, a, 1), (b, b, 2)]:
        if not add(index, anchor, number):
            raise ValueError("Not enough free memory slots for both drops. Replace memory cues or review saved loops.")
    for index in second_indices[1:4]:
        if not add(index, b, 2):
            warnings.append("Existing memory points leave too few slots for the 48-bar countdown.")
            break
    for index in first_indices[1:]:
        if not add(index, a, 1):
            warnings.append("Ten-slot limit: the earliest intro sections could not be marked.")
            break
    for index in second_indices[4:]:
        if not add(index, b, 2):
            break
    if not math.isclose(a % 64, 0, abs_tol=1e-7) and not math.isclose(a % 64, 64, abs_tol=1e-7):
        warnings.append("Track start is outside the first drop's 16-bar pattern; no off-pattern start cue added.")
    result = sorted(keep + list(chosen.values()), key=lambda c: c.time)
    return result, list(dict.fromkeys(warnings))
