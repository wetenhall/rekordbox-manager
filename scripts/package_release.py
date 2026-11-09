"""Smoke-test the frozen app, then archive it for GitHub Releases.

Run on the target OS after scripts/build.py. No personal library is used.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tomllib


def main():
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
    if sys.platform == 'darwin':
        target = 'macOS-Apple-Silicon' if platform.machine() == 'arm64' else 'macOS-Intel'
        bundle = root / 'dist/Rekordbox Manager.app'
        executable = bundle / 'Contents/MacOS/Rekordbox Manager'
    elif sys.platform == 'win32' and platform.machine().lower() in ('amd64', 'x86_64'):
        target = 'Windows-x64'
        bundle = root / 'dist/Rekordbox Manager'
        executable = bundle / 'Rekordbox Manager.exe'
    else:
        raise RuntimeError('Release packaging supports macOS and Windows x64 only.')

    output = root / 'build' / f'smoke-{target}'
    output.mkdir(parents=True, exist_ok=True)
    report = output / 'selftest.json'
    report.unlink(missing_ok=True)
    # The offscreen Windows plugin does not load system fonts. Exercise the
    # shipped native plugin there so screenshot QA verifies readable text too.
    env = dict(os.environ, QT_QPA_PLATFORM='windows' if sys.platform == 'win32' else 'offscreen')
    completed = subprocess.run([str(executable), '--self-test', '--output-dir', str(output)],
                               env=env, timeout=300)
    if completed.returncode:
        error = output / 'selftest-error.txt'
        if error.is_file():
            print(error.read_text(encoding='utf-8'))
        completed.check_returncode()
    result = json.loads(report.read_text())
    if result.get('passed') is not True:
        raise RuntimeError('Packaged-app self-test did not pass.')
    release = root / 'dist' / 'release'
    release.mkdir(parents=True, exist_ok=True)
    archive = release / f'Rekordbox-Manager-{version}-{target}.zip'
    archive.unlink(missing_ok=True)
    if sys.platform == 'darwin':
        # Preserve executable permissions and framework symlinks.
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                        str(bundle), str(archive)], check=True)
    else:
        shutil.make_archive(str(archive.with_suffix('')), 'zip', bundle.parent, bundle.name)
    with archive.open('rb') as file:
        checksum = hashlib.file_digest(file, 'sha256').hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {archive.name}\n')
    print(f'Release package verified: {archive}')


if __name__ == '__main__':
    main()
