import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("REKORDBOX_MANAGER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Rekordbox Manager"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Rekordbox Manager"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "rekordbox-manager"


def discover_databases() -> list[Path]:
    bases = [Path.home() / "Library", Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))]
    candidates = [base / vendor / "rekordbox/master.db" for base in bases
                  for vendor in ("Pioneer", "Pioneer DJ", "AlphaTheta")]
    return [p for p in candidates if p.is_file()]
