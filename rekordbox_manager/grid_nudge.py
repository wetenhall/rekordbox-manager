"""Explicit constant-tempo grid nudges; never move saved cues or drop markers."""
from dataclasses import replace
import math

from .grid_writer import tempo, rounded_grid
from .models import Grid


def nudge_grid(proposal, seconds):
    p = proposal
    if p.applied or p.error:
        raise ValueError('This track cannot be edited.')
    if not math.isfinite(seconds) or not 0 < abs(seconds) <= .05:
        raise ValueError('Choose a grid adjustment of at most 50 ms.')
    original = p.track.grid
    tempo(original)
    tempo(p.grid)
    half_beat = (original.times[1] - original.times[0]) / 2 + .002
    raw = p.manual_grid
    if raw is None:
        # Recover the full translation so reversing a nudge restores a trimmed boundary beat.
        begin = None
        for candidate in (0, 1):
            if candidate + len(p.grid.times) > len(original.times):
                continue
            offset = p.grid.times[0] - original.times[candidate]
            if abs(offset) <= half_beat and all(abs(new - old - offset) <= .0011
                    for new, old in zip(p.grid.times, original.times[candidate:])):
                begin = candidate
                break
        if begin is None or len(p.grid.times) not in (len(original.times), len(original.times) - 1):
            raise ValueError('The proposed grid is not a simple timing shift. Review it in Rekordbox.')
        raw = Grid([t + offset for t in original.times],
                   [(p.grid.positions[0] - 1 + i - begin) % 4 + 1 for i in range(len(original.times))])
    shifted = rounded_grid(Grid([t + seconds for t in raw.times], raw.positions.copy()))
    offset = shifted.times[0] - original.times[0]
    if abs(offset) > half_beat:
        raise ValueError('Grid adjustment is limited to half a beat. Use Align to Drop for larger alignment changes.')
    inside = [(t, beat) for t, beat in zip(shifted.times, shifted.positions) if 0 <= t < p.track.duration]
    if len(inside) < len(original.times) - 1:
        raise ValueError('This shift would remove more than one boundary beat.')
    grid = Grid([t for t, _ in inside], [beat for _, beat in inside])
    grid.validate()
    tempo(grid)
    p.grid, p.manual_grid = grid, shifted
    p.options = replace(p.options, fix_grid=True)
    p.preserve_drop_positions = True
    p.cues_dirty = p.options.set_cues
    p.reviewed = p.grid_approved = False
    p.grid_issue = ''
    p.grid_note = f'Manual grid offset: {offset * 1000:+.0f} ms. BPM and drop positions unchanged.'
    p.review_note = 'Rebuild cues, listen and accept the proposed grid.' if p.options.set_cues else 'Listen and confirm the proposed grid before importing.'
