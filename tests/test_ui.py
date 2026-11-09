import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QMessageBox
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
    assert window.playlists.currentText()=='My playlist'
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
    assert not window.apply_button.isEnabled()


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


def prepare_apply(window, tmp_path, monkeypatch):
    proposals = review_playlist(window, tmp_path, monkeypatch)
    calls, messages = [], []
    window.library.writable = True
    window.library.demo = True
    monkeypatch.setattr(window.library, 'apply', lambda items, store: calls.append(items) or tmp_path / 'backup', raising=False)
    monkeypatch.setattr(window, 'load_tracks', lambda: None)
    def confirm(*args):
        messages.append(args[2])
        return QMessageBox.Yes
    monkeypatch.setattr(QMessageBox, 'question', confirm)
    window.update_details()
    return proposals, calls, messages


def test_playlist_apply_needs_no_per_track_confirmation(window, tmp_path, monkeypatch):
    proposals, calls, messages = prepare_apply(window, tmp_path, monkeypatch)
    assert window.apply_button.isEnabled()
    assert not hasattr(window, 'grid_confirm') and not hasattr(window, 'approve_all')
    window.first.setValue(96)
    window.rebuild_cues()
    window.apply_changes()
    assert len(messages) == 1 and len(calls) == 1
    assert all(p.can_apply for p in calls[0])
    assert [p.first_drop for p in calls[0]] == [96, 160, 192]
    assert all(not p.reviewed for p in proposals)  # confirmation scoped to write


def test_cancel_playlist_apply_changes_nothing(window, tmp_path, monkeypatch):
    proposals, calls, _ = prepare_apply(window, tmp_path, monkeypatch)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.No)
    window.apply_changes()
    assert not calls
    assert all(not p.reviewed and not p.grid_approved for p in proposals)


def test_playlist_apply_skips_errors_and_unrebuilt_edits(window, tmp_path, monkeypatch):
    proposals, calls, messages = prepare_apply(window, tmp_path, monkeypatch)
    proposals[1].error = 'Audio unavailable'
    window.first.setValue(96)
    window.apply_changes()
    assert [p.track.id for p in calls[0]] == ['2']
    assert '2 track(s) will be skipped' in messages[0]
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
    assert not window.apply_button.isEnabled()


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
    assert not window.apply_button.isEnabled()
    assert window.apply_button.text() == 'Apply all changes (3 tracks)'


def test_all_invalid_or_busy_playlist_cannot_apply(window, tmp_path, monkeypatch):
    proposals, calls, messages = prepare_apply(window, tmp_path, monkeypatch)
    window.set_busy(True)
    window.update_details()
    assert not window.apply_button.isEnabled()
    window.apply_changes()
    assert not calls and not messages
    window.set_busy(False)
    for p in proposals:
        p.error = 'Failed'
    window.update_details()
    assert not window.apply_button.isEnabled()
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
    assert window.wave.mapTo(window, QPoint(0, window.wave.height())).y() < window.table.mapTo(window, QPoint(0, 0)).y()
    assert window.table.height() >= 4 * 28
    assert window.apply_button.mapTo(window, QPoint(window.apply_button.width(), window.apply_button.height())).y() <= window.height()
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
    assert window.tabs.currentIndex() == 1
    next(b for b in window.findChildren(QPushButton) if b.text() == '← Back to playlist').click()
    assert window.tabs.currentIndex() == 0


def test_live_import_confirmation_includes_grid_files(window, tmp_path, monkeypatch):
    proposals, calls, messages = prepare_apply(window, tmp_path, monkeypatch)
    window.library.demo = False
    for p in proposals:
        p.options = Options(False, True)
    window.update_details()
    assert window.apply_button.text() == 'Import cues to Rekordbox (3 tracks)'
    window.apply_changes()
    assert len(calls) == 1 and 'verified database backup' in messages[0]
    assert 'Rekordbox must remain closed' in messages[0]
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


def test_grid_anchor_invalidates_old_cues_and_metronome(window, tmp_path, monkeypatch):
    proposals = review_playlist(window, tmp_path, monkeypatch)
    proposal = proposals[0]
    monkeypatch.setattr(window.player, 'position', lambda: 128520)
    window.align_grid_to_playhead()
    assert proposal.grid.positions[257] == 1
    assert proposal.first_drop == 128.52
    assert proposal.cues_dirty and not proposal.ready_to_apply
    window.rebuild_cues()
    assert not proposal.cues_dirty
    assert any(c.time == 128.52 and c.label == 'DROP 1' for c in proposal.cues)


def test_metronome_rebuilds_accents_after_bar_alignment(window, tmp_path, monkeypatch):
    from types import SimpleNamespace
    proposals=review_playlist(window,tmp_path,monkeypatch)
    proposals[0].track.path.write_bytes(b'only-stat-needed')
    paths,callbacks,sources=[],[],[]
    def worker(track,grid,path):
        paths.append(path)
        return SimpleNamespace(done=SimpleNamespace(connect=callbacks.append),
                               start=lambda:None,isRunning=lambda:False)
    monkeypatch.setattr('rekordbox_manager.ui.MetronomeWorker',worker)
    monkeypatch.setattr(window.player,'setSource',lambda url:sources.append(url))
    monkeypatch.setattr(window.player,'position',lambda:129000)
    window.metronome.setChecked(True)
    window.align_grid_to_playhead()  # Beat times stay fixed; only bar accents change.
    window.metronome.setChecked(True)
    assert len(paths)==2 and paths[0]!=paths[1]
    sources.clear()
    callbacks[0](str(paths[0]),'')
    assert sources==[]  # An old asynchronous render cannot replace the new grid.
    callbacks[1](str(paths[1]),'')
    assert len(sources)==1


def test_rebuild_preserves_manual_anchor_and_snap_change_does_not_move_it(window,tmp_path,monkeypatch):
    p=review_playlist(window,tmp_path,monkeypatch)[0]
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
    if outcome=='cancel':monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.No)
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
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    proposals=review_playlist(window,tmp_path,monkeypatch)
    sources=[]
    monkeypatch.setattr(window.player,'setSource',lambda url:sources.append(url.toLocalFile()))
    window.pages.setCurrentWidget(window.workspace)
    window.show();window.activateWindow()
    window.move_drop_marker(2,385.25)
    window.play.setFocus();QApplication.processEvents()
    assert window.rebuild_button.property('needsRebuild')
    QTest.keyClick(window.play,Qt.Key_Down)
    assert window.table.currentRow()==1 and window.wave.proposal is proposals[1]
    assert sources[-1]==str(proposals[1].track.path)
    assert window.first.value()==160 and window.second.value()==384
    assert not window.rebuild_button.property('needsRebuild')
    QTest.keyClick(window.play,Qt.Key_Up)
    assert window.wave.proposal is proposals[0] and window.second.value()==385.25
    assert window.rebuild_button.property('needsRebuild') and 'needed' in window.rebuild_button.text()
    QTest.keyClick(window.play,Qt.Key_Up)
    assert window.table.currentRow()==2
    QTest.keyClick(window.play,Qt.Key_Down)
    assert window.table.currentRow()==0
    window.rebuild_button.click()
    assert not window.rebuild_button.property('needsRebuild')
    assert window.rebuild_button.text()=='Rebuild cues'


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
