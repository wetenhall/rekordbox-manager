"""Organiser-only multi-selection and track drag gestures."""
from PySide6.QtCore import Qt, QEvent, QMimeData, QPoint
from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor
from PySide6.QtWidgets import QApplication, QWidget, QCheckBox

from .track_list import TrackList

TRACK_MIME = 'application/x-rekordbox-manager-tracks'


class OrganiserTrackList(TrackList):
    def __init__(self, owner, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.anchor = None
        self.press = None
        self.active_drag = None

    def set_cells(self, rows, reasons=None):
        self.press = None
        super().set_cells(rows, reasons)
        for index, button in enumerate(self._buttons):
            # The container receives clicks on text; the checkbox keeps its own events.
            for widget in (button, button.layout().itemAt(0).widget()):
                widget.setProperty('organiserRow', index)
                widget.installEventFilter(self)
        self.sync_selection()

    def sync_selection(self):
        for track, button in zip(self.page_tracks(), self._buttons):
            selected = track.id in self.owner.selected_ids
            button.setChecked(selected)
            check = button.findChild(QCheckBox)
            check.blockSignals(True)
            check.setChecked(selected)
            check.blockSignals(False)

    def page_tracks(self):
        start = self.owner.page * self.owner.PAGE_SIZE
        return self.owner.matches[start:start + self.owner.PAGE_SIZE]

    def choose(self, index, modifiers=Qt.NoModifier):
        tracks = self.page_tracks()
        if self.owner.scanning or not 0 <= index < len(tracks):
            return
        identity = tracks[index].id
        selected = self.owner.selected_ids
        toggle = bool(modifiers & (Qt.ControlModifier | Qt.MetaModifier))
        if modifiers & Qt.ShiftModifier:
            ordered = [t.id for t in self.owner.matches]
            anchor = self.anchor if self.anchor in ordered else identity
            first, last = sorted((ordered.index(anchor), ordered.index(identity)))
            if not toggle:
                selected.clear()
            selected.update(ordered[first:last + 1])
        elif toggle:
            selected.symmetric_difference_update({identity})
            self.anchor = identity
        else:
            selected.clear()
            selected.add(identity)
            self.anchor = identity
        self._selected = index
        self._buttons[index].setFocus(Qt.MouseFocusReason)
        self.sync_selection()
        self.owner.update_selection()

    def activate_row(self, index):
        # Keyboard/accessibility activation uses the same selection as mouse clicks.
        self.choose(index, QApplication.keyboardModifiers())

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            index = watched.property('organiserRow')
            tracks = self.page_tracks()
            if self.owner.scanning or index >= len(tracks):
                return True
            modifiers = event.modifiers()
            selected = tracks[index].id in self.owner.selected_ids
            defer = selected and not modifiers & (Qt.ControlModifier | Qt.MetaModifier | Qt.ShiftModifier)
            self.press = (index, event.globalPosition().toPoint(), defer)
            if not defer:
                self.choose(index, modifiers)
            return True
        if kind == QEvent.MouseMove and self.press and event.buttons() & Qt.LeftButton:
            index, origin, _ = self.press
            if (event.globalPosition().toPoint() - origin).manhattanLength() >= QApplication.startDragDistance():
                self.press = None
                self.start_track_drag(index)
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self.press:
            index, _, defer = self.press
            self.press = None
            if defer:
                self.choose(index)
            return True
        return super().eventFilter(watched, event)

    def start_track_drag(self, index):
        page = self.owner
        if not page.add_button.isEnabled() or not page.scan:
            return
        tracks = self.page_tracks()
        if not 0 <= index < len(tracks) or tracks[index].id not in page.selected_ids:
            return
        identities = tuple(t.id for t in page.selected_tracks())
        # Trust the in-process source and immutable scan, never arbitrary external MIME IDs.
        self.active_drag = (page.library, page.scan, identities)
        mime = QMimeData()
        mime.setData(TRACK_MIME, b'1')
        drag = QDrag(self)
        drag.setMimeData(mime)
        label = f'{len(identities)} track' + ('s' if len(identities) != 1 else '')
        pixmap = QPixmap(140, 30)
        pixmap.fill(QColor('#30373e'))
        painter = QPainter(pixmap)
        painter.setPen(QColor('#e4e7eb'))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, label)
        painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(12, 15))
        try:
            drag.exec(Qt.CopyAction)
        finally:
            self.active_drag = None
