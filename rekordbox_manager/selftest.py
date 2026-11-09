"""Packaged-app smoke test using only a disposable synthetic library."""
import json
import os
import platform
from pathlib import Path
import tempfile
import time
from copy import deepcopy


def run(output: Path):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QUrl, QPoint, Qt
    from PySide6.QtTest import QTest
    from .demo import create_demo, DemoLibrary
    from .analysis import render_metronome
    from .backups import BackupStore, digest
    from .ui import MainWindow
    from .dialogs import ImportDialog
    from PySide6.QtWidgets import QDialog
    from sqlcipher3 import dbapi2 as cipher
    from pyrekordbox.masterdb.database import BLOB
    from pyrekordbox.utils import deobfuscate

    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="rekordbox-manager-selftest-") as temp:
        root = Path(temp).resolve()
        os.environ['REKORDBOX_MANAGER_DATA_DIR'] = str(root)
        window = MainWindow()
        # A hidden error dialog must fail automation, never wait for a click.
        def fail_test(error):
            raise RuntimeError(str(error))
        window.fail = fail_test
        window.show()
        app.processEvents()
        window.grab().save(str(output / 'welcome.png'))
        saved_database = root / 'remembered-master.db'
        saved_database.touch()
        window.config_file.write_text(json.dumps({'last_database': str(saved_database)}))
        remembered_window = MainWindow()
        assert remembered_window.startup_database_state == 'saved'
        assert remembered_window.startup_database_card.property('state') == 'saved'
        assert remembered_window.library is None and not remembered_window.continue_button.isEnabled()
        remembered_window.show()
        app.processEvents()
        remembered_window.grab().save(str(output / 'welcome-saved-library.png'))
        remembered_window.close()
        library = DemoLibrary(create_demo(root / 'Demo'))
        window.pages.setCurrentWidget(window.workspace)
        window.fix_grid.setChecked(True)
        window.set_library(library)
        window.set_playlist_selection(("all", "house"))
        assert len(window.tracks) == 3
        window.ignore_cued.setChecked(True)
        assert not window.tracks and window.ignored_track_count == 3
        assert not window.analyse_button.isEnabled() and not window.apply_button.isEnabled()
        app.processEvents()
        window.grab().save(str(output / 'ignored-existing-cues.png'))
        window.ignore_cued.setChecked(False)
        assert len(window.tracks) == 3 and window.ignored_track_count == 0
        # A synthetic ANLZ pair exercises the saved-data route inside the
        # packaged executable; the other demo tracks exercise audio fallback.
        import struct
        import numpy as np
        import soundfile as sf
        fixture_track = window.tracks[0]
        samples, sample_rate = sf.read(str(fixture_track.path), dtype='float32')
        edges = (np.arange(int(np.ceil(len(samples)/sample_rate*150))) * sample_rate/150).astype(int)
        heights = np.maximum.reduceat(np.abs(samples), edges)
        heights /= max(float(heights.max()), 1e-6)
        words = (np.round(heights**2*31).astype(np.uint16) << 2).astype('>u2')
        bands = np.column_stack([heights, heights*.3, heights*.1])
        def fixture_file(suffix, kind, payload, size):
            tag = struct.pack('>4s5I', kind, 24, 24+len(payload), size, len(payload)//size, 0)+payload
            filename = root / ('saved-waveform'+suffix)
            filename.write_bytes(struct.pack('>4s6I', b'PMAI', 28, 28+len(tag), 0, 0, 0, 0)+tag)
            return filename
        fixture_track.analysis_paths += [
            fixture_file('.EXT', b'PWV5', words.tobytes(), 2),
            fixture_file('.2EX', b'PWV7', np.round(bands*127).astype(np.uint8).tobytes(), 3)]
        from .dialogs import PlaylistDialog
        picker = PlaylistDialog(window, library.playlists, window.selected_playlist_ids())
        picker.show()
        app.processEvents()
        picker.grab().save(str(output / 'playlist-picker.png'))
        picker.close()
        window.select_track()
        assert not window.proposals and window.analysis_scope is None
        assert window.wave.proposal.waveform_data.source == 'Rekordbox saved waveform'
        assert not window.apply_button.isEnabled() and not window.first.isEnabled()
        assert not window.play.isEnabled() and window.player.source().isEmpty()
        app.processEvents()
        window.grab().save(str(output / 'saved-preview.png'))
        window.start_analysis()
        deadline = time.monotonic() + 180
        while (not window.proposals or window.worker.isRunning()) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert window.proposals and not window.worker.isRunning(), 'Background analysis did not complete'
        proposals = window.proposals
        assert all(not p.error for p in proposals), [p.error for p in proposals]
        assert all(p.first_drop is not None and p.second_drop is not None for p in proposals)
        assert proposals[0].waveform_data.source == 'Rekordbox saved waveform'
        assert proposals[0].waveform_data.sample_rate == 150
        assert proposals[0].waveform_data.channels
        assert 'Audio fallback' in proposals[1].waveform_data.source
        assert window.analyse_button.text() == 'Set cues + grid'
        # A deterministic review case exercises the queue and cue-only retry.
        proposals[0].review_note = 'Automatic timing check inconclusive. Listen and check both drops, then confirm review.'
        window.populate_table()
        window.review_filter.setCurrentIndex(1)
        assert window.table.visible_rows() == [0]
        assert window.wave.zoom == 16 and window.wave.view_center == proposals[0].first_drop
        app.processEvents()
        window.grab().save(str(output / 'needs-review.png'))
        original_grid, original_cues = deepcopy(proposals[0].grid), proposals[0].cues.copy()
        assert window.confirm_review_button.isEnabled()
        window.confirm_review_button.click()
        assert proposals[0].ready_to_apply and proposals[0].reviewed
        assert proposals[0].grid == original_grid and proposals[0].cues == original_cues
        assert window.table.visible_rows() == [] and not window.backups.list()
        proposals[0].review_note = 'Automatic timing check inconclusive.'
        proposals[0].reviewed = proposals[0].grid_approved = False
        window.populate_table()
        window.auto_cue_button.click()
        deadline = time.monotonic() + 180
        while (window.analysis_busy or window.worker.isRunning()) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert not window.analysis_busy and not window.worker.isRunning()
        assert window.proposals[0].ready_to_apply and not window.proposals[0].options.fix_grid
        assert window.proposals[0].grid == window.proposals[0].track.grid
        assert all(window.proposals[i] is proposals[i] for i in (1, 2))
        assert window.table.visible_rows() == [] and not window.backups.list()
        app.processEvents()
        window.grab().save(str(output / 'review-complete.png'))
        window.review_filter.setCurrentIndex(0)
        # Continue the existing grid-import checks with their original proposals.
        proposals[0].grid_issue = ''
        proposals[0].cues_dirty = False
        proposals[0].review_note = ''
        window.proposals = proposals
        window.populate_table()
        window.table.selectRow(0)
        window.select_track()
        app.processEvents()
        from .waveform import Waveform
        window.settings_button.click()
        assert window.tabs.currentIndex() == 2
        assert window.waveform_style_combo.isVisible()
        assert window.waveform_style_combo.count() == len(Waveform.STYLES)
        for index, style in enumerate(Waveform.STYLES):
            window.waveform_style_combo.setCurrentIndex(index)
            assert window.wave.waveform_style == style
            assert window.wave.proposal.waveform_data is not None
            window.tabs.setCurrentIndex(0)
            app.processEvents()
            window.wave.grab().save(str(output / f'waveform-{style}.png'))
            window.tabs.setCurrentIndex(2)
        assert json.loads(window.config_file.read_text())['waveform_style'] == 'stereo'
        window.waveform_style_combo.setCurrentIndex(0)
        app.processEvents()
        window.grab().save(str(output / 'settings.png'))
        window.tabs.setCurrentIndex(0)
        app.processEvents()
        window.grab().save(str(output / 'manager.png'))
        window.resize(1050, 720)
        app.processEvents()
        window.grab().save(str(output / 'manager-compact.png'))
        window.resize(1280, 870)
        app.processEvents()
        p = proposals[0]
        print('Checking grid alignment and marker editing', flush=True)
        window.grid_anchor_buttons[1].click()
        assert p.grid_anchor == 2 and not p.ready_to_apply
        window.confirm_review_button.click()
        assert p.ready_to_apply
        assert p.grid.times[p.grid.nearest_downbeat(p.second_drop)] == p.second_drop
        window.focus_drop(1)
        original_anchor = p.first_drop
        handle = window.wave.marker_rect(1).center().toPoint()
        moved = handle + QPoint(100, 0)
        QTest.mousePress(window.wave, Qt.LeftButton, pos=handle)
        QTest.mouseMove(window.wave, moved)
        QTest.mouseRelease(window.wave, Qt.LeftButton, pos=moved)
        app.processEvents()
        assert p.first_drop != original_anchor and p.cues_dirty and not p.can_apply
        # Both user-edited anchors must retain a common bar phase.
        window.second.setValue(p.second_drop + p.first_drop - original_anchor)
        window.rebuild_cues()
        print('Checking playlist import and restore', flush=True)
        assert not p.cues_dirty and not p.reviewed
        assert window.confirm_review_button.isEnabled()
        window.confirm_review_button.click()
        assert p.ready_to_apply
        app.processEvents()
        window.grab().save(str(output / 'zoomed.png'))
        original = library.fingerprints.copy()
        store = window.backups
        assert window.apply_button.isEnabled()
        original_question = ImportDialog.exec
        original_information = QMessageBox.information
        try:
            def confirm_import(dialog):
                assert dialog.playlist_table.rowCount() == 2
                assert [dialog.playlist_table.item(i, 1).text() for i in range(2)] == ['3', '1']
                assert [dialog.playlist_table.item(i, 2).text() for i in range(2)] == ['3', '1']
                dialog.show()
                app.processEvents()
                dialog.grab().save(str(output / 'import-summary.png'))
                dialog.details_toggle.click()
                app.processEvents()
                dialog.grab().save(str(output / 'import-details.png'))
                dialog.close()
                return QDialog.Accepted
            ImportDialog.exec = confirm_import
            QMessageBox.information = lambda *args: QMessageBox.Ok
            window.apply_changes()
        finally:
            ImportDialog.exec = original_question
            QMessageBox.information = original_information
        snapshots = store.list()
        assert len(snapshots) == 1, 'Playlist apply did not create one backup'
        snapshot = snapshots[0][0]
        assert all(len([c for c in track.cues if c.kind == 'memory']) == 10
                   for track in window.tracks)
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
                  'explicit_drop_grid_alignment': True,
                  'saved_rekordbox_waveforms': True, 'audio_waveform_fallback': True,
                  'saved_preview_before_preparation': True,
                  'review_filter_and_batch_cue_only': True,
                  'confirm_review_preserves_timings': True,
                  'ignore_existing_saved_cues': True,
                  'encrypted_database_dependency': True, 'media_decoder': True,
                  'multi_playlist_deduplication': True, 'playlist_import_breakdown': True,
                  'waveform_styles': list(Waveform.STYLES), 'waveform_settings_verified': True,
                  'grid_notes': [p.grid_note for p in proposals]}
        window.player.stop()
        window.player.setSource(QUrl())
        window.close()
        app.processEvents()
        (output / 'selftest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
