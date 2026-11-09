# Build this spec with the Python interpreter for the target architecture.
import sys
import platform
import tomllib
from pathlib import Path

root = Path(SPECPATH)
version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
datas = [(str(root / 'build/third-party-notices'), 'third-party-notices'),
         (str(root / 'README.md'), '.'),
         (str(root / 'rekordbox_manager/assets/icon.png'), 'rekordbox_manager/assets'),
         (str(root / 'rekordbox_manager/assets/check.svg'), 'rekordbox_manager/assets')]
a = Analysis(
    ['run.py'], pathex=[str(root)], binaries=[], datas=datas,
    hiddenimports=['sqlcipher3.dbapi2', 'pyrekordbox.masterdb.database'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtQml', 'PySide6.QtQuick', 'matplotlib', 'tkinter', 'IPython'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Rekordbox Manager',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, target_arch=platform.machine() if sys.platform == 'darwin' else None,
          icon=str(root / 'rekordbox_manager/assets/icon.ico') if sys.platform == 'win32' else None,
          codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Rekordbox Manager')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='Rekordbox Manager.app',
                 icon=str(root / 'rekordbox_manager/assets/icon.icns'),
                 bundle_identifier='local.rekordboxmanager.preview',
                 info_plist={'CFBundleShortVersionString': version,
                             'CFBundleVersion': version,
                             'LSMinimumSystemVersion': '12.3' if platform.machine() == 'arm64' else '12.0',
                             'NSHighResolutionCapable': True})
