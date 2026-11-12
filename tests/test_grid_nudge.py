from copy import deepcopy
from dataclasses import replace
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from rekordbox_manager.models import Grid, Track, Options, Proposal
from rekordbox_manager.grid_nudge import nudge_grid
from rekordbox_manager.analysis import rebuild_proposal, confirm_proposal_review
from rekordbox_manager.grid_writer import tempo
from test_ui import window
from test_cue_audit import correction_playlist


def proposal(tmp_path):
    grid = Grid([i * .5 for i in range(600)], [i % 4 + 1 for i in range(600)])
    track = Track('t', 'Track', '', '', tmp_path/'t.wav', 300, 120, grid)
    return Proposal(track, Options(False, True, True), grid, [], 64, 192)


def test_nudge_trim_reverse_rebuild_and_confirmation_preserve_bpm_and_original(tmp_path):
    p = proposal(tmp_path)
    saved = deepcopy(p.track)
    nudge_grid(p, -.010)
    assert p.grid.times[0] == .49 and p.grid.positions[0] == 2
    assert p.options.fix_grid and p.cues_dirty and not p.reviewed
    assert p.first_drop == 64 and p.second_drop == 192
    shifted = deepcopy(p.grid)
    rebuild_proposal(p, manual=True)
    assert p.grid == shifted and not p.cues_dirty and not p.ready_to_apply
    confirm_proposal_review(p)
    assert p.grid_approved and p.can_apply
    nudge_grid(p, .010)
    assert p.grid == saved.grid and not p.can_apply
    assert p.track == saved and tempo(p.grid) == tempo(saved.grid)
    nudge_grid(p, .001)
    assert p.grid.times[0] == .001


def test_invalid_nudges_leave_proposal_unchanged(tmp_path):
    p = proposal(tmp_path)
    for step in (.05, .05, .05, .05, .05):
        nudge_grid(p, step)
    before = deepcopy(p)
    with pytest.raises(ValueError, match='half a beat'):
        nudge_grid(p, .01)
    assert p == before
    p = proposal(tmp_path)
    p.grid = deepcopy(p.grid)
    p.grid.times[5] += .1
    with pytest.raises(Exception, match='Variable-tempo'):
        nudge_grid(p, .01)


def test_comparison_grid_edits_sync_views_but_never_mutate_original(window, tmp_path, monkeypatch):
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    saved = deepcopy(track)
    window.pages.setCurrentWidget(window.workspace)
    window.resize(1050, 720)
    window.show(); window.activateWindow(); QApplication.processEvents()
    p = window.selected()
    assert window.original_wave_box.isVisible()
    assert window.original_wave.width() == window.wave.width()
    assert window.original_wave.proposal.options == Options(False, False)
    window.wave.set_zoom(16, 150)
    assert window.original_wave.visible_range() == window.wave.visible_range()
    window.original_wave.pan(.25)
    assert window.original_wave.visible_range() == window.wave.visible_range()
    window.seek(90)
    assert window.original_wave.position == window.wave.position == 90
    window.confirm_review()
    assert window.import_queue.ready()
    QTest.mouseClick(window.grid_left, Qt.LeftButton)
    assert p.options.fix_grid and p.cues_dirty and not window.import_queue.ready()
    assert window.original_wave.proposal.grid == saved.grid
    assert window.wave.proposal.grid != saved.grid
    window.rebuild_cues()
    assert not p.cues_dirty and window.confirm_review_button.isEnabled()
    assert window.confirm_review_button.text() == 'Use cues + grid'
    window.confirm_review()
    assert window.import_queue.ready()[0].proposal is p and p.grid_approved
    QTest.mouseClick(window.grid_right, Qt.LeftButton, Qt.ShiftModifier)
    assert p.manual_grid.times[0] == -.009 and not window.import_queue.ready()
    assert window.original_wave.proposal.grid == saved.grid and track == saved
    window.keep_original_cues()
    assert not window.import_queue.entries and track == saved


def test_manual_grid_and_cues_import_with_boundary_trim_and_backup(tmp_path):
    from test_grid_writer import prepared, rows
    lib, p, store = prepared(tmp_path)
    p.grid = deepcopy(p.track.grid)
    p.options = Options(False, True, True)
    p.first_drop, p.second_drop = 32, 64
    protected = rows(lib, 'djmdCue', "WHERE ID IN ('h','l')")
    original = deepcopy(p.track)
    nudge_grid(p, -.010)
    rebuild_proposal(p, manual=True)
    confirm_proposal_review(p)
    backup = lib.apply([p], store)
    updated = lib.tracks('p')[0]
    assert updated.grid == p.grid and updated.cues == p.cues
    assert rows(lib, 'djmdCue', "WHERE ID IN ('h','l')") == protected
    lib.restore(store, backup)
    assert lib.tracks('p')[0].grid == original.grid
