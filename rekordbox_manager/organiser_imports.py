"""Reviewable playlist changes within the Imports tab."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QMessageBox
from .track_list import TrackList, track_columns
from .usage_ui import text_label


class OrganiserImports(QWidget):
    import_requested = Signal()
    changed = Signal()

    PAGE_SIZE = 100

    def __init__(self, queue):
        super().__init__()
        self.queue = queue
        self.busy = False
        self.page = 0
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.summary = text_label('', 'muted')
        box.addWidget(self.summary)
        box.addWidget(text_label('Draft changes · Nothing is written until you import. Import before closing or reconnecting.', 'muted'))
        widths, stretches = (110, 0, 0, 0), (0, 3, 2, 3)
        header = QWidget()
        header.setObjectName('columnHeader')
        header.setFixedHeight(26)
        track_columns(header, ('CHANGE', 'PLAYLIST / FOLDER', 'TRACK / POSITION', 'ARTIST / FOLDER'), widths, stretches)
        box.addWidget(header)
        self.table = TrackList(widths, stretches)
        box.addWidget(self.table, 1)
        self.message = text_label('', 'muted')
        box.addWidget(self.message)
        footer = QHBoxLayout()
        self.previous = QPushButton('← Previous')
        self.next = QPushButton('Next →')
        self.page_label = text_label('', 'muted')
        self.previous.clicked.connect(lambda: self.change_page(-1))
        self.next.clicked.connect(lambda: self.change_page(1))
        footer.addWidget(self.previous)
        footer.addWidget(self.page_label)
        footer.addWidget(self.next)
        self.discard = QPushButton('Discard playlist changes')
        self.discard.clicked.connect(self.discard_changes)
        footer.addWidget(self.discard)
        footer.addStretch()
        self.import_button = QPushButton('Import playlist changes')
        self.import_button.setObjectName('primary')
        self.import_button.clicked.connect(self.import_requested)
        footer.addWidget(self.import_button)
        box.addLayout(footer)
        self.refresh()

    def refresh(self):
        view = self.queue.view()
        paths = {}
        for node in view.playlist_nodes:
            paths[node.identity] = paths.get(node.parent_id, '') + (' / ' if node.parent_id else '') + node.name
        rows = [['New folder' if n.attribute == 1 else 'New playlist', paths[n.identity], '', ''] for n in self.queue.nodes]
        for key, parent, position in self.queue.structure_changes():
            rows.append(['Move / reorder', paths.get(key, key), f'Position {position}', paths.get(parent, 'Top level')])
        for key, tracks in self.queue.assignments.items():
            rows.extend(['Add track', paths.get(key, key), title, artist] for _, title, artist in tracks.values())
        self.page = min(self.page, max(0, (len(rows) - 1) // self.PAGE_SIZE))
        start = self.page * self.PAGE_SIZE
        self.table.set_cells(rows[start:start + self.PAGE_SIZE])
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(start + self.PAGE_SIZE < len(rows))
        self.previous.setVisible(len(rows) > self.PAGE_SIZE)
        self.next.setVisible(len(rows) > self.PAGE_SIZE)
        self.page_label.setText(f'{start + 1 if rows else 0}–{min(start + self.PAGE_SIZE, len(rows))} of {len(rows):,} changes')
        count = sum(len(tracks) for tracks in self.queue.assignments.values())
        self.summary.setText(f'{len(self.queue.nodes)} new folders/playlists · {count:,} track assignments · {len(self.queue.structure_changes())} moved/reordered')
        self.import_button.setEnabled(self.queue.pending() and not self.busy)
        self.discard.setEnabled(self.queue.pending() and not self.busy)

    def change_page(self, step):
        self.page = max(0, self.page + step)
        self.refresh()

    def discard_changes(self):
        if QMessageBox.question(self, 'Discard playlist changes', 'Discard all queued folders, playlists, moves and track assignments?',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.queue.reset(self.queue.library)
        self.message.setText('Playlist drafts discarded. Rekordbox is unchanged.')
        self.changed.emit()
