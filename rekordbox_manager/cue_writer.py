"""Local memory-cue writer, matched to native Rekordbox 7.2.19 records.

Only a private database copy is opened writable. Installation is handled by
BackupStore after staged validation. The grid adapter stages analysis files separately; source audio is never edited.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import plistlib
import secrets
import sqlite3
import sys
from uuid import uuid4

from .guards import SafetyError

TESTED_VERSION = '7.2.19.0342'
STATS = {'UUID', 'rb_data_status', 'rb_local_data_status', 'rb_local_deleted',
         'rb_local_synced', 'usn', 'rb_local_usn', 'created_at', 'updated_at'}
CUE_FIELDS = {'ID', 'ContentID', 'InMsec', 'InFrame', 'InMpegFrame', 'InMpegAbs',
              'OutMsec', 'OutFrame', 'OutMpegFrame', 'OutMpegAbs', 'Kind', 'Color',
              'ColorTableIndex', 'ActiveLoop', 'Comment', 'BeatLoopSize', 'CueMicrosec',
              'InPointSeekInfo', 'OutPointSeekInfo', 'ContentUUID'}
CACHE_FIELDS = {'ID', 'ContentID', 'Cues', 'rb_cue_count'}


def installed_version():
    if sys.platform != 'darwin':
        return None
    path = Path('/Applications/rekordbox 7/rekordbox.app/Contents/Info.plist')
    try:
        return plistlib.loads(path.read_bytes()).get('CFBundleShortVersionString')
    except (OSError, ValueError):
        return None


def schema_problem(db):
    required = {'djmdCue': CUE_FIELDS | STATS, 'contentCue': CACHE_FIELDS | STATS,
                'djmdContent': {'ID', 'UUID', 'FolderPath', 'FileType', 'SampleRate', 'Length',
                                'ServiceID', 'CueUpdated', 'BPM', 'TrackInfoUpdated'} | STATS,
                'agentRegistry': {'registry_id', 'int_1'}, 'djmdProperty': {'DBVersion'}}
    for table, columns in required.items():
        actual = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
        if not columns <= actual:
            return f'Unsupported {table} schema; library writing is locked.'
    versions = [r[0] for r in db.execute('SELECT DBVersion FROM djmdProperty')]
    if versions != ['6000']:
        return 'Unsupported database version; library writing is locked.'
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND lower(tbl_name) IN "
                  "('djmdcue','contentcue','djmdcontent','agentregistry')").fetchone():
        return 'Unexpected database triggers; library writing is locked.'
    row = db.execute("SELECT int_1 FROM agentRegistry WHERE registry_id='localUpdateCount'").fetchone()
    if row is None or not isinstance(row[0], int) or row[0] < 0:
        return 'Missing update counter; library writing is locked.'
    return ''


def compatibility_problem(db):
    if installed_version() != TESTED_VERSION:
        return f'Grid/cue writing is currently verified only with Rekordbox {TESTED_VERSION} on macOS. Writing is locked; this installation remains read-only.'
    return schema_problem(db)


@contextmanager
def staged_connection(path):
    """Writable connection for a PRIVATE staged copy, never the source path."""
    with path.open('rb') as source:
        plain = source.read(16) == b'SQLite format 3\0'
    if plain:
        db = sqlite3.connect(str(path))
        db.row_factory = sqlite3.Row
    else:
        from sqlcipher3 import dbapi2 as cipher
        from pyrekordbox.masterdb.database import BLOB
        from pyrekordbox.utils import deobfuscate
        db = cipher.connect(str(path))
        db.execute("PRAGMA key='" + deobfuscate(BLOB).replace("'", "''") + "'")
        db.row_factory = cipher.Row
    try:
        yield db
    finally:
        db.close()


def cue_key(row):
    start = max(0, row.get('InMsec') or 0)
    out = row.get('OutMsec')
    end = out if out is not None and 0 < out < 0xFFFFFF00 and out > start else None
    kind = 'memory' if row['Kind'] == 0 else 'hot'
    if end is not None:
        kind += '_loop'
    return start, row.get('Comment') or kind.replace('_', ' ').title(), kind, end


def proposed_key(cue):
    if not math.isfinite(cue.time) or cue.time < 0:
        raise SafetyError('Cue timestamps must be finite and non-negative.')
    if cue.end is not None and (not math.isfinite(cue.end) or cue.end <= cue.time):
        raise SafetyError('Invalid saved-loop endpoint.')
    return round(cue.time * 1000), cue.label, cue.kind, None if cue.end is None else round(cue.end * 1000)


def insert_row(db, table, values):
    columns = list(values)
    db.execute(f'INSERT INTO "{table}" ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
               [values[k] for k in columns])


def cache_entry(row):
    result = {k: v for k, v in row.items() if k in CUE_FIELDS | {'UUID', 'created_at', 'updated_at'} and v is not None}
    for key in ('created_at', 'updated_at'):
        result[key] = result[key].replace(' ', 'T', 1).replace(' +', '+').replace(' -', '-')
    return result


def validate_cache(rows, cache):
    if cache is None:
        if rows:
            raise SafetyError('Existing cues have no matching cache. Open the track in Rekordbox and save it first.')
        return {}
    if cache['rb_local_deleted'] or cache['rb_local_synced'] or cache['rb_data_status']:
        raise SafetyError('Synced or deleted cue caches are not supported by this local-only writer.')
    try:
        entries = json.loads(cache['Cues'])
        if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
            raise ValueError()
        by_id = {e['ID']: e for e in entries}
        if len(by_id) != len(entries) or set(by_id) != {r['ID'] for r in rows} or cache['rb_cue_count'] != len(rows):
            raise ValueError()
        for row in rows:
            for key, value in cache_entry(row).items():
                if by_id[row['ID']].get(key) != value:
                    raise ValueError()
        return by_id
    except (TypeError, ValueError, KeyError) as exc:
        raise SafetyError('Cue rows and their cache disagree. Nothing will be written.') from exc


def write_staged(path, proposals, *, grid_updates=None):
    """Modify one private copy, preserving existing hot cues, loops and unknown fields."""
    if not proposals or len({p.track.id for p in proposals}) != len(proposals):
        raise SafetyError('Select a non-empty set of unique tracks.')
    grid_updates = grid_updates or {}
    if set(grid_updates) != {p.track.id for p in proposals if p.options.fix_grid}:
        raise SafetyError('Every grid edit must have verified staged analysis files.')
    with staged_connection(path) as db:
        problem = schema_problem(db)
        if problem:
            raise SafetyError(problem)
        journal = db.execute('PRAGMA journal_mode').fetchone()[0]
        db.execute('PRAGMA journal_mode=DELETE').fetchall()
        db.execute('PRAGMA synchronous=FULL')
        now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('T', ' ').replace('+00:00', ' +00:00')
        counter = db.execute("SELECT int_1 FROM agentRegistry WHERE registry_id='localUpdateCount'").fetchone()[0]
        expected = {}
        try:
            db.execute('BEGIN IMMEDIATE')
            for p in proposals:
                if not p.can_apply:
                    raise SafetyError('Review the proposed changes before importing.')
                content = db.execute('SELECT * FROM djmdContent WHERE ID=?', (p.track.id,)).fetchone()
                if content is None:
                    raise SafetyError('Track no longer exists in the library.')
                content = dict(content)
                if content['FileType'] not in (1, 11) or content['SampleRate'] not in (44100, 48000):
                    raise SafetyError(f'{p.track.title}: this version supports 44.1/48 kHz local MP3 and WAV files only.')
                if content['ServiceID'] not in (None, 0) or any(content[k] for k in ('rb_local_deleted','rb_local_synced','rb_data_status')):
                    raise SafetyError('Streaming, cloud-synced or deleted tracks are not supported by this local-only writer.')
                if str(Path(content['FolderPath']).resolve()) != str(p.track.path.resolve()):
                    raise SafetyError('The track audio path changed. Reload and analyse again.')
                if p.options.fix_grid:
                    bpm = grid_updates[p.track.id]
                    if bpm != content['BPM']:
                        counter += 1
                        db.execute('UPDATE djmdContent SET BPM=?,TrackInfoUpdated=?,rb_local_usn=?,updated_at=? WHERE ID=?',
                                   (bpm, '2', counter, now, p.track.id))
                if not p.options.set_cues:
                    if Counter(proposed_key(c) for c in p.cues) != Counter(proposed_key(c) for c in p.track.cues):
                        raise SafetyError('Grid-only changes must preserve all cues.')
                    continue
                rows = [dict(r) for r in db.execute('SELECT * FROM djmdCue WHERE ContentID=?', (p.track.id,))]
                if any(r['rb_local_deleted'] or r['Kind'] is None for r in rows):
                    raise SafetyError('Unsupported deleted or unclassified cue records.')
                caches = [dict(r) for r in db.execute('SELECT * FROM contentCue WHERE ContentID=?', (p.track.id,))]
                if len(caches) > 1:
                    raise SafetyError('Duplicate cue caches; nothing will be written.')
                cache = caches[0] if caches else None
                if cache and cache['ID'] != content['UUID']:
                    raise SafetyError('Unrecognised cue-cache identity.')
                old_entries = validate_cache(rows, cache)
                desired = [proposed_key(c) for c in p.cues]
                protected = [r for r in rows if cue_key(r)[2] != 'memory']
                if Counter(cue_key(r) for r in protected) != Counter(k for k in desired if k[2] != 'memory'):
                    raise SafetyError('Hot cues and saved loops must be preserved exactly.')
                if not p.options.replace_memory and Counter(cue_key(r) for r in rows) - Counter(desired):
                    raise SafetyError('Existing memory cues must be preserved unless replacement was selected.')
                memory = [k for k in desired if k[2] == 'memory']
                if len(memory) + sum(cue_key(r)[2] == 'memory_loop' for r in rows) > 10:
                    raise SafetyError('A track can hold at most ten memory cues including saved loops.')
                if len({k[0] for k in memory}) != len(memory):
                    raise SafetyError('Duplicate memory-cue timestamps are not supported.')
                if any(k[0] >= p.track.duration * 1000 or k[3] is not None or not isinstance(k[1], str)
                       or len(k[1]) > 255 or '\0' in k[1] for k in memory):
                    raise SafetyError('Invalid memory-cue position or label.')
                keep = list(protected)
                remaining = list(memory)
                for row in rows:
                    if cue_key(row)[2] != 'memory':
                        continue
                    key = cue_key(row)
                    if key in remaining:
                        remaining.remove(key)
                        keep.append(row)
                    else:
                        db.execute('DELETE FROM djmdCue WHERE ID=? AND ContentID=?', (row['ID'], p.track.id))
                for milliseconds, comment, _, _ in remaining:
                    while True:
                        identity = str(secrets.randbelow(2**32 - 1) + 1)
                        if not db.execute('SELECT 1 FROM djmdCue WHERE ID=?', (identity,)).fetchone():
                            break
                    row = dict(ID=identity, ContentID=p.track.id, ContentUUID=content['UUID'],
                               InMsec=milliseconds, InFrame=milliseconds * 150 // 1000,
                               InMpegFrame=0, InMpegAbs=0, OutMsec=-1, OutFrame=0, OutMpegFrame=0,
                               OutMpegAbs=0, Kind=0, Color=-1, Comment=comment, UUID=str(uuid4()),
                               created_at=now, updated_at=now)
                    insert_row(db, 'djmdCue', row)
                    keep.append(row)
                entries = [old_entries[r['ID']] if r['ID'] in old_entries else cache_entry(r)
                           for r in sorted(keep, key=lambda r: (r['Kind'], r['InMsec'], r['ID']))]
                encoded = json.dumps(entries, separators=(',', ':'), ensure_ascii=False)
                counter += 1
                if cache:
                    db.execute('UPDATE contentCue SET Cues=?,rb_cue_count=?,rb_local_usn=?,rb_local_synced=0,updated_at=? WHERE ID=?',
                               (encoded, len(entries), counter, now, cache['ID']))
                else:
                    insert_row(db, 'contentCue', dict(ID=content['UUID'], ContentID=p.track.id,
                               Cues=encoded, rb_cue_count=len(entries), UUID=str(uuid4()), rb_local_usn=counter,
                               created_at=now, updated_at=now))
                counter += 1
                db.execute('UPDATE djmdContent SET CueUpdated=?,rb_local_usn=?,updated_at=? WHERE ID=?',
                           ('1', counter, now, p.track.id))
                expected[p.track.id] = Counter(desired)
            db.execute("UPDATE agentRegistry SET int_1=? WHERE registry_id='localUpdateCount'", (counter,))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SafetyError('Staged database integrity check failed.')
            for identity, keys in expected.items():
                rows = [dict(r) for r in db.execute('SELECT * FROM djmdCue WHERE ContentID=?', (identity,))]
                cache = dict(db.execute('SELECT * FROM contentCue WHERE ContentID=?', (identity,)).fetchone())
                validate_cache(rows, cache)
                if Counter(cue_key(r) for r in rows) != keys:
                    raise SafetyError('Staged cue read-back does not match the proposals.')
        except Exception:
            db.rollback()
            raise
        finally:
            # Keep the source database's journaling mode; never install sidecars.
            if journal == 'wal':
                db.execute('PRAGMA journal_mode=WAL').fetchall()
