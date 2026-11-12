from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QAbstractItemView

from rekordbox_manager.organiser_dialogs import NewPlaylistDialog
from test_ui import window
from test_organiser_moves import hierarchy
from test_cue_writer import supported_install


def display(window, tmp_path, monkeypatch):
    lib, _, store = hierarchy(tmp_path)
    monkeypatch.setattr(window.player, 'setSource', lambda *args: None)
    window.backups = store
    window.set_library(lib)
    window.pages.setCurrentWidget(window.workspace)
    window.tabs.setCurrentWidget(window.usage_tab)
    window.resize(1280, 900)
    window.show()
    for item in window.usage_tab.browser.items.values():
        item.setExpanded(True)
    QApplication.processEvents()
    return window.usage_tab


def test_left_click_folder_offers_subfolder_and_playlist(window, tmp_path, monkeypatch):
    page = display(window, tmp_path, monkeypatch)
    item = page.browser.items['100']
    rect = page.browser.tree.visualItemRect(item)
    QTest.mouseClick(page.browser.tree.viewport(), Qt.LeftButton, pos=QPoint(rect.left() - 9, rect.center().y()))
    assert not item.isExpanded()
    assert not hasattr(page, 'folder_menu') or not page.folder_menu.isVisible()
    QTest.mouseClick(page.browser.tree.viewport(), Qt.LeftButton,
                     pos=page.browser.tree.visualItemRect(item).center())
    assert page.folder_menu.isVisible()
    actions = page.folder_menu.actions()
    assert [a.text() for a in actions] == ['New subfolder…', 'New playlist…']
    def create(dialog):
        assert dialog.parent_folder.currentData() == '100'
        dialog.name.setText('From folder click')
        return QDialog.Accepted
    monkeypatch.setattr(NewPlaylistDialog, 'exec', create)
    actions[0].trigger()
    page.folder_menu.close()
    node = page.queue.nodes[0]
    assert node.parent_id == '100' and node.attribute == 1


def perform_drop(page, identity, target, edge=None):
    tree = page.browser.tree
    source = page.browser.items[identity]
    tree.setCurrentItem(source)
    tree.dragged_id = identity
    mime = tree.model().mimeData([tree.indexFromItem(source)])
    rect = tree.visualItemRect(page.browser.items[target])
    position = rect.center() if edge is None else QPoint(rect.center().x(), rect.top() + 1 if edge == 'above' else rect.bottom() - 1)
    class Enter(QDragEnterEvent):
        def source(self): return tree
    class Move(QDragMoveEvent):
        def source(self): return tree
    class Drop(QDropEvent):
        def source(self): return tree
    enter = Enter(position, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    tree.dragEnterEvent(enter)
    move = Move(position, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    tree.dragMoveEvent(move)
    indicator = tree.dropIndicatorPosition()
    drop = Drop(QPointF(position), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    tree.dropEvent(drop)
    tree.dragged_id = None
    return move.isAccepted(), drop.isAccepted(), indicator


def test_native_drop_positions_queue_nesting_and_reordering(window, tmp_path, monkeypatch):
    page = display(window, tmp_path, monkeypatch)
    accepted, dropped, indicator = perform_drop(page, '110', '200')
    assert accepted and dropped and indicator == QAbstractItemView.OnItem
    assert next(n for n in page.queue.view().playlist_nodes if n.identity == '110').parent_id == '200'
    QApplication.processEvents()
    accepted, dropped, indicator = perform_drop(page, '10', '210', 'above')
    assert accepted and dropped and indicator == QAbstractItemView.AboveItem
    siblings = [n.identity for n in page.queue.view().playlist_nodes if n.parent_id == '200']
    assert siblings == ['10', '210', '110']
    assert window.imports_tab.organiser.import_button.isEnabled()


def test_drop_on_descendant_and_filtered_tree_rejected(window, tmp_path, monkeypatch):
    page = display(window, tmp_path, monkeypatch)
    accepted, dropped, _ = perform_drop(page, '100', '120')
    assert not accepted and not dropped and not page.queue.pending()
    page.browser.search.setText('Folder')
    assert not page.browser.tree.structure_enabled
    page.browser.search.clear()
    assert page.browser.tree.structure_enabled
    page.set_external_busy(True)
    assert not page.browser.tree.structure_enabled


def test_drag_source_does_not_delete_tree_rows(window, tmp_path, monkeypatch):
    page = display(window, tmp_path, monkeypatch)
    tree = page.browser.tree
    tree.setCurrentItem(page.browser.items['110'])
    seen = []
    class Drag:
        def __init__(self, source): assert source is tree
        def setMimeData(self, mime): assert mime.hasFormat('application/x-qabstractitemmodeldatalist')
        def setPixmap(self, image): assert not image.isNull()
        def setHotSpot(self, point): pass
        def exec(self, actions):
            seen.append(tree.dragged_id)
            return Qt.MoveAction
    monkeypatch.setattr('rekordbox_manager.organiser_tree.QDrag', Drag)
    tree.startDrag(Qt.MoveAction)
    assert seen == ['110'] and tree.dragged_id is None
    assert page.browser.items['110'].parent() is page.browser.items['100']
    assert not page.queue.pending()
