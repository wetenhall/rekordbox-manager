"""Bounded dialogs for batch selection and import review."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem, QLineEdit, QCheckBox, QStyle,
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
    def __init__(self, parent, playlists, selected, paths=None, *, organise=False):
        super().__init__(parent)
        self.setWindowTitle('Choose playlists')
        self.resize(700, 560)
        self.playlists = playlists
        self.items = {}
        self.folders = {}
        self._filtered = False
        self._expanded = set()
        box = QVBoxLayout(self)
        box.addWidget(text_label('Tick the destination playlists. Every selected track will be added to each playlist.' if organise else
                                'Browse folders or search, then tick the playlists to prepare together.'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search playlist or folder names…')
        self.search.setAccessibleName('Find a playlist or folder')
        self.search.setClearButtonEnabled(True)
        box.addWidget(self.search)
        actions = QHBoxLayout()
        self.selected_only = QCheckBox('Selected only')
        actions.addWidget(self.selected_only)
        actions.addStretch()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAccessibleName('Playlist folders and playlists')
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(22)
        self.tree.setStyleSheet('QTreeWidget { background: #1d1f22; border: 1px solid #43474c; }'
                                'QTreeWidget::item { padding: 5px; }'
                                'QTreeWidget::item:selected { background: #35414d; }')
        for title, callback in (('Expand all', self.tree.expandAll), ('Collapse all', self.tree.collapseAll)):
            control = QPushButton(title)
            control.setAutoDefault(False)
            control.clicked.connect(callback)
            actions.addWidget(control)
        box.addLayout(actions)
        folder_icon = self.style().standardIcon(QStyle.SP_DirIcon)
        playlist_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        for identity, name in playlists.items():
            # Use database identities, not a split display path: names can contain
            # slashes and distinct folders can have the same name.
            parts = (paths or {}).get(identity) or ((identity, name),)
            parent_item = self.tree.invisibleRootItem()
            key = ()
            for folder_id, folder_name in parts[:-1]:
                key += (folder_id,)
                if key not in self.folders:
                    folder = QTreeWidgetItem(parent_item, [folder_name])
                    folder.setIcon(0, folder_icon)
                    folder.setToolTip(0, 'Expand to browse playlists')
                    self.folders[key] = folder
                parent_item = self.folders[key]
            item = QTreeWidgetItem(parent_item, [parts[-1][1]])
            item.setIcon(0, playlist_icon)
            item.setData(0, Qt.UserRole, identity)
            item.setToolTip(0, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if identity in selected else Qt.Unchecked)
            self.items[identity] = item
        box.addWidget(self.tree, 1)
        self.empty = text_label('No matching playlists. Try another name or clear the filters.')
        box.addWidget(self.empty)
        selection_actions = QHBoxLayout()
        for title, state in (('Select visible', Qt.Checked), ('Clear visible', Qt.Unchecked)):
            control = QPushButton(title)
            control.setAutoDefault(False)
            control.clicked.connect(lambda checked=False, value=state: self.check_visible(value))
            control.setToolTip('Applies to all playlists matching the filters, including collapsed folders.')
            selection_actions.addWidget(control)
        selection_actions.addStretch()
        self.clear_all = QPushButton('Clear selection')
        self.clear_all.setAutoDefault(False)
        self.clear_all.clicked.connect(self.clear_selection)
        selection_actions.addWidget(self.clear_all)
        box.addLayout(selection_actions)
        self.count = text_label('')
        box.addWidget(self.count)
        box.addWidget(text_label('Tracks will be appended in the reviewed order. Audio files stay in their current locations.' if organise else
                                'Shared tracks are included once. Prepared tracks stay in Imports when you switch playlists; preparing a shared track again replaces its earlier draft.'))
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
        self.selected_only.toggled.connect(self.filter_items)
        self.tree.itemChanged.connect(self.selection_changed)
        for identity in selected:
            item = self.items.get(identity)
            if item is not None:
                ancestor = item.parent()
                while ancestor is not None:
                    ancestor.setExpanded(True)
                    ancestor = ancestor.parent()
        self.filter_items()
        self.search.setFocus()

    def selected_ids(self):
        return tuple(identity for identity, item in self.items.items()
                     if item.checkState(0) == Qt.Checked)

    def filter_items(self, *_):
        words = self.search.text().casefold().split()
        filtered = bool(words) or self.selected_only.isChecked()
        if filtered and not self._filtered:
            self._expanded = {key for key, item in self.folders.items() if item.isExpanded()}
        for identity, item in self.items.items():
            matches = all(word in self.playlists[identity].casefold() for word in words)
            matches = matches and (not self.selected_only.isChecked() or item.checkState(0) == Qt.Checked)
            item.setHidden(not matches)
        # Children precede parents, so a matching leaf reveals its entire path.
        for key, folder in sorted(self.folders.items(), key=lambda pair: len(pair[0]), reverse=True):
            visible = any(not folder.child(i).isHidden() for i in range(folder.childCount()))
            folder.setHidden(not visible)
            if filtered and visible:
                folder.setExpanded(True)
            elif self._filtered and not filtered:
                folder.setExpanded(key in self._expanded)
        self._filtered = filtered
        self.update_count()

    def check_visible(self, state):
        # Snapshot before changing checks: Selected only updates visibility too.
        items = [item for item in self.items.values() if not item.isHidden()]
        self.tree.blockSignals(True)
        for item in items:
            item.setCheckState(0, state)
        self.tree.blockSignals(False)
        self.filter_items()

    def clear_selection(self):
        self.tree.blockSignals(True)
        for item in self.items.values():
            item.setCheckState(0, Qt.Unchecked)
        self.tree.blockSignals(False)
        self.filter_items()

    def selection_changed(self, *_):
        self.filter_items()

    def update_count(self):
        count = len(self.selected_ids())
        shown = sum(not item.isHidden() for item in self.items.values())
        hidden_selected = sum(item.isHidden() and item.checkState(0) == Qt.Checked for item in self.items.values())
        self.count.setText(f'{shown} of {len(self.items)} playlists shown · {count} selected'
                           + (f' ({hidden_selected} hidden by filters)' if hidden_selected else ''))
        self.empty.setVisible(shown == 0)
        self.use_button.setEnabled(count > 0)
        self.clear_all.setEnabled(count > 0)
