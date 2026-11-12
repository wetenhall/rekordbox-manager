"""Shared compact track rows for Manager and Imports."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QSizePolicy, QHBoxLayout, QVBoxLayout, QScrollArea, QFrame, QWidget, QPushButton


class ElidedLabel(QLabel):
    """One-line text that keeps long titles and warnings from widening the window."""
    def __init__(self, text="", kind=""):
        super().__init__()
        self.full_text = ""
        self.setTextFormat(Qt.PlainText)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if kind:
            self.setObjectName(kind)
        self.setText(text)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self.full_text.replace("\n", " · "),
                                                    Qt.ElideRight, max(0, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


def track_columns(parent, values, widths=(32, 158, 0, 0, 62, 72, 118), stretches=(0, 0, 3, 2, 0, 0, 0), interactive_columns=()):
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(10, 0, 10, 0)
    layout.setSpacing(12)
    # Same geometry for header and rows; title/artist take the spare width.
    for index, (text, width, stretch) in enumerate(zip(values, widths, stretches)):
        cell = text if isinstance(text, QWidget) else ElidedLabel(text)
        cell.setAttribute(Qt.WA_TransparentForMouseEvents, index not in interactive_columns)
        if width:
            cell.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            cell.setFixedWidth(width)
        layout.addWidget(cell, stretch)
    return layout


class TrackList(QScrollArea):
    """Ordinary accessible buttons avoid Qt's macOS table AX ownership bug.

    See QTBUG-149612. Keep native accessibility enabled for every track.
    """
    itemSelectionChanged = Signal()

    def __init__(self, widths=(32, 158, 0, 0, 62, 72, 118), stretches=(0, 0, 3, 2, 0, 0, 0), interactive_columns=()):
        super().__init__()
        self.widths, self.stretches = widths, stretches
        self.interactive_columns = interactive_columns
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._selected = -1
        self._buttons = []

    def set_rows(self, rows, reasons=None, previews=None):
        cells = []
        for index, (title, genre, bpm, memory, status) in enumerate(rows):
            title, _, artist = title.partition("\n")
            cells.append([str(index + 1), previews[index] if previews else genre, title, artist, bpm, memory, status])
        self.set_cells(cells, reasons)

    def set_cells(self, rows, reasons=None):
        self._selected = -1
        old = self.takeWidget()
        if old:
            old.deleteLater()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._buttons = []
        for index, values in enumerate(rows):
            text = " · ".join(v.accessibleName() if isinstance(v, QWidget) else v for v in values)
            item = QPushButton()
            reason = reasons[index] if reasons else ""
            item.setFixedHeight(28)
            item.setObjectName('track')
            item.setProperty('alternate', bool(index % 2))
            item.setProperty('needsReview', bool(reason))
            item.setAccessibleName(text + (" · " + reason if reason else ""))
            item.setToolTip(text + ("\n" + reason if reason else ""))
            item.setCheckable(True)
            outer = QVBoxLayout(item)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)
            main_row = QWidget()
            main_row.setAttribute(Qt.WA_TransparentForMouseEvents, not bool(self.interactive_columns))
            main_row.setStyleSheet("background: transparent;")
            main_row.setFixedHeight(28)
            track_columns(main_row, values, self.widths, self.stretches, self.interactive_columns)
            outer.addWidget(main_row)
            item.clicked.connect(lambda checked=False, row=index: self.activate_row(row))
            layout.addWidget(item)
            self._buttons.append(item)
        layout.addStretch()
        self.setWidget(content)

    def activate_row(self, index):
        # macOS button clicks need an explicit focus handoff from editors/menus.
        self._buttons[index].setFocus(Qt.MouseFocusReason)
        self.selectRow(index)

    def visible_rows(self):
        return [i for i, item in enumerate(self._buttons) if not item.isHidden()]

    def set_visible_rows(self, indices):
        visible = set(indices)
        for i, item in enumerate(self._buttons):
            item.setVisible(i in visible)
        if self._selected not in visible:
            self._selected = -1

    def currentRow(self):
        return self._selected

    def selectRow(self, index):
        if 0 <= index < len(self._buttons) and not self._buttons[index].isHidden():
            self._selected = index
            for row, item in enumerate(self._buttons):
                item.setChecked(row == index)
            self.ensureWidgetVisible(self._buttons[index])
            self.itemSelectionChanged.emit()
