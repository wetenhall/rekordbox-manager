from array import array
from collections import OrderedDict
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rekordbox_manager.cue_audit import audit_track, audit_key, compare_cues, CueAuditResult
from rekordbox_manager.models import Cue, Grid, Options, Proposal, Track
from rekordbox_manager.ui import CueAuditWorker
from test_ui import window
from test_imports_ui import prepared_playlists


def sample_track(tmp_path):
    path = tmp_path / 'song.wav'
    path.write_bytes(b'original audio')
    grid = Grid([i * .5 for i in range(1000)], [i % 4 + 1 for i in range(1000)])
    return Track('t', 'Song', 'Artist', 'House', path, 500, 120, grid,
                 [Cue(100, 'My drop'), Cue(200, 'My second drop'), Cue(220, 'Hot cue', 'hot'), Cue(240, 'Loop', 'memory_loop', 248)])


def test_comparison_tolerance_names_duplicates_and_missing_cues():
    expected = [Cue(100, 'DROP 1'), Cue(200, 'DROP 2')]
    assert compare_cues([Cue(100.05, 'unrelated label'), Cue(199.96, '')], expected) == ((), ())
    missing, extra = compare_cues([Cue(100, ''), Cue(100, 'duplicate'), Cue(200.2, 'late')], expected)
    assert missing == (expected[1],)
    assert len(extra) == 2 and extra[-1].time == 200.2
    assert compare_cues([Cue(100, 'Hot', 'hot')], [Cue(100, 'memory')])[0]


@pytest.mark.parametrize('issue,status', [('', 'Cue differences'), ('uncertain', 'Inconclusive'), ('missing audio', 'Unavailable')])
def test_audit_is_independent_and_never_mutates_saved_state(tmp_path, monkeypatch, issue, status):
    track = sample_track(tmp_path)
    before = deepcopy(track)
    def suggest(copy, options):
        assert options == Options(False, True, True)
        assert copy is not track and copy.grid is not track.grid
        copy.cues.clear()
        return Proposal(copy, options, copy.grid, [Cue(101, 'DROP 1'), Cue(200, 'DROP 2')], 101, 200,
                        peaks=array('f', [.1, .7] * 5000), review_note=issue if issue == 'uncertain' else '',
                        error=issue if issue == 'missing audio' else '')
    monkeypatch.setattr('rekordbox_manager.cue_audit.analyse', suggest)
    result = audit_track(track)
    assert result.status == status and result.flagged
    assert track == before and track.path.read_bytes() == b'original audio'
    assert len(result.peaks) <= 4096
    assert all(c.kind == 'memory' for c in result.saved)
    assert result.preview(track).options == Options(False, False)
    assert not result.preview(track).ready_to_apply


def test_no_memory_cues_skips_audio_detection(tmp_path, monkeypatch):
    track = sample_track(tmp_path)
    track.cues = track.cues[2:]
    monkeypatch.setattr('rekordbox_manager.cue_audit.analyse', lambda *a: pytest.fail('No memory points must not decode audio'))
    result = audit_track(track)
    assert result.status == 'No memory cues' and not result.flagged


def test_cache_invalidates_audio_cues_grid_and_tolerance(tmp_path):
    track = sample_track(tmp_path)
    original = audit_key(track, 50)
    assert audit_key(track, 20) != original
    track.cues.append(Cue(300, 'New'))
    assert audit_key(track, 50) != original
    track.cues.pop()
    track.grid.times[1] += .001
    assert audit_key(track, 50) != original
    track.grid.times[1] -= .001
    track.path.write_bytes(b'changed audio size')
    assert audit_key(track, 50) != original


def test_worker_cancellation_keeps_completed_results_and_cache(tmp_path, monkeypatch):
    track = sample_track(tmp_path)
    cache = OrderedDict()
    worker = CueAuditWorker([track, replace(track, id='second')], 50, cache)
    calls = []
    def check(t, tolerance):
        calls.append(t.id)
        return CueAuditResult('Cues match', tuple(t.cues))
    monkeypatch.setattr('rekordbox_manager.ui.audit_track', check)
    monkeypatch.setattr(worker, 'isInterruptionRequested', lambda: bool(calls))
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert list(results[0]) == ['t'] and calls == ['t']
    repeat = CueAuditWorker([track], 50, cache)
    repeat.run()
    assert repeat.cache_hits == 1 and calls == ['t']


def finish_check(window):
    for _ in range(500):
        QApplication.processEvents()
        if not window.analysis_busy:
            window.worker.wait(2000)
            return
        QTest.qWait(10)
    pytest.fail('Cue check did not finish')


def test_manager_check_includes_saved_cues_preserves_drafts_and_cannot_import(window, tmp_path, monkeypatch):
    library, writes = prepared_playlists(window, tmp_path, monkeypatch)
    before = dict(window.import_queue.entries)
    for t in window.tracks:
        t.cues = [Cue(100, 'Saved')]
    window.ignore_cued.setChecked(True)
    assert not window.tracks
    window.scan_mode.setCurrentIndex(1)
    assert len(window.tracks) == 2 and window.audit_mode()
    assert window.ignore_cued.isHidden() and window.replace_cues.isHidden()
    seen = []
    def check(t, tolerance):
        seen.append(t.id)
        return CueAuditResult('Cue differences' if len(seen) == 1 else 'Inconclusive', tuple(t.cues), (Cue(101, 'DROP 1'),), reason='Check timing', peaks=array('f', [.1, .9]), duration=t.duration, playable=True)
    monkeypatch.setattr('rekordbox_manager.ui.audit_track', check)
    window.start_analysis()
    finish_check(window)
    assert len(seen) == 2 and window.proposals == [] and window.selected() is None
    assert dict(window.import_queue.entries) == before and not writes
    assert not window.confirm_review_button.isEnabled() and not window.rebuild_button.isEnabled()
    assert window.play.isEnabled() and window.wave.comparison_cues
    window.apply_changes()
    assert not writes
    window.review_filter.setCurrentIndex(2)
    assert len(window.table.visible_rows()) == 1
    window.audit_tolerance.setValue(20)
    assert not window.audit_results and not window.wave.comparison_cues
    window.scan_mode.setCurrentIndex(0)
    assert window.ignore_cued.isChecked() and not window.tracks
    window.ignore_cued.setChecked(False)
    assert window.proposals and dict(window.import_queue.entries) == before


def test_check_filters_leave_uncued_and_cancelled_tracks_distinct(window, tmp_path, monkeypatch):
    prepared_playlists(window, tmp_path, monkeypatch)
    window.scan_mode.setCurrentIndex(1)
    track = window.tracks[0]
    window.audit_results = {track.id: CueAuditResult('No memory cues', ())}
    window.populate_table()
    window.review_filter.setCurrentIndex(4)
    assert window.table.visible_rows() == [0]
    window.review_filter.setCurrentIndex(6)
    assert window.table.visible_rows() == [1]
    assert not window.play.isEnabled() and not window.confirm_review_button.isEnabled()


def test_cache_reuses_prior_results_even_when_playlist_exceeds_cache_capacity(tmp_path, monkeypatch):
    track = sample_track(tmp_path)
    tracks = [replace(track, id=str(i)) for i in range(300)]
    cache = OrderedDict()
    calls = []
    def check(t, tolerance):
        calls.append(t.id)
        return CueAuditResult('Cues match', tuple(t.cues))
    monkeypatch.setattr('rekordbox_manager.ui.audit_track', check)
    first = CueAuditWorker(tracks, 50, cache)
    first.run()
    assert len(cache) == 256 and len(calls) == 300
    repeat = CueAuditWorker(tracks, 50, cache)
    repeat.run()
    assert repeat.cache_hits == 256 and len(calls) == 344 and len(cache) == 256


def test_import_queue_review_returns_to_preparation_mode(window, tmp_path, monkeypatch):
    prepared_playlists(window, tmp_path, monkeypatch)
    draft = window.import_queue.entries['0'].proposal
    window.scan_mode.setCurrentIndex(1)
    assert window.selected() is None
    window.review_queued_track('0')
    assert not window.audit_mode() and window.selected() is draft
    assert window.first.isEnabled() and window.rebuild_button.isEnabled()


def test_source_change_during_check_is_not_cached(tmp_path, monkeypatch):
    track = sample_track(tmp_path)
    cache = OrderedDict()
    worker = CueAuditWorker([track], 50, cache)
    def changed(t, tolerance):
        t.path.write_bytes(b'changed audio')
        return CueAuditResult('Cues match', tuple(t.cues))
    monkeypatch.setattr('rekordbox_manager.ui.audit_track', changed)
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results[0]['t'].status == 'Unavailable' and not cache


def correction_playlist(window, tmp_path, monkeypatch):
    from rekordbox_manager.cues import plan_cues
    track = sample_track(tmp_path)
    other = replace(deepcopy(track), id='other', title='Other track')
    library = SimpleNamespace(demo=True, writable=True, write_reason='', playlists={'p': 'Playlist'}, tracks=lambda key: [track, other])
    monkeypatch.setattr(window.player, 'setSource', lambda source: None)
    def analyse(t, options):
        cues, _ = plan_cues(t.grid, 100, 200, t.duration, t.cues, True, preserve_anchors=True)
        return Proposal(t, options, t.grid, cues, 100, 200, peaks=array('f', [.1, .9]*100), review_note='Detection uncertain: listen to both drops.')
    monkeypatch.setattr('rekordbox_manager.cue_audit.analyse', analyse)
    window.set_library(library)
    window.scan_mode.setCurrentIndex(1)
    checked = audit_track(track)
    window.audit_results = {track.id: checked}
    window.populate_table()
    window.table.selectRow(0)
    return track, checked


def test_check_exposes_editable_drop_navigation_and_both_cue_sets(window, tmp_path, monkeypatch):
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    assert not window.anchor_controls.isHidden()
    assert window.first.value() == 100 and window.second.value() == 200
    assert window.first.isEnabled() and window.second.isEnabled()
    window.focus_drop(2)
    assert window.wave.visible_range()[0] < 200 < window.wave.visible_range()[1]
    assert window.wave.cue_view == 'suggested'
    assert window.original_wave.cue_view == 'saved'
    assert window.original_wave.proposal.grid == track.grid
    assert window.wave.saved_cues == tuple(track.cues)
    assert window.wave.comparison_cues == checked.suggested
    assert not window.import_queue.entries


def test_replacement_edit_rebuild_confirm_queues_only_selected_track_without_writes(window, tmp_path, monkeypatch):
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    original = deepcopy(track)
    cached = deepcopy(checked.candidate)
    draft = window.selected()
    assert draft.options == Options(False, True, True)
    assert window.first.isEnabled() and window.second.isEnabled()
    assert not draft.ready_to_apply and not window.import_queue.entries
    window.first.setValue(110)
    assert draft.cues_dirty and not window.confirm_review_button.isEnabled()
    window.rebuild_cues()
    assert not draft.cues_dirty and window.confirm_review_button.isEnabled()
    assert not window.import_queue.entries
    assert window.wave.comparison_cues == tuple(c for c in draft.cues if c.kind == 'memory')
    window.confirm_review()
    assert set(window.import_queue.entries) == {'t'}
    assert window.import_queue.entries['t'].proposal is draft
    assert window.import_queue.entries['t'].sources == {'p': 'Playlist'}
    assert draft.ready_to_apply and draft.reviewed and not draft.options.fix_grid
    assert draft.grid == original.grid
    assert [c for c in draft.cues if c.kind != 'memory'] == [c for c in original.cues if c.kind != 'memory']
    assert track == original and track.path.read_bytes() == b'original audio'
    assert checked.candidate == cached  # Cache and original suggested timings are immutable.
    window.first.setValue(112)
    assert not window.import_queue.ready()  # Later edits cannot import stale accepted cues.
    assert not draft.reviewed


def test_replacement_rejects_changed_source_before_edit_and_before_queue(window, tmp_path, monkeypatch):
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    track.path.write_bytes(b'changed audio data')
    window.confirm_review()
    assert not window.import_queue.entries and 'changed since checking' in window.status.full_text
    with pytest.raises(ValueError, match='changed since checking'):
        checked.replacement(track)


def test_audit_draft_survives_track_selection_and_confirmed_queue_survives_mode_change(window, tmp_path, monkeypatch):
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    draft = window.selected()
    window.table.selectRow(1)
    assert window.selected() is None and not window.first.isEnabled()
    window.table.selectRow(0)
    assert window.selected() is draft and window.first.isEnabled()
    window.confirm_review()
    window.scan_mode.setCurrentIndex(0)
    assert window.import_queue.entries['t'].proposal is draft and draft.ready_to_apply
    assert not window.wave.comparison_active


def test_keep_originals_revokes_queued_replacement_and_can_be_reversed(window, tmp_path, monkeypatch):
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    original = deepcopy(track)
    draft = window.selected()
    assert window.confirm_review_button.text() == 'Replace cues'
    window.confirm_review_button.click()
    assert window.import_queue.ready()
    window.keep_original_button.click()
    assert not window.import_queue.entries and not draft.reviewed
    assert window.original_cues_kept(track.id)
    assert window.keep_original_button.text() == 'Original cues kept'
    assert not window.keep_original_button.isEnabled()
    assert window.confirm_review_button.isEnabled()
    assert '0 flagged' in window.review_summary.full_text
    assert track == original and track.path.read_bytes() == b'original audio'
    window.table.selectRow(1)
    window.table.selectRow(0)
    assert window.original_cues_kept(track.id) and not window.import_queue.entries
    window.confirm_review_button.click()
    assert not window.original_cues_kept(track.id)
    assert window.import_queue.ready()[0].proposal is draft
    assert window.keep_original_button.isEnabled()


def test_keep_originals_removes_prior_preparation_only_for_this_content_id(window, tmp_path, monkeypatch):
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    old = deepcopy(window.selected())
    other = replace(deepcopy(old), track=replace(deepcopy(track), id='other'))
    window.import_queue.capture(window.library, [old, other], {'p': ('Playlist', {'t', 'other'}), 'shared': ('Shared playlist', {'t'})})
    window.keep_original_cues()
    assert set(window.import_queue.entries) == {'other'}
    window.scan_mode.setCurrentIndex(0)
    assert set(window.import_queue.entries) == {'other'}
    window.scan_mode.setCurrentIndex(1)
    window.audit_results = {'t': checked}
    window.populate_table()
    window.table.selectRow(0)
    assert window.original_cues_kept('t')
    assert set(window.import_queue.entries) == {'other'}
    window.audit_results['t'] = replace(checked, source_key='changed source')
    window.update_details()
    assert not window.original_cues_kept('t')
    assert window.keep_original_button.isEnabled()


def test_keep_originals_resolves_flagged_filter_and_is_blocked_during_scan(window, tmp_path, monkeypatch):
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    window.set_busy(True)
    assert not window.keep_original_button.isEnabled()
    window.keep_original_cues()
    assert not window.audit_kept
    window.set_busy(False)
    window.review_filter.setCurrentIndex(1)
    window.keep_original_button.click()
    assert window.original_cues_kept(track.id)
    assert 0 not in window.table.visible_rows()
    window.review_filter.setCurrentIndex(0)
    window.table.selectRow(0)
    window.selected().applied = True
    window.update_details()
    assert not window.keep_original_button.isEnabled()


@pytest.mark.parametrize('size', [(1050, 720), (1280, 870)])
def test_manager_modes_keep_waveform_at_top_and_filters_in_playlist(window, tmp_path, monkeypatch, size):
    from PySide6.QtCore import QPoint
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    window.pages.setCurrentWidget(window.workspace)
    window.resize(*size)
    window.show()
    QApplication.processEvents()
    baseline = (window.deck_splitter.widget(0).mapTo(window, QPoint()).y(), window.first.x(), window.second.x(), window.first.width())
    for mode, results in ((0, {}), (1, {}), (1, {track.id: checked}), (0, {})):
        window.scan_mode.setCurrentIndex(mode)
        window.audit_results = results
        window.populate_table()
        window.select_track()
        QApplication.processEvents()
        assert window.size().width() == size[0]
        assert (window.deck_splitter.widget(0).mapTo(window, QPoint()).y(), window.first.x(), window.second.x(), window.first.width()) == baseline
        assert window.review_controls.isVisible()
        assert window.review_controls.parentWidget() is window.library_splitter.widget(1)
        assert window.review_controls.mapTo(window, QPoint()).y() > window.anchor_controls.mapTo(window, QPoint(0, window.anchor_controls.height())).y()
        assert window.review_controls.mapTo(window, QPoint(0, window.review_controls.height())).y() <= window.table.mapTo(window, QPoint()).y()


@pytest.mark.parametrize('original_status', ['Inconclusive', 'Cues match'])
def test_accepted_replacement_clears_highlight_and_edits_restore_it(window, tmp_path, monkeypatch, original_status):
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    checked.status = original_status
    window.populate_table()
    original = deepcopy(track)
    draft = window.selected()
    window.confirm_review()
    assert not window.table._buttons[0].property('needsReview')
    assert not window.audit_needs_review(track.id)
    assert '0 flagged' in window.review_summary.full_text and '1 queued' in window.review_summary.full_text
    assert window.import_queue.ready()[0].proposal is draft
    window.review_filter.setCurrentIndex(1)
    assert 0 not in window.table.visible_rows()
    window.review_filter.setCurrentIndex(0)
    window.table.selectRow(0)
    window.first.setValue(window.first.value() + 2)
    assert window.table._buttons[0].property('needsReview')
    assert window.audit_needs_review(track.id)
    assert '1 flagged' in window.review_summary.full_text and 'queued' not in window.review_summary.full_text
    assert not window.import_queue.ready()
    window.rebuild_cues()
    assert window.table._buttons[0].property('needsReview')
    window.review_filter.setCurrentIndex(1)
    assert 0 in window.table.visible_rows()
    window.confirm_review()
    assert 0 not in window.table.visible_rows()
    assert not window.table._buttons[0].property('needsReview')
    assert track == original


def test_near_duplicate_countdown_does_not_falsely_flag_matching_saved_cues(tmp_path, monkeypatch):
    from rekordbox_manager.cues import plan_cues
    track = sample_track(tmp_path)
    track.cues = [Cue(t, 'Saved') for t in (0, 32, 64, 96, 128, 160, 192, 224)]
    def suggest(copy, options):
        cues, _ = plan_cues(copy.grid, 64, 224.006, copy.duration, copy.cues, True, preserve_anchors=True)
        return Proposal(copy, options, copy.grid, cues, 64, 224.006, peaks=array('f', [.1, .7]))
    monkeypatch.setattr('rekordbox_manager.cue_audit.analyse', suggest)
    result = audit_track(track)
    assert result.status == 'Cues match' and not result.flagged
    assert len(result.suggested) == 8 and not result.missing and not result.extra


@pytest.mark.parametrize('issue,expected', [
    ('confidence', 'Cues match'), ('grid', 'Inconclusive'),
    ('dirty', 'Inconclusive'), ('missing_drop', 'Inconclusive'),
    ('different', 'Inconclusive'),
])
def test_matching_cues_are_separate_from_detection_confidence(tmp_path, monkeypatch, issue, expected):
    track = sample_track(tmp_path)
    def suggest(copy, options):
        return Proposal(copy, options, copy.grid,
                        [Cue(100.013 if issue != 'different' else 100.1, 'DROP 1'), Cue(200.001, 'DROP 2')],
                        100.013, None if issue == 'missing_drop' else 200.001,
                        peaks=array('f', [.1, .7]), review_note='Listen and check the suggested drop markers.',
                        grid_issue='Invalid grid' if issue == 'grid' else '', cues_dirty=issue == 'dirty')
    monkeypatch.setattr('rekordbox_manager.cue_audit.analyse', suggest)
    result = audit_track(track)
    assert result.status == expected
    assert result.flagged == (expected != 'Cues match')
    assert result.candidate.review_note and not result.candidate.reviewed
    assert not result.candidate.ready_to_apply


def test_browsing_matching_audit_does_not_change_status_or_flag_track(window, tmp_path, monkeypatch):
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    checked.status = 'Cues match'
    for row in (1, 0, 1, 0):
        window.table.selectRow(row)
        window.populate_table()
        assert 'Cues match' in window.table._buttons[0].accessibleName()
        assert 'Review replacement' not in window.table._buttons[0].accessibleName()
        assert not window.table._buttons[0].property('needsReview')
        assert not window.import_queue.entries
    window.first.setValue(110)
    assert 'Review replacement' in window.table._buttons[0].accessibleName()
    assert window.table._buttons[0].property('needsReview')


def multi_review_playlist(window, tmp_path, monkeypatch):
    from rekordbox_manager.analysis import confirm_proposal_review
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    window.tracks = [replace(deepcopy(track), id=str(i), title=f'Track {i}') for i in range(6)]
    window.audit_results = {}
    window.audit_drafts = {}
    for i, item in enumerate(window.tracks):
        result = deepcopy(checked)
        result.status = 'Cues match' if i == 1 else 'Cue differences' if i == 2 else 'Inconclusive'
        result.source_key = audit_key(item, result.tolerance_ms)
        result.candidate.track = deepcopy(item)
        window.audit_results[item.id] = result
    window.loaded_playlist_tracks = {'p': ('Playlist', frozenset(t.id for t in window.tracks))}
    window.audit_kept = {'3': window.audit_results['3'].source_key}
    queued = window.audit_results['4'].replacement(window.tracks[4])
    confirm_proposal_review(queued)
    window.audit_drafts['4'] = queued
    window.import_queue.capture(window.library, [queued], {'p': ('Playlist', frozenset(['4']))})
    window.populate_table()


@pytest.mark.parametrize('action', ['keep', 'replace'])
@pytest.mark.parametrize('filter_index', [0, 1, 2])
def test_audit_decisions_advance_skip_resolved_and_wrap(window, tmp_path, monkeypatch, action, filter_index):
    multi_review_playlist(window, tmp_path, monkeypatch)
    window.review_filter.setCurrentIndex(filter_index)
    window.table.selectRow(2)
    def resolve():
        (window.keep_original_button if action == 'keep' else window.confirm_review_button).click()
    for expected in (5, 0):
        previous = window.tracks[window.table.currentRow()].id
        resolve()
        assert not window.audit_needs_review(previous)
        assert window.table.currentRow() == expected
        assert window.wave.proposal.track.id == str(expected)
        assert window.first.value() == window.selected().first_drop
        assert window.second.value() == window.selected().second_drop
    resolve()
    assert not any(window.audit_needs_review(t.id) for t in window.tracks)
    assert 'No tracks left to review' in window.status.full_text
    assert window.table.currentRow() == (0 if filter_index == 0 else -1)
    assert set(window.import_queue.entries) == ({'4'} if action == 'keep' else {'0', '2', '4', '5'})


def test_failed_replacement_does_not_advance(window, tmp_path, monkeypatch):
    multi_review_playlist(window, tmp_path, monkeypatch)
    window.table.selectRow(2)
    window.selected().cues_dirty = True
    window.confirm_review()
    assert window.table.currentRow() == 2 and window.wave.proposal.track.id == '2'
    assert '2' not in window.import_queue.entries


@pytest.mark.parametrize('status', [None, 'No memory cues', 'Unavailable', 'Inconclusive'])
def test_second_waveform_only_shown_when_suggestions_exist(window, tmp_path, monkeypatch, status):
    track, checked = correction_playlist(window, tmp_path, monkeypatch)
    assert not window.original_wave_box.isHidden() and not window.proposed_wave_label.isHidden()
    other = window.tracks[1]
    if status:
        window.audit_results[other.id] = CueAuditResult(status, tuple(other.cues), duration=other.duration)
    window.table.selectRow(1)
    assert window.original_wave_box.isHidden() and window.proposed_wave_label.isHidden()
    assert window.original_wave.proposal is None
    assert window.wave.proposal.track.id == other.id
    assert window.wave.cue_view == 'saved' and window.wave.saved_cues == tuple(other.cues)
    assert window.wave.minimumHeight() == 150
    window.table.selectRow(0)
    assert not window.original_wave_box.isHidden() and not window.proposed_wave_label.isHidden()
    assert window.wave.cue_view == 'suggested' and window.wave.comparison_cues == checked.suggested
    assert window.original_wave.proposal.track.id == track.id
    assert window.wave.minimumHeight() == 115
    window.clear_audit_results()
    assert window.original_wave_box.isHidden() and window.proposed_wave_label.isHidden()
    assert window.wave.cue_view == 'saved'
    window.clear_track_preview()
    assert window.original_wave_box.isHidden() and not window.wave.comparison_cues
