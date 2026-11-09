"""Packaged-app smoke test using only a disposable synthetic library."""
import json
import os
import platform
from pathlib import Path
import tempfile
import time


def run(output: Path):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QUrl, QPoint, Qt
    from PySide6.QtTest import QTest
    from .demo import create_demo, DemoLibrary
    from .analysis import render_metronome
    from .backups import BackupStore, digest
    from .ui import MainWindow
    from sqlcipher3 import dbapi2 as cipher
    from pyrekordbox.masterdb.database import BLOB
    from pyrekordbox.utils import deobfuscate

    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="rekordbox-manager-selftest-") as temp:
        root = Path(temp).resolve()
        os.environ['REKORDBOX_MANAGER_DATA_DIR'] = str(root)
        window = MainWindow()
        window.show()
        app.processEvents()
        window.grab().save(str(output / 'welcome.png'))
        library = DemoLibrary(create_demo(root / 'Demo'))
        window.pages.setCurrentWidget(window.workspace)
        window.fix_grid.setChecked(True)
        window.set_library(library)
        window.start_analysis()
        deadline = time.monotonic() + 180
        while (not window.proposals or window.worker.isRunning()) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert window.proposals and not window.worker.isRunning(), 'Background analysis did not complete'
        proposals = window.proposals
        assert all(not p.error for p in proposals), [p.error for p in proposals]
        assert all(p.first_drop is not None and p.second_drop is not None for p in proposals)
        window.proposals = proposals
        window.populate_table()
        window.table.selectRow(0)
        window.select_track()
        app.processEvents()
        window.grab().save(str(output / 'manager.png'))
        window.resize(1050, 720)
        app.processEvents()
        window.grab().save(str(output / 'manager-compact.png'))
        window.resize(1280, 870)
        app.processEvents()
        p = proposals[0]
        window.focus_drop(1)
        original_anchor = p.first_drop
        handle = window.wave.marker_rect(1).center().toPoint()
        moved = handle + QPoint(100, 0)
        QTest.mousePress(window.wave, Qt.LeftButton, pos=handle)
        QTest.mouseMove(window.wave, moved)
        QTest.mouseRelease(window.wave, Qt.LeftButton, pos=moved)
        app.processEvents()
        assert p.first_drop != original_anchor and p.cues_dirty and not p.can_apply
        window.rebuild_cues()
        assert not p.cues_dirty and not p.reviewed
        app.processEvents()
        window.grab().save(str(output / 'zoomed.png'))
        original = library.fingerprints.copy()
        store = window.backups
        assert window.apply_button.isEnabled()
        original_question = QMessageBox.question
        original_information = QMessageBox.information
        try:
            QMessageBox.question = lambda *args: QMessageBox.Yes
            QMessageBox.information = lambda *args: QMessageBox.Ok
            window.apply_changes()
        finally:
            QMessageBox.question = original_question
            QMessageBox.information = original_information
        snapshots = store.list()
        assert len(snapshots) == 1, 'Playlist apply did not create one backup'
        snapshot = snapshots[0][0]
        assert all(len([c for c in track.cues if c.kind == 'memory']) == 10
                   for track in library.tracks(window.playlists.currentData()))
        store.restore(snapshot, library.root, lambda: None, set(library.fingerprints))
        library.reload()
        assert library.fingerprints == original
        render_metronome(p.track, p.grid, root / 'click.wav')
        db = cipher.connect(str(root / 'test.db'))
        db.execute("PRAGMA key='" + deobfuscate(BLOB).replace("'", "''") + "'")
        db.execute('CREATE TABLE check_table(value INT)')
        db.commit()
        db.close()
        assert (root / 'test.db').read_bytes()[:16] != b'SQLite format 3\0'
        window.player.setSource(QUrl.fromLocalFile(str(p.track.path)))
        deadline = time.monotonic() + 8
        while window.player.duration() == 0 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert window.player.duration() > 0, 'Packaged multimedia decoder did not load demo audio'
        result = {'passed': True, 'architecture': platform.machine(), 'system': platform.platform(),
                  'tracks_analysed': len(proposals), 'background_analysis': True, 'demo_apply_restore': True,
                  'drag_zoom_and_rebuild': True, 'single_confirmation_playlist_apply': True,
                  'encrypted_database_dependency': True, 'media_decoder': True,
                  'grid_notes': [p.grid_note for p in proposals]}
        window.player.stop()
        window.player.setSource(QUrl())
        window.close()
        app.processEvents()
        (output / 'selftest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
