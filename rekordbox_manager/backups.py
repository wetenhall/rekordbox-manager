"""Verified file snapshots and recoverable multi-file installation.

There is deliberately no claim of atomicity across separate files. A durable
journal is written BEFORE replacement; interrupted operations require recovery.
Rekordbox memory-cue imports use this engine to install a verified database copy.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import psutil
from datetime import datetime
from uuid import uuid4
from contextlib import contextmanager

from .guards import SafetyError


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def durable_json(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)
    sync_directory(path.parent)


def sync_directory(path: Path) -> None:
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def contained(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise SafetyError("Invalid backup path.")
    result = root / rel
    if not result.resolve().is_relative_to(root.resolve()):
        raise SafetyError("Backup path escapes its library.")
    # Reject symlinks even when they happen to point inside the library.
    if any(p.is_symlink() for p in [result, *result.parents] if p != root.parent):
        raise SafetyError("Symlinked backup or library files are not supported.")
    return result


def replace_file(source: Path, target: Path) -> None:
    temp = target.with_name(target.name + ".manager-" + uuid4().hex)
    try:
        shutil.copy2(source, temp)
        # Windows _commit (os.fsync) requires a writable file handle.
        with temp.open("r+b" if os.name == "nt" else "rb") as f:
            os.fsync(f.fileno())
        os.replace(temp, target)
        sync_directory(target.parent)
    finally:
        temp.unlink(missing_ok=True)


class BackupStore:
    def __init__(self, directory: Path):
        self.directory = directory.expanduser().resolve()

    @contextmanager
    def lock(self, root: Path):
        lock = root / ".rekordbox-manager.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise SafetyError("Another operation or interrupted session holds the library lock. Use Recover interrupted session in Backups.") from exc
        try:
            os.write(fd, str(os.getpid()).encode())
            os.fsync(fd)
            yield
        finally:
            os.close(fd)
            lock.unlink(missing_ok=True)

    def create(self, root: Path, paths: list[Path], description: str) -> Path:
        root = root.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        paths = list(dict.fromkeys(paths))
        if not paths:
            raise SafetyError("Cannot create an empty backup.")
        need = sum(p.stat().st_size for p in paths)
        if shutil.disk_usage(self.directory).free < need + 32 * 1024 * 1024:
            raise SafetyError("Not enough space for a verified backup. Nothing changed.")
        name = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S") + "_" + uuid4().hex[:8]
        folder = self.directory / name
        folder.mkdir(mode=0o700)
        record = {"format": 1, "root": str(root), "created": datetime.now().astimezone().isoformat(),
                  "description": description, "state": "copying", "files": []}
        durable_json(folder / "manifest.json", record)
        for path in paths:
            relative = str(path.relative_to(root))
            source = contained(root, relative)
            before = digest(source)
            dest = contained(folder / "files", relative)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            with dest.open("r+b" if os.name == "nt" else "rb") as f:
                os.fsync(f.fileno())
            if digest(dest) != before or digest(source) != before:
                raise SafetyError("A source file changed during backup. Nothing may be applied.")
            record["files"].append({"path": relative, "sha256": before, "bytes": source.stat().st_size})
        # Recheck the entire set, not just each file as it was copied.
        for entry in record["files"]:
            if digest(contained(root, entry["path"])) != entry["sha256"]:
                raise SafetyError("Library changed while backup was being created.")
        record["state"] = "verified"
        durable_json(folder / "manifest.json", record)
        return folder

    def validate(self, folder: Path, root: Path) -> dict:
        folder = folder.resolve()
        if not folder.is_relative_to(self.directory):
            raise SafetyError("Backup is outside the selected backup location.")
        record = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if record.get("format") != 1 or record.get("root") != str(root.resolve()):
            raise SafetyError("This backup belongs to a different library.")
        if record.get("state") == "copying" or not record.get("files"):
            raise SafetyError("Backup did not finish successfully.")
        seen = set()
        for entry in record["files"]:
            if entry["path"] in seen:
                raise SafetyError("Duplicate entry in backup manifest.")
            seen.add(entry["path"])
            contained(root, entry["path"])
            p = contained(folder / "files", entry["path"])
            if digest(p) != entry["sha256"]:
                raise SafetyError("Backup verification failed; no files have been restored.")
        return record

    def install(self, root: Path, replacements: dict[str, Path], expected: dict[str, str],
                guard, validate_result, description: str) -> Path:
        root = root.resolve()
        with self.lock(root):
            guard()
            for _, previous in self.list():
                if previous.get("root") == str(root) and previous.get("state") in {"applying", "restoring"}:
                    raise SafetyError("An interrupted operation needs restoration before another apply.")
            for relative, sha in expected.items():
                if digest(contained(root, relative)) != sha:
                    raise SafetyError("Library changed since it was loaded. Reload and analyse again.")
            if not replacements or not set(replacements).issubset(expected):
                raise SafetyError("Every replacement must have a recorded original fingerprint.")
            backup = self.create(root, [contained(root, p) for p in replacements], description)
            record = self.validate(backup, root)
            record["after"] = {p: digest(source) for p, source in replacements.items()}
            record["state"] = "applying"
            durable_json(backup / "manifest.json", record)
            started = False
            try:
                guard()
                for relative, sha in expected.items():
                    if digest(contained(root, relative)) != sha:
                        raise SafetyError("Library changed after backup; apply was cancelled.")
                # All files are already staged and validated before this point.
                for relative, staged in replacements.items():
                    started = True
                    replace_file(staged, contained(root, relative))
                validate_result()
                record["state"] = "applied"
                durable_json(backup / "manifest.json", record)
            except Exception:
                if not started:
                    record["state"] = "cancelled"
                    durable_json(backup / "manifest.json", record)
                    raise
                # Restore only while exclusive access can still be established.
                guard()
                for entry in record["files"]:
                    replace_file(contained(backup / "files", entry["path"]), contained(root, entry["path"]))
                record["state"] = "rolled_back"
                durable_json(backup / "manifest.json", record)
                raise
            return backup

    def release_stale_lock(self, root: Path) -> None:
        lock = root / ".rekordbox-manager.lock"
        if not lock.exists():
            return
        try:
            pid = int(lock.read_text())
        except (ValueError, OSError) as exc:
            raise SafetyError("Cannot identify the lock owner. Recovery requires manual inspection.") from exc
        if psutil.pid_exists(pid):
            raise SafetyError("The operation's process is still running. Close the other Manager instance first.")
        lock.unlink()

    def restore(self, folder: Path, root: Path, guard, allowed: set[str]) -> None:
        with self.lock(root):
            guard()
            record = self.validate(folder, root)
            if not {e["path"] for e in record["files"]}.issubset(allowed):
                raise SafetyError("Backup includes files that this library adapter cannot restore.")
            after = record.get("after", {})
            for entry in record["files"]:
                current = digest(contained(root, entry["path"]))
                if current not in {entry["sha256"], after.get(entry["path"])}:
                    raise SafetyError("Library has newer changes. Restore is blocked to avoid overwriting them.")
            record["state"] = "restoring"
            durable_json(folder / "manifest.json", record)
            for entry in record["files"]:
                replace_file(contained(folder / "files", entry["path"]), contained(root, entry["path"]))
            for entry in record["files"]:
                if digest(contained(root, entry["path"])) != entry["sha256"]:
                    raise SafetyError("Restore verification failed. Keep Rekordbox closed.")
            record["state"] = "restored"
            durable_json(folder / "manifest.json", record)

    def list(self) -> list[tuple[Path, dict]]:
        result = []
        if self.directory.exists():
            for path in sorted(self.directory.glob("*/manifest.json"), reverse=True):
                try:
                    result.append((path.parent, json.loads(path.read_text(encoding="utf-8"))))
                except (ValueError, OSError):
                    continue
        return result
