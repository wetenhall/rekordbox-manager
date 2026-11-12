from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox, QDialog

from rekordbox_manager.dialogs import ImportDialog
from rekordbox_manager.models import Track, Grid, Options, Proposal
from test_ui import window


def prepared_playlists(window, tmp_path, monkeypatch):
    monkeypatch.setattr(window.player, 'setSource', lambda source: None)
    grid = Grid([i * .5 for i in range(1024)], [i % 4 + 1 for i in range(1024)])
    tracks = []
    for i in range(6):
        path = tmp_path / f'{i}.wav'
        path.write_bytes(b'unchanged source audio')
        tracks.append(Track(str(i), f'Track {i}', 'Artist', 'House', path, 512, 120, grid))
    groups = {f'p{i+1}': tracks[i:i+2] for i in range(5)}
    calls = []
    library = SimpleNamespace(demo=True, writable=True, write_reason='',
                              playlists={key:key for key in groups}, tracks=lambda key: groups[key],
                              apply=lambda proposals, backups: calls.append(proposals) or tmp_path / 'backup')
    window.set_library(library)
    for key in groups:
        window.set_playlist_selection((key,))
        window.invalidate()
        window.capture_analysis_scope()
        window.analysis_done([Proposal(t, Options(True, True), t.grid, [], 128, 384) for t in window.tracks])
    return library, calls


def test_imports_collects_five_playlists_and_imports_shared_tracks_once(window, tmp_path, monkeypatch):
    library, calls = prepared_playlists(window, tmp_path, monkeypatch)
    window.tabs.setCurrentWidget(window.imports_tab)
    assert len(window.import_queue.ready()) == 6
    assert '5 source playlists' in window.imports_tab.summary.text()
    assert window.imports_tab.import_button.isEnabled()
    summaries = []
    def confirm(dialog):
        summaries.append(dialog)
        assert dialog.playlist_table.rowCount() == 5
        return QDialog.Accepted
    monkeypatch.setattr(ImportDialog, 'exec', confirm)
    window.imports_tab.import_button.click()
    assert len(calls) == len(summaries) == 1
    assert [p.track.id for p in calls[0]] == list('012345')
    assert all(p.can_apply for p in calls[0])
    assert not window.import_queue.pending()
    window.import_queued_tracks()
    assert len(calls) == 1


@pytest.mark.parametrize('result', ['cancel', 'failure'])
def test_cancelled_or_failed_queue_import_keeps_every_preparation(window, tmp_path, monkeypatch, result):
    library, calls = prepared_playlists(window, tmp_path, monkeypatch)
    originals = [e.proposal for e in window.import_queue.ready()]
    monkeypatch.setattr(ImportDialog, 'exec', lambda self: QDialog.Rejected if result == 'cancel' else QDialog.Accepted)
    errors = []
    monkeypatch.setattr(window, 'fail', errors.append)
    if result == 'failure':
        def fail(*args):
            raise RuntimeError('Import failed; nothing installed')
        library.apply = fail
    window.import_queued_tracks()
    assert not calls
    assert [e.proposal for e in window.import_queue.ready()] == originals
    assert all(not p.applied and not p.reviewed for p in originals)
    assert bool(errors) == (result == 'failure')


def test_dirty_track_leaves_ready_queue_and_can_be_reviewed_from_other_playlist(window, tmp_path, monkeypatch):
    library, calls = prepared_playlists(window, tmp_path, monkeypatch)
    current = window.selected()
    window.first.setValue(129)
    assert current.cues_dirty and len(window.import_queue.ready()) == 5
    window.set_playlist_selection(('p1',))
    window.review_queued_track(current.track.id)
    assert window.tabs.currentWidget() is window.manager_tab
    assert window.selected() is current and window.first.value() == 129
    window.tabs.setCurrentWidget(window.imports_tab)
    assert '1 need review' in window.imports_tab.summary.text()
    monkeypatch.setattr(ImportDialog, 'exec', lambda self: QDialog.Accepted)
    window.import_queued_tracks()
    assert len(calls[0]) == 5 and all(p.track.id != current.track.id for p in calls[0])
    assert window.import_queue.pending()[0].proposal is current


def test_mutation_during_confirmation_is_rejected(window, tmp_path, monkeypatch):
    library, calls = prepared_playlists(window, tmp_path, monkeypatch)
    errors = []
    monkeypatch.setattr(window, 'fail', errors.append)
    def confirm(dialog):
        window.import_queue.entries['0'].proposal.grid = Grid([.1,.6], [1,2])
        return QDialog.Accepted
    monkeypatch.setattr(ImportDialog, 'exec', confirm)
    window.import_queued_tracks()
    assert not calls and 'changed' in str(errors[0])


def test_reconnect_and_close_warn_before_discarding_queue(window, tmp_path, monkeypatch):
    library, calls = prepared_playlists(window, tmp_path, monkeypatch)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.No)
    assert window.set_library(library) is False and len(window.import_queue.ready()) == 6
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    assert window.set_library(library) is True and not window.import_queue.pending()


def test_background_analysis_blocks_queue_import_and_refreshes_button(window, tmp_path, monkeypatch):
    library, calls = prepared_playlists(window, tmp_path, monkeypatch)
    window.tabs.setCurrentWidget(window.imports_tab)
    window.set_busy(True)
    assert not window.imports_tab.import_button.isEnabled()
    window.import_queued_tracks()
    assert not calls
    window.set_busy(False)
    assert window.imports_tab.import_button.isEnabled()


def test_review_retained_track_when_sibling_preparation_was_invalidated(window, tmp_path, monkeypatch):
    library, calls = prepared_playlists(window, tmp_path, monkeypatch)
    original = window.import_queue.entries['0'].proposal
    window.import_queue.forget(['1'])
    window.review_queued_track('0')
    assert window.selected() is original and window.queued_review_only
    assert window.import_playlist_breakdown() == [('p1', 1, 1, 0, 0)]
    window.set_playlist_selection(('p1',))
    assert not window.queued_review_only and len(window.tracks) == 2
    assert window.selected_playlist_ids() == ('p1',) and {t.id for t in window.tracks} == {'0', '1'}


def test_compact_queue_reviews_correct_track_after_paging_and_filtering(window, tmp_path, monkeypatch):
    prepared_playlists(window, tmp_path, monkeypatch)
    page = window.imports_tab
    page.PAGE_SIZE = 2
    window.tabs.setCurrentWidget(page)
    page.next.click()
    assert [e.proposal.track.id for e in page.visible_entries] == ['2', '3']
    page.table.selectRow(1)
    page.review_button.click()
    assert window.tabs.currentWidget() is window.manager_tab
    assert window.selected().track.id == '3'
    window.tabs.setCurrentWidget(page)
    page.search.setText('Track 0')
    assert page.selected_identity() == '0'
    assert page.import_button.text() == 'Import all 6 ready tracks'
    page.busy = True
    page.refresh()
    assert not page.review_button.isEnabled() and not page.import_button.isEnabled()
    page.busy = False
    page.search.setText('no matching track')
    assert page.table.currentRow() == -1 and not page.review_button.isEnabled()
    assert not page.empty.isHidden()


@pytest.mark.parametrize('size', [(1050, 720), (1280, 870)])
def test_imports_matches_compact_manager_rows(window, tmp_path, monkeypatch, size):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication
    prepared_playlists(window, tmp_path, monkeypatch)
    page = window.imports_tab
    window.import_queue.entries['0'].proposal.review_note = 'Check both drops before import.'
    window.pages.setCurrentWidget(window.workspace)
    window.tabs.setCurrentWidget(page)
    page.filter.setCurrentIndex(2)
    window.resize(*size)
    window.show()
    QApplication.processEvents()
    # The Windows CI desktop clamps a window's initial show to its small screen.
    # Apply the requested test geometry after that initial native resize.
    window.resize(*size)
    QApplication.processEvents()
    assert window.width() == size[0]
    assert len(page.table._buttons) == 6
    assert page.table._buttons[0].property('needsReview')
    assert 'Check both drops' in page.table._buttons[0].toolTip()
    header = page.header.layout()
    for row in page.table._buttons:
        assert row.height() == 28
        layout = row.layout().itemAt(0).widget().layout()
        for i in range(layout.count()):
            cell = layout.itemAt(i).widget()
            heading = header.itemAt(i).widget()
            assert abs(cell.mapTo(page, QPoint(0, 0)).x() - heading.mapTo(page, QPoint(0, 0)).x()) <= 3
            assert cell.width() > 0
    assert page.import_button.mapTo(window, QPoint(0, page.import_button.height())).y() <= window.height()
