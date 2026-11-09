"""Translate a constant grid; never change its tempo to fit two drop guesses."""
from __future__ import annotations

import numpy as np

from .grid_writer import align_downbeat


# Allows small detector/drag timing differences, not a beat or bar disagreement.
DROP_TOLERANCE = .025


def align_drops(grid, first, second, duration, *, reference=1, first_edited=False, second_edited=False):
    if not 0 <= first < second < duration:
        raise ValueError("Drop 1 must precede drop 2, and both must be inside the track.")
    if reference not in (1, 2):
        raise ValueError("Choose Drop 1 or Drop 2 as the grid anchor.")
    anchors = [first, second]
    active, other = reference - 1, 2 - reference
    shifted, anchors[active] = align_downbeat(grid, anchors[active], duration, trim_edges=True)
    aligned_other = shifted.times[shifted.nearest_downbeat(anchors[other])]
    error = anchors[other] - aligned_other
    # Automatic estimates can move slightly. An explicitly edited anchor must
    # remain at its chosen millisecond, even when the other drop was edited later.
    edited = (first_edited, second_edited)[other]
    tolerance = .0005 if edited else DROP_TOLERANCE
    ordered = aligned_other < anchors[active] if reference == 2 else aligned_other > anchors[active]
    if abs(error) > tolerance + 1e-9 or not ordered:
        reason = "Both manually placed drops have been preserved. " if edited else ""
        issue = (f"Proposed grid aligned to Drop {reference}. Drop {other + 1} is {error * 1000:+.0f} ms from the nearest bar start. "
                 + reason + "Check the other drop and BPM; shifting alone cannot align both, so import is blocked.")
        return shifted, first, second, issue
    anchors[other] = aligned_other
    return shifted, anchors[0], anchors[1], ""


def rhythm_issue(grid, attacks, first, second):
    """Check independent regions, allowing eighth-note DnB syncopation.

    This is evidence of consistent timing, not proof of musical drop identity.
    Sparse regions abstain; strongly conflicting regions veto the automatic shift.
    Manual rebuild uses the user's anchors instead of this automatic evidence gate.
    """
    step = (grid.times[-1] - grid.times[0]) / (len(grid.times) - 1)
    windows = np.linspace(grid.times[0], grid.times[-1], 6)
    supported = 0
    for left, right in zip(windows[:-1], windows[1:]):
        local = [a for a in attacks if left <= a.time < right]
        if not local:
            continue
        threshold = max(.05, max(a.strength for a in local) * .2)
        local = [a for a in local if a.strength >= threshold]
        if len(local) < 8:
            continue
        positions = (np.array([a.time for a in local]) - grid.times[0]) / step
        errors = np.abs(positions - np.round(positions * 2) / 2) * step
        fraction = float(np.mean(errors <= .030))
        if fraction < .5:
            return "Drum timing elsewhere in the track disagrees with the drop-aligned grid. Review the markers/BPM, then rebuild; import is blocked."
        supported += 1
    if supported < 3:
        return "Not enough drum evidence across the track to validate the automatic grid shift. Check both drops and rebuild; import is blocked."
    return ""
