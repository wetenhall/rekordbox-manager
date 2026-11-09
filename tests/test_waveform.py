import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rekordbox_manager.models import Grid, Options, Proposal, Track
from rekordbox_manager.waveform import Waveform


@pytest.fixture
def wave(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = Waveform()
    widget.resize(1024, 210)
    grid = Grid([i * .5 for i in range(1024)], [i % 4 + 1 for i in range(1024)])
    track = Track('t', 'Test', '', '', tmp_path / 'test.wav', 512, 120, grid)
    widget.proposal = Proposal(track, Options(False, True), grid, [], 128, 384, peaks=[.5] * 1000)
    def update(number, seconds):
        if number == 1:
            widget.proposal.first_drop = seconds
        else:
            widget.proposal.second_drop = seconds
    widget.anchor_moved.connect(update)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def drag(wave, number, target_seconds):
    rect = wave.marker_rect(number)
    point = rect.center().toPoint()
    start, end = wave.visible_range()
    delta = (target_seconds - wave.marker_time(number)) / (end - start) * wave.width()
    destination = QPoint(round(point.x() + delta), point.y())
    QTest.mousePress(wave, Qt.LeftButton, pos=point)
    QTest.mouseMove(wave, destination)
    QTest.mouseRelease(wave, Qt.LeftButton, pos=destination)


def test_drag_snaps_to_downbeat_without_seeking(wave):
    wave.snap_mode = "bar"
    seeks, starts = [], []
    wave.seek.connect(seeks.append)
    wave.drag_started.connect(lambda: starts.append(True))
    drag(wave, 1, 145.3)
    assert wave.proposal.first_drop == 146
    assert seeks == [] and starts == [True]


@pytest.mark.parametrize('number,target,expected', [(1, 450, 382), (2, 10, 130)])
def test_markers_cannot_cross(wave, number, target, expected):
    wave.snap_mode = "bar"
    drag(wave, number, target)
    assert wave.marker_time(number) == expected
    assert wave.proposal.first_drop < wave.proposal.second_drop


def test_zoom_preserves_time_under_cursor_and_pan_reaches_both_ends(wave):
    wave.zoom_by(1, 256)
    start, end = wave.visible_range()
    assert start + .25 * (end - start) == 128
    wave.pan(1)
    assert wave.visible_range()[1] == 512
    wave.pan(0)
    assert wave.visible_range()[0] == 0


def test_zoomed_drag_does_not_move_viewport(wave):
    wave.set_zoom(16, 128)
    before = wave.visible_range()
    wave.follow_playhead = True
    wave.drag_started.connect(lambda: wave.set_position(150))
    drag(wave, 1, 137)
    assert wave.proposal.first_drop == 137
    assert wave.visible_range() == before
    assert not wave.follow_playhead


def test_click_elsewhere_still_seeks_and_grid_only_has_no_handles(wave):
    seeks = []
    wave.seek.connect(seeks.append)
    QTest.mouseClick(wave, Qt.LeftButton, pos=QPoint(512, 150))
    assert seeks == [256]
    wave.proposal.options = Options(True, False)
    assert wave.hit_marker(wave.marker_rect(1).center()) is None


def test_default_beat_snap_can_reach_between_bar_starts(wave):
    wave.set_zoom(16, 384)
    drag(wave, 2, 385)
    assert wave.proposal.second_drop == 385


def test_off_snap_can_reach_between_beats(wave):
    wave.snap_mode = "off"
    wave.set_zoom(64, 384)
    drag(wave, 2, 384.125)
    assert wave.proposal.second_drop == 384.125


@pytest.mark.parametrize('number,target,expected', [(1,450,383.999),(2,10,128.001),(1,-10,0),(2,600,511.999)])
def test_off_snap_respects_order_and_audio_bounds(wave,number,target,expected):
    wave.snap_mode = "off"
    drag(wave,number,target)
    assert wave.marker_time(number) == expected
