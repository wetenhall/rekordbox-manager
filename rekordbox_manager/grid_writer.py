"""Constant-tempo ANLZ grid updates matched to Rekordbox 7.2.19 native edits.

Patch only PQTZ and invalidate PQT2 as the native editor does. Other tags stay
byte-identical. The caller stages these files alongside the database for backup.
"""
from __future__ import annotations

import math
from pathlib import Path
import statistics
import struct

from .guards import SafetyError
from .models import Grid


def tags(data):
    if len(data) < 28 or data[:4] != b'PMAI':
        raise SafetyError('Unrecognised analysis file.')
    header, total = struct.unpack_from('>II', data, 4)
    if total != len(data) or not 28 <= header <= total:
        raise SafetyError('Invalid analysis file envelope.')
    result = []
    offset = header
    while offset < total:
        if offset + 12 > total:
            raise SafetyError('Truncated analysis tag.')
        tag, size, length = struct.unpack_from('>4sII', data, offset)
        if not 12 <= size <= length or offset + length > total:
            raise SafetyError('Invalid analysis tag length.')
        result.append((tag, size, data[offset:offset + length]))
        offset += length
    return data[:header], result


def tempo(grid):
    grid.validate()
    step = (grid.times[-1] - grid.times[0]) / (len(grid.times) - 1)
    if any(abs(t - (grid.times[0] + i * step)) > .003 for i, t in enumerate(grid.times)):
        raise SafetyError('Variable-tempo grids need correction in Rekordbox; this writer supports constant tempo only.')
    bpm = round(6000 / step)
    if not 4000 <= bpm <= 24000:
        raise SafetyError('Grid tempo must be between 40 and 240 BPM. Check half/double-time in Rekordbox.')
    return bpm


def rounded_grid(grid):
    return Grid([round(t * 1000) / 1000 for t in grid.times], grid.positions.copy())


def align_downbeat(grid, seconds, duration):
    """Explicit user anchor: move the nearest beat to the playhead and call it 1."""
    tempo(grid)
    if not math.isfinite(seconds) or not 0 <= seconds < duration:
        raise SafetyError('Choose a position inside the track.')
    index = min(range(len(grid.times)), key=lambda i: abs(grid.times[i] - seconds))
    offset = seconds - grid.times[index]
    step = statistics.median(b-a for a,b in zip(grid.times,grid.times[1:]))
    if abs(offset) > step / 2 + .002:
        raise SafetyError('The playhead is outside the analysed grid.')
    result = rounded_grid(Grid([t + offset for t in grid.times],
                               [(i - index) % 4 + 1 for i in range(len(grid.times))]))
    result.validate()
    if result.times[-1] >= duration:
        raise SafetyError('This adjustment crosses the end of the audio. Correct the grid in Rekordbox.')
    return result, result.times[index]


def patch_analysis(data, grid, bpm, *, dat=False):
    header, sections = tags(data)
    output = bytearray(header)
    seen = set()
    for tag, size, raw in sections:
        if tag.startswith(b'PQT') and tag not in (b'PQTZ', b'PQT2'):
            raise SafetyError('Unsupported beat-grid tag; no changes were written.')
        if tag in (b'PQTZ', b'PQT2'):
            if tag in seen:
                raise SafetyError('Duplicate beat-grid tags.')
            seen.add(tag)
        if tag == b'PQTZ':
            count = struct.unpack_from('>I', raw, 20)[0] if len(raw) >= 24 else -1
            if size != 24 or len(raw) != 24 + count * 8 or count != len(grid.times):
                raise SafetyError('Unsupported beat-grid layout or changed beat count.')
            body = b''.join(struct.pack('>HHI', beat, bpm, round(time * 1000))
                            for time, beat in zip(grid.times, grid.positions))
            raw = raw[:24] + body
        elif tag == b'PQT2':
            if size != 56 or len(raw) < 56 or len(raw) != 56 + struct.unpack_from('>I',raw,40)[0] * 2:
                raise SafetyError('Unsupported extended grid layout.')
            # Native edits clear the cached endpoints and entries, retaining the
            # format prefix through byte 23; verified on both WAV and VBR MP3.
            raw = raw[:8] + struct.pack('>I',56) + raw[12:24] + bytes(32)
        output.extend(raw)
    if dat and b'PQTZ' not in seen:
        raise SafetyError('Primary analysis file has no grid.')
    struct.pack_into('>I',output,8,len(output))
    return bytes(output)


def stage_grid(proposal, root: Path, stage: Path):
    from .library import read_grid
    import soundfile as sf
    duration = sf.info(str(proposal.track.path)).duration
    original, grid = proposal.track.grid, proposal.grid
    tempo(original)
    bpm = tempo(grid)
    grid = rounded_grid(grid)
    grid.validate()
    if grid == original:
        return {}, round(proposal.track.bpm * 100)
    if len(grid.times) != len(original.times) or grid.times[-1] >= duration:
        raise SafetyError('Grid changes must preserve beat count and stay inside the audio.')
    paths = [p.resolve() for p in proposal.track.analysis_paths]
    if len(set(paths)) != len(paths) or not any(p.suffix.upper()=='.EXT' for p in paths):
        raise SafetyError('Missing or duplicate companion analysis files. Reanalyse in Rekordbox.')
    dats = [p for p in paths if p.suffix.upper()=='.DAT']
    if len(dats) != 1 or read_grid(dats[0]) != original:
        raise SafetyError('The original grid changed. Reload the library.')
    replacements = {}
    for path in paths:
        if not path.is_relative_to(root / 'share') or path.parent != dats[0].parent:
            raise SafetyError('Analysis files must belong to this track inside the library.')
        if path.suffix.upper() == '.3EX':
            # Native grid edits leave the embedding file byte-identical. It is
            # MessagePack rather than ANLZ and contains no supported grid tags.
            continue
        data = path.read_bytes()
        patched = patch_analysis(data, grid, bpm, dat=path==dats[0])
        if patched != data:
            relative = str(path.relative_to(root))
            target = stage / relative
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(patched)
            if path == dats[0] and read_grid(target) != grid:
                raise SafetyError('Staged grid failed read-back validation.')
            replacements[relative] = target
    return replacements, bpm
