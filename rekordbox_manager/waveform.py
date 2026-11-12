"""Waveform viewport and drop handles with selectable snapping."""
import math

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from .waveform_data import pixel_peaks


class Waveform(QWidget):
    STYLES = {
        'classic': ('Classic bars', 'The original single-colour amplitude waveform.'),
        'filled': ('Smooth filled', 'A continuous, filled amplitude silhouette.'),
        'frequency': ('Frequency-coloured', 'Bass is orange, mids green and highs blue; mixed colours show their relative strengths.'),
        'three_band': ('Three-band', 'Separate bass, mid and high lanes using saved Rekordbox band heights when available.'),
        'bass': ('Bass-focused', 'Bass in blue, with the full waveform faintly behind it. Uses saved Rekordbox band heights when available.'),
        'stereo': ('Stereo', 'Separate left and right channels on the same scale. Mono files show one lane.'),
    }
    seek = Signal(float)
    anchor_moved = Signal(int, float)
    drag_started = Signal()
    view_changed = Signal()
    ZOOMS = (1, 2, 4, 8, 16, 32, 64)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(210)
        self.proposal = None
        self.comparison_cues = ()
        self.comparison_active = False
        self.saved_cues = ()
        self.cue_view = 'both'
        self.waveform_style = 'classic'
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
        self.navigation_help = 'Red lines show the current grid: proposed after preparation, otherwise saved Rekordbox timing. Each four-beat bar starts with one thick line, followed by three thin lines. At whole-track zoom, only spaced bar starts are shown. Triangle flags mark memory cues. Zoom in to see every beat. Drag a DROP handle, click elsewhere to seek, scroll vertically to zoom, or scroll sideways to move through the track.'
        self.setToolTip(self.navigation_help)

    @property
    def duration(self):
        return max(self.proposal.track.duration, 1) if self.proposal else 1

    def set_style(self, style):
        self.waveform_style = style if isinstance(style, str) and style in self.STYLES else 'classic'
        self.update()

    def draw_audio(self, painter, start, end, mid, amp):
        """All styles share the same time coordinates and marker overlays."""
        p = self.proposal
        width = self.width()
        data = p.waveform_data
        peak_duration = len(p.peaks) / data.sample_rate if data and data.sample_rate else self.duration
        columns = pixel_peaks(p.peaks, peak_duration, start, end, width)
        style = self.waveform_style
        painter.save()

        def bars(values, center, amplitude, color):
            painter.setPen(QPen(QColor(color), 1))
            for x, peak in enumerate(values):
                painter.drawLine(x, round(center - amplitude * peak), x, round(center + amplitude * peak))

        def filled(values, center, amplitude, color):
            polygon = QPolygonF([QPointF(x, center - amplitude * v) for x, v in enumerate(values)] +
                                [QPointF(x, center + amplitude * values[x]) for x in range(len(values) - 1, -1, -1)])
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawPolygon(polygon)
            painter.setRenderHint(QPainter.Antialiasing, False)

        legend = self.STYLES[style][0]
        missing_channels = style == 'stereo' and (not data or not data.channels or not all(data.channels))
        missing_bands = style in ('frequency', 'three_band', 'bass') and (not data or len(data.bands) != 3 or not all(data.bands))
        if missing_channels or missing_bands:
            style = 'classic'
            legend += ' — showing saved amplitude; prepare cues / grid for this view'
        if style == 'classic':
            bars(columns, mid, amp, '#748c9f')
        elif style == 'filled':
            filled(columns, mid, amp, '#92b5ce')
        elif style == 'stereo':
            count = len(data.channels)
            for index, channel in enumerate(data.channels):
                center = mid - amp + (2 * index + 1) * amp / count
                channel_duration = len(channel) / data.channel_rate if data.channel_rate else self.duration
                values = pixel_peaks(channel, channel_duration, start, end, width)
                bars(values, center, amp / count * .88, ('#85bce0', '#c2a4e5')[index])
                painter.setPen(QColor('#ffffff'))
                painter.drawText(5, round(center - amp / count * .55), 'Mono' if count == 1 else ('L', 'R')[index])
            legend += ' — mono source' if count == 1 else ' — left / right'
        else:
            bands = [pixel_peaks(band, len(band) / data.band_rate if data.band_rate else self.duration,
                                 start, end, width) for band in data.bands]
            colors = ('#f2a052', '#62ca90', '#699de9')
            if style == 'frequency':
                palette = [QColor(c) for c in colors]
                for x, peak in enumerate(columns):
                    total = sum(band[x] for band in bands)
                    weights = [band[x] / total for band in bands] if total > 1e-8 else [0, 0, 1]
                    color = QColor(*(round(sum(w * getattr(c, component)() for w, c in zip(weights, palette)))
                                     for component in ('red', 'green', 'blue')))
                    painter.setPen(QPen(color, 1))
                    painter.drawLine(x, round(mid - amp * peak), x, round(mid + amp * peak))
                legend += ' — bass: orange · mids: green · highs: blue'
            elif style == 'bass':
                bars(columns, mid, amp, '#303b43')
                filled(bands[0], mid, amp, '#699de9')
                legend += ' — bass: blue · full amplitude: grey'
            else:
                for index, (values, color) in enumerate(zip(bands, colors)):
                    center = mid - amp + (2 * index + 1) * amp / 3
                    bars(values, center, amp / 3 * .88, color)
                    painter.setPen(QColor('#ffffff'))
                    painter.drawText(5, round(center - amp / 3 * .45), ('Low', 'Mid', 'High')[index])
        if data:
            legend = ('Stereo from audio' if style == 'stereo' else data.source) + ' · ' + legend
        description = legend + '\n' + self.navigation_help
        if self.toolTip() != description:
            self.setToolTip(description)
        painter.restore()

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
                      4, 76, 23)

    def hit_marker(self, point):
        p = self.proposal
        if not p or p.error or not p.options.set_cues or (self.comparison_active and self.cue_view == 'saved'):
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
        self.setFocus(Qt.MouseFocusReason)
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
        if self._dragging is not None:
            self._wheel_delta = 0
            event.accept()
            return
        pixels, angles = event.pixelDelta(), event.angleDelta()
        delta = pixels if not pixels.isNull() else angles
        if abs(delta.x()) > abs(delta.y()):
            # Mac touch surfaces provide smooth pixel deltas. Qt has already
            # applied the user's scrolling direction; do not invert it again.
            self._wheel_delta = 0
            start, end = self.visible_range()
            distance = end - start
            movement = (pixels.x() / max(1, self.width()) if not pixels.isNull()
                        else angles.x() / 120 * .1)
            available = self.duration - distance
            if available > 0:
                self.pan((start - movement * distance) / available)
            event.accept()
            return
        self._wheel_delta += event.angleDelta().y()
        if abs(self._wheel_delta) >= 120:
            self.zoom_by(1 if self._wheel_delta > 0 else -1, event.position().x())
            self._wheel_delta = 0
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#121416'))
        p = self.proposal
        if not p or not p.peaks:
            painter.setPen(QColor('#a7adb5'))
            painter.drawText(self.rect(), Qt.AlignCenter, ('Saved detailed waveform unavailable. Set cues / grid to prepare an audio preview.' if p else 'Select a playlist and track to view saved Rekordbox analysis'))
            return
        width, height = self.width(), self.height()
        # Leave a narrow lane for cue triangles above the tallest grid ticks.
        show_drops = p.options.set_cues or self.comparison_active
        has_drop_labels = show_drops and (p.first_drop is not None or p.second_drop is not None)
        memories = [c for c in (self.saved_cues if self.comparison_active else p.cues) if c.kind in ('memory', 'memory_loop')]
        if self.comparison_active and self.cue_view == 'suggested':
            memories = []
        top, bottom = (52 if has_drop_labels else 28 if memories else 18), height - 30
        flag_tip = top - 16
        flags = []
        mid, amp = (top + bottom) / 2, max(1, (bottom - top) / 2)
        start, end = self.visible_range()
        span = end - start
        self.draw_audio(painter, start, end, mid, amp)
        interval = next((v for v in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if v >= span / 10), 600)
        tick = math.ceil(start / interval) * interval
        while tick <= end:
            x = int((tick - start) / span * width)
            painter.setPen(QColor('#33373c'))
            painter.drawLine(x, top, x, height - 20)
            painter.setPen(QColor('#979fa8'))
            painter.drawText(x + 3, height - 5, f'{int(tick) // 60}:{int(tick) % 60:02}')
            tick += interval
        # One active grid avoids interleaving old and shifted beat positions.
        marks = self.grid_marks(p.grid, start, end, width)
        if self.zoom >= 8:
            for x, downbeat in marks:
                painter.setPen(QPen(QColor(255, 101, 114, 125 if downbeat else 65), 2 if downbeat else 1))
                painter.drawLine(x, top, x, bottom)
        for cue in memories:
            if not start <= cue.time <= end or (not self.comparison_active and p.options.set_cues and cue.label in ('DROP 1', 'DROP 2')):
                continue
            x = (cue.time - start) / span * width
            color = QColor('#ff535f' if self.comparison_active else '#a4c4dc' if 'DROP 2' in cue.label else '#739fc9')
            painter.setPen(QPen(color, 1))
            painter.drawLine(int(x), flag_tip, int(x), height - 22)
            flags.append((x, color))
        for number, color in ((1, '#739fc9'), (2, '#a4c4dc')):
            rect = self.marker_rect(number)
            if rect.isEmpty() or not show_drops or (self.comparison_active and self.cue_view == 'saved'):
                continue
            if self.comparison_active:
                color = '#efb34f'
            x = (self.marker_time(number) - start) / span * width
            painter.setPen(QPen(QColor(color), 2))
            painter.drawLine(int(x), int(rect.bottom()), int(x), height - 22)
            if not self.comparison_active:
                flags.append((x, QColor(color)))
            painter.setPen(QPen(QColor(color), 2))
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor('#101820'))
            painter.drawText(rect, Qt.AlignCenter, f'DROP {number}' + (' ↔' if p.options.set_cues else ''))
        painter.setPen(QPen(QColor('#ffffff'), 2))
        x = (self.position - start) / span * width
        painter.drawLine(int(x), top, int(x), height - 18)

        for above in (True, False):
            for x, downbeat in marks:
                color = QColor('#ff6572' if downbeat else '#d45c68')
                painter.setPen(QPen(color, 2 if downbeat else 1))
                if above:
                    painter.drawLine(x, top - (13 if downbeat else 6), x, top + 2)
                    if downbeat:
                        painter.fillRect(x - 2, top - 13, 5, 3, color)
                else:
                    painter.drawLine(x, bottom - 2, x, bottom + (13 if downbeat else 6))
                    if downbeat:
                        painter.fillRect(x - 2, bottom + 10, 5, 3, color)

        # Draw last so a coincident grid or playhead cannot obscure a cue flag.
        for x, color in flags:
            self.draw_cue_flag(painter, x, color, flag_tip)
        # Suggestions use a separate amber lane; saved cues remain blue above.
        for cue in (() if self.comparison_active and self.cue_view == 'saved' else self.comparison_cues):
            if start <= cue.time <= end:
                x = (cue.time - start) / span * width
                painter.setPen(QPen(QColor('#efb34f'), 1, Qt.DashLine))
                painter.drawLine(round(x), top, round(x), bottom + 12)
                self.draw_cue_flag(painter, x, QColor('#efb34f'), bottom + 18)

    @staticmethod
    def draw_cue_flag(painter, x, color, tip):
        """The downward tip and vertical line share the exact cue timestamp."""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([QPointF(x - 5, tip - 8), QPointF(x + 5, tip - 8), QPointF(x, tip)]))
        painter.restore()

    @staticmethod
    def grid_marks(grid, start, end, width):
        """Keep exact source timestamps; thin marks only when zoomed out."""
        if len(grid.times) < 2 or end <= start:
            return []
        beat_width = (grid.times[-1] - grid.times[0]) / (len(grid.times) - 1) * width / (end - start)
        if beat_width <= 0:
            return []
        bar_stride = 1
        while beat_width * 4 * bar_stride < 12:
            bar_stride *= 2
        first_bar = next((i for i, beat in enumerate(grid.positions) if beat == 1), 0)
        marks = []
        for index, (time, beat) in enumerate(zip(grid.times, grid.positions)):
            if not start <= time <= end:
                continue
            if beat_width < 6 and (beat != 1 or ((index - first_bar) // 4) % bar_stride):
                continue
            marks.append((round((time - start) / (end - start) * width), beat == 1))
        return marks
