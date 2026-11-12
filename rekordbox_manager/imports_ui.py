"""Imports page: all preparation sessions for the currently connected library."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QFrame, QStackedWidget

from .dialogs import review_reason
from .organiser_imports import OrganiserImports
from .track_list import TrackList, track_columns


def label(text, kind=''):
    result = QLabel(text)
    result.setTextFormat(Qt.PlainText)
    result.setWordWrap(True)
    result.setObjectName(kind)
    return result


class ImportsTab(QWidget):
    import_requested = Signal()
    review_requested = Signal(str)
    PAGE_SIZE = 100
    WIDTHS = (32, 0, 0, 50, 66, 90, 0, 112)
    STRETCHES = (0, 3, 2, 0, 0, 0, 2, 0)

    def __init__(self, queue, organiser_queue=None):
        super().__init__()
        self.queue = queue
        self.page = 0
        self.busy = False
        self.visible_entries = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.queue_view = QComboBox()
        self.queue_view.addItems(['Cues & beat grids', 'Playlist changes'])
        self.queue_view.setAccessibleName('Import type')
        self.queue_view.setMaximumWidth(220)
        self.stack = QStackedWidget()
        cue_page = QWidget()
        self.stack.addWidget(cue_page)
        self.organiser = OrganiserImports(organiser_queue) if organiser_queue is not None else None
        if self.organiser:
            self.stack.addWidget(self.organiser)
            outer.addWidget(self.queue_view)
        outer.addWidget(self.stack)
        self.queue_view.currentIndexChanged.connect(self.stack.setCurrentIndex)
        box = QVBoxLayout(cue_page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        controls = QWidget()
        controls_box = QVBoxLayout(controls)
        controls_box.setContentsMargins(10, 7, 10, 7)
        controls_box.setSpacing(6)
        heading = QHBoxLayout()
        heading.addWidget(label('IMPORTS', 'eyebrow'))
        self.summary = label('', 'muted')
        heading.addWidget(self.summary, 1)
        controls_box.addLayout(heading)
        filters = QHBoxLayout()
        filters.addWidget(label('Show'))
        self.filter = QComboBox()
        self.filter.setAccessibleName('Import queue filter')
        self.filter.addItems(['Ready to import', 'Needs review', 'All pending tracks'])
        self.filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.filter)
        self.search = QLineEdit()
        self.search.setAccessibleName('Search import queue')
        self.search.setPlaceholderText('Search track, artist or source playlist…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        controls_box.addLayout(filters)
        session_note = label('Session queue · Import before closing or reconnecting your library.', 'muted')
        session_note.setToolTip('Prepared tracks from every playlist managed in this session. Shared tracks appear once; their latest preparation is used. Import updates existing tracks while preserving playlist membership, folders and track order. Review the drops and grid before importing.')
        controls_box.addWidget(session_note)
        box.addWidget(controls)
        self.message = label('', 'muted')
        box.addWidget(self.message)
        browser = QFrame()
        browser.setObjectName('browser')
        browser_box = QVBoxLayout(browser)
        browser_box.setContentsMargins(0, 0, 0, 0)
        browser_box.setSpacing(0)
        self.header = QWidget()
        self.header.setObjectName('columnHeader')
        self.header.setFixedHeight(25)
        columns = track_columns(self.header, ['#', 'TRACK TITLE', 'ARTIST', 'BPM', 'MEMORY', 'CHANGES', 'SOURCE PLAYLISTS', 'STATUS'], self.WIDTHS, self.STRETCHES)
        columns.setContentsMargins(10, 0, 19, 0)
        browser_box.addWidget(self.header)
        self.table = TrackList(self.WIDTHS, self.STRETCHES)
        self.table.setAccessibleName('Tracks queued for import')
        self.table.itemSelectionChanged.connect(self.update_review_action)
        browser_box.addWidget(self.table, 1)
        self.empty = label('', 'muted')
        browser_box.addWidget(self.empty)
        box.addWidget(browser, 1)
        footer = QHBoxLayout()
        self.previous = QPushButton('← Previous')
        self.previous.clicked.connect(lambda: self.change_page(-1))
        footer.addWidget(self.previous)
        self.page_label = label('', 'muted')
        footer.addWidget(self.page_label)
        self.next = QPushButton('Next →')
        self.next.clicked.connect(lambda: self.change_page(1))
        footer.addWidget(self.next)
        footer.addStretch()
        self.review_button = QPushButton('Review in Manager')
        self.review_button.clicked.connect(self.review_selected)
        footer.addWidget(self.review_button)
        self.import_button = QPushButton('Import all ready tracks')
        self.import_button.setObjectName('primary')
        self.import_button.clicked.connect(self.import_requested)
        footer.addWidget(self.import_button)
        box.addLayout(footer)
        self.refresh()

    def selected_identity(self):
        row = self.table.currentRow()
        return self.visible_entries[row].proposal.track.id if 0 <= row < len(self.visible_entries) else None

    def update_review_action(self):
        self.review_button.setEnabled(self.selected_identity() is not None and not self.busy)

    def review_selected(self):
        identity = self.selected_identity()
        if identity is not None and not self.busy:
            self.review_requested.emit(identity)

    def refresh(self, *args, keep_page=False):
        if self.organiser:
            self.organiser.busy = self.busy
            self.organiser.refresh()
            count = len(self.organiser.queue.nodes) + len(self.organiser.queue.structure_changes()) + sum(len(t) for t in self.organiser.queue.assignments.values())
            self.queue_view.setItemText(1, f'Playlist changes ({count})' if count else 'Playlist changes')
        selected = self.selected_identity()
        if not keep_page:
            self.page = 0
        pending = self.queue.pending()
        ready = len(self.queue.ready())
        count = len({key for entry in pending for key in entry.sources})
        self.summary.setText(f'{ready:,} ready to import · {len(pending) - ready:,} need review · {count:,} source playlist' + ('s' if count != 1 else ''))
        library = self.queue.library
        self.import_button.setText(f'Import all {ready:,} ready tracks')
        self.import_button.setEnabled(bool(ready and library and library.writable and not self.busy))
        self.import_button.setToolTip('Imports every ready track in the queue, including tracks hidden by search or filters. Playlist membership and order are preserved.')
        words = self.search.text().casefold().split()
        mode = self.filter.currentIndex()
        matches = [entry for entry in pending if (mode == 2 or entry.proposal.ready_to_apply == (mode == 0))
                   and all(word in (' '.join((entry.proposal.track.title, entry.proposal.track.artist, *entry.sources.values()))).casefold() for word in words)]
        self.page = min(self.page, max(0, (len(matches) - 1) // self.PAGE_SIZE))
        start = self.page * self.PAGE_SIZE
        self.visible_entries = matches[start:start + self.PAGE_SIZE]
        rows, reasons = [], []
        for index, entry in enumerate(self.visible_entries, start + 1):
            p = entry.proposal
            cues = sum(c.kind in ('memory', 'memory_loop') for c in p.cues)
            operation = 'Grid + cues' if p.options.fix_grid and p.options.set_cues else 'Grid only' if p.options.fix_grid else 'Cues only'
            rows.append([str(index), p.track.title, p.track.artist, f'{p.track.bpm:g}', f'{cues} / 10', operation,
                         ' · '.join(entry.sources.values()), 'Ready to import' if p.ready_to_apply else 'Needs review'])
            reasons.append('' if p.ready_to_apply else review_reason(p))
        self.table.set_cells(rows, reasons)
        if rows:
            self.table.selectRow(next((i for i, entry in enumerate(self.visible_entries) if entry.proposal.track.id == selected), 0))
        self.empty.setText('No tracks match this view.' if pending else 'Prepare playlists in Manager. Ready tracks will collect here automatically.')
        self.empty.setVisible(not rows)
        self.update_review_action()
        self.page_label.setText(f'{start + 1 if matches else 0}–{min(start + self.PAGE_SIZE, len(matches))} of {len(matches):,} tracks')
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(start + self.PAGE_SIZE < len(matches))
        self.previous.setVisible(len(matches) > self.PAGE_SIZE)
        self.next.setVisible(len(matches) > self.PAGE_SIZE)

    def change_page(self, step):
        self.page = max(0, self.page + step)
        self.refresh(keep_page=True)
