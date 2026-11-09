"""Publish verified CI packages as a preview release; never replace a published release."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import tomllib


def main():
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
    tag = f'v{version}'
    ref = os.environ.get('GITHUB_REF', '')
    if ref.startswith('refs/tags/') and ref != f'refs/tags/{tag}':
        raise RuntimeError('Tag must match the version in pyproject.toml.')
    artifacts = Path(sys.argv[1])
    archives = []
    checksums = []
    for target in ('Windows-x64', 'macOS-Intel', 'macOS-Apple-Silicon'):
        name = f'Rekordbox-Manager-{version}-{target}.zip'
        matches = list(artifacts.rglob(name))
        if len(matches) != 1:
            raise RuntimeError(f'Expected exactly one verified package: {name}')
        archive = matches[0]
        with archive.open('rb') as file:
            digest = hashlib.file_digest(file, 'sha256').hexdigest()
        line = f'{digest}  {name}\n'
        if archive.with_suffix('.zip.sha256').read_text() != line:
            raise RuntimeError(f'Checksum mismatch: {name}')
        archives.append(str(archive))
        checksums.append(line)
    checksum_file = artifacts / 'SHA256SUMS.txt'
    checksum_file.write_text(''.join(checksums))
    repo = os.environ['GITHUB_REPOSITORY']
    commit = os.environ['GITHUB_SHA']
    notes = root / 'docs' / 'releases' / f'{tag}.md'
    if not notes.is_file():
        raise RuntimeError(f'Write release notes first: {notes}')
    subprocess.run(['gh', 'release', 'create', tag, '--repo', repo, '--target', commit,
                    '--draft', '--prerelease', '--title', f'Rekordbox Manager {version} Preview',
                    '--notes-file', str(notes), *archives, str(checksum_file)], check=True)
    # Uploads have all succeeded. Make the complete release public.
    subprocess.run(['gh', 'release', 'edit', tag, '--repo', repo, '--draft=false'], check=True)


if __name__ == '__main__':
    main()
