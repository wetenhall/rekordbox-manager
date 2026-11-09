import json
from pathlib import Path
import pytest

from rekordbox_manager.backups import BackupStore, digest, durable_json
from rekordbox_manager.guards import SafetyError


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "db").write_text("old-db")
    (root / "grid").write_text("old-grid")
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "db").write_text("new-db")
    (staged / "grid").write_text("new-grid")
    store = BackupStore(tmp_path / "backups")
    expected = {p.name: digest(p) for p in root.iterdir()}
    return root, staged, store, expected


def install(setup, validator=lambda: None):
    root, staged, store, expected = setup
    return store.install(root, {"db": staged / "db", "grid": staged / "grid"}, expected,
                         lambda: None, validator, "Test")


def test_apply_and_restore_roundtrip(setup):
    root, _, store, _ = setup
    backup = install(setup)
    assert (root / "db").read_text() == "new-db"
    assert store.validate(backup, root)["state"] == "applied"
    store.restore(backup, root, lambda: None, {"db", "grid"})
    assert (root / "db").read_text() == "old-db"
    assert (root / "grid").read_text() == "old-grid"


def test_failed_validation_rolls_back_all_files(setup):
    root, _, store, _ = setup
    def fail():
        raise RuntimeError("Validation failed")
    with pytest.raises(RuntimeError):
        install(setup, fail)
    assert (root / "db").read_text() == "old-db"
    assert (root / "grid").read_text() == "old-grid"
    assert store.list()[0][1]["state"] == "rolled_back"


def test_stale_source_refuses_all_changes(setup):
    root, _, store, _ = setup
    (root / "grid").write_text("external-edit")
    with pytest.raises(SafetyError, match="changed"):
        install(setup)
    assert (root / "db").read_text() == "old-db"
    assert (root / "grid").read_text() == "external-edit"


def test_corrupt_backup_refuses_restore(setup):
    root, _, store, _ = setup
    backup = install(setup)
    (backup / "files/grid").write_text("corrupt")
    with pytest.raises(SafetyError, match="verification"):
        store.restore(backup, root, lambda: None, {"db", "grid"})
    assert (root / "db").read_text() == "new-db"


def test_restore_blocks_newer_edits(setup):
    root, _, store, _ = setup
    backup = install(setup)
    (root / "grid").write_text("edited-again")
    with pytest.raises(SafetyError, match="newer changes"):
        store.restore(backup, root, lambda: None, {"db", "grid"})
    assert (root / "grid").read_text() == "edited-again"


def test_restore_wrong_library_blocked(setup, tmp_path):
    _, _, store, _ = setup
    backup = install(setup)
    with pytest.raises(SafetyError, match="different library"):
        store.validate(backup, tmp_path)


def test_manifest_path_traversal_blocked(setup):
    root, _, store, _ = setup
    backup = install(setup)
    record = store.validate(backup, root)
    record["files"][0]["path"] = "../outside"
    durable_json(backup / "manifest.json", record)
    with pytest.raises(SafetyError, match="Invalid backup path"):
        store.restore(backup, root, lambda: None, {"db", "grid"})


def test_no_space_prevents_changes(setup, monkeypatch):
    import shutil
    from collections import namedtuple
    usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(1, 1, 0))
    with pytest.raises(SafetyError, match="space"):
        install(setup)
    assert (setup[0] / "db").read_text() == "old-db"


def test_failure_mid_install_restores_both_files(setup, monkeypatch):
    import rekordbox_manager.backups as module
    original = module.replace_file
    calls = 0
    def fail_once(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("Disk write failure")
        original(source, target)
    monkeypatch.setattr(module, "replace_file", fail_once)
    with pytest.raises(OSError):
        install(setup)
    assert (setup[0] / "db").read_text() == "old-db"
    assert (setup[0] / "grid").read_text() == "old-grid"


def test_external_edit_after_backup_is_not_rolled_back(setup, monkeypatch):
    root, _, store, _ = setup
    original = store.create
    def intervene(*args):
        result = original(*args)
        (root / "grid").write_text("external-edit")
        return result
    monkeypatch.setattr(store, "create", intervene)
    with pytest.raises(SafetyError, match="changed after backup"):
        install(setup)
    assert (root / "db").read_text() == "old-db"
    assert (root / "grid").read_text() == "external-edit"


def test_interrupted_operation_blocks_new_apply(setup):
    root, _, store, _ = setup
    backup = store.create(root, [root / "db"], "Interrupted")
    record = store.validate(backup, root)
    record["state"] = "applying"
    durable_json(backup / "manifest.json", record)
    with pytest.raises(SafetyError, match="interrupted"):
        install(setup)


def test_file_outside_adapter_allowlist_cannot_be_restored(setup):
    root, _, store, _ = setup
    backup = install(setup)
    with pytest.raises(SafetyError, match="cannot restore"):
        store.restore(backup, root, lambda: None, {"db"})


def test_simulated_process_death_can_restore_partial_install(setup, monkeypatch):
    import rekordbox_manager.backups as module
    original = module.replace_file
    calls = 0
    class ProcessDeath(BaseException):
        pass
    def die_on_second_file(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ProcessDeath()
        original(source, target)
    monkeypatch.setattr(module, 'replace_file', die_on_second_file)
    with pytest.raises(ProcessDeath):
        install(setup)
    root, _, store, _ = setup
    backup, record = store.list()[0]
    assert record['state'] == 'applying'
    assert (root / 'db').read_text() == 'new-db'
    assert (root / 'grid').read_text() == 'old-grid'
    monkeypatch.setattr(module, 'replace_file', original)
    store.restore(backup, root, lambda: None, {'db','grid'})
    assert (root / 'db').read_text() == 'old-db'
    assert (root / 'grid').read_text() == 'old-grid'
