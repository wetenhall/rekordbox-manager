"""Fail packaging if any embedded Mach-O requires a newer OS than Monterey."""
from pathlib import Path
from macholib.MachO import MachO
import sys


def audit(root: Path):
    seen, failures, versions = set(), [], {}
    for path in root.rglob('*'):
        if not path.is_file() or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        with path.open('rb') as file:
            magic = file.read(4)
        if magic not in (b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xfe\xed\xfa\xcf'):
            continue
        for header in MachO(str(path)).headers:
            for command, body, data in header.commands:
                if command.cmd not in (0x32, 0x24):
                    continue
                value = getattr(body, 'minos', getattr(body, 'version', 0))
                version = (value >> 16, (value >> 8) & 255, value & 255)
                versions[version] = versions.get(version, 0) + 1
                if version > (12, 0, 0):
                    failures.append(f'{path.relative_to(root)} requires {version}')
    if failures:
        raise RuntimeError('Monterey compatibility audit failed:\n' + '\n'.join(failures))
    print('Embedded minimum macOS versions:', versions)


if __name__ == '__main__':
    audit(Path(sys.argv[1]))
