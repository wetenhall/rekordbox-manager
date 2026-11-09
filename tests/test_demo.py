from dataclasses import asdict
from pathlib import Path
import pytest

from rekordbox_manager.demo import create_demo, DemoLibrary
from rekordbox_manager.models import Options, Proposal
from rekordbox_manager.cues import plan_cues
from rekordbox_manager.backups import BackupStore, digest
from rekordbox_manager.guards import SafetyError


def test_full_demo_apply_and_restore(tmp_path):
    library = DemoLibrary(create_demo(tmp_path / "Demo"))
    backups = BackupStore(tmp_path / "Backups")
    track = library.tracks('house')[0]
    originals = library.fingerprints.copy()
    audio_hash = digest(track.path)
    first, second = track.grid.times[48*4], track.grid.times[144*4]
    cues, _ = plan_cues(track.grid, first, second, track.duration, track.cues, False)
    p = Proposal(track, Options(False, True), track.grid, cues, first, second, reviewed=True)
    backup = library.apply([p], backups)
    changed = library.tracks('house')[0]
    assert sum(c.kind == 'memory' for c in changed.cues) == 10
    assert track.cues[0] in changed.cues
    assert changed.grid == track.grid
    assert digest(track.path) == audio_hash
    assert library.fingerprints['analysis/dnb.json'] == originals['analysis/dnb.json']
    backups.restore(backup, library.root, lambda: None, set(library.fingerprints))
    library.reload()
    assert library.fingerprints == originals


def test_unreviewed_proposal_cannot_apply(tmp_path):
    library = DemoLibrary(create_demo(tmp_path / "Demo"))
    track = library.tracks('house')[0]
    p = Proposal(track, Options(False,True), track.grid, [])
    with pytest.raises(SafetyError, match='reviewed'):
        library.apply([p], BackupStore(tmp_path / 'Backups'))
