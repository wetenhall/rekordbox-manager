"""Self-contained Library usage tab. Manager edits remain in their own workspace."""
from threading import Event
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QScrollArea, QProgressBar, QSizePolicy,
)

from .usage import scan_usage


def text_label(text, kind=''):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setObjectName(kind)
    return label


class UsageWorker(QThread):
    result = Signal(object, str)

    def __init__(self, library, generation, parent):
        super().__init__(parent)
        self.library, self.generation = library, generation
        self.cancelled = Event()

    def run(self):
        try:
            result = scan_usage(self.library, self.cancelled.is_set)
            self.result.emit(result, '')
        except Exception as exc:
            self.result.emit(None, 'Scan cancelled.' if self.cancelled.is_set() else str(exc))


class LibraryUsageTab(QWidget):
    busy_changed = Signal()
    PAGE_SIZE = 100

    def __init__(self, parent=None, title='Library usage'):
        super().__init__(parent)
        self.library = self.worker = self.scan = None
        self.generation = 0
        self.page = 0
        self.matches = []
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 18, 22, 18)
        heading = QHBoxLayout()
        heading.addWidget(text_label(title, 'title'))
        heading.addStretch()
        self.scan_button = QPushButton('Scan library')
        self.scan_button.setObjectName('primary')
        self.scan_button.clicked.connect(self.start_scan)
        self.scan_button.setEnabled(False)
        heading.addWidget(self.scan_button)
        self.cancel_button = QPushButton('Cancel scan')
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.cancel_button.hide()
        heading.addWidget(self.cancel_button)
        box.addLayout(heading)
        box.addWidget(text_label('Find overlooked tracks across your entire collection. Scanning only reads library metadata.', 'muted'))
        self.source = text_label('Connect a Rekordbox library in Settings.', 'muted')
        box.addWidget(self.source)
        box.addWidget(text_label(
            '“No recorded plays” means a zero play count and no saved history entries in the available data. '
            'Missing play counts are unknown. Reset counts, deleted history and unsynced device plays can hide past use. '
            'Playlist membership covers regular playlists only; smart playlists are excluded.', 'muted'))
        self.summary = text_label('Scan your library to see usage counts.', 'section')
        box.addWidget(self.summary)
        filters = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.setAccessibleName('Usage filter')
        for title, key in (
            ('No recorded plays', 'unplayed'), ('Outside regular playlists', 'outside'),
            ('No recorded plays + outside playlists', 'both'), ('Played', 'played'),
            ('Unknown play status', 'unknown'), ('All tracks', 'all'),
        ):
            self.filter.addItem(title, key)
        filters.addWidget(self.filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search title, artist or genre…')
        self.search.setAccessibleName('Search library usage')
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 1)
        self.sort = QComboBox()
        self.sort.setAccessibleName('Sort library usage')
        for title, key in (('Title A–Z', 'title'), ('Artist A–Z', 'artist'), ('Fewest plays', 'plays'), ('Most plays', 'most')):
            self.sort.addItem(title, key)
        filters.addWidget(self.sort)
        box.addLayout(filters)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        box.addWidget(self.progress)
        self.message = text_label('No scan yet.', 'muted')
        box.addWidget(self.message)
        self.list = QScrollArea()
        self.list.setWidgetResizable(True)
        box.addWidget(self.list, 1)
        pagination = QHBoxLayout()
        self.previous = QPushButton('← Previous')
        self.previous.clicked.connect(lambda: self.change_page(-1))
        pagination.addWidget(self.previous)
        self.page_label = text_label('')
        pagination.addWidget(self.page_label, 1)
        self.next = QPushButton('Next →')
        self.next.clicked.connect(lambda: self.change_page(1))
        pagination.addWidget(self.next)
        box.addLayout(pagination)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self.apply_filters)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        self.filter.currentIndexChanged.connect(self.apply_filters)
        self.sort.currentIndexChanged.connect(self.apply_filters)
        self.render_page()

    @property
    def scanning(self):
        # Include queued results/finished signals, not just the thread's run().
        return self.worker is not None

    def set_library(self, library):
        self.cancel_scan()
        self.generation += 1
        self.library = library
        self.scan = None
        self.summary.setText('Scan your library to see usage counts.')
        self.source.setText(str(getattr(library, 'path', 'No library connected')))
        supported = library is not None and not getattr(library, 'demo', False) and hasattr(library, 'connect')
        self.scan_button.setEnabled(supported and not self.scanning)
        self.message.setText('Ready to scan the whole library.' if supported else 'Connect a Rekordbox database in Settings to scan usage.')
        self.apply_filters()

    def start_scan(self):
        if self.scanning or self.library is None or getattr(self.library, 'demo', False):
            return
        self.scan = None
        self.apply_filters()
        self.summary.setText('Scanning the whole library…')
        self.message.setText('Reading play counts, saved history and regular-playlist membership…')
        self.scan_button.setEnabled(False)
        self.cancel_button.show()
        self.progress.show()
        worker = UsageWorker(self.library, self.generation, self)
        self.worker = worker
        worker.result.connect(self.scan_result)
        worker.finished.connect(self.scan_finished)
        self.busy_changed.emit()
        worker.start()

    def cancel_scan(self):
        if self.scanning:
            self.worker.cancelled.set()

    def scan_result(self, scan, error):
        if self.worker.generation != self.generation:
            return
        if self.worker.cancelled.is_set():
            scan, error = None, 'Scan cancelled.'
        if error:
            self.summary.setText('Scan incomplete — no results shown.')
            self.message.setText(error)
            return
        self.scan = scan
        self.message.setText(f'Scanned {scan.scanned_at}. ' + ' '.join(scan.notes))
        self.apply_filters()

    def scan_finished(self):
        self.progress.hide()
        self.cancel_button.hide()
        self.scan_button.setEnabled(self.library is not None and not getattr(self.library, 'demo', False) and hasattr(self.library, 'connect'))
        worker = self.worker
        self.worker = None
        worker.deleteLater()
        self.busy_changed.emit()

    def outside_playlists(self, track):
        return track.playlists == 0

    def update_summary(self):
        tracks = self.scan.tracks
        self.summary.setText(
            f'{len(tracks):,} tracks  ·  {sum(t.play_status == "No recorded plays" for t in tracks):,} no recorded plays  ·  '
            f'{sum(self.outside_playlists(t) for t in tracks):,} outside regular playlists  ·  '
            f'{sum(t.play_status == "Played" for t in tracks):,} played  ·  '
            f'{sum(t.play_status == "Unknown" for t in tracks):,} unknown')

    def apply_filters(self):
        if self.scan:
            self.update_summary()
        key = self.filter.currentData()
        words = self.search.text().casefold().split()
        def matches(t):
            status = t.play_status
            include = (key == 'all' or (key == 'unplayed' and status == 'No recorded plays')
                       or (key == 'outside' and self.outside_playlists(t))
                       or (key == 'both' and status == 'No recorded plays' and self.outside_playlists(t))
                       or (key == 'played' and status == 'Played') or (key == 'unknown' and status == 'Unknown'))
            return include and self.track_in_scope(t) and all(word in f'{t.title} {t.artist} {t.genre}'.casefold() for word in words)
        self.matches = [t for t in self.scan.tracks if matches(t)] if self.scan else []
        sort = self.sort.currentData()
        def order(t):
            if sort in ('plays', 'most'):
                return (t.plays is None, (t.plays or 0) * (-1 if sort == 'most' else 1), t.title.casefold(), t.id)
            return (getattr(t, sort).casefold(), t.title.casefold(), t.id)
        self.matches.sort(key=order)
        self.page = 0
        self.render_page()

    def track_in_scope(self, track):
        return True

    def change_page(self, step):
        self.page = max(0, min(self.page + step, max(0, (len(self.matches) - 1) // self.PAGE_SIZE)))
        self.render_page()

    def render_page(self):
        old = self.list.takeWidget()
        if old:
            old.deleteLater()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 8, 10, 8)
        start = self.page * self.PAGE_SIZE
        for track in self.matches[start:start + self.PAGE_SIZE]:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(4, 6, 4, 6)
            self.add_row_controls(line, track)
            title = text_label(f'{track.title}\n{track.artist}' + (f' · {track.genre}' if track.genre else ''))
            title.setMinimumWidth(0)
            title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            title.setTextInteractionFlags(Qt.TextSelectableByMouse)
            title.setToolTip(f'{track.title}\n{track.artist}\n{track.path}')
            line.addWidget(title, 1)
            def count(value):
                return 'Unknown' if value is None else str(value)
            evidence = text_label(f'Plays: {count(track.plays)}  ·  History entries: {count(track.history_entries)}\n'
                                  f'Regular playlists: {count(track.playlists)}  ·  {track.play_status}', 'muted')
            evidence.setFixedWidth(385)
            line.addWidget(evidence)
            layout.addWidget(row)
        if not self.matches:
            layout.addWidget(text_label('No tracks match these filters.' if self.scan and self.scan.tracks else
                                       'This library has no active tracks.' if self.scan else 'Scan results will appear here.', 'muted'))
        layout.addStretch()
        self.list.setWidget(content)
        self.list.verticalScrollBar().setValue(0)
        total = len(self.matches)
        self.page_label.setText(f'{start + 1 if total else 0}–{min(start + self.PAGE_SIZE, total)} of {total:,} matching tracks')
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(start + self.PAGE_SIZE < total)

    def add_row_controls(self, line, track):
        pass
