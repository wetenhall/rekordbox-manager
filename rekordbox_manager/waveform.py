"""Waveform viewport and drop handles with selectable snapping."""
import math

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class Waveform(QWidget):
    seek = Signal(float)
    anchor_moved = Signal(int, float)
    drag_started = Signal()
    view_changed = Signal()
    ZOOMS = (1, 2, 4, 8, 16, 32, 64)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(210)
        self.proposal = None
        self.position = 0.0
        self.zoom = 1
        self.snap_mode = "beat"
        self.view_center = 0.0
        self.follow_playhead = False
        self._dragging = None
        self._drag_range = None
        self._drag_offset = 0.0
        self._wheel_delta = 0
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName('Track waveform with draggable first and second drop markers')
        self.setToolTip('Drag a DROP handle. Choose Beat, Bar or Off snapping below. Click elsewhere to seek. Scroll to zoom.')

    @property
    def duration(self):
        return max(self.proposal.track.duration, 1) if self.proposal else 1

    def visible_range(self):
        if self._drag_range is not None:
            return self._drag_range
        span = self.duration / self.zoom
        start = min(max(0, self.view_center - span / 2), self.duration - span)
        return start, start + span

    def set_zoom(self, factor, center=None):
        if self._dragging is not None:
            return
        start, end = self.visible_range()
        self.zoom = min(self.ZOOMS, key=lambda z: abs(z - factor))
        self.view_center = (start + end) / 2 if center is None else center
        self.follow_playhead = False
        self.update()
        self.view_changed.emit()

    def zoom_by(self, step, cursor_x=None):
        index = self.ZOOMS.index(self.zoom)
        factor = self.ZOOMS[max(0, min(len(self.ZOOMS) - 1, index + step))]
        center = None
        if cursor_x is not None:
            ratio = max(0, min(1, cursor_x / max(1, self.width())))
            start, end = self.visible_range()
            time = start + ratio * (end - start)
            center = time + (.5 - ratio) * self.duration / factor
        self.set_zoom(factor, center)

    def pan(self, fraction):
        if self._dragging is not None:
            return
        span = self.duration / self.zoom
        self.view_center = max(0, min(1, fraction)) * (self.duration - span) + span / 2
        self.follow_playhead = False
        self.update()
        self.view_changed.emit()

    def set_position(self, seconds):
        self.position = seconds
        if self.follow_playhead and self._dragging is None:
            self.view_center = seconds
            self.view_changed.emit()
        self.update()

    def reset_view(self):
        self._dragging = self._drag_range = None
        self.zoom = 1
        self.position = self.view_center = 0.0
        self.follow_playhead = False
        self.update()
        self.view_changed.emit()

    def marker_time(self, number):
        if not self.proposal:
            return None
        return self.proposal.first_drop if number == 1 else self.proposal.second_drop

    def marker_rect(self, number):
        time = self.marker_time(number)
        start, end = self.visible_range()
        if time is None or not start <= time <= end:
            return QRectF()
        x = (time - start) / (end - start) * self.width()
        return QRectF(min(max(0, x - 36), max(0, self.width() - 76)),
                      4 if number == 1 else 29, 76, 23)

    def hit_marker(self, point):
        p = self.proposal
        if not p or p.error or not p.options.set_cues:
            return None
        for number in (1, 2):
            rect = self.marker_rect(number)
            if not rect.isEmpty() and rect.contains(point):
                return number
        return None

    def move_marker(self, x):
        p, number = self.proposal, self._dragging
        if p is None or number is None:
            return
        start, end = self.visible_range()
        target = start + max(0, min(self.width(), x - self._drag_offset)) / max(1, self.width()) * (end - start)
        other = self.marker_time(2 if number == 1 else 1)
        if self.snap_mode == "off":
            lower = (math.floor(other * 1000) + 1) / 1000 if number == 2 and other is not None else 0
            upper = (math.ceil(min(other, p.track.duration) * 1000) - 1) / 1000 if number == 1 and other is not None else (math.ceil(p.track.duration * 1000) - 1) / 1000
            if lower > upper:
                return
            snapped = round(max(lower, min(upper, target)), 3)
        else:
            candidates = [t for t, beat in zip(p.grid.times, p.grid.positions)
                          if (self.snap_mode == "beat" or beat == 1) and 0 <= t < p.track.duration
                          and (other is None or (t < other if number == 1 else t > other))]
            if not candidates:
                return
            snapped = min(candidates, key=lambda t: abs(t - target))
        if snapped != self.marker_time(number):
            self.anchor_moved.emit(number, snapped)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self.proposal:
            return
        number = self.hit_marker(event.position())
        if number:
            self._drag_range = self.visible_range()
            start, end = self._drag_range
            self.view_center = (start + end) / 2
            self._drag_offset = event.position().x() - (self.marker_time(number) - start) / (end - start) * self.width()
            self._dragging = number
            self.follow_playhead = False
            self.setCursor(Qt.ClosedHandCursor)
            self.drag_started.emit()
        else:
            start, end = self.visible_range()
            self.seek.emit(max(0, min(self.duration, start + event.position().x() / max(1, self.width()) * (end - start))))

    def mouseMoveEvent(self, event):
        if self._dragging is not None:
            self.move_marker(event.position().x())
        else:
            self.setCursor(Qt.OpenHandCursor if self.hit_marker(event.position()) else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging is not None:
            self.move_marker(event.position().x())
            self._dragging = self._drag_range = None
            self.setCursor(Qt.OpenHandCursor)
            self.update()
            self.view_changed.emit()

    def wheelEvent(self, event):
        if not self.proposal:
            event.ignore()
            return
        self._wheel_delta += event.angleDelta().y()
        if abs(self._wheel_delta) >= 120:
            self.zoom_by(1 if self._wheel_delta > 0 else -1, event.position().x())
            self._wheel_delta = 0
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#090e17'))
        p = self.proposal
        if not p or not p.peaks:
            painter.setPen(QColor('#91a5c1'))
            painter.drawText(self.rect(), Qt.AlignCenter, 'Analyse a track to view its waveform and cue proposals')
            return
        width, height = self.width(), self.height()
        mid, amp = height * .64, height * .20
        start, end = self.visible_range()
        span = end - start
        lower = max(0, int(start / self.duration * len(p.peaks)))
        upper = min(len(p.peaks), int(end / self.duration * len(p.peaks)) + 1)
        painter.setPen(QPen(QColor('#3d82be'), max(1.0, width / max(upper - lower, 1) - .5)))
        for i in range(lower, upper):
            x = (i / len(p.peaks) * self.duration - start) / span * width
            painter.drawLine(int(x), int(mid - amp * p.peaks[i]), int(x), int(mid + amp * p.peaks[i]))
        if self.zoom >= 8:
            for grid, color in ((p.track.grid, '#7b8492'), (p.grid, '#88c0ff')):
                for time, beat in zip(grid.times, grid.positions):
                    if start <= time <= end:
                        x = int((time - start) / span * width)
                        painter.setPen(QPen(QColor(color), 1))
                        painter.drawLine(x, 78 if beat == 1 else int(mid - 8), x, height - 22 if beat == 1 else int(mid + 8))
        interval = next((v for v in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if v >= span / 10), 600)
        tick = math.ceil(start / interval) * interval
        while tick <= end:
            x = int((tick - start) / span * width)
            painter.setPen(QColor('#1e304a'))
            painter.drawLine(x, 78, x, height - 20)
            painter.setPen(QColor('#7f98bb'))
            painter.drawText(x + 3, height - 5, f'{int(tick) // 60}:{int(tick) % 60:02}')
            tick += interval
        memories = [c for c in p.cues if c.kind in ('memory', 'memory_loop')]
        for i, cue in enumerate(memories):
            if not start <= cue.time <= end or cue.label in ('DROP 1', 'DROP 2'):
                continue
            x = (cue.time - start) / span * width
            color = QColor('#83ddff' if 'DROP 2' in cue.label else '#63a8ff')
            painter.setPen(QPen(color, 1))
            painter.drawLine(int(x), 78, int(x), height - 22)
            painter.drawText(int(min(max(2, x + 4), width - 62)), 62 if i % 2 == 0 else 75, cue.label.replace('DROP ', 'D'))
        for number, color in ((1, '#63a8ff'), (2, '#83ddff')):
            rect = self.marker_rect(number)
            if rect.isEmpty() or not p.options.set_cues:
                continue
            x = (self.marker_time(number) - start) / span * width
            painter.setPen(QPen(QColor(color), 2))
            painter.drawLine(int(x), int(rect.bottom()), int(x), height - 22)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor('#071426'))
            painter.drawText(rect, Qt.AlignCenter, f'DROP {number} ↔')
        painter.setPen(QPen(QColor('#ffffff'), 2))
        x = (self.position - start) / span * width
        painter.drawLine(int(x), 78, int(x), height - 18)
