"""Small, non-editable waveform and saved/suggested cue strip for track rows."""
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget
from .waveform_data import pixel_peaks


class CueOverview(QWidget):
    def __init__(self, track, peaks=(), suggested=()):
        super().__init__()
        self.duration = max(track.duration, 1)
        self.saved = tuple(track.cues)
        self.suggested = tuple(suggested)
        self.peaks = peaks
        self.bass = ()
        self.setStyleSheet('background: transparent;')
        self.setFixedHeight(28)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        memory = sum(c.kind == 'memory' for c in self.saved)
        self.setAccessibleName(f'{memory} saved memory cues; {len(self.saved) - memory} hot cues or loops')
        self.setToolTip('Bass-focused waveform. Red triangles: saved memory cues. Grey: hot cues/loops. Amber: app suggestions.')

    def set_data(self, data):
        self.duration = max(data.duration, 1)
        self.peaks, self.bass = data.peaks, data.bass
        self.setToolTip(data.error or 'Bass-focused waveform. Red triangles: saved memory cues. Grey: hot cues/loops. Amber: app suggestions.')
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        for values, color in ((self.peaks, '#48525b'), (self.bass, '#739fc9')):
            p.setPen(QColor(color))
            if len(values):
                peaks = pixel_peaks(values, self.duration, 0, self.duration, max(1, w))
                for x, peak in enumerate(peaks):
                    p.drawLine(x, round(h/2 - peak*8), x, round(h/2 + peak*8))
        for cues, suggestion in ((self.saved, False), (self.suggested, True)):
            for cue in cues:
                if not 0 <= cue.time <= self.duration:
                    continue
                x = round(cue.time / self.duration * max(1, w - 1))
                if not suggestion and cue.kind == 'memory':
                    # Keep the point at the exact cue time, in the clear strip
                    # above the waveform, including cues at either track edge.
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor('#ff535f'))
                    p.drawPolygon(QPolygonF([
                        QPointF(max(0, x - 3), 1),
                        QPointF(min(w - 1, x + 3), 1),
                        QPointF(x, 6),
                    ]))
                    continue
                color = '#efb34f' if suggestion else '#b2b6bc'
                p.setPen(QPen(QColor(color), 1))
                p.drawLine(x, h//2 if suggestion else 1, x, h-2 if suggestion else h//2)
