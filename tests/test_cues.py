import pytest
from rekordbox_manager.models import Grid, Cue
from rekordbox_manager.cues import plan_cues


def grid(bars=256):
    return Grid([i * .5 for i in range(bars * 4)], [i % 4 + 1 for i in range(bars * 4)])


def test_64_bar_intro_and_second_countdown_use_ten():
    cues, warnings = plan_cues(grid(), 128, 384, 512, [], False)
    assert [c.time for c in cues] == [0, 32, 64, 96, 128, 256, 288, 320, 352, 384]
    assert not warnings


@pytest.mark.parametrize("intro,expected_second", [(32, 96), (48, 80), (64, 64)])
def test_spare_slots_extend_second_countdown(intro, expected_second):
    cues, _ = plan_cues(grid(), intro * 2, 384, 512, [], False)
    assert len(cues) == 10
    second = [c for c in cues if "DROP 2" in c.label]
    assert second[0].label == f"DROP 2 −{expected_second}"


def test_variable_grid_counts_beats_instead_of_seconds():
    g = grid()
    g.times = [i * .5 if i < 512 else 256 + (i - 512) * .4 for i in range(1024)]
    cues, _ = plan_cues(g, g.times[256], g.times[768], 500, [], False)
    assert [c.time for c in cues if "DROP 2" in c.label] == [g.times[i] for i in (512, 576, 640, 704, 768)]


def test_hot_cues_and_loops_preserved_on_replace():
    existing = [Cue(2, "Hot A", "hot"), Cue(10, "Loop", "memory_loop", 18), Cue(20, "Old")]
    cues, _ = plan_cues(grid(), 128, 384, 512, existing, True)
    assert existing[0] in cues and existing[1] in cues and existing[2] not in cues
    assert sum(c.kind.startswith("memory") for c in cues) == 10


def test_keep_existing_never_removes_points():
    existing = [Cue(5, "Keep me"), Cue(7, "Keep me too")]
    cues, _ = plan_cues(grid(), 128, 384, 512, existing, False)
    assert all(c in cues for c in existing)
    assert len(cues) == 10


def test_preserved_anchor_does_not_duplicate():
    existing = [Cue(128, "User drop")]
    cues, _ = plan_cues(grid(), 128, 384, 512, existing, False)
    assert sum(c.time == 128 for c in cues) == 1


def test_no_room_for_anchors_is_blocked():
    with pytest.raises(ValueError, match="free memory slots"):
        plan_cues(grid(), 128, 384, 512, [Cue(i, str(i)) for i in range(10)], False)


def test_partial_intro_does_not_force_time_zero():
    cues, warnings = plan_cues(grid(), 130, 384, 512, [], False)
    assert min(c.time for c in cues) == 2
    assert any("outside" in w for w in warnings)


def test_second_countdown_never_crosses_first_drop():
    cues, warnings = plan_cues(grid(), 128, 160, 512, [], False)
    assert all(c.time > 128 for c in cues if "DROP 2" in c.label)
    assert any("48 bars" in w for w in warnings)


def test_long_intro_reports_capacity_limit():
    cues, warnings = plan_cues(grid(400), 256, 640, 800, [], False)
    assert len(cues) == 10
    assert any("earliest intro" in w for w in warnings)


@pytest.mark.parametrize("first,second", [(200, 100), (100, 100), (-1, 100), (100, 600), (float('nan'), 100)])
def test_invalid_anchors_refused(first, second):
    with pytest.raises(ValueError):
        plan_cues(grid(), first, second, 512, [], False)


def test_discontinuous_grid_refused():
    g = grid()
    g.positions[50] = 1
    with pytest.raises(ValueError, match="discontinuity"):
        plan_cues(g, 128, 384, 512, [], False)


def test_manual_anchors_are_preserved_with_64_beat_countdowns():
    cues, warnings = plan_cues(grid(),128.125,384.25,512,[],False,preserve_anchors=True)
    assert [c.time for c in cues if c.label.startswith('DROP 1')] == [0.125,32.125,64.125,96.125,128.125]
    assert [c.time for c in cues if c.label.startswith('DROP 2')] == [256.25,288.25,320.25,352.25,384.25]
    assert any('not on a grid bar start' in w for w in warnings)


def test_manual_countdown_preserves_fractional_beat_on_variable_grid():
    g=grid()
    g.times=[i*.5 if i<700 else 350+(i-700)*.4 for i in range(1024)]
    cues,_=plan_cues(g,128.125,377.4,512,[],False,preserve_anchors=True)
    second={c.label:c.time for c in cues if c.label.startswith('DROP 2')}
    assert second['DROP 2']==377.4
    assert second['DROP 2 −16']==pytest.approx(351.8)
    assert second['DROP 2 −32']==pytest.approx(320.25)


def test_manual_anchors_outside_grid_extent_stay_in_audio():
    g=Grid([.1+i*.5 for i in range(1024)],[i%4+1 for i in range(1024)])
    cues,_=plan_cues(g,0,511.9,512,[],False,preserve_anchors=True)
    assert any(c.time==0 and c.label=='DROP 1' for c in cues)
    assert any(c.time==511.9 and c.label=='DROP 2' for c in cues)
    assert all(0<=c.time<512 for c in cues)
