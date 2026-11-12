"""Session-only playlist drafts; no writes until the Imports action."""
from dataclasses import dataclass, replace
from secrets import randbelow
from types import SimpleNamespace

from .backups import digest
from .guards import SafetyError
from .playlist_structure import PlaylistNode

XML_NAME = 'masterPlaylists6.xml'


@dataclass(frozen=True)
class OrganiserPlan:
    fingerprint: str
    xml_fingerprint: str | None
    nodes: tuple[PlaylistNode, ...]
    assignments: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...]
    structure: tuple[PlaylistNode, ...] = ()


class OrganiserQueue:
    def __init__(self):
        self.reset()

    def reset(self, library=None):
        self.library = library
        self.fingerprint = None
        self.xml_fingerprint = None
        self.nodes = []
        self.assignments = {}
        self.layout = ()

    def pending(self):
        return bool(self.nodes or self.assignments or self.layout)

    def bind(self, library, fingerprint=None):
        if self.library is not library:
            if self.pending():
                raise SafetyError('Playlist drafts belong to another library.')
            self.reset(library)
        current = digest(library.path)
        if current != library.fingerprint or (fingerprint is not None and current != fingerprint):
            raise SafetyError('Library changed since the scan. Reconnect and scan again.')
        xml = library.root / XML_NAME
        xml_hash = digest(xml) if xml.exists() else None
        if self.pending() and (self.fingerprint != current or self.xml_fingerprint != xml_hash):
            raise SafetyError('Library or playlist metadata changed. Discard the playlist drafts and reconnect.')
        self.fingerprint, self.xml_fingerprint = current, xml_hash

    def view(self, library=None, original=False):
        library = library or self.library
        existing = list(getattr(library, 'playlist_nodes', ()))
        if not existing:
            existing = [PlaylistNode(key, name, None, 0) for key, name in getattr(library, 'playlists', {}).items()]
        nodes = existing + self.nodes
        if self.layout and not original:
            arranged = {n.identity for n in self.layout}
            nodes = list(self.layout) + [n for n in nodes if n.identity not in arranged]
        children = {}
        for node in nodes:
            children.setdefault(node.parent_id, []).append(node)
        ordered, paths, playlists, playlist_paths = [], {}, {}, {}
        def visit(parent):
            for node in children.get(parent, ()):
                ordered.append(node)
                paths[node.identity] = paths.get(parent, ()) + ((node.identity, node.name),)
                if node.attribute == 0:
                    playlist_paths[node.identity] = paths[node.identity]
                    playlists[node.identity] = ' / '.join(name for _, name in paths[node.identity])
                visit(node.identity)
        visit(None)
        return SimpleNamespace(playlist_nodes=tuple(ordered), playlists=playlists, playlist_paths=playlist_paths)

    def create(self, library, name, parent=None, folder=False):
        self.bind(library)
        name = name.strip()
        if not name or len(name) > 255 or any(ord(c) < 32 for c in name):
            raise SafetyError('Use a name of 1–255 characters without line breaks or control characters.')
        nodes = self.view(library).playlist_nodes
        if parent is not None and not any(n.identity == parent and n.attribute == 1 for n in nodes):
            raise SafetyError('Choose a folder for the new item.')
        if any(n.parent_id == parent and n.name.casefold() == name.casefold() for n in nodes):
            raise SafetyError('That name is already used in this folder.')
        # Match Rekordbox/pyrekordbox: non-zero 28-bit decimal identifiers.
        with library.connect() as db:
            used = {str(r[0]) for r in db.execute('SELECT ID FROM djmdPlaylist')}
        used.update(n.identity for n in self.nodes)
        identity = str(randbelow(2**28 - 1) + 1)
        while identity in used:
            identity = str(randbelow(2**28 - 1) + 1)
        node = PlaylistNode(identity, name, parent, 1 if folder else 0)
        self.nodes.append(node)
        return node

    def add(self, library, tracks, destinations, fingerprint):
        self.bind(library, fingerprint)
        valid = self.view(library).playlists
        destinations = tuple(dict.fromkeys(destinations))
        tracks = tuple(tracks)
        if not tracks or not destinations or any(key not in valid for key in destinations):
            raise SafetyError('Select tracks and at least one regular playlist.')
        for key in destinations:
            entries = self.assignments.setdefault(key, {})
            for track in tracks:
                # Existing memberships and repeated clicks never create duplicates.
                if key not in track.playlist_ids:
                    entries.setdefault(track.id, (track.id, track.title, track.artist))
            if not entries:
                self.assignments.pop(key)

    def snapshot(self):
        return OrganiserPlan(self.fingerprint, self.xml_fingerprint, tuple(self.nodes),
                             tuple((key, tuple(rows.values())) for key, rows in self.assignments.items()), self.view().playlist_nodes if self.layout else ())

    def rebase(self, previous, library):
        # Only called after another verified app import; never accepts external changes.
        if self.pending() and self.library is library and self.fingerprint == previous:
            self.fingerprint = library.fingerprint

    def move(self, library, identity, parent=None, before=None):
        self.bind(library)
        nodes = self.view(library).playlist_nodes
        by_id = {n.identity: n for n in nodes}
        node = by_id.get(identity)
        if node is None or node.attribute not in (0, 1):
            raise SafetyError('Only regular playlists and folders can be moved.')
        if parent is not None and (parent not in by_id or by_id[parent].attribute != 1):
            raise SafetyError('Choose a folder as the destination.')
        ancestor = parent
        while ancestor is not None:
            if ancestor == identity:
                raise SafetyError('A folder cannot be placed inside itself or one of its subfolders.')
            ancestor = by_id[ancestor].parent_id
        if parent != node.parent_id and any(n.parent_id == parent and n.name.casefold() == node.name.casefold() for n in nodes):
            raise SafetyError('That name is already used in the destination folder.')
        if before == identity:
            return
        siblings = [n.identity for n in nodes if n.parent_id == parent and n.identity != identity]
        if before is not None and before not in siblings:
            raise SafetyError('The drop position is no longer available.')
        siblings.insert(siblings.index(before) if before is not None else len(siblings), identity)
        children = {}
        for n in nodes:
            if n.identity != identity:
                children.setdefault(n.parent_id, []).append(n.identity)
        children[parent] = siblings
        by_id[identity] = replace(node, parent_id=parent)
        ordered = []
        def visit(key):
            for child in children.get(key, ()):
                ordered.append(by_id[child])
                visit(child)
        visit(None)
        self.layout = tuple(ordered)
        if self.layout == self.view(library, original=True).playlist_nodes:
            self.layout = ()

    def structure_changes(self):
        if not self.layout:
            return []
        def positions(nodes):
            counts, result = {}, {}
            for node in nodes:
                counts[node.parent_id] = counts.get(node.parent_id, 0) + 1
                result[node.identity] = (node.parent_id, counts[node.parent_id])
            return result
        before = positions(self.view(original=True).playlist_nodes)
        after = positions(self.view().playlist_nodes)
        return [(key, parent, position) for key, (parent, position) in after.items()
                if before.get(key) != (parent, position)]
