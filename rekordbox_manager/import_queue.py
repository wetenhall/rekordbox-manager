"""Session preparation queue, keyed by Rekordbox content ID, never playlist order."""
from dataclasses import dataclass, replace
from copy import deepcopy
from pathlib import Path

from .backups import digest
from .guards import SafetyError, ensure_rekordbox_closed
from .models import Proposal


def import_snapshot(proposal):
    """Freeze import fields without duplicating decoded waveform caches."""
    return replace(proposal, track=deepcopy(proposal.track), grid=deepcopy(proposal.grid),
                   cues=proposal.cues.copy(), peaks=[], attacks=[], waveform_data=None,
                   warnings=[], drop_notes=[])


@dataclass
class QueuedTrack:
    proposal: Proposal
    sources: dict[str, str]
    audio_path: Path
    audio_stamp: tuple[int, int] | None
    analysis_hashes: dict[Path, str]


class ImportQueue:
    def __init__(self):
        self.library = None
        self.fingerprint = None
        self.entries: dict[str, QueuedTrack] = {}
        self.origins: dict[str, dict[str, str]] = {}

    def reset(self, library=None):
        self.library = library
        self.fingerprint = getattr(library, 'fingerprint', None)
        self.entries.clear()
        self.origins.clear()

    def capture(self, library, proposals, membership):
        if self.library is None:
            self.reset(library)
        if self.library is not library:
            raise SafetyError('The import queue belongs to another library. Reconnect before preparing tracks.')
        identities = [p.track.id for p in proposals]
        allowed = set().union(*(ids for _, ids in membership.values()))
        if not membership or set(identities) != allowed or len(identities) != len(set(identities)):
            raise SafetyError('Prepared tracks do not match their scanned playlists.')
        for p in proposals:
            identity = p.track.id
            sources = self.origins.setdefault(identity, {})
            sources.update({key: name for key, (name, ids) in membership.items() if identity in ids})
            old = self.entries.get(identity)
            if old and old.proposal is p:
                old.sources = sources.copy()
                continue
            # Capture preparation-time evidence. Later browsing must not silently
            # replace these baselines with newer audio or analysis files.
            path = p.track.path
            stamp = getattr(library, 'audio_stamps', {}).get(str(path))
            if stamp is None and path.is_file():
                stat = path.stat()
                stamp = (stat.st_size, stat.st_mtime_ns)
            hashes = {}
            for analysis_path in p.track.analysis_paths:
                root = getattr(library, 'root', None)
                expected = (getattr(library, 'fingerprints', {}).get(str(analysis_path.relative_to(root)))
                            if root and analysis_path.is_relative_to(root) else None)
                if expected is not None:
                    hashes[analysis_path] = expected
                elif analysis_path.is_file():
                    hashes[analysis_path] = digest(analysis_path)
            self.entries[identity] = QueuedTrack(p, sources.copy(), path, stamp, hashes)

    def forget(self, identities):
        for identity in identities:
            self.entries.pop(identity, None)

    def pending(self):
        return [entry for entry in self.entries.values() if not entry.proposal.applied]

    def ready(self):
        return [entry for entry in self.entries.values() if entry.proposal.ready_to_apply]

    def breakdown(self):
        playlists = {}
        for entry in self.pending():
            for key, name in entry.sources.items():
                row = playlists.setdefault(key, [name, 0, 0, 0, 0])
                row[1] += 1
                row[2 if entry.proposal.ready_to_apply else 3] += 1
        return [tuple(row) for row in playlists.values()]

    def validate(self, library, identities=None):
        if self.library is not library:
            raise SafetyError('The connected library does not match the import queue.')
        if not library.demo:
            ensure_rekordbox_closed()
            if self.fingerprint != library.fingerprint or digest(library.path) != self.fingerprint:
                raise SafetyError('Library changed since preparation. Reconnect and prepare the tracks again.')
        for identity, entry in self.entries.items():
            if identities is not None and identity not in identities:
                continue
            p = entry.proposal
            if not p.ready_to_apply:
                continue
            if p.track.id != identity or p.track.path != entry.audio_path or not entry.sources:
                raise SafetyError('Queued track identity changed. Prepare the track again.')
            if not entry.audio_path.is_file() or entry.audio_stamp is None:
                raise SafetyError(f'Audio unavailable for {p.track.title}. Prepare the track again.')
            stat = entry.audio_path.stat()
            if (stat.st_size, stat.st_mtime_ns) != entry.audio_stamp:
                raise SafetyError(f'Audio changed for {p.track.title}. Prepare the track again.')
            for path, expected in entry.analysis_hashes.items():
                if not path.is_file() or digest(path) != expected:
                    raise SafetyError(f'Analysis changed for {p.track.title}. Prepare the track again.')
            p.grid.validate()

    def complete(self, identities, library):
        for identity in identities:
            if identity in self.entries:
                self.entries[identity].proposal.applied = True
        # Only the app's verified import can advance this database baseline.
        self.fingerprint = getattr(library, 'fingerprint', None)
