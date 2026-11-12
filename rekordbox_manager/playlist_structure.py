"""Read Rekordbox's folder hierarchy and per-parent sequence without changing it."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PlaylistNode:
    identity: str
    name: str
    parent_id: str | None
    attribute: int


def ordered_playlist_nodes(rows):
    # Seq is local to each parent, not a global playlist ordering.
    ordered = sorted(rows, key=lambda row: int(row.get('Seq') or 0))
    by_id = {str(row['ID']): row for row in ordered}
    parents = {}
    for identity, row in by_id.items():
        parent = str(row['ParentID'])
        parents[identity] = parent if parent in by_id and int(by_id[parent]['Attribute'] or 0) == 1 else None
    # Broken parent links must not hide playlists or recurse forever.
    for identity in parents:
        seen = {identity}
        parent = parents[identity]
        while parent is not None:
            if parent in seen:
                parents[identity] = None
                break
            seen.add(parent)
            parent = parents[parent]
    children = {}
    for identity in by_id:
        children.setdefault(parents[identity], []).append(identity)
    result = []
    stack = list(reversed(children.get(None, [])))
    while stack:
        identity = stack.pop()
        row = by_id[identity]
        attribute = int(row['Attribute'] or 0)
        result.append(PlaylistNode(identity, row['Name'] or ('Folder' if attribute == 1 else 'Untitled playlist'), parents[identity], attribute))
        stack.extend(reversed(children.get(identity, [])))
    return tuple(result)
