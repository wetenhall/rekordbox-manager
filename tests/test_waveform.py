import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
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


def wheel(wave, pixels=(0, 0), angles=(0, 0)):
    event = QWheelEvent(QPointF(512, 100), QPointF(512, 100), QPoint(*pixels),
                        QPoint(*angles), Qt.NoButton, Qt.NoModifier,
                        Qt.NoScrollPhase, False)
    QApplication.sendEvent(wave, event)


def test_horizontal_touch_scroll_pans_without_zoom_seek_or_marker_changes(wave):
    wave.set_zoom(16, 256)
    wave.follow_playhead = True
    seeks, moves, views = [], [], []
    wave.seek.connect(seeks.append)
    wave.anchor_moved.connect(lambda *args: moves.append(args))
    wave.view_changed.connect(lambda: views.append(wave.visible_range()))
    before = wave.visible_range()
    # Sideways swipe with incidental vertical motion must only pan.
    wheel(wave, pixels=(-128, 5), angles=(-120, 120))
    assert wave.visible_range()[0] == pytest.approx(before[0] + 4)
    assert wave.zoom == 16 and not wave.follow_playhead
    assert not seeks and not moves and len(views) == 1
    wheel(wave, pixels=(128, 0))
    assert wave.visible_range() == before


def test_horizontal_wheel_fallback_clamps_and_reverses_at_track_edges(wave):
    wheel(wave, angles=(-120, 0))
    assert wave.visible_range() == (0, 512)  # whole-track view cannot pan
    wave.set_zoom(16, 256)
    wheel(wave, angles=(-120, 0))
    assert wave.visible_range()[0] == pytest.approx(243.2)
    wheel(wave, pixels=(-100000, 0))
    assert wave.visible_range()[1] == 512
    wheel(wave, pixels=(32, 0))
    assert wave.visible_range()[1] == 511  # no accumulated overscroll
    wheel(wave, pixels=(100000, 0))
    assert wave.visible_range()[0] == 0


def test_vertical_zoom_remains_available_and_scroll_cannot_disrupt_drag(wave):
    wave.set_zoom(16, 128)
    wheel(wave, angles=(0, 120))
    assert wave.zoom == 32
    point = wave.marker_rect(1).center().toPoint()
    QTest.mousePress(wave, Qt.LeftButton, pos=point)
    before = wave.visible_range()
    wheel(wave, pixels=(-128, 0))
    wheel(wave, angles=(0, 120))
    assert wave.visible_range() == before and wave.zoom == 32
    QTest.mouseRelease(wave, Qt.LeftButton, pos=point)


@pytest.mark.parametrize('style', list(Waveform.STYLES))
def test_styles_keep_marker_hit_targets_seek_and_zoom(wave, style):
    from array import array
    from rekordbox_manager.waveform_data import WaveformData
    wave.proposal.waveform_data = WaveformData(
        array('f', wave.proposal.peaks),
        tuple(array('f', [value] * 1000) for value in (.6, .3, .1)),
        tuple(array('f', [value] * 1000) for value in (.5, .2)))
    wave.set_zoom(16, 128)
    before = wave.visible_range()
    marker = wave.marker_rect(1)
    wave.set_style(style)
    assert not wave.grab().isNull()
    assert wave.visible_range() == before and wave.marker_rect(1) == marker
    drag(wave, 1, 137)
    assert wave.proposal.first_drop == 137
    seeks = []
    wave.seek.connect(seeks.append)
    QTest.mouseClick(wave, Qt.LeftButton, pos=QPoint(512, 150))
    assert seeks == [128]


def test_saved_waveform_clock_is_not_stretched_to_audio_duration(wave,monkeypatch):
    from array import array
    from rekordbox_manager.waveform_data import WaveformData, pixel_peaks
    data=WaveformData(array('f',[.5]*300),tuple(array('f',[.3]*300) for _ in range(3)),
                      (array('f',[.4]*2040),),'Rekordbox saved waveform',150,150,1000)
    wave.proposal.waveform_data=data;wave.proposal.peaks=data.peaks
    wave.proposal.track.duration=2.04
    durations=[]
    def capture(values,duration,*args):
        durations.append(duration)
        return pixel_peaks(values,duration,*args)
    monkeypatch.setattr('rekordbox_manager.waveform.pixel_peaks',capture)
    wave.set_style('bass');wave.grab()
    assert durations and all(d==2 for d in durations)
    durations.clear()
    wave.set_style('stereo');wave.grab()
    assert durations==[2,2.04]


@pytest.mark.parametrize('style', ['stereo', 'bass', 'frequency', 'three_band'])
def test_partial_saved_waveform_displays_amplitude_fallback(wave, style):
    from rekordbox_manager.waveform_data import WaveformData
    from array import array
    wave.proposal.waveform_data = WaveformData(peaks=array('f',wave.proposal.peaks), source='Rekordbox saved waveform')
    wave.set_style('classic')
    expected = wave.grab().toImage()
    wave.set_style(style)
    rendered = wave.grab().toImage()
    # The data area remains the same amplitude view; the explanatory legend differs.
    assert rendered.copy(0, 80, wave.width(), wave.height()-80) == expected.copy(0, 80, wave.width(), wave.height()-80)


def test_grid_emphasis_follows_bar_positions_even_when_view_starts_mid_bar():
    grid = Grid([i * .5 for i in range(12)], [3, 4, 1, 2] * 3)
    marks = Waveform.grid_marks(grid, .5, 4.5, 800)
    assert [thick for _, thick in marks] == [False, True, False, False, False, True, False, False, False]


def test_shifted_grid_is_one_thick_then_three_thin_without_old_grid_overlay(wave):
    p = wave.proposal
    p.grid = Grid([t + .17 for t in p.track.grid.times], p.track.grid.positions.copy())
    p.first_drop = p.second_drop = None
    p.cues = []
    p.peaks = [.1] * 1000
    wave.set_zoom(64, 128)
    image = wave.grab().toImage()
    start, end = wave.visible_range()
    def x(time):
        return round((time - start) / (end - start) * wave.width())
    def red_at(column, y):
        color = image.pixelColor(column, y)
        return color.red() > color.green() * 1.5 and color.red() > color.blue() * 1.5
    # Away from waveform/cues/axis text, active beats use two pixels for beat 1,
    # one pixel for beats 2–4. Saved (unshifted) grid positions leave no red lines.
    for beat in range(4):
        active_x = x(126.17 + beat * .5)
        assert red_at(active_x, 25)
        assert sum(red_at(column, 25) for column in range(active_x - 2, active_x + 3)) == (2 if beat == 0 else 1)
        assert not red_at(x(126 + beat * .5), 25)
        assert red_at(active_x, 15) and red_at(active_x, wave.height() - 27)
