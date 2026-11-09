import sqlite3
import struct
from pathlib import Path
import pytest

from rekordbox_manager.library import RekordboxLibrary, read_grid
from rekordbox_manager.backups import digest
from rekordbox_manager.guards import SafetyError, ensure_clean_database


@pytest.fixture(autouse=True)
def no_running_rekordbox(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, 'process_iter', lambda attrs: [])


def anlz_bytes(count=200):
    entries = b"".join(struct.pack(">HHI", i % 4 + 1, 12000, i * 500) for i in range(count))
    tag = struct.pack(">4sIIIII", b"PQTZ", 24, 24 + len(entries), 0, 0x80000, count) + entries
    return struct.pack(">4sII", b"PMAI", 28, 28 + len(tag)) + bytes(16) + tag


def make_library(path, encrypted=False):
    if encrypted:
        from sqlcipher3 import dbapi2 as cipher
        from pyrekordbox.masterdb.database import BLOB
        from pyrekordbox.utils import deobfuscate
        db = cipher.connect(str(path))
        db.execute("PRAGMA key='" + deobfuscate(BLOB).replace("'", "''") + "'")
    else:
        db = sqlite3.connect(path)
    db.executescript('''
    CREATE TABLE djmdPlaylist(ID TEXT, Name TEXT, ParentID TEXT, Attribute INT, Seq INT);
    INSERT INTO djmdPlaylist VALUES('folder','Music','root',1,0),('p','House','folder',0,1),('smart','Smart', 'root', 4, 2);
    CREATE TABLE djmdContent(ID TEXT, Title TEXT, ArtistID TEXT, GenreID TEXT, FolderPath TEXT, AnalysisDataPath TEXT, BPM INT, Length INT);
    CREATE TABLE djmdArtist(ID TEXT, Name TEXT);
    INSERT INTO djmdArtist VALUES('a','Artist');
    CREATE TABLE djmdGenre(ID TEXT, Name TEXT);
    INSERT INTO djmdGenre VALUES('g','House');
    CREATE TABLE djmdSongPlaylist(PlaylistID TEXT, ContentID TEXT, TrackNo INT);
    INSERT INTO djmdSongPlaylist VALUES('p','t',1);
    CREATE TABLE djmdCue(ContentID TEXT, InMsec INT, OutMsec INT, Kind INT, Comment TEXT);
    INSERT INTO djmdCue VALUES('t',1000,4294967295,0,'Memory'),('t',2000,3000,1,'Hot loop');
    ''')
    db.execute("INSERT INTO djmdContent VALUES(?,?,?,?,?,?,?,?)", ('t', 'Track', 'a', 'g', str(path.parent/'audio.wav'), '/PIONEER/USBANLZ/a/ANLZ0000.DAT', 12000, 100))
    db.commit()
    db.close()
    dat = path.parent / "share/PIONEER/USBANLZ/a/ANLZ0000.DAT"
    dat.parent.mkdir(parents=True)
    dat.write_bytes(anlz_bytes())
    return path


@pytest.mark.parametrize("encrypted", [False, True])
def test_readonly_adapter_and_playlist_folder_names(tmp_path, encrypted):
    path = make_library(tmp_path / "master.db", encrypted)
    before = digest(path)
    lib = RekordboxLibrary(path)
    assert lib.playlists == {'p': 'Music / House'}
    track = lib.tracks('p')[0]
    assert track.bpm == 120 and track.title == 'Track'
    assert track.grid.times[2] == 1
    assert [c.kind for c in track.cues] == ['memory', 'hot_loop']
    assert digest(path) == before
    with lib.connect() as db:
        with pytest.raises(Exception, match="readonly"):
            db.execute("DELETE FROM djmdContent")
    with pytest.raises(SafetyError, match="locked"):
        lib.apply([])


def test_wal_data_blocks_connection(tmp_path):
    path = tmp_path / 'master.db'
    path.write_bytes(b'')
    Path(str(path) + '-wal').write_bytes(b'pending')
    with pytest.raises(SafetyError, match="journal"):
        ensure_clean_database(path)


def test_unknown_and_truncated_anlz_refused(tmp_path):
    path = tmp_path / 'ANLZ0000.DAT'
    for data in (b'bad', anlz_bytes()[:-1], anlz_bytes()[:40]):
        path.write_bytes(data)
        with pytest.raises(ValueError):
            read_grid(path)


def test_process_guard_blocks_agent(monkeypatch):
    import psutil
    from types import SimpleNamespace
    from rekordbox_manager.guards import ensure_rekordbox_closed
    monkeypatch.setattr(psutil, 'process_iter', lambda attrs: [SimpleNamespace(info={'name':'rekordboxAgent.exe'})])
    with pytest.raises(SafetyError, match='rekordboxAgent'):
        ensure_rekordbox_closed()


def test_process_guard_does_not_block_itself(monkeypatch):
    import psutil
    from types import SimpleNamespace
    from rekordbox_manager.guards import ensure_rekordbox_closed
    monkeypatch.setattr(psutil, 'process_iter', lambda attrs: [SimpleNamespace(info={'name':'Rekordbox Manager'})])
    ensure_rekordbox_closed()
