"""Unfiled-track selection on top of the whole-library usage scanner."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QVBoxLayout, QPushButton, QWidget, QSplitter, QDialog, QMenu

from .playlist_writer import compatibility_problem
from .organiser_queue import OrganiserQueue
from .organiser_tree import OrganiserTree
from .organiser_tracks import OrganiserTrackList
from .organiser_dialogs import NewPlaylistDialog
from .playlist_browser import PlaylistBrowser
from .track_list import TrackList, track_columns, ElidedLabel
from .usage_ui import LibraryUsageTab, text_label


class OrganiserTab(LibraryUsageTab):
    add_requested = Signal(object)
    drafts_changed = Signal()

    def __init__(self, parent=None, queue=None):
        self.queue = queue or OrganiserQueue()
        self.playlist_id = None
        self.selected_ids = set()
        self.assigned_ids = set()
        self.external_busy = False
        self.write_problem = 'Connect a Rekordbox library to add tracks to playlists.'
        super().__init__(parent, title='Organiser')
        self.filter.setCurrentIndex(self.filter.findData('outside'))
        self.filter.setItemText(self.filter.findData('outside'), 'No regular playlists')
        self.search.setAccessibleName('Search organiser tracks')
        self.filter.setAccessibleName('Organiser filter')
        self.sort.setAccessibleName('Sort organiser tracks')
        self.build_workspace()
        actions = QHBoxLayout()
        actions.addWidget(self.scan_button)
        actions.addWidget(self.cancel_button)
        self.select_matching = QPushButton('Select all matching')
        self.select_matching.clicked.connect(self.select_matches)
        actions.addWidget(self.select_matching)
        self.clear_selection_button = QPushButton('Clear selection')
        self.clear_selection_button.clicked.connect(self.clear_selection)
        actions.addWidget(self.clear_selection_button)
        self.selection_count = text_label('')
        actions.addWidget(self.selection_count, 1)
        self.add_button = QPushButton('Queue in playlists…')
        self.add_button.setObjectName('primary')
        self.add_button.clicked.connect(self.request_add)
        actions.addWidget(self.add_button)
        self.layout().addLayout(actions)
        self.action_note = text_label('', 'muted')
        self.layout().addWidget(self.action_note)
        self.result_note = text_label('', 'muted')
        self.layout().addWidget(self.result_note)
        self.render_page()
        self.update_selection()

    def build_workspace(self):
        # Reuse scanner/filter controls, but use the same browser and rows as Manager.
        retained = {self.scan_button, self.cancel_button, self.filter, self.search,
                    self.sort, self.progress, self.message, self.summary,
                    self.previous, self.next, self.page_label}
        def clear_layout(layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.layout():
                    clear_layout(item.layout())
                elif item.widget():
                    widget = item.widget()
                    if widget in retained or widget is self.source:
                        widget.setParent(self)
                        widget.hide()
                    else:
                        widget.deleteLater()
        box = self.layout()
        clear_layout(box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.browser = PlaylistBrowser(tree_factory=OrganiserTree)
        self.browser.tree.itemClicked.disconnect(self.browser.toggle_folder)
        self.browser.tree.itemClicked.connect(self.folder_actions)
        self.browser.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.browser.tree.customContextMenuRequested.connect(self.folder_context_menu)
        self.browser.tree.move_requested.connect(self.move_draft)
        self.browser.search.textChanged.connect(lambda: self.update_selection() if hasattr(self, 'add_button') else None)
        self.collection_button = QPushButton('All library tracks')
        self.collection_button.setObjectName('prepareToggle')
        self.collection_button.setCheckable(True)
        self.collection_button.setChecked(True)
        self.collection_button.clicked.connect(self.show_collection)
        self.browser.layout().insertWidget(1, self.collection_button)
        self.browser.playlist_selected.connect(self.show_playlist)
        create = QHBoxLayout()
        self.new_folder = QPushButton('New folder')
        self.new_playlist = QPushButton('New playlist')
        self.new_folder.clicked.connect(lambda: self.create_draft(True))
        self.new_playlist.clicked.connect(lambda: self.create_draft(False))
        create.addWidget(self.new_folder)
        create.addWidget(self.new_playlist)
        self.browser.layout().addLayout(create)
        panel = QWidget()
        tracks = QVBoxLayout(panel)
        tracks.setContentsMargins(0, 0, 0, 0)
        tracks.setSpacing(0)
        filters = QHBoxLayout()
        filters.setContentsMargins(10, 8, 10, 8)
        filters.setSpacing(6)
        filters.addWidget(text_label('Show'))
        self.filter.setMaximumWidth(230)
        filters.addWidget(self.filter)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.sort)
        tracks.addLayout(filters)
        self.scope = ElidedLabel('All library tracks', 'muted')
        self.scope.setContentsMargins(10, 0, 10, 4)
        tracks.addWidget(self.scope)
        widths = (24, 30, 0, 0, 56, 64, 70, 145)
        stretches = (0, 0, 3, 2, 0, 0, 0, 0)
        header = QWidget()
        header.setObjectName('columnHeader')
        header.setFixedHeight(26)
        track_columns(header, ('', '#', 'TRACK TITLE', 'ARTIST', 'PLAYS', 'HISTORY', 'PLAYLISTS', 'STATUS'), widths, stretches)
        tracks.addWidget(header)
        self.list = OrganiserTrackList(self, widths, stretches, interactive_columns=(0,))
        self.browser.tree.track_source = self.list
        self.browser.tree.track_drop = self.drop_tracks
        self.list.setAccessibleName('Organiser tracks')
        tracks.addWidget(self.list, 1)
        self.empty = text_label('Scan results will appear here.', 'muted')
        tracks.addWidget(self.empty)
        pagination = QHBoxLayout()
        pagination.setContentsMargins(10, 6, 10, 6)
        pagination.setSpacing(8)
        pagination.addWidget(self.previous)
        pagination.addWidget(self.page_label, 1)
        pagination.addWidget(self.next)
        tracks.addLayout(pagination)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.browser)
        self.splitter.addWidget(panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([230, 1000])
        self.splitter.setChildrenCollapsible(False)
        box.addWidget(self.splitter, 1)
        box.addWidget(self.progress)
        box.addWidget(self.summary)
        self.summary.setObjectName('muted')
        box.addWidget(self.message)
        for widget in retained - {self.progress, self.cancel_button}:
            widget.show()

    def show_collection(self):
        self.playlist_id = None
        self.browser.set_selected([])
        self.collection_button.setChecked(True)
        self.scope.setText('All library tracks')
        self.apply_filters()

    def show_playlist(self, identity):
        self.playlist_id = identity
        self.collection_button.setChecked(False)
        self.scope.setText(' / '.join(self.browser.paths.get(identity, (identity,))))
        # Unfiled-only cannot contain playlist members; start with the complete playlist.
        self.filter.blockSignals(True)
        self.filter.setCurrentIndex(self.filter.findData('all'))
        self.filter.blockSignals(False)
        self.apply_filters()

    def apply_filters(self):
        self.assigned_ids = {identity for tracks in self.queue.assignments.values() for identity in tracks}
        if self.filter.currentData() in ('outside', 'both'):
            # A hidden, newly assigned track must not join the next drag accidentally.
            self.selected_ids.difference_update(self.assigned_ids)
        super().apply_filters()

    def outside_playlists(self, track):
        return super().outside_playlists(track) and track.id not in self.assigned_ids

    def track_in_scope(self, track):
        return (self.playlist_id is None or self.playlist_id in track.playlist_ids
                or track.id in self.queue.assignments.get(self.playlist_id, {}))

    def set_library(self, library):
        self.selected_ids.clear()
        self.playlist_id = None
        self.browser.set_library(self.queue.view(library))
        self.collection_button.setChecked(True)
        self.scope.setText('All library tracks')
        self.result_note.setText('')
        self.write_problem = 'Connect a Rekordbox library to add tracks to playlists.'
        if library is not None and not getattr(library, 'demo', False) and hasattr(library, 'connect'):
            try:
                with library.connect() as db:
                    self.write_problem = compatibility_problem(db)
            except Exception as exc:
                self.write_problem = str(exc)
        super().set_library(library)

    def start_scan(self):
        if self.scanning:
            return
        self.selected_ids.clear()
        super().start_scan()
        self.update_selection()

    def scan_finished(self):
        super().scan_finished()
        self.update_selection()

    def selection_control(self, track):
        check = QCheckBox()
        check.setAccessibleName(f'Select {track.title} by {track.artist}')
        check.setChecked(track.id in self.selected_ids)
        check.setEnabled(not self.scanning)
        check.toggled.connect(lambda checked, identity=track.id: self.set_selected(identity, checked))
        return check

    def set_selected(self, identity, checked):
        if checked:
            self.selected_ids.add(identity)
        else:
            self.selected_ids.discard(identity)
        self.list.anchor = identity
        self.list.sync_selection()
        self.update_selection()

    def select_matches(self):
        self.selected_ids.update(t.id for t in self.matches)
        self.render_page()

    def clear_selection(self):
        self.selected_ids.clear()
        self.render_page()

    def render_page(self):
        if not isinstance(self.list, TrackList):
            return super().render_page()
        start = self.page * self.PAGE_SIZE
        count = lambda value: '—' if value is None else str(value)
        queued = {identity for tracks in self.queue.assignments.values() for identity in tracks}
        rows = [[self.selection_control(t), str(start + index + 1), t.title, t.artist,
                 count(t.plays), count(t.history_entries), count(t.playlists), 'Queued for import' if t.id in queued else t.play_status]
                for index, t in enumerate(self.matches[start:start + self.PAGE_SIZE])]
        self.list.set_cells(rows)
        total = len(self.matches)
        self.empty.setVisible(not total)
        self.empty.setText('No tracks match these filters.' if self.scan else 'Scan library to see tracks here.')
        self.page_label.setText(f'{start + 1 if total else 0}–{min(start + self.PAGE_SIZE, total)} of {total:,} matching tracks')
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(start + self.PAGE_SIZE < total)
        if hasattr(self, 'add_button'):
            self.update_selection()

    def set_external_busy(self, busy):
        self.external_busy = busy
        self.update_selection()

    def update_selection(self):
        visible = {t.id for t in self.matches[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]}
        hidden = len(self.selected_ids - visible)
        self.selection_count.setText(f'{len(self.selected_ids):,} selected' + (f' · {hidden:,} off this page' if hidden else ''))
        self.select_matching.setEnabled(bool(self.scan) and not self.scanning and bool(self.matches))
        self.clear_selection_button.setEnabled(bool(self.selected_ids))
        problem = ('Finish the Manager scan before adding tracks.' if self.external_busy else self.write_problem)
        can_create = bool(self.library and not self.scanning and not problem)
        self.new_folder.setEnabled(can_create)
        self.new_playlist.setEnabled(can_create)
        self.browser.tree.enable_tracks(can_create and bool(self.scan))
        self.browser.tree.enable_structure(can_create and not self.browser.search.text().strip())
        if not problem and not self.queue.view(self.library).playlists:
            problem = 'Create a playlist to queue your selected tracks.'
        self.add_button.setEnabled(bool(self.selected_ids and self.scan) and not self.scanning and not problem)
        self.action_note.setText(problem or 'Drag selected tracks into a playlist, then apply from Imports. Existing memberships are kept.')

    def drop_tracks(self, destination, payload):
        if not self.browser.tree.tracks_enabled or not payload:
            return False
        library, scan, identities = payload
        if library is not self.library or scan is not self.scan or not identities:
            return False
        tracks = {track.id: track for track in scan.tracks}
        if any(identity not in tracks for identity in identities):
            return False
        try:
            before = len(self.queue.assignments.get(destination, {}))
            self.queue.add(library, [tracks[key] for key in identities], [destination], scan.fingerprint)
            added = len(self.queue.assignments.get(destination, {})) - before
        except Exception as exc:
            self.result_note.setText(str(exc))
            return False
        name = ' / '.join(self.browser.paths.get(destination, (destination,)))
        self.result_note.setText(f'{added} track(s) queued for {name}. Apply from Imports.' if added
                                 else f'These tracks are already in {name} or queued for it.')
        # Refresh queue-aware filters while keeping the current page when possible.
        page = self.page
        self.apply_filters()
        if page:
            self.page = min(page, max(0, (len(self.matches) - 1) // self.PAGE_SIZE))
            self.render_page()
        self.drafts_changed.emit()
        return True

    def request_add(self):
        if not self.add_button.isEnabled() or not self.scan:
            return
        # Preserve visible sort order, followed by selected tracks hidden by filters/pages.
        ordered = dict.fromkeys([t.id for t in self.matches] + [t.id for t in self.scan.tracks])
        self.add_requested.emit(tuple(identity for identity in ordered if identity in self.selected_ids))

    def selected_tracks(self):
        if not self.scan:
            return []
        tracks = {t.id: t for t in self.scan.tracks}
        ordered = dict.fromkeys([t.id for t in self.matches] + list(tracks))
        return [tracks[key] for key in ordered if key in self.selected_ids]

    def refresh_browser(self):
        selected = self.playlist_id
        expanded = {key for key, item in self.browser.items.items() if item.isExpanded()}
        self.browser.set_library(self.queue.view(self.library))
        for key in expanded:
            if key in self.browser.items:
                self.browser.items[key].setExpanded(True)
        pending = {n.identity for n in self.queue.nodes}
        for key in pending:
            item = self.browser.items.get(key)
            if item:
                item.setText(0, item.text(0) + ' · draft')
        if selected in self.browser.items:
            self.browser.set_selected([selected])
            self.scope.setText(" / ".join(self.browser.paths[selected]))
        else:
            self.show_collection()
        self.apply_filters()

    def create_draft(self, folder):
        if not (self.new_folder if folder else self.new_playlist).isEnabled():
            return
        view = self.queue.view(self.library)
        item = self.browser.tree.currentItem()
        identity = next((key for key, value in self.browser.items.items() if value is item), None)
        node = next((n for n in view.playlist_nodes if n.identity == identity), None)
        parent = node.identity if node and node.attribute == 1 else node.parent_id if node else None
        dialog = NewPlaylistDialog(self, view, folder, parent, len(self.selected_ids))
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            if dialog.include_tracks.isChecked() and not folder:
                self.queue.bind(self.library, self.scan.fingerprint)
            node = self.queue.create(self.library, dialog.name.text(), dialog.parent_folder.currentData(), folder)
            if dialog.include_tracks.isChecked() and not folder:
                self.queue.add(self.library, self.selected_tracks(), [node.identity], self.scan.fingerprint)
                self.selected_ids.clear()
            self.refresh_browser()
            self.browser.tree.setCurrentItem(self.browser.items[node.identity])
            self.result_note.setText('Draft queued. Open Imports → Playlist changes to apply it to Rekordbox.')
            self.drafts_changed.emit()
        except Exception as exc:
            self.result_note.setText(str(exc))

    def folder_context_menu(self, position):
        item = self.browser.tree.itemAt(position)
        if item:
            self.browser.tree.setCurrentItem(item)
            self.folder_actions(item, 0)

    def folder_actions(self, item, column):
        if item.data(0, Qt.UserRole + 1) != 1:
            return
        if hasattr(self, 'folder_menu'):
            self.folder_menu.close()
            self.folder_menu.deleteLater()
        menu = self.folder_menu = QMenu(self)
        menu.addAction('New subfolder…', lambda: self.create_draft(True)).setEnabled(self.new_folder.isEnabled())
        menu.addAction('New playlist…', lambda: self.create_draft(False)).setEnabled(self.new_playlist.isEnabled())
        point = self.browser.tree.visualItemRect(item).bottomLeft()
        menu.popup(self.browser.tree.viewport().mapToGlobal(point))

    def move_draft(self, identity, parent, before):
        if not self.browser.tree.structure_enabled:
            return
        try:
            self.queue.move(self.library, identity, parent, before)
            self.refresh_browser()
            self.browser.set_selected([identity])
            self.result_note.setText('Folder/order changes queued. Apply them from Imports → Playlist changes.')
            self.drafts_changed.emit()
        except Exception as exc:
            self.result_note.setText(str(exc))
