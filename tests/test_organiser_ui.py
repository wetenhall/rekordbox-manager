from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QMessageBox

from rekordbox_manager.backups import digest
from rekordbox_manager.dialogs import PlaylistDialog
from rekordbox_manager.usage import scan_usage
from test_ui import window, usage_results, finish_usage_worker
from test_cue_writer import fixture_library, supported_install


def load_scan(page, count=250):
    page.library = SimpleNamespace(playlists={'p': 'Folder / Rediscover'})
    page.write_problem = ''
    page.scan = usage_results(count)
    page.apply_filters()


def test_selection_across_pages_and_filters_is_explicit(window):
    page = window.usage_tab
    load_scan(page)
    assert page.filter.currentData() == 'outside'
    page.select_matching.click()
    assert len(page.selected_ids) == 249 and '149 off this page' in page.selection_count.text()
    page.next.click()
    assert len(page.selected_ids) == 249
    page.search.setText('Quiet')
    page.apply_filters()
    assert [t.id for t in page.matches] == ['zero']
    assert '248 off this page' in page.selection_count.text()
    emitted = []
    page.add_requested.connect(emitted.append)
    page.add_button.click()
    assert set(emitted[0]) == page.selected_ids and emitted[0][0] == 'zero'
    page.clear_selection_button.click()
    assert not page.selected_ids and not page.add_button.isEnabled()


def test_all_scanned_tracks_are_selectable(window):
    page = window.usage_tab
    load_scan(page, 3)
    page.filter.setCurrentIndex(page.filter.findData('all'))
    checks = page.list.widget().findChildren(QCheckBox)
    assert len(checks) == 3 and sum(c.isEnabled() for c in checks) == 3
    page.select_matching.click()
    assert page.selected_ids == {'zero', 'history', 'unknown'}
    page.set_external_busy(True)
    assert not page.add_button.isEnabled() and 'Finish' in page.action_note.text()
    page.set_external_busy(False)
    assert page.add_button.isEnabled()
    page.write_problem = 'Unsupported installation'
    page.update_selection()
    assert not page.add_button.isEnabled() and 'Unsupported' in page.action_note.text()


def test_rescan_clears_selection_and_readonly_keeps_discovery(window, monkeypatch):
    page = window.usage_tab
    load_scan(page, 3)
    page.library.demo = False
    page.select_matching.click()
    monkeypatch.setattr('rekordbox_manager.usage_ui.scan_usage', lambda *args: usage_results(3))
    page.start_scan()
    assert not page.selected_ids and not page.add_button.isEnabled()
    finish_usage_worker(page)
    assert len(page.matches) == 2
    page.set_library(SimpleNamespace(demo=False, path='/other', connect=lambda: None))
    assert not page.selected_ids and page.scan is None


def connected(window, tmp_path, monkeypatch):
    lib, proposal, backups = fixture_library(tmp_path)
    window.library = lib
    window.backups = backups
    window.import_queue.reset(lib)
    window.import_queue.capture(lib, [proposal], {'p': ('Test', frozenset(['t']))})
    window.usage_tab.set_library(lib)
    window.usage_tab.scan = scan_usage(lib)
    window.usage_tab.apply_filters()
    window.usage_tab.select_matching.click()
    monkeypatch.setattr(window, 'load_tracks', lambda: None)
    def choose(dialog):
        assert 'destination' in dialog.layout().itemAt(0).widget().text()
        dialog.items['p'].setCheckState(0, Qt.Checked)
        return QDialog.Accepted
    monkeypatch.setattr(PlaylistDialog, 'exec', choose)
    return lib, proposal, backups


def test_confirmed_addition_refreshes_unfiled_and_preserves_queue(window, tmp_path, monkeypatch):
    lib, proposal, backups = connected(window, tmp_path, monkeypatch)
    details = []
    def confirm(box):
        details.append(box.detailedText())
        assert '1 track assignments' in box.text() and 'Test' in box.detailedText()
        return QMessageBox.Yes
    monkeypatch.setattr(QMessageBox, 'exec', confirm)
    before = digest(lib.path)
    window.usage_tab.add_button.click()
    assert digest(lib.path) == before and not backups.list()
    assert window.organiser_queue.pending()
    window.import_organiser_changes()
    finish_usage_worker(window.usage_tab)
    assert details and 'unrelated' in details[0]
    assert not window.usage_tab.matches and not window.usage_tab.selected_ids
    assert 'imported' in window.usage_tab.result_note.text()
    assert len(backups.list()) == 1
    assert window.import_queue.entries['t'].proposal is proposal
    assert window.import_queue.fingerprint == lib.fingerprint
    assert window.import_queue.pending()


def test_cancelling_confirmation_preserves_database_selection_and_queue(window, tmp_path, monkeypatch):
    lib, proposal, backups = connected(window, tmp_path, monkeypatch)
    before = digest(lib.path)
    monkeypatch.setattr(QMessageBox, 'exec', lambda box: QMessageBox.Cancel)
    window.usage_tab.add_button.click()
    queued = window.organiser_queue.snapshot()
    window.import_organiser_changes()
    assert digest(lib.path) == before and not backups.list()
    assert window.organiser_queue.snapshot() == queued
    assert window.import_queue.entries['t'].proposal is proposal


def test_addition_failure_retains_selection_for_review(window, tmp_path, monkeypatch):
    lib, _, backups = connected(window, tmp_path, monkeypatch)
    monkeypatch.setattr(QMessageBox, 'exec', lambda box: QMessageBox.Yes)
    failures = []
    monkeypatch.setattr(window, 'fail', failures.append)
    def fail(*args): raise RuntimeError('Stale scan')
    monkeypatch.setattr('rekordbox_manager.ui.apply_plan', fail)
    before = digest(lib.path)
    window.usage_tab.add_button.click()
    queued = window.organiser_queue.snapshot()
    window.import_organiser_changes()
    assert failures and 'Stale scan' in window.imports_tab.organiser.message.text()
    assert window.organiser_queue.snapshot() == queued
    assert digest(lib.path) == before and not backups.list()


def test_shared_browser_scopes_tracks_and_preserves_unfiled_selection(window, tmp_path):
    from test_usage import usage_library
    from rekordbox_manager.track_list import TrackList
    from rekordbox_manager.playlist_browser import PlaylistBrowser
    page = window.usage_tab
    library = usage_library(tmp_path)
    page.set_library(library)
    page.scan = scan_usage(library)
    page.apply_filters()
    assert isinstance(page.browser, PlaylistBrowser) and isinstance(page.list, TrackList)
    page.select_matching.click()
    selected = page.selected_ids.copy()
    page.browser.tree.setCurrentItem(page.browser.items['p'])
    assert page.playlist_id == 'p' and page.filter.currentData() == 'all'
    assert [t.id for t in page.matches] == ['t']
    assert all(c.isEnabled() for c in page.list.widget().findChildren(QCheckBox))
    assert page.selected_ids == selected
    page.collection_button.click()
    assert page.playlist_id is None and len(page.matches) == len(page.scan.tracks)
    page.filter.setCurrentIndex(page.filter.findData('outside'))
    page.clear_selection_button.click()
    check = page.list.widget().findChildren(QCheckBox)[0]
    check.click()
    assert len(page.selected_ids) == 1
    check.click()
    assert not page.selected_ids
    page.set_library(None)
    assert not page.browser.items and not page.matches and page.playlist_id is None


def test_create_nested_folder_playlist_with_tracks_is_draft_only(window, tmp_path, monkeypatch):
    from rekordbox_manager.organiser_dialogs import NewPlaylistDialog
    lib, proposal, backups = connected(window, tmp_path, monkeypatch)
    page = window.usage_tab
    before = digest(lib.path)
    def folder(dialog):
        dialog.name.setText('Rediscover')
        return QDialog.Accepted
    monkeypatch.setattr(NewPlaylistDialog, 'exec', folder)
    page.new_folder.click()
    root = window.organiser_queue.nodes[0]
    assert root.attribute == 1 and page.browser.tree.currentItem() is page.browser.items[root.identity]
    def playlist(dialog):
        assert dialog.parent_folder.currentData() == root.identity
        assert dialog.include_tracks.isChecked()
        dialog.name.setText('Fresh set')
        return QDialog.Accepted
    monkeypatch.setattr(NewPlaylistDialog, 'exec', playlist)
    page.new_playlist.click()
    created = window.organiser_queue.nodes[1]
    assert created.parent_id == root.identity
    assert list(window.organiser_queue.assignments[created.identity]) == ['unrelated']
    assert page.playlist_id == created.identity and [t.id for t in page.matches] == ['unrelated']
    assert 'draft' in page.browser.items[created.identity].text(0)
    assert digest(lib.path) == before and not backups.list()
    assert window.imports_tab.organiser.import_button.isEnabled()
    assert len(window.imports_tab.organiser.table._buttons) == 3
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.No)
    assert not window.confirm_discard_preparation('Close')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    window.imports_tab.organiser.discard.click()
    assert not window.organiser_queue.pending() and created.identity not in page.browser.items
    assert digest(lib.path) == before


def test_cue_import_preserves_and_rebases_playlist_drafts(window, tmp_path, monkeypatch):
    from rekordbox_manager.dialogs import ImportDialog
    lib, proposal, backups = connected(window, tmp_path, monkeypatch)
    q = window.organiser_queue
    node = q.create(lib, 'Later playlist')
    q.add(lib, window.usage_tab.selected_tracks(), [node.identity], window.usage_tab.scan.fingerprint)
    before = q.fingerprint
    monkeypatch.setattr(ImportDialog, 'exec', lambda dialog: QDialog.Accepted)
    window.import_queued_tracks()
    assert proposal.applied and q.pending() and q.fingerprint != before
    assert q.fingerprint == lib.fingerprint
    q.bind(lib)
    assert node.identity in q.view(lib).playlists
    assert node.identity not in lib.playlists


def test_import_new_playlist_refreshes_both_browsers(window, tmp_path, monkeypatch):
    lib, proposal, backups = fixture_library(tmp_path)
    monkeypatch.setattr(window.player, 'setSource', lambda *args: None)
    window.backups = backups
    window.set_library(lib)
    page = window.usage_tab
    page.scan = scan_usage(lib)
    page.apply_filters()
    q = window.organiser_queue
    node = q.create(lib, 'Imported playlist')
    q.add(lib, page.scan.tracks, [node.identity], page.scan.fingerprint)
    monkeypatch.setattr(QMessageBox, 'exec', lambda dialog: QMessageBox.Yes)
    window.import_organiser_changes()
    finish_usage_worker(page)
    assert not q.pending()
    assert node.identity in window.playlist_browser.items and node.identity in page.browser.items
    assert 'draft' not in page.browser.items[node.identity].text(0)
    window.set_playlist_selection((node.identity,))
    assert {t.id for t in window.tracks} == {'t', 'unrelated'}


def test_many_draft_assignments_paginate_without_changing_queue(window):
    page = window.imports_tab.organiser
    q = window.organiser_queue
    q.library = SimpleNamespace(playlists={'p': 'Target'})
    q.assignments['p'] = {str(i): (str(i), f'Track {i}', 'Artist') for i in range(250)}
    page.refresh()
    assert len(page.table._buttons) == 100 and '250 changes' in page.page_label.text()
    page.next.click()
    page.next.click()
    assert len(page.table._buttons) == 50 and '201–250' in page.page_label.text()
    assert len(q.assignments['p']) == 250
