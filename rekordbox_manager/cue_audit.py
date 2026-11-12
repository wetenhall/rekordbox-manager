"""Read-only comparisons of saved memory cues against independently generated cues."""
from array import array
from copy import deepcopy
from dataclasses import dataclass, field, replace
import hashlib
import math

from .analysis import analyse
from .models import Cue, Options, Proposal
from .waveform_data import WaveformData, pixel_peaks, rekordbox_waveforms


@dataclass
class CueAuditResult:
    status: str
    saved: tuple[Cue, ...]
    suggested: tuple[Cue, ...] = ()
    missing: tuple[Cue, ...] = ()
    extra: tuple[Cue, ...] = ()
    reason: str = ''
    peaks: array = field(default_factory=lambda: array('f'))
    duration: float = 0.
    audio_offset: float = 0.
    playable: bool = False
    tolerance_ms: int = 50
    candidate: Proposal | None = None
    source_key: str = ''

    @property
    def flagged(self):
        return self.status in ('Cue differences', 'Inconclusive', 'Unavailable')

    def details(self):
        lines = [self.status, self.reason, f'Timing tolerance: ±{self.tolerance_ms} ms. Cue names are not compared.',
                 'Memory loops and hot cues are preserved and excluded from timing comparison.',
                 'Suggested positions are estimates, not proof that your saved cues are wrong.']
        for title, cues in (('Saved memory cues', self.saved), ('Suggested memory cues', self.suggested),
                            ('Suggested positions without a saved cue', self.missing), ('Saved cues outside the suggested pattern', self.extra)):
            lines += ['', title] + [f'{c.time:.3f} s  {c.label}' for c in cues]
        return '\n'.join(lines)

    def preview(self, track):
        display = replace(track, duration=self.duration or track.duration, audio_offset=self.audio_offset)
        data = rekordbox_waveforms(track.analysis_paths, display.duration) or WaveformData(peaks=self.peaks, source='Cue check overview', sample_rate=len(self.peaks) / max(display.duration, 1))
        return Proposal(display, Options(False, False), track.grid, list(track.cues),
                        peaks=data.peaks, waveform_data=data, grid_note=self.details(),
                        first_drop=self.candidate.first_drop if self.candidate else None,
                        second_drop=self.candidate.second_drop if self.candidate else None)

    def replacement(self, track):
        if not self.candidate or not self.playable:
            raise ValueError('Check this track successfully before reviewing a replacement.')
        if self.source_key != audit_key(track, self.tolerance_ms):
            raise ValueError('Track or analysis changed since checking. Check the playlist again.')
        draft = deepcopy(self.candidate)
        preview = self.preview(track)
        draft.peaks, draft.waveform_data = preview.peaks, preview.waveform_data
        draft.reviewed = False
        draft.review_note = draft.review_note or 'Listen to both suggested drops, then choose Replace cues.'
        return draft


def compare_cues(saved, suggested, tolerance_ms=50):
    """One-to-one chronological matching; duplicate cues cannot share a match."""
    tolerance = tolerance_ms / 1000
    left = sorted((c for c in saved if c.kind == 'memory'), key=lambda c: c.time)
    right = sorted((c for c in suggested if c.kind == 'memory'), key=lambda c: c.time)
    missing, extra = [], []
    i = j = 0
    while i < len(left) and j < len(right):
        delta = left[i].time - right[j].time
        if abs(delta) <= tolerance + 1e-9:
            i += 1
            j += 1
        elif delta < 0:
            extra.append(left[i])
            i += 1
        else:
            missing.append(right[j])
            j += 1
    return tuple(missing + right[j:]), tuple(extra + left[i:])


def audit_key(track, tolerance_ms):
    def stamp(path):
        try:
            s = path.stat()
            return str(path), s.st_size, s.st_mtime_ns
        except OSError:
            return str(path), None
    values = ('cue-audit-v4', track.id, track.title, track.artist, track.duration, track.bpm,
              track.genre, track.cues, track.grid.times, track.grid.positions, track.issues,
              stamp(track.path), [stamp(p) for p in track.analysis_paths], tolerance_ms)
    return hashlib.sha256(repr(values).encode()).hexdigest()


def audit_track(track, tolerance_ms=50):
    saved = tuple(c for c in track.cues if c.kind == 'memory')
    result = CueAuditResult('No memory cues', saved, duration=track.duration, tolerance_ms=tolerance_ms)
    result.source_key = audit_key(track, tolerance_ms)
    if not saved:
        result.reason = 'No saved memory points to compare. Hot cues and loops are not treated as memory points.'
        data = rekordbox_waveforms(track.analysis_paths, track.duration)
        if data:
            result.peaks = array('f', pixel_peaks(data.peaks, track.duration, 0, track.duration, 4096))
        return result
    if any(not math.isfinite(c.time) or c.time < 0 for c in saved):
        result.status, result.reason = 'Unavailable', 'Saved cue timestamps are invalid.'
        return result
    # Never mutate the Manager track, its saved cues, or its import proposal.
    proposal = analyse(deepcopy(track), Options(False, True, True))
    result.duration = proposal.track.duration
    result.audio_offset = proposal.track.audio_offset
    if proposal.peaks:
        result.peaks = array('f', pixel_peaks(proposal.peaks, result.duration, 0, result.duration, 4096))
    result.playable = bool(result.peaks and not proposal.error)
    if proposal.error:
        result.status, result.reason = 'Unavailable', proposal.error
        return result
    result.suggested = tuple(c for c in proposal.cues if c.kind == 'memory')
    # Retain the exact checked proposal for review, without detailed waveform
    # arrays. Editing always uses a deep copy, so cached comparisons stay intact.
    result.candidate = replace(proposal, peaks=result.peaks, waveform_data=None)
    result.missing, result.extra = compare_cues(saved, result.suggested, tolerance_ms)
    valid_drops = (proposal.first_drop is not None and proposal.second_drop is not None
                   and math.isfinite(proposal.first_drop) and math.isfinite(proposal.second_drop)
                   and 0 <= proposal.first_drop < proposal.second_drop < result.duration)
    incomplete = proposal.grid_issue or ('Both drops could not be identified.' if proposal.cues_dirty or not valid_drops else '')
    uncertainty = incomplete or proposal.review_note
    # Comparison answers whether the cue sets agree, not whether the detector
    # can prove those drops are musically correct. Keep detection warnings on the
    # candidate so any replacement still requires explicit human confirmation.
    if result.suggested and not incomplete and not result.missing and not result.extra:
        result.status = 'Cues match'
        result.reason = 'All saved memory points match the suggested pattern within the tolerance.'
        if proposal.review_note:
            result.reason += ' Drop detection is uncertain; matching positions do not verify musical drop placement.'
    elif uncertainty:
        result.status, result.reason = 'Inconclusive', uncertainty
    elif result.missing or result.extra:
        result.status = 'Cue differences'
        result.reason = f'{len(result.missing)} suggested positions have no matching saved cue; {len(result.extra)} saved cues are outside the suggested pattern.'
    else:
        result.status, result.reason = 'Cues match', 'All saved memory points match the suggested pattern within the tolerance.'
    return result
