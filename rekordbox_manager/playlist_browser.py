"""Persistent playlist navigation in the library's saved folder order."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QStyle, QAbstractItemView

from .playlist_structure import PlaylistNode


class PlaylistBrowser(QWidget):
    playlist_selected = Signal(str)

    def __init__(self, tree_factory=QTreeWidget):
        super().__init__()
        self.setMinimumWidth(180)
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 10, 8, 8)
        box.setSpacing(8)
        heading = QLabel('PLAYLISTS')
        heading.setObjectName('eyebrow')
        heading.setMinimumHeight(18)
        box.addWidget(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find playlist or folder…')
        self.search.setAccessibleName('Find a playlist or folder in the sidebar')
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(32)
        box.addWidget(self.search)
        self.tree = tree_factory()
        self.tree.setHeaderHidden(True)
        self.tree.setSortingEnabled(False)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(18)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.tree.setAccessibleName('Rekordbox playlist folders in library order')
        self.tree.setStyleSheet('QTreeWidget { background: #1a1c1e; border: 1px solid #3a3d41; }'
                                'QTreeWidget::item { height: 27px; padding: 0 3px; }'
                                'QTreeWidget::item:selected { background: #30373e; color: #e7e8ea; }'
                                'QTreeWidget::item:disabled { color: #777b81; }')
        box.addWidget(self.tree, 1)
        self.empty = QLabel('No matching playlists or folders.')
        self.empty.setObjectName('muted')
        self.empty.setWordWrap(True)
        self.empty.hide()
        box.addWidget(self.empty)
        self.items = {}
        self.paths = {}
        self.nodes = ()
        self._expanded = set()
        self._filtered = False
        self.search.textChanged.connect(self.filter_items)
        self.tree.currentItemChanged.connect(self.choose_current)
        self.tree.itemClicked.connect(self.toggle_folder)

    def set_library(self, library):
        self.tree.blockSignals(True)
        self.tree.clear()
        self.items = {}
        self.paths = {}
        nodes = getattr(library, 'playlist_nodes', None)
        if nodes is None:
            # Demo/adapter fallback uses identity paths, never splits names on '/'.
            found = {}
            for identity, name in library.playlists.items():
                parts = getattr(library, 'playlist_paths', {}).get(identity) or ((identity, name),)
                parent = None
                for index, (key, title) in enumerate(parts):
                    found.setdefault(key, PlaylistNode(key, title, parent, 0 if index == len(parts) - 1 else 1))
                    parent = key
            nodes = tuple(found.values())
        self.nodes = nodes
        folder_icon = self.style().standardIcon(QStyle.SP_DirIcon)
        playlist_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        for node in nodes:
            parent = self.items.get(node.parent_id, self.tree.invisibleRootItem())
            item = QTreeWidgetItem(parent, [node.name])
            item.setIcon(0, folder_icon if node.attribute == 1 else playlist_icon)
            item.setData(0, Qt.UserRole, node.identity if node.attribute == 0 else None)
            item.setData(0, Qt.UserRole + 1, node.attribute)
            item.setData(0, Qt.UserRole + 2, node.identity)
            if node.attribute != 1:
                item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)
            self.paths[node.identity] = self.paths.get(node.parent_id, ()) + (node.name,)
            tooltip = ' / '.join(self.paths[node.identity])
            if node.attribute not in (0, 1):
                item.setDisabled(True)
                tooltip += '\nSmart or unsupported playlist: scanning is not available.'
            item.setToolTip(0, tooltip)
            self.items[node.identity] = item
        self.tree.blockSignals(False)
        self._filtered = False
        self._expanded = set()
        self.search.clear()
        self.filter_items()

    def choose_current(self, item, previous):
        identity = item.data(0, Qt.UserRole) if item else None
        if identity is not None and self.isEnabled():
            self.playlist_selected.emit(identity)

    def toggle_folder(self, item, column):
        if item.data(0, Qt.UserRole + 1) == 1:
            item.setExpanded(not item.isExpanded())

    def set_selected(self, identities):
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        item = self.items.get(identities[0]) if len(identities) == 1 else None
        self.tree.setCurrentItem(item)
        if item:
            if item.isHidden():
                self.search.clear()
            parent = item.parent()
            while parent:
                parent.setExpanded(True)
                parent = parent.parent()
            self.tree.scrollToItem(item)
        self.tree.blockSignals(False)

    def filter_items(self):
        words = self.search.text().casefold().split()
        if words and not self._filtered:
            self._expanded = {key for key, item in self.items.items() if item.isExpanded()}
        for node in reversed(self.nodes):
            item = self.items[node.identity]
            matches = all(word in ' / '.join(self.paths[node.identity]).casefold() for word in words)
            visible = matches or any(not item.child(i).isHidden() for i in range(item.childCount()))
            item.setHidden(not visible)
            if node.attribute == 1:
                if words and visible:
                    item.setExpanded(True)
                elif self._filtered and not words:
                    item.setExpanded(node.identity in self._expanded)
        self._filtered = bool(words)
        self.empty.setVisible(not any(not item.isHidden() for item in self.items.values()))
