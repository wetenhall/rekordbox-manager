from PySide6.QtCore import QEvent, QPoint, Qt, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import pytest

from test_ui import window, review_playlist
from test_cue_audit import correction_playlist


def transport(window, tmp_path, monkeypatch):
    proposals = review_playlist(window, tmp_path, monkeypatch)
    state = {'position': 0, 'state': QMediaPlayer.PausedState, 'source': QUrl.fromLocalFile(str(proposals[0].track.path))}
    monkeypatch.setattr(window.player, 'position', lambda: state['position'])
    monkeypatch.setattr(window.player, 'playbackState', lambda: state['state'])
    monkeypatch.setattr(window.player, 'source', lambda: state['source'])
    monkeypatch.setattr(window.player, 'setPosition', lambda value: state.update(position=value))
    monkeypatch.setattr(window.player, 'play', lambda: state.update(state=QMediaPlayer.PlayingState))
    monkeypatch.setattr(window.player, 'pause', lambda: state.update(state=QMediaPlayer.PausedState))
    monkeypatch.setattr(window.player, 'stop', lambda: state.update(state=QMediaPlayer.StoppedState, position=0))
    monkeypatch.setattr(window.player, 'setSource', lambda value: state.update(source=value, position=0))
    window.update_details()
    return state, proposals


@pytest.mark.parametrize('offset', [0, .037, -.021])
def test_hold_plays_release_returns_to_cue_with_audio_offset(window, tmp_path, monkeypatch, offset):
    state, proposals = transport(window, tmp_path, monkeypatch)
    proposals[0].track.audio_offset = offset
    original_cues = proposals[0].cues.copy()
    window.seek(12.5)
    expected = round((12.5-offset)*1000)
    window.cue_button.pressed.emit()
    assert window.cue_held and state['state'] == QMediaPlayer.PlayingState
    assert state['position'] == expected
    state['position'] += 1250
    window.play_position(state['position'])
    window.cue_button.released.emit()
    assert not window.cue_held and state['state'] == QMediaPlayer.PausedState
    assert state['position'] == expected and window.wave.position == pytest.approx(12.5)
    window.cue_button.pressed.emit()
    assert state['position'] == expected
    window.release_cue()
    assert proposals[0].cues == original_cues


def test_cue_during_playback_uses_last_paused_cue(window, tmp_path, monkeypatch):
    state, _ = transport(window, tmp_path, monkeypatch)
    window.seek(10)
    window.toggle_play()
    state['position'] = 25000
    window.seek(30)  # Seeking during ordinary playback doesn't redefine the cue.
    window.press_cue()
    assert state['position'] == 10000
    window.toggle_play()  # Play must not latch the hold audition.
    state['position'] = 14000
    window.release_cue()
    assert state['state'] == QMediaPlayer.PausedState and state['position'] == 10000


def test_track_switch_cancels_hold_and_old_release_cannot_seek_new_track(window, tmp_path, monkeypatch):
    state, _ = transport(window, tmp_path, monkeypatch)
    window.seek(10)
    window.press_cue()
    window.table.selectRow(1)
    assert not window.cue_held and window.cue_position == 0
    state['position'] = 5000
    window.release_cue()
    assert state['position'] == 5000


@pytest.mark.parametrize('action', ['deactivate', 'tab', 'scan', 'source', 'error'])
def test_hold_cancels_on_interruption(window, tmp_path, monkeypatch, action):
    state, _ = transport(window, tmp_path, monkeypatch)
    window.seek(10)
    window.press_cue()
    state['position'] = 12000
    if action == 'deactivate':
        window.eventFilter(window, QEvent(QEvent.WindowDeactivate))
    elif action == 'tab':
        window.tabs.setCurrentWidget(window.settings_tab)
    elif action == 'scan':
        window.set_busy(True)
    elif action == 'source':
        state.update(source=QUrl.fromLocalFile('/tmp/different.wav'), position=0)
        window.player.sourceChanged.emit(state['source'])
    else:
        window.player.errorOccurred.emit(QMediaPlayer.ResourceError, 'Test decoder error')
    assert not window.cue_held and state['state'] != QMediaPlayer.PlayingState
    assert state['position'] == (0 if action == 'source' else 12000 if action == 'error' else 10000)


def test_mouse_cue_releases_outside_and_space_on_cue_uses_normal_transport(window, tmp_path, monkeypatch):
    state, _ = transport(window, tmp_path, monkeypatch)
    window.pages.setCurrentWidget(window.workspace)
    window.show()
    window.activateWindow()
    QApplication.processEvents()
    window.seek(8)
    QTest.mousePress(window.cue_button, Qt.LeftButton)
    assert window.cue_held
    state['position'] = 9000
    QTest.mouseRelease(window, Qt.LeftButton, pos=QPoint(2, 2))
    assert not window.cue_held and state['position'] == 8000
    window.cue_button.setFocus()
    QApplication.processEvents()
    assert window.play_shortcut.isEnabled()
    QTest.keyClick(window.cue_button, Qt.Key_Space)
    assert not window.cue_held and state['state'] == QMediaPlayer.PlayingState
    state['position'] = 10000
    QTest.keyClick(window.cue_button, Qt.Key_Space)
    assert not window.cue_held and state['state'] == QMediaPlayer.PausedState and state['position'] == 10000


def test_comparison_drop_handles_drag_and_rebuild_without_activation_step(window, tmp_path, monkeypatch):
    _, _ = correction_playlist(window, tmp_path, monkeypatch)
    window.pages.setCurrentWidget(window.workspace)
    window.show()
    QApplication.processEvents()
    draft = window.selected()
    assert draft and window.first.isEnabled() and window.rebuild_button.isEnabled()
    window.wave.reset_view()
    window.wave.snap_mode = 'off'
    point = window.wave.marker_rect(1).center().toPoint()
    QTest.mousePress(window.wave, Qt.LeftButton, pos=point)
    QTest.mouseMove(window.wave, point + QPoint(20, 0))
    QTest.mouseRelease(window.wave, Qt.LeftButton, pos=point + QPoint(20, 0))
    assert draft.first_drop != 100 and draft.cues_dirty
    assert window.rebuild_button.isEnabled() and not window.import_queue.entries
    window.rebuild_button.click()
    assert not draft.cues_dirty and window.confirm_review_button.isEnabled()
    assert not window.import_queue.entries


def test_full_memory_slot_blocker_is_visible_in_prepare_mode(window, tmp_path, monkeypatch):
    state, proposals = transport(window, tmp_path, monkeypatch)
    proposals[0].error = 'Not enough free memory slots for both drops. Replace memory cues or review saved loops.'
    window.update_details()
    assert not window.rebuild_button.isEnabled()
    assert not window.edit_feedback.isHidden()
    assert 'Enable Replace memory cues and scan again' in window.edit_feedback.text()
    assert not proposals[0].ready_to_apply


def test_check_cues_mouse_focus_restores_space_and_arrows_load_audited_tracks(window, tmp_path, monkeypatch):
    from rekordbox_manager.cue_audit import audit_track
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    other = window.tracks[1]
    window.audit_results[other.id] = audit_track(other)
    state = {'state': QMediaPlayer.PausedState, 'source': QUrl()}
    monkeypatch.setattr(window.player, 'playbackState', lambda: state['state'])
    monkeypatch.setattr(window.player, 'play', lambda: state.update(state=QMediaPlayer.PlayingState))
    monkeypatch.setattr(window.player, 'pause', lambda: state.update(state=QMediaPlayer.PausedState))
    monkeypatch.setattr(window.player, 'setSource', lambda source: state.update(source=source))
    window.pages.setCurrentWidget(window.workspace)
    window.show()
    window.activateWindow()
    for previous in (window.audit_tolerance, window.first, window.playlist_browser.search):
        previous.setFocus()
        QApplication.processEvents()
        assert not window.play_shortcut.isEnabled()
        QTest.mouseClick(window.wave, Qt.LeftButton, pos=QPoint(window.wave.width() // 2, window.wave.height() // 2))
        assert window.wave.hasFocus() and window.play_shortcut.isEnabled()
        QTest.keyClick(window.wave, Qt.Key_Space)
        assert state['state'] == QMediaPlayer.PlayingState
        QTest.keyClick(window.wave, Qt.Key_Space)
        assert state['state'] == QMediaPlayer.PausedState
        QTest.keyClick(window.wave, Qt.Key_Down)
        assert window.table.currentRow() == 1 and window.wave.proposal.track.id == other.id
        assert state['source'].toLocalFile() == str(other.path)
        QTest.keyClick(window.wave, Qt.Key_Up)
        assert window.table.currentRow() == 0 and window.wave.proposal.track.id == track.id
    window.audit_tolerance.setFocus()
    QApplication.processEvents()
    QTest.mouseClick(window.table._buttons[1], Qt.LeftButton)
    assert window.table._buttons[1].hasFocus() and window.play_shortcut.isEnabled()
    QTest.keyClick(window.table._buttons[1], Qt.Key_Space)
    assert state['state'] == QMediaPlayer.PlayingState
    QTest.keyClick(window.table._buttons[1], Qt.Key_Up)
    assert window.table.currentRow() == 0 and window.wave.proposal.track.id == track.id


def test_completed_manager_choices_return_focus_to_transport(window, tmp_path, monkeypatch):
    correction_playlist(window, tmp_path, monkeypatch)
    window.pages.setCurrentWidget(window.workspace)
    window.show()
    window.activateWindow()
    for control in (window.scan_mode, window.review_filter):
        control.setFocus()
        QApplication.processEvents()
        control.activated.emit(control.currentIndex())
        QApplication.processEvents()
        assert window.wave.hasFocus()
        assert window.play_shortcut.isEnabled() and all(s.isEnabled() for s in window.track_shortcuts)
    window.tabs.setCurrentWidget(window.settings_tab)
    window.focus_transport()
    assert not window.play_shortcut.isEnabled()
