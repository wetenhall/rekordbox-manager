"""Drag gestures request draft moves; the Qt model never writes the library."""
from PySide6.QtCore import Qt, Signal, QPoint, QTimer
from PySide6.QtGui import QDrag, QColor, QPen
from PySide6.QtWidgets import QTreeWidget, QAbstractItemView

from .organiser_tracks import TRACK_MIME

IDENTITY_ROLE = Qt.UserRole + 2


class OrganiserTree(QTreeWidget):
    move_requested = Signal(str, object, object)

    def __init__(self):
        super().__init__()
        self.structure_enabled = False
        self.dragged_id = None
        self.tracks_enabled = False
        self.track_source = None
        self.track_drop = None
        self.track_target = None
        self.hover_item = None
        self.scroll_direction = 0
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(650)
        self.hover_timer.timeout.connect(self.expand_hover_folder)
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setInterval(75)
        self.scroll_timer.timeout.connect(self.scroll_tracks)
        self.setAutoExpandDelay(650)

    def enable_structure(self, enabled):
        self.structure_enabled = enabled
        accepting = enabled or self.tracks_enabled
        self.setDragDropMode(QAbstractItemView.DragDrop if accepting else QAbstractItemView.NoDragDrop)
        self.setDragEnabled(enabled)
        self.setAcceptDrops(accepting)
        self.setDropIndicatorShown(enabled)
        self.setDefaultDropAction(Qt.MoveAction)

    def enable_tracks(self, enabled):
        self.tracks_enabled = enabled
        self.enable_structure(self.structure_enabled)
        if not enabled:
            self.clear_track_hover()

    def is_track_drag(self, event):
        return (self.tracks_enabled and self.track_source is not None
                and event.source() is self.track_source and self.track_source.active_drag is not None
                and event.mimeData().hasFormat(TRACK_MIME))

    def track_destination(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and not item.isDisabled() and item.data(0, Qt.UserRole + 1) == 0:
            return item.data(0, IDENTITY_ROLE)
        return None

    def clear_track_hover(self):
        self.track_target = None
        self.hover_item = None
        self.hover_timer.stop()
        self.scroll_timer.stop()
        self.viewport().update()

    def expand_hover_folder(self):
        if self.hover_item and self.hover_item.data(0, Qt.UserRole + 1) == 1:
            self.hover_item.setExpanded(True)

    def scroll_tracks(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + self.scroll_direction * bar.singleStep())

    def drawRow(self, painter, option, index):
        super().drawRow(painter, option, index)
        if self.track_target and index.data(IDENTITY_ROLE) == self.track_target:
            painter.save()
            painter.setPen(QPen(QColor('#83afd0'), 2))
            painter.drawRect(option.rect.adjusted(1, 1, -2, -2))
            painter.restore()

    def dragLeaveEvent(self, event):
        self.clear_track_hover()
        super().dragLeaveEvent(event)

    def startDrag(self, actions):
        item = self.currentItem()
        if not self.structure_enabled or item is None or item.data(0, Qt.UserRole + 1) not in (0, 1):
            return
        self.dragged_id = item.data(0, IDENTITY_ROLE)
        drag = QDrag(self)
        drag.setMimeData(self.model().mimeData(self.selectedIndexes()))
        rect = self.visualItemRect(item)
        drag.setPixmap(self.viewport().grab(rect))
        drag.setHotSpot(QPoint(16, rect.height() // 2))
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.dragged_id = None

    def destination(self, item, indicator):
        if item is None or indicator == QAbstractItemView.OnViewport:
            return None, None
        if indicator == QAbstractItemView.OnItem:
            if item.data(0, Qt.UserRole + 1) != 1:
                raise ValueError('Tracks cannot contain playlists.')
            return item.data(0, IDENTITY_ROLE), None
        parent = item.parent()
        parent_id = parent.data(0, IDENTITY_ROLE) if parent else None
        container = parent or self.invisibleRootItem()
        index = container.indexOfChild(item)
        if indicator == QAbstractItemView.BelowItem:
            index += 1
        before = container.child(index).data(0, IDENTITY_ROLE) if index < container.childCount() else None
        return parent_id, before

    def valid_target(self, parent):
        item = next((i for i in self.findItems('*', Qt.MatchWildcard | Qt.MatchRecursive)
                     if i.data(0, IDENTITY_ROLE) == parent), None) if parent else None
        while item:
            if item.data(0, IDENTITY_ROLE) == self.dragged_id:
                return False
            item = item.parent()
        return True

    def dragEnterEvent(self, event):
        if self.is_track_drag(event):
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        if not self.structure_enabled or event.source() is not self or not self.dragged_id:
            event.ignore()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self.is_track_drag(event):
            point = event.position().toPoint()
            item = self.itemAt(point)
            if item is not self.hover_item:
                self.hover_item = item
                self.hover_timer.start()
            self.scroll_direction = -1 if point.y() < 24 else (1 if point.y() > self.viewport().height() - 24 else 0)
            if self.scroll_direction:
                self.scroll_timer.start()
            else:
                self.scroll_timer.stop()
            self.track_target = self.track_destination(event)
            self.viewport().update()
            if self.track_target:
                event.setDropAction(Qt.CopyAction)
                event.accept()
            else:
                event.ignore()
            return
        if not self.structure_enabled or event.source() is not self:
            event.ignore()
            return
        super().dragMoveEvent(event)
        try:
            parent, _ = self.destination(self.itemAt(event.position().toPoint()), self.dropIndicatorPosition())
            if not self.valid_target(parent):
                event.ignore()
        except ValueError:
            event.ignore()

    def dropEvent(self, event):
        if self.is_track_drag(event):
            destination = self.track_destination(event)
            payload = self.track_source.active_drag
            self.clear_track_hover()
            if destination and self.track_drop and self.track_drop(destination, payload):
                event.setDropAction(Qt.CopyAction)
                event.accept()
            else:
                event.ignore()
            return
        self.clear_track_hover()
        if not self.structure_enabled or event.source() is not self or not self.dragged_id:
            event.ignore()
            return
        try:
            parent, before = self.destination(self.itemAt(event.position().toPoint()), self.dropIndicatorPosition())
            if not self.valid_target(parent):
                event.ignore()
                return
            self.move_requested.emit(self.dragged_id, parent, before)
            event.setDropAction(Qt.MoveAction)
            event.accept()
        except ValueError:
            event.ignore()
