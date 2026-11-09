"""Bounded dialogs for batch selection and import review."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QListWidget, QListWidgetItem, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)


def text_label(text):
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    return label


def review_reason(proposal):
    if proposal.error:
        return proposal.error
    issue = proposal.grid_issue
    if 'Drum timing' in issue or 'Not enough drum evidence' in issue:
        return 'Automatic timing check inconclusive. Listen, check the drops and rebuild.'
    if 'nearest bar start' in issue:
        return 'The two drops do not align with the same grid. Check their positions and BPM.'
    if 'boundary beat' in issue:
        return 'Proposed grid shift is too large. Check the grid in Rekordbox.'
    if issue:
        return issue
    if proposal.review_note:
        return proposal.review_note
    if proposal.first_drop is None or proposal.second_drop is None:
        return 'Set both drop markers, then rebuild cues.'
    if proposal.drop_notes and not (proposal.first_drop_edited or proposal.second_drop_edited):
        return 'Check the suggested drops, then rebuild cues.'
    return 'Rebuild cues before importing.'


class ImportDialog(QDialog):
    def __init__(self, parent, candidates, skipped, backup_path, live, playlist_count=1, playlist_breakdown=None):
        super().__init__(parent)
        self.setWindowTitle('Import to Rekordbox' if live else 'Apply demo changes')
        self.setMinimumWidth(500)
        self.resize(580, 260)
        box = QVBoxLayout(self)
        box.setSpacing(10 if playlist_breakdown else 14)
        self.summary = text_label(f'{len(candidates)} ready to import  ·  {len(skipped)} need review')
        self.summary.setStyleSheet('font-size: 19px; font-weight: 600;')
        box.addWidget(self.summary)
        cue_only = sum(p.options.set_cues and not p.options.fix_grid for p in candidates)
        if cue_only:
            box.addWidget(text_label(f'{cue_only} tracks: cues only, existing Rekordbox grids kept.'))
        scope = f'Across {playlist_count} playlists. Shared tracks are included once.\n' if playlist_count > 1 else ''
        box.addWidget(text_label(scope + (f'The {len(skipped)} tracks needing review will be left unchanged.' if skipped else 'All analysed tracks are ready.')))
        if playlist_breakdown:
            box.addWidget(text_label('Scanned playlists'))
            show_done = any(row[4] for row in playlist_breakdown)
            headers = ['Playlist', 'Scanned', 'Import', 'Skip'] + (['Imported'] if show_done else [])
            self.playlist_table = QTableWidget(len(playlist_breakdown), len(headers))
            self.playlist_table.setAccessibleName('Import breakdown by scanned playlist')
            self.playlist_table.setHorizontalHeaderLabels(headers)
            self.playlist_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.playlist_table.setSelectionMode(QAbstractItemView.NoSelection)
            self.playlist_table.setWordWrap(False)
            self.playlist_table.verticalHeader().hide()
            self.playlist_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.playlist_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self.playlist_table.verticalHeader().setDefaultSectionSize(28)
            for row, values in enumerate(playlist_breakdown):
                for column, value in enumerate(values if show_done else values[:4]):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(value))
                    if column:
                        item.setTextAlignment(Qt.AlignCenter)
                    self.playlist_table.setItem(row, column, item)
            self.playlist_table.setFixedHeight(32 + min(4, len(playlist_breakdown)) * 28)
            box.addWidget(self.playlist_table)
            box.addWidget(text_label('Shared tracks count in each playlist, but are imported once.'))
            if live:
                box.addWidget(text_label('Cues and grids update the track everywhere it appears. Playlist membership is unchanged.'))
        box.addWidget(text_label('Listen to the drops and check the grid before importing.\nA backup will be created. Keep Rekordbox closed.' if live else 'Changes affect the demo library only. A backup will be created.'))
        self.details_toggle = QPushButton('Show details')
        self.details_toggle.setCheckable(True)
        self.details_toggle.setAutoDefault(False)
        box.addWidget(self.details_toggle)
        self.details = QPlainTextEdit()
        self.details.setAccessibleName('Import details')
        self.details.setReadOnly(True)
        self.details.setFixedHeight(120 if playlist_breakdown else 220)
        lines = ['NEEDS REVIEW — left unchanged', *[f'{p.track.title} — {p.track.artist}\n{review_reason(p)}\n' for p in skipped]] if skipped else []
        lines += ['READY TO IMPORT', *[f'{p.track.title} — {p.track.artist}' +
                  (' · Cues only; existing grid kept' if p.options.set_cues and not p.options.fix_grid else '') for p in candidates], '',
                  'BACKUP', str(backup_path), 'Includes the database and changed analysis files.' if live else 'Includes changed demo files.',
                  'Existing hot cues, saved loops and source audio are preserved.']
        self.details.setPlainText('\n'.join(lines))
        box.addWidget(self.details)
        self.details.hide()
        self.details_toggle.toggled.connect(self.toggle_details)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.clicked.connect(self.reject)
        self.cancel_button.setDefault(True)
        buttons.addWidget(self.cancel_button)
        self.import_button = QPushButton(f'Import {len(candidates)} tracks' if live else f'Apply {len(candidates)} tracks')
        self.import_button.setAutoDefault(False)
        self.import_button.clicked.connect(self.accept)
        buttons.addWidget(self.import_button)
        box.addLayout(buttons)

    def toggle_details(self, checked):
        self.details.setVisible(checked)
        self.details_toggle.setText('Hide details' if checked else 'Show details')
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())


class PlaylistDialog(QDialog):
    def __init__(self, parent, playlists, selected):
        super().__init__(parent)
        self.setWindowTitle('Choose playlists')
        self.resize(560, 480)
        box = QVBoxLayout(self)
        box.addWidget(text_label('Choose playlists to analyse together. Shared tracks are included once.'))
        box.addWidget(text_label('Changing the selection clears the current analysis and marker edits.'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a playlist…')
        self.search.setAccessibleName('Find a playlist')
        box.addWidget(self.search)
        self.list = QListWidget()
        self.list.setAccessibleName('Playlists to analyse')
        for identity, name in playlists.items():
            item = QListWidgetItem(name, self.list)
            item.setData(Qt.UserRole, identity)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if identity in selected else Qt.Unchecked)
        box.addWidget(self.list)
        actions = QHBoxLayout()
        for title, state in (('Select visible', Qt.Checked), ('Clear visible', Qt.Unchecked)):
            control = QPushButton(title)
            control.setAutoDefault(False)
            control.clicked.connect(lambda checked=False, value=state: self.check_visible(value))
            actions.addWidget(control)
        box.addLayout(actions)
        self.count = text_label('')
        box.addWidget(self.count)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.use_button = QPushButton('Use selected playlists')
        self.use_button.clicked.connect(self.accept)
        buttons.addWidget(self.use_button)
        box.addLayout(buttons)
        self.search.textChanged.connect(self.filter_items)
        self.list.itemChanged.connect(self.update_count)
        self.update_count()

    def selected_ids(self):
        return tuple(self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                     if self.list.item(i).checkState() == Qt.Checked)

    def filter_items(self, text):
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(text.casefold() not in item.text().casefold())

    def check_visible(self, state):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if not item.isHidden():
                item.setCheckState(state)

    def update_count(self):
        count = len(self.selected_ids())
        self.count.setText(f'{count} playlists selected')
        self.use_button.setEnabled(count > 0)
