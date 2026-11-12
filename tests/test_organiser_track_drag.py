from PySide6.QtCore import Qt, QPoint, QPointF, QMimeData
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox

from rekordbox_manager.backups import digest
from rekordbox_manager.organiser_tracks import TRACK_MIME
from rekordbox_manager.usage import scan_usage
from test_ui import window
from test_organiser_ui import load_scan
from test_organiser_tree import display
from test_cue_writer import supported_install


def click_row(page, index, modifiers=Qt.NoModifier):
    row = page.list._buttons[index].layout().itemAt(0).widget()
    QTest.mouseClick(row, Qt.LeftButton, modifiers, QPoint(180, 14))


def test_rows_support_single_toggle_range_and_checkbox_selection(window):
    page = window.usage_tab
    load_scan(page, 8)
    ids = [t.id for t in page.matches]
    click_row(page, 0)
    assert page.selected_ids == {ids[0]}
    click_row(page, 2, Qt.ControlModifier)
    assert page.selected_ids == {ids[0], ids[2]}
    click_row(page, 4, Qt.ShiftModifier)
    assert page.selected_ids == set(ids[2:5])
    click_row(page, 0, Qt.MetaModifier)
    assert page.selected_ids == {ids[0], *ids[2:5]}
    check = page.list._buttons[3].findChild(QCheckBox)
    check.click()
    assert ids[3] not in page.selected_ids and not page.list._buttons[3].isChecked()
    click_row(page, 4)
    assert page.selected_ids == {ids[4]}
    assert sum(button.isChecked() for button in page.list._buttons) == 1
    assert sum(check.isChecked() for check in page.list.widget().findChildren(QCheckBox)) == 1


def test_drag_threshold_preserves_group_and_cancel_is_readonly(window, monkeypatch):
    page = window.usage_tab
    load_scan(page, 8)
    page.select_matches()
    selected = page.selected_ids.copy()
    calls = []
    class Drag:
        def __init__(self, source): assert source is page.list
        def setMimeData(self, mime): assert mime.hasFormat(TRACK_MIME)
        def setPixmap(self, pixmap): assert not pixmap.isNull()
        def setHotSpot(self, point): pass
        def exec(self, actions):
            assert actions == Qt.CopyAction
            calls.append(page.list.active_drag)
            return Qt.IgnoreAction
    monkeypatch.setattr('rekordbox_manager.organiser_tracks.QDrag', Drag)
    row = page.list._buttons[2].layout().itemAt(0).widget()
    QTest.mousePress(row, Qt.LeftButton, pos=QPoint(180, 14))
    assert page.selected_ids == selected
    QTest.mouseMove(row, QPoint(180 + QApplication.startDragDistance() + 10, 14))
    QTest.mouseRelease(row, Qt.LeftButton, pos=QPoint(210, 14))
    assert len(calls) == 1 and set(calls[0][2]) == selected
    assert page.list.active_drag is None and page.selected_ids == selected
    assert not page.queue.pending()


def prepare(page):
    page.scan = scan_usage(page.library)
    page.filter.setCurrentIndex(page.filter.findData('all'))
    page.apply_filters()
    page.select_matches()
    QApplication.processEvents()


def drop(page, destination, payload=None, external=False):
    tree = page.browser.tree
    source = None if external else page.list
    page.list.active_drag = payload or (page.library, page.scan, tuple(t.id for t in page.selected_tracks()))
    mime = QMimeData()
    mime.setData(TRACK_MIME, b'1')
    point = tree.visualItemRect(page.browser.items[destination]).center()
    class Enter(QDragEnterEvent):
        def source(self): return source
    class Move(QDragMoveEvent):
        def source(self): return source
    class Drop(QDropEvent):
        def source(self): return source
    enter = Enter(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    tree.dragEnterEvent(enter)
    move = Move(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    tree.dragMoveEvent(move)
    event = Drop(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    tree.dropEvent(event)
    page.list.active_drag = None
    return enter.isAccepted(), move.isAccepted(), event.isAccepted()


def test_drop_queues_ordered_tracks_and_keeps_source_memberships(window, tmp_path, monkeypatch):
    page = display(window, tmp_path, monkeypatch)
    prepare(page)
    before = digest(page.library.path)
    ordered = [t.id for t in page.selected_tracks()]
    assert len(ordered) >= 2
    assert drop(page, '110') == (True, True, True)
    assert list(page.queue.assignments['110']) == ordered
    assert digest(page.library.path) == before
    assert page.selected_ids == set(ordered)
    assert window.imports_tab.organiser.import_button.isEnabled()
    snapshot = page.queue.snapshot()
    assert drop(page, '110') == (True, True, True)
    assert page.queue.snapshot() == snapshot
    assert 'already' in page.result_note.text()
    # Existing memberships are skipped, not duplicated or removed.
    assert drop(page, '10') == (True, True, True)
    existing = {t.id for t in page.scan.tracks if '10' in t.playlist_ids}
    assert existing and not existing.intersection(page.queue.assignments.get('10', {}))
    assert digest(page.library.path) == before


def test_draft_playlist_and_filtered_tree_accept_tracks(window, tmp_path, monkeypatch):
    page = display(window, tmp_path, monkeypatch)
    prepare(page)
    node = page.queue.create(page.library, 'New destination', '100', False)
    page.refresh_browser()
    page.browser.search.setText('New destination')
    QApplication.processEvents()
    assert not page.browser.tree.structure_enabled and page.browser.tree.tracks_enabled
    assert drop(page, node.identity) == (True, True, True)
    assert page.queue.assignments[node.identity]


def test_invalid_drop_targets_sources_busy_and_stale_scans_rejected(window, tmp_path, monkeypatch):
    page = display(window, tmp_path, monkeypatch)
    prepare(page)
    assert drop(page, '100') == (True, False, False)
    assert drop(page, '110', external=True) == (False, False, False)
    old = page.scan
    page.scan = scan_usage(page.library)
    assert not drop(page, '110', (page.library, old, ('t',)))[2]
    assert not drop(page, '110', (page.library, page.scan, ('missing',)))[2]
    page.set_external_busy(True)
    assert drop(page, '110') == (False, False, False)
    page.set_external_busy(False)
    assert not page.queue.pending()
    with page.library.path.open('ab') as file:
        file.write(b'stale')
    assert not drop(page, '110')[2]
    assert not page.queue.pending()


def test_queued_tracks_leave_unassigned_views_and_return_on_discard(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    page = display(window, tmp_path, monkeypatch)
    prepare(page)
    page.filter.setCurrentIndex(page.filter.findData('outside'))
    unassigned = {t.id for t in page.matches}
    assert unassigned
    page.clear_selection()
    page.select_matches()
    before = digest(page.library.path)
    assert drop(page, '110')[2]
    assert not page.matches and not page.selected_ids
    assert '0 outside regular playlists' in page.summary.text()
    page.filter.setCurrentIndex(page.filter.findData('both'))
    assert not page.matches
    page.show_playlist('110')
    assert {t.id for t in page.matches} == unassigned
    page.show_collection()
    assert unassigned <= {t.id for t in page.matches}
    page.filter.setCurrentIndex(page.filter.findData('outside'))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    window.imports_tab.organiser.discard_changes()
    assert {t.id for t in page.matches} == unassigned
    assert not page.selected_ids and digest(page.library.path) == before


def test_queue_dialog_also_removes_unassigned_tracks(window, tmp_path, monkeypatch):
    from test_organiser_ui import connected
    lib, _, _ = connected(window, tmp_path, monkeypatch)
    page = window.usage_tab
    before = digest(lib.path)
    assert page.matches and page.selected_ids
    page.add_button.click()
    assert not page.matches and not page.selected_ids
    assert digest(lib.path) == before
