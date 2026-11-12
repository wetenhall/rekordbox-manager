import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QMessageBox, QDialog
from rekordbox_manager.dialogs import ImportDialog, PlaylistDialog
from rekordbox_manager.ui import MainWindow
from rekordbox_manager.models import Track, Grid, Cue, Proposal, Options


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv('REKORDBOX_MANAGER_DATA_DIR', str(tmp_path))
    monkeypatch.setattr('rekordbox_manager.ui.ensure_rekordbox_closed', lambda: None)
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: QMessageBox.Ok)
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    yield w
    w.import_queue.reset()
    w.organiser_queue.reset()
    w.close()
    app.processEvents()


def test_confirmation_gate_loads_library_before_workspace(window, tmp_path, monkeypatch):
    from types import SimpleNamespace
    path=tmp_path/'master.db'
    track=Track('t','Track','Artist','House',tmp_path/'track.wav',120,120,Grid([0,.5],[1,2]))
    library=SimpleNamespace(demo=False,writable=True,write_reason='',playlists={'p':'My playlist'},
                            tracks=lambda key:[track])
    calls=[]
    def connect(selected):
        assert window.pages.currentWidget() is window.gate
        calls.append(selected)
        return library
    monkeypatch.setattr('rekordbox_manager.ui.RekordboxLibrary',connect)
    monkeypatch.setattr(window,'choose_database_path',lambda:str(path))
    assert not window.continue_button.isEnabled()
    window.confirm.setChecked(True)
    assert not window.continue_button.isEnabled()
    window.enter()
    assert not calls
    window.choose_startup_database()
    assert window.continue_button.isEnabled()
    window.confirm.setChecked(False)
    assert not window.continue_button.isEnabled()
    window.enter()
    assert not calls
    window.confirm.setChecked(True)
    window.enter()
    assert calls==[path]
    assert window.pages.currentWidget() is window.workspace
    assert window.library is library and window.tracks==[track]
    assert window.playlist_browser.tree.currentItem().text(0)=='My playlist'
    assert window.analyse_button.isEnabled()


@pytest.mark.parametrize('failure',['running','database','playlist'])
def test_failed_startup_connection_stays_on_first_screen(window,tmp_path,monkeypatch,failure):
    from types import SimpleNamespace
    def fail(*args):raise ValueError('Test connection failure')
    library=SimpleNamespace(demo=False,writable=True,write_reason='',playlists={'p':'Playlist'},tracks=fail)
    monkeypatch.setattr('rekordbox_manager.ui.RekordboxLibrary',fail if failure=='database' else lambda path:library)
    if failure=='running':monkeypatch.setattr('rekordbox_manager.ui.ensure_rekordbox_closed',fail)
    errors=[]
    monkeypatch.setattr(window,'fail',errors.append)
    window.startup_database=tmp_path/'master.db'
    window.confirm.setChecked(True)
    window.enter()
    assert errors and window.pages.currentWidget() is window.gate
    assert window.continue_button.isEnabled() and window.startup_browse.isEnabled()
    assert window.confirm.isEnabled()


def test_cancel_startup_picker_keeps_previous_selection(window,tmp_path,monkeypatch):
    window.startup_database=tmp_path/'master.db'
    window.confirm.setChecked(True)
    monkeypatch.setattr(window,'choose_database_path',lambda:'')
    window.choose_startup_database()
    assert window.startup_database==tmp_path/'master.db' and window.continue_button.isEnabled()


def test_options_can_be_independent(window):
    assert window.set_cues.isChecked() and not window.fix_grid.isChecked()
    window.set_cues.setChecked(False)
    window.fix_grid.setChecked(True)
    assert window.fix_grid.isChecked() and not window.set_cues.isChecked()


def test_changed_options_clear_approvals(window):
    window.proposals = ['old']
    window.fix_grid.setChecked(True)
    assert window.proposals == []


def test_track_controls_preserve_single_selection(window):
    window.table.set_rows([
        ['First\nArtist', 'House', '128', '0 / 10', 'Ready'],
        ['Second\nArtist', 'Techno', '134', '10 / 10', 'Review needed'],
    ])
    window.table._buttons[0].click()
    window.table._buttons[1].click()
    assert window.table.currentRow() == 1
    assert [item.isChecked() for item in window.table._buttons] == [False, True]
    assert 'Second' in window.table._buttons[1].accessibleName()


def test_live_write_button_remains_locked(window, tmp_path):
    from types import SimpleNamespace
    track = Track('t','Track','Artist','House',tmp_path/'a.wav',512,120,
                  Grid([i*.5 for i in range(1024)],[i%4+1 for i in range(1024)]))
    p = Proposal(track,Options(False,True),track.grid,[],128,384,reviewed=True)
    window.library = SimpleNamespace(writable=False, write_reason='Locked',demo=False)
    window.tracks = [track]
    window.proposals = [p]
    window.populate_table()
    window.table.selectRow(0)
    window.update_details()


def review_playlist(window, tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(window.player, 'setSource', lambda source: None)
    grid = Grid([i * .5 for i in range(1024)], [i % 4 + 1 for i in range(1024)])
    window.library = SimpleNamespace(writable=False, write_reason='Locked', demo=False)
    window.tracks = [Track(str(i), f'Track {i}', 'Artist', 'House', tmp_path / f'{i}.wav',
                           512, 120, grid) for i in range(3)]
    window.proposals = [Proposal(t, Options(True, True), grid, [], 128 + i * 32, 384)
                        for i, t in enumerate(window.tracks)]
    window.populate_table()
    window.table.selectRow(0)
    return window.proposals


def test_preparation_action_names_selected_operations(window,tmp_path,monkeypatch):
    review_playlist(window,tmp_path,monkeypatch)
    window.fix_grid.setChecked(True)
    window.set_cues.setChecked(True)
    window.invalidate()
    assert window.analyse_button.text()=='Scan && prepare playlist'
    assert 'set memory cues and fix beat grids' in window.analyse_button.toolTip()
    assert 'Reuse saved Rekordbox' in window.analyse_button.toolTip()
    window.fix_grid.setChecked(False)
    assert window.analyse_button.text()=='Scan && prepare playlist'
    assert 'to set memory cues,' in window.analyse_button.toolTip()
    window.fix_grid.setChecked(True)
    window.set_cues.setChecked(False)
    assert window.analyse_button.text()=='Scan && prepare playlist'
    assert 'to fix beat grids,' in window.analyse_button.toolTip()
    window.fix_grid.setChecked(False)
    assert not window.analyse_button.isEnabled()


def test_playback_seeking_uses_saved_timeline_and_alternate_source_does_not_double_offset(window,tmp_path,monkeypatch):
    from PySide6.QtCore import QUrl
    p=review_playlist(window,tmp_path,monkeypatch)[0]
    p.track.audio_offset=.053
    positions=[]
    monkeypatch.setattr(window.player,'setPosition',positions.append)
    monkeypatch.setattr(window.player,'source',lambda:QUrl.fromLocalFile(str(p.track.path)))
    window.seek(10)
    assert positions[-1]==9947
    window.play_position(9947)
    assert window.wave.position==10
    monkeypatch.setattr(window.player,'source',lambda:QUrl.fromLocalFile(str(tmp_path/'alternate.wav')))
    window.seek(10)
    assert positions[-1]==10000
    window.play_position(10000)
    assert window.wave.position==10


def prepare_apply(window, tmp_path, monkeypatch):
    proposals = review_playlist(window, tmp_path, monkeypatch)
    window.playlist_ids = ('test',)
    window.loaded_playlist_tracks = {'test': ('Test playlist', frozenset(t.id for t in window.tracks))}
    window.capture_analysis_scope()
    calls, messages = [], []
    window.library.writable = True
    window.library.demo = True
    monkeypatch.setattr(window.library, 'apply', lambda items, store: calls.append(items) or tmp_path / 'backup', raising=False)
    monkeypatch.setattr(window, 'load_tracks', lambda: None)
    def confirm(dialog):
        messages.append(dialog.summary.text() + "\n" + dialog.details.toPlainText())
        return QDialog.Accepted
    monkeypatch.setattr(ImportDialog, "exec", confirm)
    window.update_details()
    return proposals, calls, messages


def test_playlist_apply_needs_no_per_track_confirmation(window, tmp_path, monkeypatch):
    proposals, calls, messages = prepare_apply(window, tmp_path, monkeypatch)
    assert not hasattr(window, 'grid_confirm') and not hasattr(window, 'approve_all')
    window.first.setValue(96)
    window.rebuild_cues()
    window.confirm_review()
    window.apply_changes()
    assert len(messages) == 1 and len(calls) == 1
    assert all(p.can_apply for p in calls[0])
    assert [p.first_drop for p in calls[0]] == [96, 160, 192]
    assert proposals[0].reviewed and all(not p.reviewed for p in proposals[1:])


def test_cancel_playlist_apply_changes_nothing(window, tmp_path, monkeypatch):
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    monkeypatch.setattr(ImportDialog, 'exec', lambda *args: QDialog.Rejected)
    window.apply_changes()
    assert not calls
    assert all(not p.reviewed and not p.grid_approved for p in proposals)


def test_playlist_apply_skips_errors_and_unrebuilt_edits(window, tmp_path, monkeypatch):
    proposals, calls, messages = prepare_apply(window, tmp_path, monkeypatch)
    proposals[1].error = 'Audio unavailable'
    window.first.setValue(96)
    window.apply_changes()
    assert [p.track.id for p in calls[0]] == ['2']
    assert '2 need review' in messages[0]
    assert 'Rebuild cues' in messages[0] and 'Audio unavailable' in messages[0]
    assert proposals[0].cues_dirty and window.first.value() == 96


def test_grid_only_playlist_needs_no_drop_anchors(window, tmp_path, monkeypatch):
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    for p in proposals:
        p.options = Options(True, False)
        p.first_drop = p.second_drop = None
    window.apply_changes()
    assert all(p.can_apply and p.first_drop is None and not p.cues for p in calls[0])
    window.invalidate()


def test_cues_only_playlist_does_not_approve_grids(window, tmp_path, monkeypatch):
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    for p in proposals:
        p.options = Options(False, True)
    window.apply_changes()
    assert all(p.can_apply and not p.grid_approved for p in calls[0])


def test_live_library_apply_never_prompts_or_writes(window, tmp_path, monkeypatch):
    proposals = review_playlist(window, tmp_path, monkeypatch)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: pytest.fail('Live apply must remain blocked'))
    window.apply_changes()


def test_all_invalid_or_busy_playlist_cannot_apply(window, tmp_path, monkeypatch):
    proposals, calls, messages = prepare_apply(window, tmp_path, monkeypatch)
    window.set_busy(True)
    window.update_details()
    window.apply_changes()
    assert not calls and not messages
    window.set_busy(False)
    for p in proposals:
        p.error = 'Failed'
    window.update_details()
    window.apply_changes()
    assert not calls and not messages


def test_moved_markers_survive_switching_tracks_and_require_rebuild(window, tmp_path, monkeypatch):
    proposals = review_playlist(window, tmp_path, monkeypatch)
    p = proposals[0]
    p.reviewed = p.grid_approved = True
    window.move_drop_marker(1, 96)
    assert p.first_drop == 96 and p.cues_dirty and not p.can_apply
    window.table.selectRow(1)
    window.table.selectRow(0)
    assert window.first.value() == 96
    window.rebuild_cues()
    assert not p.cues_dirty and not p.reviewed
    assert next(c.time for c in p.cues if c.label == 'DROP 1') == 96


def test_focus_drop_zooms_and_updates_navigation(window, tmp_path, monkeypatch):
    proposals = review_playlist(window, tmp_path, monkeypatch)
    window.focus_drop(2)
    assert window.wave.zoom == 16 and window.zoom.currentData() == 16
    start, end = window.wave.visible_range()
    assert (start + end) / 2 == proposals[0].second_drop
    assert window.wave_scroll.isEnabled()
    window.wave_scroll.setValue(0)
    assert window.wave.visible_range()[0] == 0


@pytest.mark.parametrize('size', [(1050, 720), (1280, 870)])
def test_deck_above_playlist_and_footer_stays_visible(window, tmp_path, monkeypatch, size):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QFrame, QPushButton
    review_playlist(window, tmp_path, monkeypatch)
    window.pages.setCurrentWidget(window.workspace)
    window.resize(*size)
    window.show()
    QApplication.processEvents()
    assert window.size().width() == size[0]
    assert window.size().height() == size[1]
    assert window.navigation.mapTo(window, QPoint(0, window.navigation.height())).y() < window.review_controls.mapTo(window, QPoint(0, 0)).y()
    assert window.navigation.mapTo(window, QPoint(window.navigation.width(), 0)).x() == window.width() - 10
    assert window.table.mapTo(window, QPoint(0, window.table.height())).y() < window.status.mapTo(window, QPoint(0, 0)).y()
    assert window.wave.mapTo(window, QPoint(0, window.wave.height())).y() < window.review_controls.mapTo(window, QPoint(0, 0)).y()
    assert window.library_splitter.widget(1).layout().itemAt(2).widget().objectName() == 'columnHeader'
    assert window.library_splitter.widget(1).layout().itemAt(3).widget() is window.table
    assert window.wave.mapTo(window, QPoint(0, window.wave.height())).y() < window.table.mapTo(window, QPoint(0, 0)).y()
    assert window.table.height() >= 4 * 28
    assert window.analyse_button.mapTo(window, QPoint(0, 0)).y() > window.table.mapTo(window, QPoint(0, window.table.height())).y()
    assert window.analyse_button.mapTo(window, QPoint(0, window.analyse_button.height())).y() <= window.height()
    assert not hasattr(window, "apply_button") and not hasattr(window, "details")
    assert not hasattr(window, "playlists")
    for control in (window.fix_grid, window.set_cues, window.replace_cues, window.ignore_cued):
        assert isinstance(control, QPushButton) and control.isCheckable()
        assert control.mapTo(window, control.rect().center()).y() == window.analyse_button.mapTo(window, window.analyse_button.rect().center()).y()
        assert control.geometry().right() < window.analyse_button.geometry().left()
        assert control.text().endswith('On' if control.isChecked() else 'Off')
    assert not window.findChildren(QFrame, 'rail')
    for row in window.table._buttons:
        cells = [row.layout().itemAt(i).widget() for i in range(row.layout().count())]
        for left, right in zip(cells, cells[1:]):
            assert left.geometry().right() < right.geometry().left()
        assert cells[-1].geometry().right() <= row.width()
    window.deck_splitter.setSizes([330, 600])
    QApplication.processEvents()
    assert window.table.height() >= 4 * 28
    window.show_backups()
    assert window.tabs.currentWidget() is window.backups_tab
    next(b for b in window.findChildren(QPushButton) if b.text() == '← Back to playlist').click()
    assert window.tabs.currentIndex() == 0


def test_live_import_confirmation_includes_grid_files(window, tmp_path, monkeypatch):
    proposals, calls, messages = prepare_apply(window, tmp_path, monkeypatch)
    window.library.demo = False
    for p in proposals:
        p.options = Options(False, True)
    window.update_details()
    window.apply_changes()
    assert len(calls) == 1 and 'Includes the database' in messages[0]
    calls.clear(); messages.clear()
    for p in proposals:
        p.applied = False
    proposals[0].options = Options(True, True)
    errors = []
    monkeypatch.setattr(window, 'fail', errors.append)
    window.apply_changes()
    assert len(calls) == 1 and not errors
    assert calls[0][0].grid_approved
    assert 'changed analysis files' in messages[0]


def test_successful_batch_preserves_skipped_marker_edits(window, tmp_path, monkeypatch):
    proposals, calls, messages = prepare_apply(window, tmp_path, monkeypatch)
    window.first.setValue(96)
    window.apply_changes()
    assert len(calls[0]) == 2
    assert proposals[0].cues_dirty and proposals[0].first_drop == 96
    assert not proposals[0].applied
    assert all(p.applied and not p.ready_to_apply for p in proposals[1:])
    assert window.first.value() == 96
    window.rebuild_cues()
    assert not proposals[0].ready_to_apply
    window.confirm_review()
    assert proposals[0].ready_to_apply


def test_space_toggles_transport_from_playlist_and_ignores_repeat(window, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt, QEvent
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest
    from PySide6.QtMultimedia import QMediaPlayer
    review_playlist(window, tmp_path, monkeypatch)
    calls = []
    state = [QMediaPlayer.StoppedState]
    def play():
        calls.append('play')
        state[0] = QMediaPlayer.PlayingState
    def pause():
        calls.append('pause')
        state[0] = QMediaPlayer.PausedState
    monkeypatch.setattr(window.player, 'playbackState', lambda: state[0])
    monkeypatch.setattr(window.player, 'play', play)
    monkeypatch.setattr(window.player, 'pause', pause)
    window.pages.setCurrentWidget(window.workspace)
    window.show()
    window.activateWindow()
    row = window.table._buttons[0]
    row.setFocus()
    QApplication.processEvents()
    QTest.keyClick(row, Qt.Key_Space)
    assert calls == ['play']
    QApplication.sendEvent(row, QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, ' ', True))
    assert calls == ['play']
    QTest.keyClick(row, Qt.Key_Space)
    assert calls == ['play', 'pause']
    assert window.table.currentRow() == 0


def test_space_preserves_editor_and_dialog_keys(window, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLineEdit, QDialog, QVBoxLayout
    review_playlist(window, tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(window.player, 'play', lambda: calls.append('play'))
    window.pages.setCurrentWidget(window.workspace)
    window.show()
    window.activateWindow()
    window.first.setFocus()
    QApplication.processEvents()
    QTest.keyClick(window.first, Qt.Key_Space)
    assert calls == []
    assert not window.play_shortcut.isEnabled()
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    field = QLineEdit()
    layout.addWidget(field)
    dialog.setModal(True)
    dialog.show()
    dialog.activateWindow()
    field.setFocus()
    QApplication.processEvents()
    QTest.keyClicks(field, 'two words')
    assert field.text() == 'two words'
    assert calls == []
    dialog.close()


def test_grid_anchor_invalidates_old_cues(window, tmp_path, monkeypatch):
    proposals = review_playlist(window, tmp_path, monkeypatch)
    proposal = proposals[0]
    monkeypatch.setattr(window.player, 'position', lambda: 128520)
    window.align_grid_to_playhead()
    assert proposal.grid.positions[257] == 1
    assert proposal.first_drop == 128.52
    assert proposal.cues_dirty and not proposal.ready_to_apply
    window.second.setValue(384.52)
    window.rebuild_cues()
    assert not proposal.cues_dirty
    assert any(c.time == 128.52 and c.label == 'DROP 1' for c in proposal.cues)


def test_rebuild_preserves_manual_anchor_and_snap_change_does_not_move_it(window,tmp_path,monkeypatch):
    p=review_playlist(window,tmp_path,monkeypatch)[0]
    p.options=Options(False,True)
    window.update_details()
    window.first.setValue(128.125)
    window.second.setValue(385.25)
    assert p.cues_dirty
    for mode in ('off','bar','beat'):
        window.marker_snap.setCurrentIndex(window.marker_snap.findData(mode))
        assert window.wave.snap_mode==mode
        assert (p.first_drop,p.second_drop)==(128.125,385.25)
    window.rebuild_cues()
    assert not p.cues_dirty
    assert (p.first_drop,p.second_drop)==(128.125,385.25)
    assert any(c.label=='DROP 2' and c.time==385.25 for c in p.cues)
    assert p.grid is p.track.grid


@pytest.mark.parametrize('outcome', ['success','partial','failure','cancel'])
def test_import_completion_only_after_success(window,tmp_path,monkeypatch,outcome):
    proposals,calls,_=prepare_apply(window,tmp_path,monkeypatch)
    window.library.demo=False
    notices=[]
    def completed(*args):
        assert calls, 'Completion must follow the write'
        assert all(p.applied for p in proposals if p.error=='')
        notices.append(args)
        return QMessageBox.Ok
    monkeypatch.setattr(QMessageBox,'information',completed)
    if outcome=='partial':proposals[1].error='Audio unavailable'
    if outcome=='cancel':monkeypatch.setattr(ImportDialog,'exec',lambda *args:QDialog.Rejected)
    if outcome=='failure':
        def fail(*args):raise RuntimeError('Test import failure')
        monkeypatch.setattr(window.library,'apply',fail)
        monkeypatch.setattr(window,'fail',lambda exc:None)
    window.apply_changes()
    if outcome in ('failure','cancel'):
        assert not notices
    else:
        assert len(notices)==1
        _,title,message,buttons=notices[0]
        assert title=='Import complete' and buttons==QMessageBox.Ok
        assert f"{2 if outcome=='partial' else 3} track(s)" in message
        assert ('1 track(s) were skipped' in message)==(outcome=='partial')


def test_arrows_change_preview_from_deck_and_wrap_preserving_edits(window,tmp_path,monkeypatch):
    from pathlib import Path
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    proposals=review_playlist(window,tmp_path,monkeypatch)
    sources=[]
    monkeypatch.setattr(window.player,'setSource',lambda url:sources.append(url.toLocalFile()))
    window.pages.setCurrentWidget(window.workspace)
    window.show();window.activateWindow()
    window.move_drop_marker(2,386)
    window.play.setFocus();QApplication.processEvents()
    assert window.rebuild_button.property('needsRebuild')
    QTest.keyClick(window.play,Qt.Key_Down)
    assert window.table.currentRow()==1 and window.wave.proposal is proposals[1]
    assert Path(sources[-1])==proposals[1].track.path
    assert window.first.value()==160 and window.second.value()==384
    assert not window.rebuild_button.property('needsRebuild')
    QTest.keyClick(window.play,Qt.Key_Up)
    assert window.wave.proposal is proposals[0] and window.second.value()==386
    assert window.rebuild_button.property('needsRebuild')
    assert 'Rebuild needed' in window.review_title.toolTip()
    QTest.keyClick(window.play,Qt.Key_Up)
    assert window.table.currentRow()==2
    QTest.keyClick(window.play,Qt.Key_Down)
    assert window.table.currentRow()==0
    window.rebuild_button.click()
    assert not window.rebuild_button.property('needsRebuild')
    assert window.rebuild_button.text()=='Rebuild grid + cues'


def test_arrows_leave_editors_menus_dialogs_and_busy_analysis_alone(window,tmp_path,monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog,QVBoxLayout,QPushButton
    review_playlist(window,tmp_path,monkeypatch)
    window.pages.setCurrentWidget(window.workspace)
    window.show();window.activateWindow()
    for control in (window.first,window.second,window.marker_snap,window.zoom):
        control.setFocus();QApplication.processEvents()
        assert all(not shortcut.isEnabled() for shortcut in window.track_shortcuts)
        QTest.keyClick(control,Qt.Key_Down)
        assert window.table.currentRow()==0
    dialog=QDialog(window);layout=QVBoxLayout(dialog);control=QPushButton('OK');layout.addWidget(control)
    dialog.setModal(True);dialog.show();dialog.activateWindow();control.setFocus();QApplication.processEvents()
    QTest.keyClick(control,Qt.Key_Down)
    assert window.table.currentRow()==0
    dialog.close();window.activateWindow();window.play.setFocus();QApplication.processEvents()
    window.set_busy(True)
    QTest.keyClick(window.play,Qt.Key_Down)
    assert window.table.currentRow()==0
    window.set_busy(False)
    window.invalidate()
    assert not window.rebuild_button.isEnabled() and not window.rebuild_button.property('needsRebuild')


def test_snap_to_kick_preserves_exact_attack_and_requires_rebuild(window,tmp_path,monkeypatch):
    from rekordbox_manager.attacks import Attack
    p=review_playlist(window,tmp_path,monkeypatch)[0]
    p.attacks=[Attack(128.08,1),Attack(384.12,1)]
    original=p.grid.times.copy()
    window.update_details()
    window.marker_snap.setCurrentIndex(window.marker_snap.findData('bar'))
    window.snap_drop_to_kick(1)
    assert p.first_drop==128.08 and p.cues_dirty
    assert window.rebuild_button.property('needsRebuild')
    window.snap_drop_to_kick(2)
    assert p.second_drop==384.12 and p.grid.times==original
    window.rebuild_cues()
    assert not p.cues_dirty and not p.grid_issue and p.review_note and not p.ready_to_apply
    assert window.confirm_review_button.isEnabled()
    window.second.setValue(384.08)
    window.rebuild_cues()
    assert not p.cues_dirty and not p.grid_issue
    assert next(c.time for c in p.cues if c.label=='DROP 2')==384.08
    assert not any('grid was not moved' in note for note in p.warnings)


def test_unchanged_kick_selects_drop_two_and_explicit_alignment_preserves_conflict(window,tmp_path,monkeypatch):
    from rekordbox_manager.attacks import Attack
    from rekordbox_manager.analysis import rebuild_proposal
    from rekordbox_manager.grid_writer import tempo
    p=review_playlist(window,tmp_path,monkeypatch)[0]
    original=Grid([round(.3+i*60/175,3) for i in range(1000)], [i%4+1 for i in range(1000)])
    p.track.grid=original
    p.track.bpm=175
    p.first_drop,p.second_drop=43.798,153.601
    p.attacks=[Attack(153.601,1)]
    rebuild_proposal(p)
    assert p.grid_anchor==1 and p.review_note and not p.grid_issue
    window.select_track()
    previous=p.grid
    window.snap_drop_to_kick(2)
    assert p.second_drop==153.601 and p.second_drop_edited and p.grid_anchor==2
    assert p.cues_dirty and p.grid==previous
    assert 'Align to Drop 2' in window.status.text()
    window.grid_anchor_buttons[1].click()
    assert p.grid.times[p.grid.nearest_downbeat(153.601)]==153.601
    assert (p.first_drop,p.second_drop)==(43.798,153.601)
    assert tempo(p.grid)==tempo(original) and p.track.grid==original
    assert not p.grid_issue and 'bar start' in p.review_note and not p.ready_to_apply
    assert window.confirm_review_button.isEnabled()
    assert 'Rebuild needed' not in window.review_title.toolTip()
    window.grid_anchor_buttons[0].click()
    assert p.grid.times[p.grid.nearest_downbeat(43.798)]==43.798
    assert (p.first_drop,p.second_drop)==(43.798,153.601)
    assert not p.ready_to_apply


def test_explicit_drop_alignment_rebuilds_cues_and_respects_edit_guards(window,tmp_path,monkeypatch):
    p=review_playlist(window,tmp_path,monkeypatch)[0]
    p.first_drop,p.second_drop=128.08,384.08
    window.select_track()
    window.grid_anchor_buttons[1].click()
    assert p.grid_anchor==2 and p.review_note and not p.ready_to_apply
    window.confirm_review()
    assert p.ready_to_apply
    assert p.grid.times[p.grid.nearest_downbeat(384.08)]==384.08
    assert next(c.time for c in p.cues if c.label=='DROP 2')==384.08
    previous=p.grid
    for options,applied,busy in ((Options(False,True),False,False),
                                 (Options(True,False),False,False),
                                 (Options(True,True),True,False),
                                 (Options(True,True),False,True)):
        p.options,p.applied,window.analysis_busy=options,applied,busy
        window.update_details()
        assert all(not control.isEnabled() for control in window.grid_anchor_buttons)
        window.align_grid_to_drop(1)
        assert p.grid_anchor==2 and p.grid==previous


def test_snap_to_kick_leaves_ambiguous_marker_unchanged(window,tmp_path,monkeypatch):
    from rekordbox_manager.attacks import Attack
    p=review_playlist(window,tmp_path,monkeypatch)[0]
    p.attacks=[Attack(383.9,1),Attack(384.1,1)]
    window.snap_drop_to_kick(2)
    assert p.second_drop==384 and not p.cues_dirty
    assert 'Two nearby attacks' in window.status.text()
    assert p.drop_notes
    p.attacks=[]
    window.snap_drop_to_kick(2)
    assert p.second_drop==384 and 'No distinct' in window.status.text()
    p.options=Options(True,False)
    window.update_details()
    assert all(not button.isEnabled() for button in window.kick_buttons)


def test_successful_connection_remembered_after_restart_without_confirmation(window,tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    path=tmp_path/'music'/'master.db';path.parent.mkdir();path.touch()
    backup=tmp_path/'custom-backups'
    window.settings['backups']=str(backup)
    calls=[]
    library=SimpleNamespace(demo=False,writable=False,write_reason='Read only',playlists={},tracks=lambda key:[])
    def connect(selected):
        calls.append(selected)
        return library
    monkeypatch.setattr('rekordbox_manager.ui.RekordboxLibrary',connect)
    window.startup_database=path
    window.confirm.setChecked(True)
    window.enter()
    saved=json.loads(window.config_file.read_text())
    assert saved['last_database']==str(path) and saved['backups']==str(backup)
    reopened=MainWindow()
    try:
        assert reopened.startup_database==path
        assert reopened.startup_database_label.text()==str(path)
        assert reopened.startup_database_state == 'saved'
        assert reopened.startup_database_heading.text() == 'Saved library'
        assert reopened.startup_database_card.property('state') == 'saved'
        assert reopened.startup_browse.text() == 'Change database…'
        assert 'Reconnect saved library' in reopened.continue_button.text()
        assert not reopened.confirm.isChecked() and not reopened.continue_button.isEnabled()
        assert reopened.library is None and calls==[path]
        reopened.confirm.setChecked(True)
        assert reopened.continue_button.isEnabled()
        reopened.enter()
        assert calls==[path,path] and reopened.pages.currentWidget() is reopened.workspace
    finally:
        reopened.close()


@pytest.mark.parametrize('saved', ['missing', ['invalid'], 'relative.db'])
def test_unavailable_saved_database_requires_selection(window,tmp_path,saved):
    import json
    value=str(tmp_path/'missing.db') if saved=='missing' else saved
    window.config_file.write_text(json.dumps({'last_database':value}))
    reopened=MainWindow()
    try:
        assert reopened.startup_database is None
        assert reopened.startup_database_state == ('empty' if isinstance(saved, list) else 'unavailable')
        assert reopened.startup_browse.text() == 'Choose database…'
        reopened.confirm.setChecked(True)
        assert not reopened.continue_button.isEnabled()
    finally:
        reopened.close()


def test_change_library_remembers_only_success_and_cancel_keeps_it(window,tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    old=tmp_path/'old.db';old.touch()
    new=tmp_path/'new.db';new.touch()
    window.remember_database(old)
    before=window.config_file.read_bytes()
    monkeypatch.setattr(window,'choose_database_path',lambda:str(new))
    monkeypatch.setattr('rekordbox_manager.ui.RekordboxLibrary',lambda path:SimpleNamespace())
    monkeypatch.setattr(window,'set_library',lambda library:False)
    window.connect_library()
    assert window.config_file.read_bytes()==before and window.startup_database==old
    monkeypatch.setattr(window,'set_library',lambda library:True)
    window.connect_library()
    assert json.loads(window.config_file.read_text())['last_database']==str(new)
    assert window.startup_database==new
    monkeypatch.setattr(window,'choose_database_path',lambda:'')
    window.connect_library()
    assert window.startup_database==new


def test_settings_save_failure_does_not_block_connected_library(window,tmp_path,monkeypatch):
    from types import SimpleNamespace
    def fail_write(*args):raise OSError('Read only settings')
    monkeypatch.setattr('rekordbox_manager.ui.durable_json',fail_write)
    monkeypatch.setattr('rekordbox_manager.ui.RekordboxLibrary',lambda path:SimpleNamespace(
        demo=False,writable=False,write_reason='',playlists={}))
    window.startup_database=tmp_path/'master.db'
    window.confirm.setChecked(True)
    window.enter()
    assert window.pages.currentWidget() is window.workspace
    assert 'could not be saved' in window.status.text()


def test_edited_second_drop_shifts_grid_without_snapping_back(window,tmp_path,monkeypatch):
    from rekordbox_manager.analysis import rebuild_proposal
    p=review_playlist(window,tmp_path,monkeypatch)[0]
    # Reproduce the screenshot: Drop 2 edited from 198.681 to 198.661.
    p.track.grid=Grid([round(66.144+(i-191)*60/174,3) for i in range(1000)], [i%4+1 for i in range(1000)])
    p.track.bpm=174
    p.first_drop,p.second_drop=66.267,198.681
    rebuild_proposal(p)
    previous=p.grid.times.copy()
    window.select_track()
    window.marker_snap.setCurrentIndex(window.marker_snap.findData('off'))
    window.move_drop_marker(2,198.661)
    assert p.grid_anchor==2 and p.second_drop_edited and not p.first_drop_edited
    window.table.selectRow(1)
    window.table.selectRow(0)
    window.rebuild_cues()
    assert p.review_note and not p.ready_to_apply
    window.confirm_review()
    assert p.ready_to_apply and p.second_drop==window.second.value()==198.661
    assert p.first_drop==66.267
    assert p.grid.times[575]==198.661 and p.grid.positions[575]==1
    assert p.grid.times[191]==66.247
    assert all(a-b==pytest.approx(-.020,abs=.001) for a,b in zip(p.grid.times,previous))
    assert next(c.time for c in p.cues if c.label=='DROP 2')==198.661
    assert 'Drop 2' in p.grid_note and 'chosen positions' in p.grid_note
    rebuilt=p.grid
    window.rebuild_cues()
    assert p.grid==rebuilt and p.second_drop==198.661


def test_two_manual_anchors_are_not_silently_quantized(window,tmp_path,monkeypatch):
    p=review_playlist(window,tmp_path,monkeypatch)[0]
    window.first.setValue(128.010)
    window.second.setValue(384.030)
    window.rebuild_cues()
    assert p.grid_anchor==2 and p.first_drop_edited and p.second_drop_edited
    assert (p.first_drop,p.second_drop)==(128.010,384.030)
    assert not p.grid_issue and not p.ready_to_apply and 'marker positions are kept' in p.review_note
    assert window.confirm_review_button.isEnabled()
    assert p.grid.times[768]==384.030
    window.first.setValue(128.030)
    window.rebuild_cues()
    assert p.grid_anchor==1 and not p.ready_to_apply
    window.confirm_review()
    assert p.ready_to_apply
    assert (p.first_drop,p.second_drop)==(128.030,384.030)


def test_manual_52ms_conflict_rebuilds_then_confirms_and_leaves_review_queue(window, tmp_path, monkeypatch):
    from rekordbox_manager.analysis import rebuild_proposal
    from rekordbox_manager.grid_writer import tempo
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    p = proposals[0]
    p.first_drop, p.second_drop = 128, 383.948
    rebuild_proposal(p)
    assert p.review_note and not p.grid_issue and not p.cues_dirty
    window.populate_table()
    window.review_filter.setCurrentIndex(1)
    window.select_track()
    window.rebuild_button.click()
    assert not p.grid_issue and not p.cues_dirty and not p.ready_to_apply
    assert '-52 ms' in p.review_note and window.confirm_review_button.isEnabled()
    assert window.selected() is p and window.table.visible_rows() == [0]
    assert (p.first_drop, p.second_drop) == (128, 383.948)
    assert next(c.time for c in p.cues if c.label == 'DROP 2') == 383.948
    assert tempo(p.grid) == tempo(p.track.grid)
    window.confirm_review_button.click()
    assert p.can_apply and p.ready_to_apply and not window.table.visible_rows()
    assert not window.table._buttons[0].property('needsReview') and not calls
    window.apply_changes()
    assert p.track.id in [item.track.id for item in calls[0]]


def test_settings_contains_library_and_diagnostics_without_changing_track_edits(window,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QAbstractSpinBox
    p=review_playlist(window,tmp_path,monkeypatch)[0]
    window.pages.setCurrentWidget(window.workspace)
    window.first.setValue(128.010)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(window.navigation, Qt.LeftButton,
                     pos=window.navigation.tabRect(window.tabs.indexOf(window.settings_tab)).center())
    assert window.tabs.currentWidget() is window.settings_tab
    settings=window.settings_tab
    assert settings.isAncestorOf(window.connect_button)
    assert settings.isAncestorOf(window.diagnostics_button)
    assert not window.play_shortcut.isEnabled()
    assert window.first.buttonSymbols()==window.second.buttonSymbols()==QAbstractSpinBox.NoButtons
    window.set_busy(True)
    assert not window.connect_button.isEnabled()
    window.set_busy(False)
    window.tabs.setCurrentIndex(0)
    assert p.first_drop==128.010 and p.cues_dirty


def test_waveform_styles_apply_persist_and_preserve_edits(window, tmp_path, monkeypatch):
    import json
    from rekordbox_manager.waveform import Waveform
    original = review_playlist(window, tmp_path, monkeypatch)[0]
    window.first.setValue(128.010)
    original.reviewed = True
    original.grid_approved = True
    grid_times = original.grid.times.copy()
    cues = original.cues.copy()
    window.wave.set_zoom(8, 0)
    for index, style in enumerate(Waveform.STYLES):
        window.waveform_style_combo.setCurrentIndex(index)
        assert window.wave.waveform_style == style
        assert window.wave.proposal is original and window.wave.zoom == 8
        assert original.first_drop == 128.010 and original.cues_dirty
        assert original.reviewed and original.grid_approved
        assert original.grid.times == grid_times and original.cues == cues
    assert json.loads(window.config_file.read_text())['waveform_style'] == 'stereo'
    reopened = MainWindow()
    try:
        assert reopened.wave.waveform_style == 'stereo'
        assert reopened.waveform_style_combo.currentData() == 'stereo'
    finally:
        reopened.close()


def test_waveform_preference_save_failure_and_invalid_saved_value(window, monkeypatch):
    def fail(*args):
        raise OSError('Read only settings')
    monkeypatch.setattr('rekordbox_manager.ui.durable_json', fail)
    window.waveform_style_combo.setCurrentIndex(1)
    assert window.wave.waveform_style == 'filled'
    assert 'could not be saved' in window.waveform_style_feedback.text()
    window.config_file.write_text('{"waveform_style": []}')
    reopened = MainWindow()
    try:
        assert reopened.wave.waveform_style == 'classic'
    finally:
        reopened.close()


def test_import_dialog_stays_compact_with_large_skip_list(window, tmp_path, monkeypatch):
    from dataclasses import replace
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    p = review_playlist(window, tmp_path, monkeypatch)[0]
    skipped = [replace(p, grid_issue='Drum timing elsewhere in the track disagrees with the drop-aligned grid.') for _ in range(100)]
    dialog = ImportDialog(window, [p], skipped, tmp_path, True, 3)
    dialog.show()
    QApplication.processEvents()
    assert dialog.height() < 380 and dialog.details.isHidden()
    assert '1 ready to import' in dialog.summary.text() and '100 need review' in dialog.summary.text()
    dialog.details_toggle.click()
    QApplication.processEvents()
    assert dialog.height() < 650 and dialog.details.height() == 220
    assert dialog.details.verticalScrollBar().maximum() > 0
    assert 'inconclusive' in dialog.details.toPlainText()
    dialog.details_toggle.click()
    QApplication.processEvents()
    assert dialog.height() < 380
    dialog.cancel_button.setFocus()
    QTest.keyClick(dialog.cancel_button, Qt.Key_Return)
    assert dialog.result() == QDialog.Rejected
    dialog.close()


def test_playlist_picker_search_preserves_hidden_checks(window):
    from PySide6.QtCore import Qt
    dialog = PlaylistDialog(window, {'a': 'House', 'b': 'DnB', 'c': 'House classics'}, ('b',))
    dialog.search.setText('house')
    dialog.check_visible(Qt.Checked)
    assert dialog.selected_ids() == ('a', 'b', 'c')
    dialog.check_visible(Qt.Unchecked)
    assert dialog.selected_ids() == ('b',)
    dialog.search.clear()
    dialog.check_visible(Qt.Unchecked)
    assert not dialog.use_button.isEnabled()
    dialog.close()


def test_multi_playlist_deduplicates_and_imports_once_preserving_skips(window, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from dataclasses import replace
    monkeypatch.setattr(window.player, 'setSource', lambda source: None)
    grid = Grid([i*.5 for i in range(1024)], [i%4+1 for i in range(1024)])
    tracks = [Track(str(i), f'Track {i}', '', '', tmp_path / f'{i}.wav', 512, 120, grid) for i in range(3)]
    calls = []
    playlists = {'a': [tracks[0], tracks[1]], 'b': [replace(tracks[1]), tracks[2]], 'empty': []}
    library = SimpleNamespace(demo=True, writable=True, playlists={k:k for k in playlists},
                              tracks=lambda key: playlists[key], apply=lambda items, store: calls.append(items) or tmp_path/'backup')
    window.set_library(library)
    window.set_playlist_selection(('a', 'b', 'empty'))
    assert window.selected_playlist_ids() == ('a', 'b', 'empty')
    assert [t.id for t in window.tracks] == ['0', '1', '2']
    proposals = [Proposal(t, Options(False, True), grid, [], 128, 384) for t in window.tracks]
    window.capture_analysis_scope()
    window.analysis_done(proposals)
    window.first.setValue(128.01)
    monkeypatch.setattr(ImportDialog, 'exec', lambda self: QDialog.Accepted)
    window.apply_changes()
    assert len(calls) == 1 and [p.track.id for p in calls[0]] == ['1', '2']
    assert window.selected_playlist_ids() == ('a', 'b', 'empty')
    assert window.proposals[0].first_drop == 128.01 and window.proposals[0].cues_dirty
    assert all(p.applied for p in window.proposals[1:])
    window.apply_changes()
    assert len(calls) == 1  # no second write of already-imported shared tracks
    window.set_playlist_selection(('b',))
    assert [t.id for t in window.tracks] == ['1', '2'] and not window.proposals


def test_multi_playlist_load_failure_never_leaves_partial_batch(window, tmp_path, monkeypatch):
    from types import SimpleNamespace
    tracks = review_playlist(window, tmp_path, monkeypatch)
    def load(key):
        if key == 'bad':
            raise OSError('Playlist unavailable')
        return [tracks[0].track]
    library = SimpleNamespace(demo=True, writable=True, playlists={'good':'Good','bad':'Bad'}, tracks=load)
    window.set_library(library)
    errors = []
    monkeypatch.setattr(window, 'fail', errors.append)
    window.set_playlist_selection(('good', 'bad'))
    assert errors and not window.tracks and not window.proposals
    assert not window.analyse_button.isEnabled()


def ignore_cued_library(window, tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(window.player, 'setSource', lambda source: None)
    grid = Grid([i * .5 for i in range(1024)], [i % 4 + 1 for i in range(1024)])
    tracks = [Track(str(i), f'Track {i}', '', '', tmp_path / f'{i}.wav', 512, 120, grid)
              for i in range(6)]
    for track, kind in zip(tracks, ('memory', 'hot', 'memory_loop', 'hot_loop')):
        track.cues = [Cue(0, 'Existing', kind, 2 if 'loop' in kind else None)]
    groups = {'a': tracks[:5], 'b': tracks[1:], 'empty': []}
    calls, analysed = [], []
    def apply(items, store):
        calls.append([p.track.id for p in items])
        for p in items:
            tracks[int(p.track.id)].cues = p.cues.copy()
        return tmp_path / 'backup'
    def analyse(track, options):
        analysed.append(track.id)
        return Proposal(track, options, grid, [Cue(128, 'DROP 1'), Cue(384, 'DROP 2')], 128, 384)
    monkeypatch.setattr('rekordbox_manager.ui.analyse', analyse)
    window.set_library(SimpleNamespace(demo=True, writable=True, playlists={k:k for k in groups},
                                       tracks=lambda key: groups[key], apply=apply))
    window.set_playlist_selection(('a', 'b', 'empty'))
    return tracks, calls, analysed


def test_ignore_cued_excludes_all_saved_cue_types_from_scan_scope_and_import(window, tmp_path, monkeypatch):
    tracks, calls, analysed = ignore_cued_library(window, tmp_path, monkeypatch)
    window.ignore_cued.setChecked(True)
    assert [t.id for t in window.tracks] == ['4', '5']
    assert window.ignored_track_count == 4 and '4 tracks with existing cues ignored' in window.status.text()
    window.start_analysis()
    assert not window.ignore_cued.isEnabled()
    finish_review_worker(window)
    assert analysed == ['4', '5']
    assert len(window.table._buttons) == 2  # Proposed cues do not hide prepared tracks.
    assert window.import_playlist_breakdown() == [('a', 1, 1, 0, 0), ('b', 2, 2, 0, 0), ('empty', 0, 0, 0, 0)]
    pending = window.proposals[1]
    pending.review_note = 'Check this drop'
    pending.first_drop_edited = True
    window.populate_table()
    monkeypatch.setattr(ImportDialog, 'exec', lambda self: QDialog.Accepted)
    window.apply_changes()
    assert calls == [['4']]
    assert [t.id for t in window.tracks] == ['5']  # Newly saved cues are now ignored.
    assert window.proposals == [pending] and pending.review_note and pending.first_drop_edited
    assert window.import_playlist_breakdown() == [('a', 0, 0, 0, 0), ('b', 1, 0, 1, 0), ('empty', 0, 0, 0, 0)]
    window.ignore_cued.setChecked(False)
    assert len(window.tracks) == 6 and not window.proposals and window.analysis_scope is None


def test_ignore_cued_rechecks_saved_cues_at_scan_start_and_handles_all_ignored(window, tmp_path, monkeypatch):
    tracks, calls, analysed = ignore_cued_library(window, tmp_path, monkeypatch)
    window.ignore_cued.setChecked(True)
    for t in tracks[4:]:
        t.cues = [Cue(0, 'Added since loading', 'hot')]
    window.start_analysis()
    assert not analysed and not calls and window.worker is None
    assert not window.tracks and window.ignored_track_count == 6
    assert not window.analyse_button.isEnabled()
    assert window.wave.proposal is None and window.analysis_scope is None
    assert 'No tracks to prepare' in window.status.full_text


def test_ignore_cued_off_keeps_existing_cues_in_scan(window, tmp_path, monkeypatch):
    tracks, calls, analysed = ignore_cued_library(window, tmp_path, monkeypatch)
    assert not window.ignore_cued.isChecked()
    window.start_analysis()
    finish_review_worker(window)
    assert analysed == [t.id for t in tracks]
    assert len(window.table._buttons) == 6 and not calls


def test_playlist_breakdown_counts_shared_skipped_empty_and_imported_tracks(window, tmp_path, monkeypatch):
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    window.playlist_ids = ('a', 'b', 'empty')
    window.loaded_playlist_tracks = {
        'a': ('House / Warm-up', frozenset(('0', '1'))),
        'b': ('House / Peak time', frozenset(('1', '2'))),
        'empty': ('Empty playlist', frozenset()),
    }
    window.capture_analysis_scope()
    proposals[2].error = 'Audio unavailable'
    rows = window.import_playlist_breakdown()
    assert rows == [('House / Warm-up', 2, 2, 0, 0), ('House / Peak time', 2, 1, 1, 0), ('Empty playlist', 0, 0, 0, 0)]
    # Later changes to the loaded membership cannot expand a completed scan.
    window.loaded_playlist_tracks['b'] = ('Changed after scan', frozenset(('1', '2', 'outside')))
    assert window.import_playlist_breakdown() == rows
    dialog = ImportDialog(window, proposals[:2], proposals[2:], tmp_path, True, 3, rows)
    assert dialog.playlist_table.rowCount() == 3
    assert dialog.playlist_table.item(1, 2).text() == '1'
    assert dialog.playlist_table.columnCount() == 4
    dialog.close()
    window.apply_changes()
    assert [p.track.id for p in calls[0]] == ['0', '1']
    assert window.import_playlist_breakdown() == [('House / Warm-up', 2, 0, 0, 2), ('House / Peak time', 2, 0, 1, 1), ('Empty playlist', 0, 0, 0, 0)]


@pytest.mark.parametrize('change', ['outside', 'duplicate', 'selection', 'library', 'no_scan'])
def test_import_rejects_results_outside_original_scan(window, tmp_path, monkeypatch, change):
    from dataclasses import replace
    from types import SimpleNamespace
    proposals, calls, messages = prepare_apply(window, tmp_path, monkeypatch)
    if change == 'outside':
        window.proposals.append(replace(proposals[0], track=replace(proposals[0].track, id='outside')))
    elif change == 'duplicate':
        window.proposals.append(proposals[0])
    elif change == 'selection':
        window.playlist_ids = ('different',)
    elif change == 'library':
        window.library = SimpleNamespace(**vars(window.library))
    else:
        window.analysis_scope = None
    errors = []
    monkeypatch.setattr(window, 'fail', errors.append)
    window.apply_changes()
    assert errors and not calls and not messages


def test_import_rechecks_scan_after_confirmation(window, tmp_path, monkeypatch):
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    def confirm(dialog):
        window.playlist_ids = ('different',)
        return QDialog.Accepted
    monkeypatch.setattr(ImportDialog, 'exec', confirm)
    errors = []
    monkeypatch.setattr(window, 'fail', errors.append)
    window.apply_changes()
    assert errors and not calls


def test_playlist_breakdown_stays_bounded_for_large_batches(window, tmp_path, monkeypatch):
    p = review_playlist(window, tmp_path, monkeypatch)[0]
    rows = [(f'Playlist {i}', 3, 1, 1, 1) for i in range(100)]
    dialog = ImportDialog(window, [p], [p], tmp_path, True, 100, rows)
    dialog.show()
    QApplication.processEvents()
    assert dialog.playlist_table.rowCount() == 100 and dialog.playlist_table.columnCount() == 5
    assert dialog.playlist_table.height() <= 144
    assert dialog.height() < 620
    dialog.details_toggle.click()
    QApplication.processEvents()
    assert dialog.height() < 760
    assert dialog.playlist_table.verticalScrollBar().maximum() > 0
    dialog.close()


def test_saved_waveform_visible_before_preparation(window, tmp_path, monkeypatch):
    from test_rekordbox_waveforms import saved_files
    from types import SimpleNamespace
    def forbidden(*args, **kwargs):
        raise AssertionError('Browsing must not decode or analyse audio')
    monkeypatch.setattr('rekordbox_manager.ui.analyse', forbidden)
    monkeypatch.setattr('rekordbox_manager.analysis.load_audio', forbidden)
    monkeypatch.setattr('rekordbox_manager.waveform_data.audio_waveforms', forbidden)
    monkeypatch.setattr('rekordbox_manager.ui.sf.info', lambda path: SimpleNamespace(duration=2.04))
    track = Track('saved', 'Saved track', 'Artist', '', tmp_path/'missing.mp3', 2, 120,
                  Grid([0, .5, 1, 1.5], [1, 2, 3, 4]), [Cue(1, 'Existing cue')], saved_files(tmp_path))
    other = Track('absent', 'No saved data', '', '', tmp_path/'missing.wav', 2, 120, track.grid)
    window.tracks = [track, other]
    window.pages.setCurrentWidget(window.workspace)
    window.invalidate()
    preview = window.wave.proposal
    assert preview.track.id == track.id and preview.track.duration == 2.04
    assert track.duration == 2  # reading metadata must not mutate the library track
    assert preview.waveform_data.source == 'Rekordbox saved waveform'
    assert preview.peaks[150] == 1 and preview.grid == track.grid and preview.cues == track.cues
    assert not preview.ready_to_apply and not window.proposals and window.analysis_scope is None
    assert window.selected() is None and window.player.source().isEmpty()
    for control in (window.first, window.second, window.rebuild_button,
                    window.align_grid, window.play, *window.kick_buttons):
        assert not control.isEnabled()
    window.seek(1)
    assert window.wave.position == 1 and window.player.source().isEmpty()
    window.navigate_track(1)
    assert window.wave.proposal.track.id == other.id
    assert not window.wave.proposal.peaks
    assert 'unavailable' in window.review_title.toolTip()
    window.navigate_track(-1)
    window.fix_grid.setChecked(True)
    assert window.wave.proposal.peaks[150] == 1 and not window.proposals
    prepared = Proposal(track, Options(True, True), track.grid, track.cues.copy(), .5, 1.5,
                        peaks=preview.peaks, waveform_data=preview.waveform_data)
    monkeypatch.setattr(window.player, 'setSource', lambda source: None)
    window.analysis_done([prepared])
    assert window.selected() is prepared and window.wave.proposal is prepared
    assert window.play.isEnabled() and window.first.isEnabled()


def test_saved_preview_cue_list_shows_existing_cues(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QTextEdit
    track = Track('t', 'Saved', '', '', tmp_path/'absent.wav', 2, 120,
                  Grid([0,.5],[1,2]), [Cue(.5,'Existing cue')])
    window.tracks = [track]
    window.invalidate()
    shown = []
    monkeypatch.setattr(QDialog, 'exec', lambda d: shown.append(d.findChild(QTextEdit).toPlainText()))
    window.show_cues()
    assert len(shown) == 1 and 'Existing cue' in shown[0]
    assert not window.proposals


def finish_review_worker(window):
    import time
    deadline = time.monotonic() + 5
    while (window.worker.isRunning() or window.analysis_busy) and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.01)
    assert not window.worker.isRunning() and not window.analysis_busy


def test_review_filter_keeps_original_ids_scope_and_navigation(window, tmp_path, monkeypatch):
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    window.pages.setCurrentWidget(window.workspace)
    proposals[1].grid_issue = 'Drum timing elsewhere disagrees'
    proposals[2].cues_dirty = True
    scope = window.analysis_scope
    window.populate_table()
    window.review_filter.setCurrentIndex(1)
    assert window.table.visible_rows() == [1, 2]
    assert window.selected() is proposals[1]
    assert 'Automatic timing check inconclusive' in window.table._buttons[1].accessibleName()
    window.navigate_track(1)
    assert window.selected() is proposals[2]
    window.navigate_track(1)
    assert window.selected() is proposals[1]
    assert window.analysis_scope is scope and len(window.tracks) == 3
    assert window.import_playlist_breakdown() == [('Test playlist', 3, 1, 2, 0)]
    proposals[1].grid_issue = ''
    proposals[2].cues_dirty = False
    window.populate_table()
    assert window.table.visible_rows() == [] and window.selected() is None
    assert window.wave.proposal is None and not window.auto_cue_button.isEnabled()
    assert window.review_title.full_text == 'No tracks need review'
    window.review_filter.setCurrentIndex(0)
    assert window.table.visible_rows() == [0, 1, 2] and window.selected() is proposals[0]
    assert not calls


def test_confirm_review_accepts_existing_timings_and_advances_review_filter(window, tmp_path, monkeypatch):
    from copy import deepcopy
    from rekordbox_manager.analysis import rebuild_proposal
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    for p in proposals[:2]:
        rebuild_proposal(p)
        p.review_note = 'Automatic timing check inconclusive.'
    p = proposals[0]
    before = deepcopy((p.grid, p.cues, p.first_drop, p.second_drop))
    window.populate_table()
    assert window.table._buttons[0].property('needsReview')
    assert window.table._buttons[0].height() == 28
    window.review_filter.setCurrentIndex(1)
    assert window.confirm_review_button.isEnabled()
    assert window.wave.zoom == 16 and window.wave.view_center == p.first_drop
    window.wave.set_zoom(64, p.second_drop)
    window.populate_table()
    assert window.wave.zoom == 64 and window.wave.view_center == p.second_drop
    window.confirm_review_button.click()
    assert p.ready_to_apply and p.can_apply and p.reviewed and p.grid_approved
    assert (p.grid, p.cues, p.first_drop, p.second_drop) == before
    assert window.table.visible_rows() == [1] and window.selected() is proposals[1]
    assert window.wave.zoom == 16 and window.wave.view_center == proposals[1].first_drop
    assert not window.table._buttons[0].property('needsReview')
    assert window.import_playlist_breakdown() == [('Test playlist', 3, 2, 1, 0)]
    assert not calls  # Acceptance never writes to the library.
    window.review_filter.setCurrentIndex(0)
    window.table.selectRow(0)
    window.first.setValue(126)
    assert not p.reviewed and p.cues_dirty and not p.ready_to_apply
    assert not window.confirm_review_button.isEnabled()


@pytest.mark.parametrize('problem', ['dirty', 'error', 'grid', 'missing', 'stale', 'misaligned', 'applied', 'busy'])
def test_confirm_review_cannot_accept_incomplete_or_invalid_changes(window, tmp_path, monkeypatch, problem):
    from rekordbox_manager.analysis import rebuild_proposal
    p = review_playlist(window, tmp_path, monkeypatch)[0]
    rebuild_proposal(p)
    p.review_note = 'Automatic check needs listening.'
    if problem == 'dirty': p.cues_dirty = True
    if problem == 'error': p.error = 'Audio unavailable'
    if problem == 'grid': p.grid_issue = 'Drops disagree with the grid'
    if problem == 'missing': p.first_drop = None
    if problem == 'stale': p.cues = []
    if problem == 'misaligned': p.second_drop += .08
    if problem == 'applied': p.applied = True
    if problem == 'busy': window.analysis_busy = True
    window.update_details()
    assert not window.confirm_review_button.isEnabled()
    window.confirm_review()  # Handler must enforce the same guard as the UI.
    assert not p.reviewed and not p.can_apply
    window.analysis_busy = False


def test_rebuild_in_review_filter_displays_next_tracks_own_markers(window, tmp_path, monkeypatch):
    proposals = review_playlist(window, tmp_path, monkeypatch)
    for p in proposals[:2]:
        p.cues_dirty = True
    window.populate_table()
    window.review_filter.setCurrentIndex(1)
    window.rebuild_cues()
    assert window.selected() is proposals[0] and window.confirm_review_button.isEnabled()
    window.confirm_review()
    assert window.selected() is proposals[1]
    assert window.first.value() == proposals[1].first_drop
    assert window.second.value() == proposals[1].second_drop


@pytest.mark.parametrize('filtered', [False, True])
def test_confirm_review_moves_forward_from_middle_and_zooms_next_drop(window, tmp_path, monkeypatch, filtered):
    from rekordbox_manager.analysis import rebuild_proposal
    proposals = review_playlist(window, tmp_path, monkeypatch)
    for p in proposals:
        rebuild_proposal(p)
        p.review_note = 'Check timing'
    window.populate_table()
    window.review_filter.setCurrentIndex(int(filtered))
    window.table.selectRow(1)
    assert window.wave.zoom == 16 and window.wave.view_center == proposals[1].first_drop
    window.confirm_review_button.click()
    assert window.selected() is proposals[2]
    assert window.wave.zoom == 16 and window.wave.view_center == proposals[2].first_drop
    window.confirm_review_button.click()
    assert window.selected() is proposals[0]
    window.confirm_review_button.click()
    assert all(p.reviewed for p in proposals)
    assert 'No tracks left to review' in window.status.text()
    assert window.table.currentRow() == (-1 if filtered else 0)


def test_review_without_first_drop_and_ready_tracks_keep_whole_track_view(window, tmp_path, monkeypatch):
    proposals = review_playlist(window, tmp_path, monkeypatch)
    proposals[1].first_drop = None
    proposals[1].cues_dirty = True
    window.table.selectRow(1)
    assert window.wave.zoom == 1
    window.table.selectRow(2)
    assert window.wave.zoom == 1


def test_auto_cue_retries_only_review_tracks_without_changing_grids_or_importing(window, tmp_path, monkeypatch):
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    proposals[1].grid_issue = 'Drum timing elsewhere disagrees'
    proposals[2].cues_dirty = True
    originals = tuple(proposals)
    original_duration = proposals[1].track.duration
    jobs = []
    def analyse(track, options):
        jobs.append((track.id, options))
        assert track is not originals[int(track.id)].track
        track.duration = 510  # worker must not mutate displayed source tracks
        result = Proposal(track, options, track.grid, [Cue(128, 'DROP 1')], 128, 384)
        if track.id == '2':
            result.cues_dirty = True
            result.drop_notes = ['Drop 1: no distinct attack']
        return result
    monkeypatch.setattr('rekordbox_manager.ui.analyse', analyse)
    scope = window.analysis_scope
    window.populate_table()
    window.review_filter.setCurrentIndex(1)
    window.auto_cue_button.click()
    assert not window.auto_cue_button.isEnabled()
    before = proposals[1].first_drop
    window.move_drop_marker(1, before + .2)
    assert proposals[1].first_drop == before
    finish_review_worker(window)
    assert [identity for identity, _ in jobs] == ['1', '2']
    assert all(not options.fix_grid and options.set_cues for _, options in jobs)
    assert window.proposals[0] is originals[0]
    assert originals[1].track.duration == original_duration
    assert window.proposals[1].grid == originals[1].track.grid
    assert window.proposals[1].ready_to_apply and not window.proposals[2].ready_to_apply
    assert window.table.visible_rows() == [2] and window.selected() is window.proposals[2]
    assert window.analysis_scope is scope and not calls
    assert '1 more ready' in window.status.full_text
    assert window.import_playlist_breakdown() == [('Test playlist', 3, 2, 1, 0)]
    dialog = ImportDialog(window, window.proposals[:2], window.proposals[2:], tmp_path, True)
    assert 'Cues only; existing grid kept' in dialog.details.toPlainText()


def test_auto_cue_preserves_manual_edits_and_imported_tracks(window, tmp_path, monkeypatch):
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    proposals[0].applied = True
    proposals[1].first_drop_edited = True
    proposals[1].cues_dirty = True
    proposals[2].error = 'Local audio unavailable'
    jobs = []
    def analyse(track, options):
        jobs.append(track.id)
        return Proposal(track, options, track.grid, [], error='Local audio unavailable')
    monkeypatch.setattr('rekordbox_manager.ui.analyse', analyse)
    window.populate_table()
    assert window.auto_cue_button.text() == 'Auto cue review tracks (1)'
    window.auto_cue_review_tracks()
    finish_review_worker(window)
    assert jobs == ['2']
    assert window.proposals[0] is proposals[0] and window.proposals[1] is proposals[1]
    assert 'manual edits were left unchanged' in window.status.full_text
    assert not calls and len(window.review_proposals()) == 2


def test_auto_cue_requires_original_scan_scope(window, tmp_path, monkeypatch):
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    proposals[1].cues_dirty = True
    window.analysis_scope = None
    errors = []
    monkeypatch.setattr(window, 'fail', errors.append)
    window.auto_cue_review_tracks()
    assert errors and not calls and window.worker is None


def test_nested_playlist_picker_search_reveals_paths_and_keeps_selection(window):
    from PySide6.QtCore import Qt
    paths = {
        'a': (('music', 'Music'), ('dnb', 'Drum & Bass'), ('year', '2026'), ('a', 'Warm up')),
        'b': (('music', 'Music'), ('house', 'House'), ('b', 'Warm up')),
        'c': (('archive', 'Archive'), ('c', 'Old favourites')),
    }
    names = {key: ' / '.join(name for _, name in parts) for key, parts in paths.items()}
    dialog = PlaylistDialog(window, names, ('c',), paths)
    assert dialog.tree.topLevelItemCount() == 2
    assert dialog.items['a'].text(0) == 'Warm up'
    assert dialog.items['a'].toolTip(0) == names['a']
    dialog.search.setText('2026 warm')
    assert not dialog.items['a'].isHidden()
    assert dialog.items['b'].isHidden() and dialog.items['c'].isHidden()
    assert all(dialog.folders[key].isExpanded() for key in [('music',), ('music', 'dnb'), ('music', 'dnb', 'year')])
    assert '1 hidden by filters' in dialog.count.text()
    dialog.check_visible(Qt.Checked)
    assert dialog.selected_ids() == ('a', 'c')
    dialog.search.clear()
    # Searching did not replace the previous browsing state.
    assert not dialog.folders[('music',)].isExpanded()
    assert dialog.folders[('archive',)].isExpanded()
    dialog.selected_only.setChecked(True)
    assert not dialog.items['a'].isHidden() and dialog.items['b'].isHidden()
    dialog.check_visible(Qt.Unchecked)
    assert dialog.selected_ids() == ()
    assert not dialog.use_button.isEnabled()
    assert not dialog.empty.isHidden()
    dialog.selected_only.setChecked(False)
    dialog.search.setText('no such playlist')
    assert all(item.isHidden() for item in dialog.items.values())
    dialog.search.clear()
    assert all(not item.isHidden() for item in dialog.items.values())
    dialog.close()


def test_playlist_picker_uses_ids_for_duplicate_folders_and_literal_slashes(window):
    from PySide6.QtCore import Qt
    paths = {
        'a': (('f1', 'Music'), ('a', 'Warm / up')),
        'b': (('f2', 'Music'), ('b', 'Warm / up')),
    }
    dialog = PlaylistDialog(window, {'a': 'Music / Warm / up', 'b': 'Music / Warm / up'}, (), paths)
    assert dialog.tree.topLevelItemCount() == 2
    assert dialog.items['a'].parent() is not dialog.items['b'].parent()
    assert dialog.items['a'].text(0) == 'Warm / up'
    dialog.items['a'].setCheckState(0, Qt.Checked)
    assert dialog.selected_ids() == ('a',)
    dialog.search.setText('missing')
    dialog.clear_all.click()
    assert dialog.selected_ids() == ()
    dialog.close()


def test_off_grid_generated_cues_confirm_directly_and_advance_without_rebuild(window, tmp_path, monkeypatch):
    from copy import deepcopy
    from rekordbox_manager.analysis import rebuild_proposal
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    p = proposals[0]
    p.first_drop, p.second_drop = 128, 383.948
    rebuild_proposal(p)  # Initial automatic preparation, not a manual rebuild.
    proposals[1].review_note = 'Listen to the suggested drop'
    before = deepcopy((p.grid, p.cues, p.first_drop, p.second_drop))
    window.populate_table()
    window.review_filter.setCurrentIndex(1)
    assert window.confirm_review_button.isEnabled()
    assert 'needed' not in window.rebuild_button.text()
    def forbidden(*args, **kwargs):
        pytest.fail('Confirm must not regenerate cues or run analysis')
    monkeypatch.setattr('rekordbox_manager.ui.rebuild_proposal', forbidden)
    monkeypatch.setattr('rekordbox_manager.ui.analyse', forbidden)
    window.confirm_review_button.click()
    assert p.can_apply and (p.grid, p.cues, p.first_drop, p.second_drop) == before
    assert window.selected() is proposals[1] and window.table.visible_rows() == [1]
    assert not window.table._buttons[0].property('needsReview') and not calls
    assert window.import_playlist_breakdown() == [('Test playlist', 3, 2, 1, 0)]


def usage_results(count=3):
    from rekordbox_manager.usage import UsageScan, TrackUsage
    tracks = [TrackUsage('zero','Quiet Track','Alice','House','/missing/zero.wav',0,0,0),
              TrackUsage('history','Reset Count','Bob','Techno','/missing/reset.wav',0,2,1),
              TrackUsage('unknown','Unknown Count','Alice','House','/missing/unknown.wav',None,0,0)]
    tracks.extend(TrackUsage(str(i),f'Extra {i:04}','Artist','House','',i,0,0) for i in range(3,count))
    return UsageScan(tuple(tracks), (), '10 Nov 2026, 12:00 GMT')


def test_feature_tabs_preserve_manager_edits_and_scope_shortcuts(window, tmp_path, monkeypatch):
    original = review_playlist(window, tmp_path, monkeypatch)[0]
    window.pages.setCurrentWidget(window.workspace)
    window.first.setValue(128.010)
    assert [window.navigation.tabText(i) for i in range(window.navigation.count())] == ['Manager','Imports','Organiser','Backups','Settings']
    window.tabs.setCurrentWidget(window.usage_tab)
    assert window.navigation.currentIndex() == window.tabs.indexOf(window.usage_tab)
    window.usage_tab.search.setFocus()
    window.update_play_shortcut(None, window.usage_tab.search)
    assert not window.play_shortcut.isEnabled()
    assert all(not shortcut.isEnabled() for shortcut in window.track_shortcuts)
    window.tabs.setCurrentWidget(window.manager_tab)
    assert window.selected() is original and original.first_drop == 128.010 and original.cues_dirty


def test_usage_filters_search_and_pagination(window):
    page = window.usage_tab
    page.scan = usage_results(250)
    page.apply_filters()
    assert len(page.matches) == 249 and all(t.playlists == 0 for t in page.matches)
    page.filter.setCurrentIndex(page.filter.findData('unplayed'))
    assert [t.id for t in page.matches] == ['zero']
    page.filter.setCurrentIndex(page.filter.findData('both'))
    assert [t.id for t in page.matches] == ['zero']
    page.filter.setCurrentIndex(page.filter.findData('unknown'))
    assert [t.id for t in page.matches] == ['unknown']
    page.filter.setCurrentIndex(page.filter.findData('played'))
    assert 'history' in [t.id for t in page.matches] and 'zero' not in [t.id for t in page.matches]
    page.filter.setCurrentIndex(page.filter.findData('all'))
    assert page.next.isEnabled() and len(page.matches) == 250
    assert page.list.widget().layout().count() == 101  # 100 rows plus stretch.
    page.next.click()
    page.next.click()
    assert page.page == 2 and not page.next.isEnabled()
    assert page.list.widget().layout().count() == 51
    page.search.setText('alice quiet')
    page.apply_filters()
    assert page.page == 0 and [t.id for t in page.matches] == ['zero']
    page.search.setText('no matching track')
    page.apply_filters()
    assert not page.matches and '0–0' in page.page_label.text()


def finish_usage_worker(page):
    from PySide6.QtTest import QTest
    for _ in range(500):
        QApplication.processEvents()
        if not page.scanning:
            return
        QTest.qWait(10)
    pytest.fail('Usage worker did not finish')


def test_usage_background_scan_and_failed_rescan_clear_results(window, monkeypatch):
    from types import SimpleNamespace
    page = window.usage_tab
    page.set_library(SimpleNamespace(path='/test/master.db', demo=False, connect=lambda: None))
    monkeypatch.setattr('rekordbox_manager.usage_ui.scan_usage', lambda *args: usage_results())
    page.scan_button.click()
    assert page.scanning and not page.scan_button.isEnabled()
    finish_usage_worker(page)
    assert page.scan is not None and '3 tracks' in page.summary.text()
    def fail(*args):
        raise ValueError('Library changed; reconnect')
    monkeypatch.setattr('rekordbox_manager.usage_ui.scan_usage', fail)
    page.scan_button.click()
    finish_usage_worker(page)
    assert page.scan is None and not page.matches
    assert 'reconnect' in page.message.text() and page.scan_button.isEnabled()


def test_usage_switch_library_discards_inflight_scan(window, monkeypatch):
    from types import SimpleNamespace
    from threading import Event
    page = window.usage_tab
    release = Event()
    def scan(*args):
        release.wait(2)
        return usage_results()
    monkeypatch.setattr('rekordbox_manager.usage_ui.scan_usage', scan)
    page.set_library(SimpleNamespace(path='/first/master.db',demo=False,connect=lambda: None))
    page.start_scan()
    page.set_library(SimpleNamespace(path='/second/master.db',demo=False,connect=lambda: None))
    release.set()
    finish_usage_worker(page)
    assert page.scan is None and not page.matches
    assert page.source.text() == '/second/master.db' and page.scan_button.isEnabled()


def test_usage_scan_cancels_and_blocks_import(window, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from threading import Event
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    page = window.usage_tab
    release = Event()
    def scan(*args):
        release.wait(2)
        return usage_results()
    monkeypatch.setattr('rekordbox_manager.usage_ui.scan_usage', scan)
    page.set_library(SimpleNamespace(path='/test/master.db',demo=False,connect=lambda: None))
    errors = []
    monkeypatch.setattr(window, 'fail', errors.append)
    page.start_scan()
    window.apply_changes()
    assert not calls and 'scan' in errors[-1]
    page.cancel_scan()
    release.set()
    finish_usage_worker(page)
    assert page.scan is None and page.message.text() == 'Scan cancelled.'
