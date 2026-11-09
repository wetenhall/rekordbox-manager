"""Build on the target OS/architecture; run with that environment's Python."""
from pathlib import Path
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys


root = Path(__file__).resolve().parents[1]
notices = root / "build" / "third-party-notices"
notices.mkdir(parents=True, exist_ok=True)
packages = []
for distribution in importlib.metadata.distributions():
    name = distribution.metadata.get("Name", "unknown")
    packages.append({"name": name, "version": distribution.version,
                     "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License", "See package licence")})
    for file in distribution.files or []:
        if any(word in file.name.lower() for word in ("license", "licence", "copying", "notice")):
            source = Path(distribution.locate_file(file))
            if source.is_file() and source.suffix not in {".py", ".pyc", ".so", ".dylib"}:
                target = notices / name / str(file).replace("../", "")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
(notices / "packages.json").write_text(json.dumps(packages, indent=2), encoding="utf-8")
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                str(root / "Rekordbox Manager.spec")], cwd=root, check=True)
if sys.platform == 'darwin':
    subprocess.run([sys.executable, str(root / 'scripts/audit_macos.py'),
                    str(root / 'dist/Rekordbox Manager.app')], check=True)
print("Built", platform.system(), platform.machine(), "preview in", root / "dist")
