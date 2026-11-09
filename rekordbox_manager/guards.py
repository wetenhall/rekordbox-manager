from pathlib import Path
import psutil


class SafetyError(RuntimeError):
    pass


def ensure_rekordbox_closed() -> None:
    found = []
    for process in psutil.process_iter(["name"]):
        try:
            name = (process.info["name"] or "").lower()
            # Do not match this app, whose executable is "Rekordbox Manager".
            if name in {"rekordbox", "rekordbox.exe", "rekordboxagent", "rekordboxagent.exe"}:
                found.append(process.info["name"])
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise SafetyError("Cannot verify running processes. No library changes allowed.") from exc
    if found:
        raise SafetyError("Fully quit Rekordbox and rekordboxAgent first: " + ", ".join(sorted(set(found))))


def ensure_clean_database(path: Path) -> None:
    ensure_rekordbox_closed()
    for suffix in ("-wal", "-journal"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise SafetyError("The database still has pending journal data. Open Rekordbox and quit it cleanly before continuing. Do not delete journal files.")
