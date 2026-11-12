"""Small draft-creation dialog using the existing playlist hierarchy."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QDialogButtonBox, QCheckBox


class NewPlaylistDialog(QDialog):
    def __init__(self, parent, view, folder=False, parent_id=None, selection_count=0):
        super().__init__(parent)
        self.setWindowTitle('New folder' if folder else 'New playlist')
        self.setMinimumWidth(420)
        box = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(255)
        self.name.setAccessibleName('Folder name' if folder else 'Playlist name')
        form.addRow('Name', self.name)
        self.parent_folder = QComboBox()
        self.parent_folder.addItem('Top level', None)
        paths = {}
        for node in view.playlist_nodes:
            paths[node.identity] = paths.get(node.parent_id, ()) + (node.name,)
            if node.attribute == 1:
                self.parent_folder.addItem(' / '.join(paths[node.identity]), node.identity)
        index = self.parent_folder.findData(parent_id)
        self.parent_folder.setCurrentIndex(max(0, index))
        form.addRow('In folder', self.parent_folder)
        box.addLayout(form)
        self.include_tracks = QCheckBox(f'Add {selection_count:,} selected tracks')
        self.include_tracks.setChecked(bool(selection_count and not folder))
        self.include_tracks.setVisible(bool(selection_count and not folder))
        box.addWidget(self.include_tracks)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Create draft')
        buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.name.textChanged.connect(lambda text: buttons.button(QDialogButtonBox.Ok).setEnabled(bool(text.strip())))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
