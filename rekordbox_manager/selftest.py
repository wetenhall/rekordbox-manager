"""Packaged-app smoke test using only a disposable synthetic library."""
import json
import os
import platform
from pathlib import Path
import tempfile
import time
from copy import deepcopy


def run(output: Path):
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QToolTip
    from PySide6.QtCore import QUrl, QPoint, Qt, QEvent
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtTest import QTest
    from PySide6.QtMultimedia import QMediaPlayer
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
        # Exercise actual tooltip requests, including controls created after startup.
        hover_dialog = QDialog(window)
        hover_button = QPushButton('Hover test', hover_dialog)
        hover_button.setToolTip('This hover popup must not appear.')
        for control in (window.confirm, window.wave, hover_button):
            QApplication.sendEvent(control, QHelpEvent(QEvent.ToolTip, QPoint(1, 1), control.mapToGlobal(QPoint(1, 1))))
            app.processEvents()
            assert not QToolTip.isVisible(), 'Hover tooltips must stay hidden'
        hover_dialog.deleteLater()
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
        remembered_window.confirm.setChecked(True)
        app.processEvents()
        remembered_window.grab().save(str(output / 'welcome-ready.png'))
        remembered_window.resize(1050, 720)
        app.processEvents()
        remembered_window.grab().save(str(output / 'welcome-compact.png'))
        remembered_window.close()
        library = DemoLibrary(create_demo(root / 'Demo'))
        window.pages.setCurrentWidget(window.workspace)
        window.fix_grid.setChecked(True)
        window.set_library(library)
        window.set_playlist_selection(("all", "house"))
        assert len(window.tracks) == 3
        window.ignore_cued.setChecked(True)
        assert not window.tracks and window.ignored_track_count == 3
        assert not window.analyse_button.isEnabled()
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
        window.populate_table()
        deadline = time.monotonic() + 30
        while window.overview_worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert window.overview_worker is None
        assert all(len(preview.peaks) and len(preview.bass) for preview in window.row_previews)
        assert not window.proposals and not window.import_queue.entries
        window.grab().save(str(output / 'automatic-playlist-previews.png'))
        from .dialogs import PlaylistDialog
        picker = PlaylistDialog(window, library.playlists, window.selected_playlist_ids())
        picker.show()
        app.processEvents()
        picker.grab().save(str(output / 'playlist-picker.png'))
        picker.close()
        window.select_track()
        assert not window.proposals and window.analysis_scope is None
        assert window.wave.proposal.waveform_data.source == 'Rekordbox saved waveform'
        assert not window.first.isEnabled()
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
        assert window.analyse_button.text() == 'Scan && prepare playlists'
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
        app.processEvents()
        window.grab().save(str(output / 'review-ready.png'))
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
        QTest.mouseClick(window.navigation, Qt.LeftButton,
                         pos=window.navigation.tabRect(window.tabs.indexOf(window.settings_tab)).center())
        assert window.tabs.currentWidget() is window.settings_tab
        assert window.waveform_style_combo.isVisible()
        assert window.waveform_style_combo.count() == len(Waveform.STYLES)
        for index, style in enumerate(Waveform.STYLES):
            window.waveform_style_combo.setCurrentIndex(index)
            assert window.wave.waveform_style == style
            assert window.wave.proposal.waveform_data is not None
            window.tabs.setCurrentWidget(window.manager_tab)
            app.processEvents()
            window.wave.grab().save(str(output / f'waveform-{style}.png'))
            window.tabs.setCurrentWidget(window.settings_tab)
        assert json.loads(window.config_file.read_text())['waveform_style'] == 'stereo'
        window.waveform_style_combo.setCurrentIndex(0)
        app.processEvents()
        window.grab().save(str(output / 'settings.png'))
        window.tabs.setCurrentWidget(window.manager_tab)
        window.playlist_browser.tree.expandAll()
        assert window.playlist_browser.items['house'].parent().text(0) == 'Demo'
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
        window.sync_import_queue()
        window.set_playlist_selection(('house',))
        assert len(window.tracks) == 1 and len(window.import_queue.ready()) == 3
        window.tabs.setCurrentWidget(window.imports_tab)
        app.processEvents()
        window.grab().save(str(output / 'imports.png'))
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
            window.imports_tab.import_button.click()
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
        db.executescript('''
            CREATE TABLE djmdContent(ID TEXT, Title TEXT, ArtistID TEXT, GenreID TEXT, FolderPath TEXT, DJPlayCount INTEGER);
            CREATE TABLE djmdArtist(ID TEXT, Name TEXT);
            CREATE TABLE djmdGenre(ID TEXT, Name TEXT);
            CREATE TABLE djmdCue(ContentID TEXT);
            CREATE TABLE djmdPlaylist(ID TEXT, Name TEXT, ParentID TEXT, Attribute INTEGER, Seq INTEGER);
            CREATE TABLE djmdSongPlaylist(ContentID TEXT, PlaylistID TEXT);
            CREATE TABLE djmdHistory(ID TEXT);
            CREATE TABLE djmdSongHistory(ContentID TEXT, HistoryID TEXT);
            INSERT INTO djmdContent VALUES('zero','Unplayed example','a','g','',0),
                ('played','History example','a','g','',0), ('unknown','Unknown example','a','g','',NULL);
            INSERT INTO djmdPlaylist VALUES('folder','Playlists',NULL,1,1),('p','Rediscover','folder',0,1);
            INSERT INTO djmdSongPlaylist VALUES('played','p');
            INSERT INTO djmdArtist VALUES('a','Synthetic artist');
            INSERT INTO djmdGenre VALUES('g','House');
            INSERT INTO djmdHistory VALUES('h');
            INSERT INTO djmdSongHistory VALUES('played','h');
        ''')
        db.commit()
        db.close()
        assert (root / 'test.db').read_bytes()[:16] != b'SQLite format 3\0'
        from .library import RekordboxLibrary
        window.usage_tab.set_library(RekordboxLibrary(root / 'test.db'))
        window.tabs.setCurrentWidget(window.usage_tab)
        before_scan = digest(root / 'test.db')
        window.usage_tab.scan_button.click()
        deadline = time.monotonic() + 30
        while window.usage_tab.scanning and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert not window.usage_tab.scanning and window.usage_tab.scan is not None
        window.usage_tab.filter.setCurrentIndex(window.usage_tab.filter.findData('unplayed'))
        assert [t.id for t in window.usage_tab.matches] == ['zero']
        assert {t.id: t.play_status for t in window.usage_tab.scan.tracks} == {
            'zero': 'No recorded plays', 'played': 'Played', 'unknown': 'Unknown'}
        assert digest(root / 'test.db') == before_scan
        app.processEvents()
        window.usage_tab.browser.tree.setCurrentItem(window.usage_tab.browser.items['p'])
        assert [t.id for t in window.usage_tab.matches] == ['played']
        window.usage_tab.browser.items['folder'].setExpanded(True)
        app.processEvents()
        window.grab().save(str(output / 'organiser-playlist.png'))
        window.usage_tab.collection_button.click()
        assert len(window.usage_tab.matches) == 3
        from .track_list import TrackList
        assert isinstance(window.usage_tab.list, TrackList)
        app.processEvents()
        window.grab().save(str(output / 'library-usage.png'))
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QCheckBox
        selection = next(c for c in window.usage_tab.list.widget().findChildren(QCheckBox)
                         if 'Unplayed example' in c.accessibleName())
        QTest.mouseClick(selection, Qt.LeftButton)
        assert window.usage_tab.selected_ids == {'zero'}
        QTest.mouseClick(selection, Qt.LeftButton)
        assert not window.usage_tab.selected_ids
        organiser_size = window.size()
        window.resize(1050, 720)
        app.processEvents()
        window.grab().save(str(output / 'organiser-compact.png'))
        window.resize(organiser_size)
        # Draft UI only: this metadata fixture intentionally cannot perform live writes.
        from .organiser_dialogs import NewPlaylistDialog
        page = window.usage_tab
        page.write_problem = ''
        page.update_selection()
        original_create = NewPlaylistDialog.exec
        try:
            def create_folder(dialog):
                dialog.name.setText('Rediscovered')
                return QDialog.Accepted
            NewPlaylistDialog.exec = create_folder
            page.new_folder.click()
            page.selected_ids = {'zero'}
            def create_playlist(dialog):
                dialog.name.setText('Next set')
                return QDialog.Accepted
            NewPlaylistDialog.exec = create_playlist
            page.new_playlist.click()
        finally:
            NewPlaylistDialog.exec = original_create
        assert len(window.organiser_queue.nodes) == 2
        assert sum(len(rows) for rows in window.organiser_queue.assignments.values()) == 1
        assert digest(root / 'test.db') == before_scan
        app.processEvents()
        window.grab().save(str(output / 'organiser-drafts.png'))
        draft_folder, draft_playlist = window.organiser_queue.nodes
        page.move_draft(draft_playlist.identity, None, 'folder')
        assert window.organiser_queue.view().playlist_nodes[0].identity == draft_playlist.identity
        page.move_draft('folder', draft_folder.identity, None)
        assert next(n for n in window.organiser_queue.view().playlist_nodes if n.identity == 'folder').parent_id == draft_folder.identity
        assert window.organiser_queue.structure_changes()
        assert digest(root / 'test.db') == before_scan
        page.folder_actions(page.browser.items[draft_folder.identity], 0)
        app.processEvents()
        assert [a.text() for a in page.folder_menu.actions()] == ['New subfolder…', 'New playlist…']
        page.folder_menu.grab().save(str(output / 'folder-actions.png'))
        page.folder_menu.close()
        app.processEvents()
        window.grab().save(str(output / 'organiser-reordered.png'))
        # Select a range through the actual row widgets, then drop onto a draft playlist.
        from PySide6.QtCore import QMimeData, QPoint, QPointF
        from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
        from .organiser_tracks import TRACK_MIME
        page.show_collection()
        page.filter.setCurrentIndex(page.filter.findData('all'))
        page.apply_filters()
        app.processEvents()
        for row, modifiers in ((0, Qt.NoModifier), (len(page.matches) - 1, Qt.ShiftModifier)):
            target_row = page.list._buttons[row].layout().itemAt(0).widget()
            QTest.mouseClick(target_row, Qt.LeftButton, modifiers, QPoint(180, 14))
        selected = tuple(t.id for t in page.selected_tracks())
        assert len(selected) == 3 and all(button.isChecked() for button in page.list._buttons)
        tree = page.browser.tree
        page.list.active_drag = (page.library, page.scan, selected)
        mime = QMimeData()
        mime.setData(TRACK_MIME, b'1')
        point = tree.visualItemRect(page.browser.items[draft_playlist.identity]).center()
        class TrackEnter(QDragEnterEvent):
            def source(self): return page.list
        class TrackMove(QDragMoveEvent):
            def source(self): return page.list
        class TrackDrop(QDropEvent):
            def source(self): return page.list
        tree.dragEnterEvent(TrackEnter(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        tree.dragMoveEvent(TrackMove(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
        app.processEvents()
        window.grab().save(str(output / 'organiser-track-drag.png'))
        drop = TrackDrop(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        tree.dropEvent(drop)
        page.list.active_drag = None
        assert drop.isAccepted() and set(page.queue.assignments[draft_playlist.identity]) == set(selected)
        assert digest(root / 'test.db') == before_scan
        app.processEvents()
        window.grab().save(str(output / 'organiser-tracks-queued.png'))
        page.filter.setCurrentIndex(page.filter.findData('outside'))
        assert not page.matches and not page.selected_ids
        assert '0 outside regular playlists' in page.summary.text()
        page.filter.setCurrentIndex(page.filter.findData('all'))
        assert len(page.matches) == 3
        window.tabs.setCurrentWidget(window.imports_tab)
        window.imports_tab.queue_view.setCurrentIndex(1)
        app.processEvents()
        window.grab().save(str(output / 'playlist-imports.png'))
        window.organiser_queue.reset(window.library)
        window.imports_tab.queue_view.setCurrentIndex(0)
        window.refresh_imports()
        window.tabs.setCurrentWidget(window.manager_tab)
        window.player.setSource(QUrl.fromLocalFile(str(p.track.path)))
        deadline = time.monotonic() + 8
        while window.player.duration() == 0 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert window.player.duration() > 0, 'Packaged multimedia decoder did not load demo audio'
        # Disposable manual-cue fixtures: one misplaced cue, one app-pattern
        # track, and one track with only its protected hot cue.
        from dataclasses import asdict, replace
        from .backups import durable_json
        for row in library.data['tracks'][:2]:
            source = next(proposal for proposal in proposals if proposal.track.id == row['id'])
            memories = [cue for cue in source.cues if cue.kind == 'memory']
            if row is library.data['tracks'][0]:
                memories[0] = replace(memories[0], time=memories[0].time + 1)
            row['cues'] += [asdict(cue) for cue in memories]
        durable_json(library.path, library.data)
        library.reload()
        # Check saved cues in Manager: suggestions are editable immediately,
        # but do not enter the import queue without confirmation.
        window.scan_mode.setCurrentIndex(1)
        window.set_playlist_selection(('all',))
        assert window.original_wave_box.isHidden() and window.proposed_wave_label.isHidden()
        assert window.wave.cue_view == 'saved' and window.wave.saved_cues
        app.processEvents()
        window.grab().save(str(output / 'cue-check-before-scan.png'))
        audit_before = {name: digest(library.root / name) for name in library.fingerprints}
        queue_before = list(window.import_queue.pending())
        window.start_analysis()
        deadline = time.monotonic() + 60
        while window.analysis_busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert not window.analysis_busy and len(window.audit_results) == 3
        assert not window.proposals and window.selected() is not None and not window.selected().ready_to_apply
        assert any(check.missing or check.extra for check in window.audit_results.values())
        assert any(check.status == 'No memory cues' for check in window.audit_results.values())
        assert window.wave.comparison_cues and window.play.isEnabled()
        assert window.original_wave_box.isVisible() and window.proposed_wave_label.isVisible()
        deadline = time.monotonic() + 8
        while window.player.duration() == 0 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        window.activateWindow()
        window.focus_transport()
        app.processEvents()
        window.player.pause()
        window.seek(1.)
        QTest.keyClick(window.wave, Qt.Key_Space)
        deadline = time.monotonic() + 8
        while window.player.position() < 1150 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert window.player.playbackState() == QMediaPlayer.PlayingState and window.player.position() >= 1150
        QTest.keyClick(window.wave, Qt.Key_Space)
        assert window.player.playbackState() == QMediaPlayer.PausedState
        first_identity = window.wave.proposal.track.id
        QTest.keyClick(window.wave, Qt.Key_Down)
        assert window.table.currentRow() == 1 and window.wave.proposal.track.id != first_identity
        assert window.player.source().toLocalFile() == str(window.wave.proposal.track.path)
        QTest.keyClick(window.wave, Qt.Key_Up)
        assert window.table.currentRow() == 0 and window.wave.proposal.track.id == first_identity
        deadline = time.monotonic() + 8
        while window.player.duration() == 0 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        window.seek(1.)
        window.press_cue()
        cue_start = window.cue_position
        deadline = time.monotonic() + 8
        while window.player.position() / 1000 + window.playback_offset() < cue_start + .15 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert window.cue_held and window.player.position() / 1000 + window.playback_offset() >= cue_start + .15
        window.release_cue()
        app.processEvents()
        assert not window.cue_held and window.player.playbackState() != QMediaPlayer.PlayingState
        assert abs(window.player.position() / 1000 + window.playback_offset() - cue_start) < .02
        assert list(window.import_queue.pending()) == queue_before
        assert window.first.isEnabled() and window.second.isEnabled()
        assert audit_before == {name: digest(library.root / name) for name in library.fingerprints}
        window.playlist_browser.tree.expandAll()
        app.processEvents()
        window.grab().save(str(output / 'cue-check.png'))
        window.resize(1050, 720)
        app.processEvents()
        window.grab().save(str(output / 'cue-check-compact.png'))
        window.start_analysis()
        deadline = time.monotonic() + 10
        while window.analysis_busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.02)
        assert not window.analysis_busy and window.worker.cache_hits == 3
        # Repair one checked track without leaving Manager or writing before
        # explicit confirmation and import. Other playlist tracks stay untouched.
        window.table.selectRow(0)
        assert abs(window.first.value() - window.current_audit().candidate.first_drop) < .001
        repair = window.selected()
        assert repair and repair.options.set_cues and repair.options.replace_memory and not repair.options.fix_grid
        assert not repair.ready_to_apply and not window.import_queue.pending()
        grid_before = deepcopy(repair.track.grid)
        protected = [c for c in repair.track.cues if c.kind != 'memory']
        window.first.setValue(repair.first_drop + .125)
        assert repair.cues_dirty and not window.confirm_review_button.isEnabled()
        window.rebuild_cues()
        assert window.confirm_review_button.isEnabled() and not window.import_queue.pending()
        window.grid_right.click()
        assert repair.options.fix_grid and repair.cues_dirty
        expected_grid = deepcopy(repair.grid)
        assert window.original_wave.proposal.grid == grid_before and expected_grid != grid_before
        window.rebuild_cues()
        assert repair.grid == expected_grid and window.confirm_review_button.isEnabled()
        window.wave.reset_view()
        assert window.original_wave.visible_range() == window.wave.visible_range()
        app.processEvents()
        assert window.width() == 1050 and window.height() == 720
        window.grab().save(str(output / 'cue-replacement-compact.png'))
        window.resize(1280, 870)
        app.processEvents()
        window.grab().save(str(output / 'cue-replacement.png'))
        window.confirm_review()
        assert [entry.proposal for entry in window.import_queue.ready()] == [repair]
        assert window.selected() is not repair and window.audit_needs_review(window.selected().track.id)
        repair_row = next(i for i, t in enumerate(window.tracks) if t.id == repair.track.id)
        window.table.selectRow(repair_row)
        window.keep_original_button.click()
        assert not window.import_queue.pending() and window.original_cues_kept(repair.track.id)
        assert window.selected() is not repair and window.audit_needs_review(window.selected().track.id)
        window.table.selectRow(repair_row)
        assert window.confirm_review_button.text() == 'Use cues + grid' and window.confirm_review_button.isEnabled()
        assert audit_before == {name: digest(library.root / name) for name in library.fingerprints}
        window.confirm_review_button.click()
        assert not window.original_cues_kept(repair.track.id)
        assert [entry.proposal for entry in window.import_queue.ready()] == [repair]
        assert not window.table._buttons[0].property('needsReview')
        assert not window.audit_needs_review(repair.track.id)
        app.processEvents()
        window.grab().save(str(output / 'cue-replacement-queued.png'))
        assert audit_before == {name: digest(library.root / name) for name in library.fingerprints}
        originals = {t.id: deepcopy(t) for t in library.tracks('all')}
        expected_cues = repair.cues.copy()
        original_question, original_information = ImportDialog.exec, QMessageBox.information
        try:
            ImportDialog.exec = lambda self: QDialog.Accepted
            QMessageBox.information = lambda *args: QMessageBox.Ok
            window.import_queued_tracks()
        finally:
            ImportDialog.exec, QMessageBox.information = original_question, original_information
        assert not window.import_queue.pending()
        updated = {t.id: t for t in library.tracks('all')}
        assert updated[repair.track.id].cues == expected_cues
        assert updated[repair.track.id].grid == expected_grid
        assert [c for c in updated[repair.track.id].cues if c.kind != 'memory'] == protected
        assert all(updated[key] == value for key, value in originals.items() if key != repair.track.id)
        result = {'passed': True, 'organiser_shared_layout': True, 'organiser_draft_creation': True, 'organiser_structure_editing': True, 'organiser_track_drag': True, 'organiser_unassigned_queue_filter': True, 'architecture': platform.machine(), 'system': platform.platform(),
                  'tracks_analysed': len(proposals), 'background_analysis': True, 'demo_apply_restore': True,
                  'drag_zoom_and_rebuild': True, 'single_confirmation_playlist_apply': True,
                  'explicit_drop_grid_alignment': True,
                  'saved_rekordbox_waveforms': True, 'audio_waveform_fallback': True,
                  'saved_preview_before_preparation': True,
                  'review_filter_and_batch_cue_only': True,
                  'confirm_review_preserves_timings': True,
                  'ignore_existing_saved_cues': True,
                  'encrypted_database_dependency': True, 'media_decoder': True,
                  'library_usage_readonly_scan': True, 'feature_tabs': True, 'manager_cue_check_readonly': True,
                  'cross_playlist_import_queue': True,
                  'automatic_bass_playlist_previews': True,
                  'audit_replacement_review_and_import': True, 'keep_original_cues_removes_import': True,
                  'hold_cue_transport': True,
                  'hover_tooltips_disabled': True, 'automatic_review_navigation': True, 'conditional_comparison_waveforms': True, 'audit_keyboard_transport': True, 'queued_replacement_clears_highlight': True, 'dual_waveform_manual_grid_import': True,
                  'multi_playlist_deduplication': True, 'playlist_import_breakdown': True,
                  'waveform_styles': list(Waveform.STYLES), 'waveform_settings_verified': True,
                  'grid_notes': [p.grid_note for p in proposals]}
        window.player.stop()
        window.player.setSource(QUrl())
        window.close()
        app.processEvents()
        (output / 'selftest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
