"""Read-only background loading of bounded, bass-focused playlist previews."""
from dataclasses import dataclass
from PySide6.QtCore import QThread, Signal
import soundfile as sf
from .waveform_data import rekordbox_waveforms, audio_waveforms, pixel_peaks


def overview_key(track):
    files = []
    for path in (track.path, *track.analysis_paths):
        try:
            stat = path.stat()
            files.append((str(path), stat.st_size, stat.st_mtime_ns))
        except OSError:
            files.append((str(path), None, None))
    return (track.duration, tuple(files))


@dataclass
class OverviewData:
    duration: float
    peaks: object
    bass: object
    error: str = ''


def load_overview(track, cancelled):
    duration = track.duration
    try:
        duration = sf.info(str(track.path)).duration
    except (OSError, RuntimeError):
        pass
    saved = rekordbox_waveforms(track.analysis_paths, duration)
    data = saved
    error = ''
    if not data or not len(data.bands[0]):
        try:
            data = audio_waveforms(track.path, cancelled=cancelled)
        except InterruptedError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            error = f'Bass preview unavailable: {exc}'
    if cancelled():
        raise InterruptedError('Waveform loading cancelled')
    peaks = saved.peaks if saved else data.peaks if data else ()
    bass = data.bands[0] if data else ()
    # Keep a few KB per track, never the detailed envelopes for a whole library.
    compact = lambda values: pixel_peaks(values, duration, 0, duration, 512) if len(values) else ()
    return OverviewData(duration, compact(peaks), compact(bass), error)


class OverviewWorker(QThread):
    loaded = Signal(object, object)

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.jobs = jobs

    def run(self):
        for key, track in self.jobs:
            if self.isInterruptionRequested():
                break
            try:
                data = load_overview(track, self.isInterruptionRequested)
            except InterruptedError:
                break
            except Exception as exc:
                data = OverviewData(track.duration, (), (), f'Preview unavailable: {exc}')
            self.loaded.emit(key, data)
