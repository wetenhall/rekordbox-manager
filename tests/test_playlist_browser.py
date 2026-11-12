from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rekordbox_manager.playlist_structure import ordered_playlist_nodes
from test_ui import window
from test_imports_ui import prepared_playlists


def test_sidebar_hierarchy_order_search_and_empty_folders(window):
    nodes = ordered_playlist_nodes([
        dict(ID=key, Name=name, ParentID=parent, Attribute=kind, Seq=seq)
        for key, name, parent, kind, seq in [
            ('z', 'Z folder', 'root', 1, 1), ('a', 'A folder', 'root', 1, 2),
            ('p', 'Late playlist', 'z', 0, 8), ('n', 'Nested / literal', 'z', 1, 1),
            ('q', 'Deep playlist', 'n', 0, 1), ('s', 'Smart', 'root', 4, 3)]])
    browser = window.playlist_browser
    browser.set_library(SimpleNamespace(playlist_nodes=nodes))
    assert [browser.tree.topLevelItem(i).text(0) for i in range(3)] == ['Z folder', 'A folder', 'Smart']
    assert browser.items['z'].child(0) is browser.items['n']
    assert browser.items['s'].isDisabled()
    assert browser.items['a'].childCount() == 0
    browser.set_selected(('p',))
    assert browser.items['z'].isExpanded()
    browser.search.setText('nested deep')
    assert browser.items['n'].isExpanded() and not browser.items['q'].isHidden()
    assert browser.items['p'].isHidden() and browser.items['a'].isHidden()
    browser.search.clear()
    assert browser.items['z'].isExpanded() and not browser.items['n'].isExpanded()
    assert not browser.items['a'].isHidden()


def test_sidebar_navigates_keeps_drafts_and_gives_arrow_keys_to_tree(window, tmp_path, monkeypatch):
    prepared_playlists(window, tmp_path, monkeypatch)
    window.pages.setCurrentWidget(window.workspace)
    window.show()
    browser = window.playlist_browser
    browser.tree.setCurrentItem(browser.items['p1'])
    assert window.selected_playlist_ids() == ('p1',)
    assert len(window.import_queue.pending()) == 6
    browser.tree.setFocus()
    QApplication.processEvents()
    assert all(not shortcut.isEnabled() for shortcut in window.track_shortcuts)
    QTest.keyClick(browser.tree, Qt.Key_Down)
    assert window.selected_playlist_ids() == ('p2',)
    window.set_playlist_selection(('p4',))
    assert browser.tree.currentItem() is browser.items['p4']
    window.set_busy(True)
    assert not browser.isEnabled()
    window.set_busy(False)
    assert browser.isEnabled()
    window.set_playlist_selection(('p1', 'p2'))
    assert not browser.tree.selectedItems()
