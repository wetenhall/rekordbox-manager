import sqlite3
import pytest

from rekordbox_manager.backups import digest
from rekordbox_manager.guards import SafetyError
from rekordbox_manager.library import RekordboxLibrary
from rekordbox_manager.usage import scan_usage, play_count
from test_library import make_library, no_running_rekordbox


def usage_library(tmp_path, encrypted=False):
    path = make_library(tmp_path / 'master.db', encrypted)
    if encrypted:
        from sqlcipher3 import dbapi2 as cipher
        from pyrekordbox.masterdb.database import BLOB
        from pyrekordbox.utils import deobfuscate
        db = cipher.connect(str(path))
        db.execute("PRAGMA key='" + deobfuscate(BLOB).replace("'", "''") + "'")
    else:
        db = sqlite3.connect(path)
    with db:
        db.executescript('''
            ALTER TABLE djmdContent ADD COLUMN DJPlayCount INTEGER;
            ALTER TABLE djmdContent ADD COLUMN rb_local_deleted INTEGER DEFAULT 0;
            ALTER TABLE djmdPlaylist ADD COLUMN rb_local_deleted INTEGER DEFAULT 0;
            ALTER TABLE djmdSongPlaylist ADD COLUMN rb_local_deleted INTEGER DEFAULT 0;
            CREATE TABLE djmdHistory(ID TEXT, rb_local_deleted INTEGER);
            CREATE TABLE djmdSongHistory(ContentID TEXT, HistoryID TEXT, rb_local_deleted INTEGER);
            INSERT INTO djmdHistory VALUES ('live',0),('deleted',1);
            UPDATE djmdContent SET DJPlayCount=0;
            INSERT INTO djmdPlaylist VALUES('deleted','Old','root',0,3,1);
            INSERT INTO djmdSongPlaylist VALUES('p','t',2,0),('smart','orphan',1,0),
                ('deleted','orphan',1,0),('p','orphan',1,1),('missing','orphan',1,0);
        ''')
        for identity, plays, deleted in [('orphan',0,0), ('played',7,0), ('reset',0,0),
                                          ('unknown',None,0), ('bad',-1,0), ('removed',0,1)]:
            db.execute('INSERT INTO djmdContent(ID,Title,ArtistID,GenreID,DJPlayCount,rb_local_deleted) VALUES(?,?,?,?,?,?)',
                       (identity, identity, 'a', 'g', plays, deleted))
        db.executescript('''
            INSERT INTO djmdSongHistory VALUES('reset','live',0),('unknown','live',0),
                ('orphan','deleted',0),('orphan','live',1),('orphan','missing',0);
        ''')
    db.close()
    return RekordboxLibrary(path)


@pytest.mark.parametrize('encrypted', [False, True])
def test_scan_full_library_readonly_with_history_and_membership(tmp_path, encrypted):
    library = usage_library(tmp_path, encrypted)
    before = digest(library.path)
    fingerprints = library.fingerprints.copy()
    result = scan_usage(library)
    rows = {t.id:t for t in result.tracks}
    assert set(rows) == {'t','orphan','played','reset','unknown','bad'}
    assert rows['t'].playlist_ids == ('p',)
    assert rows['orphan'].playlist_ids == ()
    assert rows['t'].playlists == 1  # Duplicate playlist entries count once.
    assert rows['orphan'].playlists == 0 and rows['orphan'].history_entries == 0
    assert rows['orphan'].play_status == 'No recorded plays'
    assert rows['played'].play_status == rows['reset'].play_status == rows['unknown'].play_status == 'Played'
    assert rows['bad'].play_status == 'Unknown'
    assert not result.notes
    assert library.loaded_ids == set() and library.fingerprints == fingerprints
    assert digest(library.path) == before
    assert not list(tmp_path.glob('master.db-*'))


def test_missing_usage_data_stays_unknown(tmp_path):
    result = scan_usage(RekordboxLibrary(make_library(tmp_path / 'master.db')))
    row = result.tracks[0]
    assert row.plays is None and row.history_entries is None
    assert row.play_status == 'Unknown' and row.playlists == 1
    assert len(result.notes) == 2


def test_null_count_without_history_is_not_unplayed(tmp_path):
    library = usage_library(tmp_path)
    with sqlite3.connect(library.path) as db:
        db.execute("DELETE FROM djmdSongHistory WHERE ContentID='unknown'")
    library.reload()
    row = next(t for t in scan_usage(library).tracks if t.id == 'unknown')
    assert row.play_status == 'Unknown'


@pytest.mark.parametrize('value,expected', [(None,None), ('',None), ('bad',None), (-1,None), (1.5,None),
                                          ('0',0), (' 12 ',12), (0,0)])
def test_play_count_validation(value, expected):
    assert play_count(value) == expected


def test_scan_refuses_stale_connection(tmp_path):
    library = usage_library(tmp_path)
    with sqlite3.connect(library.path) as db:
        db.execute('UPDATE djmdContent SET DJPlayCount=20')
    with pytest.raises(SafetyError, match='Reconnect'):
        scan_usage(library)


def test_scan_cancellation(tmp_path):
    library = usage_library(tmp_path)
    with pytest.raises(InterruptedError):
        scan_usage(library, cancelled=lambda: True)


def test_scan_detects_concurrent_change(tmp_path, monkeypatch):
    library = usage_library(tmp_path)
    hashes = iter([library.fingerprint, 'changed'])
    monkeypatch.setattr('rekordbox_manager.usage.digest', lambda path: next(hashes))
    with pytest.raises(SafetyError, match='during the scan'):
        scan_usage(library)
