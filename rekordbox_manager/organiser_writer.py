"""Stage playlist/folder creation and membership additions with verified recovery."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import shutil
import tempfile
import xml.etree.ElementTree as ET

from . import cue_writer
from .backups import digest
from .guards import SafetyError, ensure_clean_database
from .playlist_writer import compatibility_problem, _local
from .organiser_queue import XML_NAME
from .playlist_structure import ordered_playlist_nodes


def validate_plan(db, plan):
    problem = compatibility_problem(db)
    if problem:
        raise SafetyError(problem)
    if not plan.nodes and not plan.assignments and not plan.structure:
        raise SafetyError('No playlist changes are queued.')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND lower(tbl_name)='djmdplaylist'").fetchone():
        raise SafetyError('Unexpected playlist triggers; no changes applied.')
    existing = {str(r['ID']): dict(r) for r in db.execute('SELECT * FROM djmdPlaylist')}
    known = existing.copy()
    for node in plan.nodes:
        if (node.identity in known or not node.identity.isdecimal() or not 0 < int(node.identity) < 2**28
                or node.attribute not in (0, 1) or not node.name.strip() or len(node.name) > 255
                or any(ord(c) < 32 for c in node.name)):
            raise SafetyError('Invalid or conflicting playlist draft.')
        parent = node.parent_id
        if parent is not None and (parent not in known or known[parent]['Attribute'] != 1 or not _local(known[parent])):
            raise SafetyError('The destination folder is unavailable or cloud-synced.')
        siblings = [r for r in known.values() if (r['ParentID'] or 'root') == (parent or 'root')]
        if not plan.structure and any((r['Name'] or '').casefold() == node.name.casefold() for r in siblings):
            raise SafetyError('A playlist or folder with this name already exists.')
        known[node.identity] = dict(ID=node.identity, Name=node.name, Attribute=node.attribute,
            ParentID=parent or 'root', Seq=max([0] + [int(r.get('Seq') or 0) for r in siblings]) + 1, rb_local_deleted=0, rb_local_synced=0, rb_data_status=0)
    destinations = set()
    for destination, tracks in plan.assignments:
        if destination in destinations or not tracks:
            raise SafetyError('Invalid playlist assignments.')
        destinations.add(destination)
        row = known.get(destination)
        if row is None or row['Attribute'] != 0 or not _local(row):
            raise SafetyError('Choose active local regular playlists.')
        memberships = db.execute('SELECT * FROM djmdSongPlaylist WHERE PlaylistID=?', (destination,)).fetchall()
        if any(r['rb_local_synced'] or r['rb_data_status'] for r in memberships):
            raise SafetyError('Cloud-synced playlist entries are not supported.')
        active = [r['TrackNo'] for r in memberships if not r['rb_local_deleted']]
        if any(not isinstance(n, int) or n < 1 for n in active) or len(active) != len(set(active)):
            raise SafetyError('Destination playlist order is inconsistent.')
        seen = set()
        for identity, title, artist in tracks:
            row = db.execute('SELECT c.*, a.Name AS ArtistName FROM djmdContent c LEFT JOIN djmdArtist a '
                             'ON a.ID=c.ArtistID WHERE c.ID=?', (identity,)).fetchone()
            if (identity in seen or row is None or not _local(row) or row['ServiceID'] not in (None, 0)
                    or (row['Title'] or 'Untitled track') != title or (row['ArtistName'] or 'Unknown artist') != artist):
                raise SafetyError('A queued track changed or is unavailable, streaming or cloud-synced.')
            seen.add(identity)
    return existing, structure_updates(known, plan)



def structure_updates(known, plan):
    if not plan.structure:
        return {}
    nodes = plan.structure
    if len(nodes) != len(known) or {n.identity for n in nodes} != set(known):
        raise SafetyError('The queued folder structure does not match the library.')
    seen, children = set(), {}
    for node in nodes:
        row = known[node.identity]
        if node.name != (row['Name'] or ('Folder' if row['Attribute'] == 1 else 'Untitled playlist')) or node.attribute != row['Attribute']:
            raise SafetyError('Unexpected playlist rename or type change.')
        if node.parent_id is not None:
            parent = known.get(node.parent_id)
            if node.parent_id not in seen or parent is None or parent['Attribute'] != 1:
                raise SafetyError('Invalid folder structure or cyclic folder move.')
        seen.add(node.identity)
        children.setdefault(node.parent_id, []).append(node.identity)
    original = ordered_playlist_nodes(list(known.values()))
    old_children = {}
    original_parents = {}
    for node in original:
        old_children.setdefault(node.parent_id, []).append(node.identity)
        original_parents[node.identity] = node.parent_id
    affected = {key for key in set(children) | set(old_children) if children.get(key, []) != old_children.get(key, [])}
    for parent in affected:
        if parent is not None and not _local(known[parent]):
            raise SafetyError('Cloud-synced or deleted folders cannot be reorganised.')
    updates = {}
    new_ids = {n.identity for n in plan.nodes}
    for node in nodes:
        if node.identity in new_ids and any(other != node.identity and (known[other]['Name'] or '').casefold() == node.name.casefold()
                                            for other in children[node.parent_id]):
            raise SafetyError('That name already exists in the destination folder.')
        if node.parent_id not in affected:
            continue
        row = known[node.identity]
        position = children[node.parent_id].index(node.identity) + 1
        previous_parent = row['ParentID'] if row['ParentID'] not in (None, '', 'root') else None
        if previous_parent != original_parents[node.identity]:
            raise SafetyError('Repair broken parent links in Rekordbox before reorganising this folder.')
        fields = {}
        if previous_parent != node.parent_id:
            fields['ParentID'] = node.parent_id or 'root'
        if row.get('Seq') != position:
            fields['Seq'] = position
        if fields:
            if not _local(row) or node.attribute not in (0, 1):
                raise SafetyError('Only active local regular playlists and folders can be reordered.')
            updates[node.identity] = fields
        if 'ParentID' in fields or node.identity in new_ids:
            if any(other != node.identity and (known[other]['Name'] or '').casefold() == node.name.casefold()
                   for other in children[node.parent_id]):
                raise SafetyError('That name already exists in the destination folder.')
            # Moving a folder changes the paths of its subtree, including cloud records.
            pending = list(children.get(node.identity, ()))
            while pending:
                descendant = pending.pop()
                if not _local(known[descendant]):
                    raise SafetyError('Folders containing cloud-synced or deleted items cannot be moved.')
                pending.extend(children.get(descendant, ()))
    return updates


def stage_database(path, plan):
    with cue_writer.staged_connection(path) as db:
        before_playlists, updates = validate_plan(db, plan)
        before_songs = {r['ID']: dict(r) for r in db.execute('SELECT * FROM djmdSongPlaylist')}
        # Verify every untouched table as well as the append-only playlist rows.
        untouched = {r[0]: list(db.execute('SELECT * FROM "' + r[0].replace('"', '""') + '"'))
                     for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                     if r[0] not in ('djmdPlaylist', 'djmdSongPlaylist', 'agentRegistry')}
        counter = db.execute("SELECT int_1 FROM agentRegistry WHERE registry_id='localUpdateCount'").fetchone()[0]
        now = datetime.now(timezone.utc)
        stamp = now.isoformat(timespec='milliseconds').replace('T', ' ').replace('+00:00', ' +00:00')
        def stats(usn):
            return dict(UUID=str(uuid4()), rb_local_usn=usn, rb_data_status=0, rb_local_data_status=0,
                        rb_local_deleted=0, rb_local_synced=0, created_at=stamp, updated_at=stamp)
        journal = db.execute('PRAGMA journal_mode').fetchone()[0]
        db.execute('PRAGMA journal_mode=DELETE').fetchall()
        db.execute('PRAGMA synchronous=FULL')
        new_playlists, new_songs = {}, {}
        try:
            db.execute('BEGIN IMMEDIATE')
            for node in plan.nodes:
                parent = node.parent_id or 'root'
                seq = db.execute("SELECT MAX(Seq) FROM djmdPlaylist WHERE COALESCE(ParentID,'root')=?", (parent,)).fetchone()[0]
                # pyrekordbox creates a placeholder then renames it: two registry events.
                counter += 2
                values = dict(ID=node.identity, Name=node.name, ParentID=parent, Attribute=node.attribute,
                              Seq=max(0, int(seq or 0)) + 1, **stats(counter))
                cue_writer.insert_row(db, 'djmdPlaylist', values)
                new_playlists[node.identity] = values
            if updates:
                counter += 1
                for identity, fields in updates.items():
                    values = dict(fields, updated_at=stamp, rb_local_usn=counter)
                    db.execute('UPDATE djmdPlaylist SET ' + ','.join(key + '=?' for key in values) + ' WHERE ID=?',
                               (*values.values(), identity))
                    if identity in new_playlists:
                        new_playlists[identity].update(values)
                    else:
                        before_playlists[identity].update(values)
            for destination, tracks in plan.assignments:
                rows = [r for r in before_songs.values() if r['PlaylistID'] == destination]
                position = max([0] + [r['TrackNo'] for r in rows if isinstance(r['TrackNo'], int)])
                members = {r['ContentID'] for r in rows if not r['rb_local_deleted']}
                for identity, _, _ in tracks:
                    if identity in members:
                        continue
                    counter += 1
                    position += 1
                    values = dict(ID=str(uuid4()), PlaylistID=destination, ContentID=identity,
                                  TrackNo=position, **stats(counter))
                    cue_writer.insert_row(db, 'djmdSongPlaylist', values)
                    new_songs[values['ID']] = values
                    members.add(identity)
            db.execute("UPDATE agentRegistry SET int_1=? WHERE registry_id='localUpdateCount'", (counter,))
            for table, before, added in (('djmdPlaylist', before_playlists, new_playlists),
                                          ('djmdSongPlaylist', before_songs, new_songs)):
                after = {str(r['ID']): dict(r) for r in db.execute('SELECT * FROM ' + table)}
                if (set(after) != set(before) | set(added) or any(after[k] != v for k, v in before.items())
                        or any(any(after[k][f] != v for f, v in values.items()) for k, values in added.items())):
                    raise SafetyError('Playlist read-back differs from the reviewed draft.')
            for table, before in untouched.items():
                if list(db.execute('SELECT * FROM "' + table.replace('"', '""') + '"')) != before:
                    raise SafetyError('An unrelated database table changed; import cancelled.')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SafetyError('Staged database integrity check failed.')
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            if journal == 'wal':
                db.execute('PRAGMA journal_mode=WAL').fetchall()
    return now, updates


def stage_xml(path, nodes, now, updates):
    tree = ET.parse(path)
    playlists = tree.getroot().find('PLAYLISTS')
    if playlists is None:
        raise SafetyError('Unrecognised playlist metadata file.')
    used = {n.get('Id', '').upper() for n in playlists}
    for node in nodes:
        identity = f'{int(node.identity):X}'
        if identity in used:
            raise SafetyError('Playlist metadata contains a conflicting ID.')
        parent = f'{int(node.parent_id):X}' if node.parent_id else '0'
        if parent != '0' and parent not in used:
            raise SafetyError('The parent folder is missing from playlist metadata.')
        ET.SubElement(playlists, 'NODE', dict(Id=identity, ParentId=parent, Attribute=str(node.attribute),
            Timestamp=str(int(now.timestamp() * 1000)), Lib_Type='0', CheckType='0'))
        used.add(identity)
    for identity, fields in updates.items():
        key = f'{int(identity):X}'
        matches = [item for item in playlists if item.get('Id', '').upper() == key]
        if len(matches) != 1:
            raise SafetyError('Moved playlist is missing or duplicated in playlist metadata.')
        item = matches[0]
        if 'ParentID' in fields:
            parent = fields['ParentID']
            item.set('ParentId', '0' if parent == 'root' else f'{int(parent):X}')
        item.set('Timestamp', str(int(now.timestamp() * 1000)))
    tree.write(path, encoding='utf-8', xml_declaration=True)
    ET.parse(path)


def apply_plan(library, plan, backups):
    if backups is None:
        raise SafetyError('A verified backup is required.')
    xml = library.root / XML_NAME
    def guard():
        ensure_clean_database(library.path)
        with library.connect() as db:
            problem = compatibility_problem(db)
            if problem:
                raise SafetyError(problem)
    def unchanged():
        guard()
        if library.fingerprint != plan.fingerprint or digest(library.path) != plan.fingerprint:
            raise SafetyError('Library changed since the playlist drafts were queued.')
        if (digest(xml) if xml.exists() else None) != plan.xml_fingerprint:
            raise SafetyError('Playlist metadata changed since the drafts were queued.')
    unchanged()
    with tempfile.TemporaryDirectory(prefix='rekordbox-organiser-stage-') as temp:
        staged = Path(temp) / library.path.name
        shutil.copy2(library.path, staged)
        if digest(staged) != plan.fingerprint:
            raise SafetyError('Library changed while staging.')
        now, updates = stage_database(staged, plan)
        replacements = {library.path.name: staged}
        expected = {library.path.name: plan.fingerprint}
        if plan.xml_fingerprint is not None:
            expected[XML_NAME] = plan.xml_fingerprint
            if plan.nodes or updates:
                staged_xml = Path(temp) / XML_NAME
                shutil.copy2(xml, staged_xml)
                if digest(staged_xml) != plan.xml_fingerprint:
                    raise SafetyError('Playlist metadata changed while staging.')
                stage_xml(staged_xml, plan.nodes, now, updates)
                replacements[XML_NAME] = staged_xml
        hashes = {name: digest(path) for name, path in replacements.items()}
        def install_guard():
            guard()
            if plan.xml_fingerprint is None and xml.exists():
                raise SafetyError('Playlist metadata appeared during import.')
        def verify():
            guard()
            if any(digest(library.root / name) != value for name, value in hashes.items()):
                raise SafetyError('Installed playlist files failed verification.')
        backup = backups.install(library.root, replacements, expected, install_guard, verify,
                                 f'Organiser: {len(plan.nodes)} new folders/playlists; {len(plan.assignments)} playlist assignments; {len(updates)} structure updates')
    library.reload()
    return backup
