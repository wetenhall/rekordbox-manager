from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import math
import hashlib
import platform

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QFileDialog, QMessageBox, QStackedWidget, QFrame,
    QDoubleSpinBox, QProgressBar, QSplitter, QListWidget, QListView, QStyledItemDelegate, QDialog, QTextEdit,
    QScrollArea, QScrollBar, QSizePolicy, QApplication, QLineEdit, QPlainTextEdit, QAbstractSpinBox,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from .models import Grid, Options, Proposal
from .waveform import Waveform
from .cues import plan_cues
from .analysis import analyse, render_metronome
from .backups import BackupStore, durable_json
from .guards import SafetyError, ensure_rekordbox_closed
from .library import RekordboxLibrary
from .paths import data_dir, discover_databases


STYLE = """
QWidget { background: #0c0e12; color: #e8edf5; font-family: 'Inter', '.AppleSystemUIFont', 'Segoe UI'; font-size: 12px; }
QLabel { background: transparent; }
QMainWindow { background: #0c0e12; }
QLabel#eyebrow { color: #94a4be; font-size: 11px; font-weight: 600; letter-spacing: 2px; }
QLabel#title { font-size: 29px; font-weight: 650; }
QLabel#section { font-size: 17px; font-weight: 600; }
QLabel#muted { color: #98a5ba; }
QLabel#badge { background: #142b49; color: #a7d0ff; padding: 5px 9px; border-radius: 3px; }
QFrame#card { background: #151a23; border: 1px solid #293345; border-radius: 10px; }
QPushButton { background: #1e293b; border: 1px solid #354760; border-radius: 3px; padding: 6px 10px; font-weight: 550; }
QPushButton:hover { background: #253c59; border-color: #72b1ff; }
QPushButton:disabled { color: #6d7b91; background: #1a202c; border-color: #2b3546; }
QPushButton#primary { background: #63a8ff; color: #071426; border: 0; }
QPushButton#primary:hover { background: #8cc0ff; }
QPushButton#primary:disabled { background: #243d60; color: #8c9eb8; }
QPushButton#rebuildCues[needsRebuild="true"] { background: #efb34f; color: #171007; border-color: #ffcd7a; }
QPushButton#rebuildCues[needsRebuild="true"]:hover { background: #ffcb78; }
QPushButton#rebuildCues:disabled { background: #1a202c; color: #6d7b91; border-color: #2b3546; }
QComboBox, QDoubleSpinBox { background: #0e131d; border: 1px solid #3a4a63; border-radius: 3px; padding: 4px; min-height: 18px; }
QComboBox QAbstractItemView { background: #172238; selection-background-color: #25466c; }
QCheckBox { spacing: 9px; background: transparent; padding: 3px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #70839f; border-radius: 4px; background: #121c2b; }
QCheckBox::indicator:checked { background: #63a8ff; border: 3px solid #326cb4; }
QPushButton#track { background: #111419; text-align: left; padding: 0; border: 0; border-bottom: 1px solid #20252c; border-radius: 0; }
QPushButton#track[alternate="true"] { background: #181c22; }
QPushButton#track:hover { background: #25364a; }
QPushButton#track QLabel { background: transparent; font-weight: 400; }
QPushButton#track:focus { border: 1px solid #69acff; }
QFrame#deck { background: #090c11; border: 1px solid #272f3a; }
QFrame#browser { background: #101318; border: 1px solid #272f3a; }
QWidget#columnHeader { background: #20252d; border-bottom: 1px solid #39414c; }
QWidget#columnHeader QLabel { color: #a9b7c9; font-size: 11px; }
QLabel#brand { font-size: 15px; font-weight: 650; }
QLabel#transportClock { font-size: 19px; font-weight: 600; color: #b8dbff; }
QLabel#deckTitle { font-size: 15px; font-weight: 600; }
QLabel#deckMeta { color: #87bfff; font-size: 12px; }
QSplitter::handle:hover { background: #63a8ff; }
QPushButton#track:checked { background: #214a72; border-left: 3px solid #77baff; }
QListWidget, QTextEdit { background: #111925; border: 1px solid #30425e; border-radius: 6px; padding: 6px; }
QListWidget::item { padding: 9px; }
QListWidget::item:selected { background: #24486f; }
QProgressBar { border: 0; background: #20314c; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: #63a8ff; }
QSplitter::handle { background: #2c3746; height: 6px; }
QScrollBar:vertical { background: #111925; width: 9px; }
QScrollBar::handle:vertical { background: #3d5578; border-radius: 4px; min-height: 25px; }
QScrollBar:horizontal { background: #111925; height: 14px; }
QScrollBar::handle:horizontal { background: #3d5578; border-radius: 4px; min-width: 28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QToolTip { background: #192b45; color: #e5efff; border: 1px solid #5078aa; }
"""


def label(text: str, kind: str = "", wrap: bool = False) -> QLabel:
    result = QLabel(text)
    result.setTextFormat(Qt.PlainText)
    result.setWordWrap(wrap)
    if kind:
        result.setObjectName(kind)
    return result


def button(text: str, callback, primary=False) -> QPushButton:
    result = QPushButton(text)
    if primary:
        result.setObjectName("primary")
    result.clicked.connect(callback)
    return result


def time_text(seconds: float) -> str:
    return f"{int(seconds) // 60}:{seconds % 60:05.2f}"


class ElidedLabel(QLabel):
    """One-line text that keeps long titles and warnings from widening the window."""
    def __init__(self, text="", kind=""):
        super().__init__()
        self.full_text = ""
        self.setTextFormat(Qt.PlainText)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if kind:
            self.setObjectName(kind)
        self.setText(text)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self.full_text.replace("\n", " · "),
                                                    Qt.ElideRight, max(0, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


def track_columns(parent, values):
    layout = QHBoxLayout(parent)
    layout.setContentsMargins(10, 0, 10, 0)
    layout.setSpacing(12)
    # Same geometry for header and rows; title/artist take the spare width.
    for text, width, stretch in zip(values, (32, 0, 0, 158, 62, 72, 118), (0, 3, 2, 0, 0, 0, 0)):
        cell = ElidedLabel(text)
        cell.setAttribute(Qt.WA_TransparentForMouseEvents)
        if width:
            cell.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            cell.setFixedWidth(width)
        layout.addWidget(cell, stretch)
    return layout


class TrackList(QScrollArea):
    """Ordinary accessible buttons avoid Qt's macOS table AX ownership bug.

    See QTBUG-149612. Keep native accessibility enabled for every track.
    """
    itemSelectionChanged = Signal()

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._selected = -1
        self._buttons = []

    def set_rows(self, rows):
        self._selected = -1
        old = self.takeWidget()
        if old:
            old.deleteLater()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._buttons = []
        for index, values in enumerate(rows):
            title, genre, bpm, memory, status = values
            title, _, artist = title.partition("\n")
            text = f"{title} · {artist} · {genre} · {bpm} BPM · Memory {memory} · {status}"
            item = QPushButton()
            item.setFixedHeight(28)
            item.setObjectName('track')
            item.setProperty('alternate', bool(index % 2))
            item.setAccessibleName(text)
            item.setToolTip(text)
            item.setCheckable(True)
            track_columns(item, [str(index + 1), title, artist, genre, bpm, memory, status])
            item.clicked.connect(lambda checked=False, row=index: self.selectRow(row))
            layout.addWidget(item)
            self._buttons.append(item)
        layout.addStretch()
        self.setWidget(content)

    def currentRow(self):
        return self._selected

    def selectRow(self, index):
        if 0 <= index < len(self._buttons):
            self._selected = index
            for row, item in enumerate(self._buttons):
                item.setChecked(row == index)
            self.ensureWidgetVisible(self._buttons[index])
            self.itemSelectionChanged.emit()


class MetronomeWorker(QThread):
    done = Signal(str, str)

    def __init__(self, track, grid, path):
        super().__init__()
        self.track, self.grid, self.path = track, grid, path

    def run(self):
        try:
            render_metronome(self.track, self.grid, self.path)
            self.done.emit(str(self.path), "")
        except Exception as exc:
            self.done.emit("", str(exc))


class AnalysisWorker(QThread):
    progress = Signal(int, str)
    result = Signal(object)

    def __init__(self, tracks, options):
        super().__init__()
        self.tracks, self.options = tracks, options

    def run(self):
        results = []
        for i, track in enumerate(self.tracks):
            if self.isInterruptionRequested():
                break
            self.progress.emit(i, track.title)
            results.append(analyse(track, self.options))
        self.result.emit(results)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rekordbox Manager · Preview")
        self.resize(1280, 870)
        self.setMinimumSize(1050, 720)
        self.library = None
        self.startup_database = None
        self.proposals: list[Proposal] = []
        self.tracks = []
        self.worker = None
        self.metronome_worker = None
        self.current = -1
        self.base = data_dir()
        self.base.mkdir(parents=True, exist_ok=True)
        self.config_file = self.base / "settings.json"
        try:
            self.settings = json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.settings = {}
        if not isinstance(self.settings, dict):
            self.settings = {}
        self.backups = BackupStore(Path(self.settings.get("backups", str(self.base / "Backups"))))
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(.5)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self.play_position)
        self.player.errorOccurred.connect(lambda error, text: self.status.setText("Playback unavailable: " + text))
        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)
        self.gate = self.build_gate()
        self.pages.addWidget(self.gate)
        self.workspace = self.build_workspace()
        self.pages.addWidget(self.workspace)
        self.setStyleSheet(STYLE)
        self.play_shortcut = QShortcut(QKeySequence("Space"), self)
        self.play_shortcut.setAutoRepeat(False)
        self.play_shortcut.activated.connect(self.toggle_play)
        self.track_shortcuts = []
        for key, step in (("Up", -1), ("Down", 1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(lambda step=step: self.navigate_track(step))
            self.track_shortcuts.append(shortcut)
        self.pages.currentChanged.connect(lambda: self.update_play_shortcut(None, QApplication.focusWidget()))
        self.tabs.currentChanged.connect(lambda: self.update_play_shortcut(None, QApplication.focusWidget()))
        QApplication.instance().focusChanged.connect(self.update_play_shortcut)
        self.update_play_shortcut(None, QApplication.focusWidget())

    def update_play_shortcut(self, old, focused):
        enabled = (focused is not None and focused.window() is self
                   and self.pages.currentWidget() is self.workspace
                   and self.tabs.currentIndex() == 0)
        widget = focused
        while widget is not None and enabled:
            if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
                enabled = False
            widget = widget.parentWidget()
        self.play_shortcut.setEnabled(enabled)
        navigation_enabled = enabled and not getattr(self, "analysis_busy", False)
        widget = focused
        while widget is not None and navigation_enabled:
            if isinstance(widget, QComboBox):
                navigation_enabled = False
            widget = widget.parentWidget()
        for shortcut in self.track_shortcuts:
            shortcut.setEnabled(navigation_enabled)

    def navigate_track(self, step):
        if (not self.proposals or getattr(self, "analysis_busy", False)
                or self.pages.currentWidget() is not self.workspace or self.tabs.currentIndex() != 0):
            return
        current = self.table.currentRow()
        index = (current + step) % len(self.proposals) if current >= 0 else (0 if step > 0 else len(self.proposals) - 1)
        if index != current:
            self.table.selectRow(index)

    def build_gate(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(100, 70, 100, 70)
        outer.addStretch()
        outer.addWidget(label("REKORDBOX MANAGER", "eyebrow"))
        outer.addSpacing(18)
        outer.addWidget(label("Prepare your next set.", "title"))
        outer.addWidget(label("Playlist preparation, with your cue rules.", "muted"))
        outer.addSpacing(34)
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(28, 25, 28, 25)
        box.addWidget(label("Before you continue", "section"))
        box.addSpacing(10)
        box.addWidget(label("Ensure Rekordbox is closed and you have backed up your library.", wrap=True))
        box.addWidget(label("The app checks for Rekordbox background processes too. Never force-quit Rekordbox while it is saving.", "muted", True))
        box.addSpacing(15)
        self.confirm = QCheckBox("I confirm Rekordbox is closed and my library is backed up.")
        box.addWidget(self.confirm)
        box.addSpacing(18)
        box.addWidget(label("Connect your Rekordbox library", "section"))
        box.addWidget(label("Choose your master.db database. Your playlists will be loaded before you continue.", "muted", True))
        self.startup_database_label = label("No database selected", "muted", True)
        box.addWidget(self.startup_database_label)
        self.startup_browse = button("Choose database…", self.choose_startup_database)
        box.addWidget(self.startup_browse)
        self.startup_status = label("", "muted", True)
        box.addWidget(self.startup_status)
        self.continue_button = button("Connect and continue  →", self.enter, True)
        self.continue_button.setEnabled(False)
        self.confirm.toggled.connect(self.update_startup_ready)
        box.addWidget(self.continue_button)
        outer.addWidget(card)
        outer.addSpacing(20)
        outer.addWidget(label("PREVIEW 0.3.5  ·  Grid and memory cue import is available for verified Rekordbox installations. Automatic backups cover the database and changed analysis files.", "muted", True))
        outer.addStretch()
        return page

    def update_startup_ready(self):
        self.continue_button.setEnabled(self.confirm.isChecked() and self.startup_database is not None)

    def choose_startup_database(self):
        path = self.choose_database_path()
        if path:
            self.startup_database = Path(path)
            self.startup_database_label.setText(str(self.startup_database))
            self.startup_status.setText("")
            self.update_startup_ready()

    def enter(self):
        if not self.confirm.isChecked() or self.startup_database is None:
            return
        self.continue_button.setEnabled(False)
        self.startup_browse.setEnabled(False)
        self.confirm.setEnabled(False)
        self.startup_status.setText("Connecting and loading your playlists…")
        QApplication.processEvents()
        try:
            ensure_rekordbox_closed()
            library = RekordboxLibrary(self.startup_database)
            if not self.set_library(library):
                self.startup_status.setText("Could not load the library. Check the database and try again.")
                return
            self.pages.setCurrentWidget(self.workspace)
            self.playlists.setFocus()
            self.startup_status.setText("")
        except Exception as exc:
            self.startup_status.setText("Connection failed. Check the database and try again.")
            self.fail(exc)
        finally:
            self.startup_browse.setEnabled(True)
            self.confirm.setEnabled(True)
            self.update_startup_ready()

    def build_workspace(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)
        toolbar = QHBoxLayout()
        toolbar.addWidget(label("REKORDBOX MANAGER", "brand"))
        toolbar.addWidget(label("0.3.5 · Preview", "muted"))
        toolbar.addStretch()
        self.connect_button = button("Change library…", self.connect_library)
        toolbar.addWidget(self.connect_button)
        toolbar.addWidget(button("Diagnostics…", self.save_diagnostics))
        toolbar.addWidget(button("Backups", self.show_backups))
        self.mode = label("No library connected", "badge")
        toolbar.addWidget(self.mode)
        layout.addLayout(toolbar)
        self.tabs = QStackedWidget()
        self.tabs.addWidget(self.build_manager())
        self.tabs.addWidget(self.build_backups())
        layout.addWidget(self.tabs, 1)
        return page

    def build_manager(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.notice = label("Connect your Rekordbox library to choose a playlist.", "muted", True)
        box.addWidget(self.notice)
        self.deck_splitter = QSplitter(Qt.Vertical)
        self.deck_splitter.setChildrenCollapsible(False)
        self.deck_splitter.setHandleWidth(6)
        self.deck_splitter.setAccessibleName("Resize waveform deck and playlist")
        deck = QFrame()
        deck.setObjectName("deck")
        deck_box = QVBoxLayout(deck)
        deck_box.setContentsMargins(10, 7, 10, 7)
        deck_box.setSpacing(5)
        heading = QHBoxLayout()
        self.review_title = ElidedLabel("Select a track after analysing your playlist", "deckTitle")
        heading.addWidget(self.review_title, 1)
        self.deck_meta = label("— BPM  ·  — cues", "deckMeta")
        heading.addWidget(self.deck_meta)
        heading.addWidget(button("Cue list", self.show_cues))
        deck_box.addLayout(heading)
        self.wave = Waveform()
        self.wave.setMinimumHeight(150)
        self.wave.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.wave.seek.connect(self.seek)
        self.wave.anchor_moved.connect(self.move_drop_marker)
        self.wave.drag_started.connect(self.player.pause)
        deck_box.addWidget(self.wave, 1)
        self.wave_scroll = QScrollBar(Qt.Horizontal)
        self.wave_scroll.setAccessibleName("Waveform horizontal position")
        self.wave_scroll.setToolTip("Move through the track while zoomed in")
        self.wave_scroll.valueChanged.connect(self.pan_waveform)
        self.wave_scroll.setEnabled(False)
        deck_box.addWidget(self.wave_scroll)
        playback = QHBoxLayout()
        self.play = button("▶ / Ⅱ", self.toggle_play)
        self.play.setAccessibleName("Play / pause")
        self.play.setToolTip("Play / pause (Space)")
        playback.addWidget(self.play)
        self.clock = label("0:00.00", "transportClock")
        self.clock.setMinimumWidth(95)
        playback.addWidget(self.clock)
        self.metronome = QCheckBox("Metronome")
        self.metronome.toggled.connect(self.toggle_metronome)
        playback.addWidget(self.metronome)
        playback.addStretch()
        playback.addWidget(label("Space: play / pause · ↑/↓: tracks", "muted"))
        self.zoom = QComboBox()
        for factor in Waveform.ZOOMS:
            self.zoom.addItem("Whole track" if factor == 1 else f"{factor}× zoom", factor)
        self.zoom.currentIndexChanged.connect(self.change_zoom)
        playback.addWidget(button("−", lambda: self.wave.zoom_by(-1)))
        playback.addWidget(self.zoom)
        playback.addWidget(button("+", lambda: self.wave.zoom_by(1)))
        self.align_grid = button("Set drop 1 / bar 1 here", self.align_grid_to_playhead)
        self.align_grid.setToolTip("Seek to the actual first drop, then align the nearest grid beat and bar start here. Rebuild cues afterwards.")
        self.align_grid.setEnabled(False)
        playback.addWidget(self.align_grid)
        deck_box.addLayout(playback)
        self.wave.view_changed.connect(self.update_wave_navigation)
        anchors = QHBoxLayout()
        self.first = QDoubleSpinBox()
        self.second = QDoubleSpinBox()
        for spin in (self.first, self.second):
            spin.setDecimals(3)
            spin.setRange(0, 3600)
            spin.setSuffix(" s")
            spin.setSingleStep(.1)
            spin.setFixedWidth(110)
            spin.valueChanged.connect(self.anchor_changed)
        anchors.addWidget(label("DROP 1", "deckMeta"))
        anchors.addWidget(self.first)
        anchors.addWidget(button("Zoom to drop 1", lambda: self.focus_drop(1)))
        anchors.addSpacing(16)
        anchors.addWidget(label("DROP 2", "deckMeta"))
        anchors.addWidget(self.second)
        anchors.addWidget(button("Zoom to drop 2", lambda: self.focus_drop(2)))
        anchors.addStretch()
        anchors.addWidget(label("Snap", "muted"))
        self.marker_snap = QComboBox()
        self.marker_snap.setAccessibleName("Drop marker snapping")
        self.marker_snap.setMinimumWidth(96)
        # The macOS combo delegate reserves a checkmark column that clips short
        # styled popups. Use a regular list delegate with explicit room for text.
        snap_view = QListView(self.marker_snap)
        snap_view.setItemDelegate(QStyledItemDelegate(snap_view))
        snap_view.setMinimumWidth(120)
        snap_view.setSpacing(2)
        self.marker_snap.setView(snap_view)
        for name, mode in (("Beat", "beat"), ("Bar", "bar"), ("Off", "off")):
            self.marker_snap.addItem(name, mode)
        self.marker_snap.setToolTip("Beat: each beat. Bar: bar starts only. Off: precise placement without snapping. Rebuild cues keeps your chosen positions.")
        self.marker_snap.currentIndexChanged.connect(lambda: setattr(self.wave, "snap_mode", self.marker_snap.currentData()))
        anchors.addWidget(self.marker_snap)
        self.rebuild_button = button("Rebuild cues", self.rebuild_cues)
        self.rebuild_button.setObjectName("rebuildCues")
        self.rebuild_button.setEnabled(False)
        anchors.addWidget(self.rebuild_button)
        deck_box.addLayout(anchors)
        self.details = ElidedLabel("Analyse a playlist, then listen and adjust the drop markers above.", "muted")
        self.details.setMinimumHeight(22)
        deck_box.addWidget(self.details)
        self.deck_splitter.addWidget(deck)

        browser = QFrame()
        browser.setObjectName("browser")
        browser_box = QVBoxLayout(browser)
        browser_box.setContentsMargins(0, 0, 0, 0)
        browser_box.setSpacing(0)
        controls = QWidget()
        controls_box = QVBoxLayout(controls)
        controls_box.setContentsMargins(10, 7, 10, 7)
        controls_box.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(label("PLAYLIST", "eyebrow"))
        self.playlists = QComboBox()
        self.playlists.setMinimumWidth(220)
        self.playlists.currentIndexChanged.connect(self.load_tracks)
        row.addWidget(self.playlists, 1)
        self.track_count = label("0 tracks", "muted")
        row.addWidget(self.track_count)
        self.analyse_button = button("Analyse playlist", self.start_analysis, True)
        self.analyse_button.setEnabled(False)
        row.addWidget(self.analyse_button)
        controls_box.addLayout(row)
        row = QHBoxLayout()
        self.fix_grid = QCheckBox("Fix beat grid")
        self.set_cues = QCheckBox("Set memory cues")
        self.set_cues.setChecked(True)
        self.replace_cues = QCheckBox("Replace existing memory cues")
        self.replace_cues.setToolTip("Saved loops and hot cues are preserved. Unchecked: keep existing memory cues and fill free slots.")
        for widget in (self.fix_grid, self.set_cues, self.replace_cues):
            widget.toggled.connect(self.invalidate)
            row.addWidget(widget)
        row.addStretch()
        controls_box.addLayout(row)
        browser_box.addWidget(controls)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        browser_box.addWidget(self.progress)
        header = QWidget()
        header.setObjectName("columnHeader")
        header.setFixedHeight(25)
        columns = track_columns(header, ["#", "TRACK TITLE", "ARTIST", "GENRE", "BPM", "MEMORY", "STATUS"])
        columns.setContentsMargins(10, 0, 19, 0)  # match the track scrollbar gutter
        browser_box.addWidget(header)
        self.table = TrackList()
        self.table.itemSelectionChanged.connect(self.select_track)
        self.table.setMinimumHeight(112)
        browser_box.addWidget(self.table, 1)
        self.deck_splitter.addWidget(browser)
        self.deck_splitter.setStretchFactor(0, 0)
        self.deck_splitter.setStretchFactor(1, 1)
        self.deck_splitter.setSizes([340, 390])
        box.addWidget(self.deck_splitter, 1)
        footer = QHBoxLayout()
        self.status = ElidedLabel("No changes have been made.", "muted")
        footer.addWidget(self.status, 1)
        self.apply_button = button("Apply all changes", self.apply_changes, True)
        self.apply_button.setEnabled(False)
        footer.addWidget(self.apply_button)
        box.addLayout(footer)
        return page

    def build_backups(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(30, 30, 30, 30)
        box.addWidget(button("← Back to playlist", lambda: self.tabs.setCurrentIndex(0)))
        box.addWidget(label("RECOVERY", "eyebrow"))
        box.addWidget(label("Backups", "title"))
        box.addWidget(label("Every import creates a verified snapshot first. Nothing is deleted automatically.", "muted", True))
        self.backup_path = label(str(self.backups.directory), "muted", True)
        box.addWidget(self.backup_path)
        row = QHBoxLayout()
        row.addWidget(button("Open backup folder", self.open_backup_folder))
        row.addWidget(button("Change location…", self.choose_backup_folder))
        row.addStretch()
        box.addLayout(row)
        self.backup_list = QListWidget()
        box.addWidget(self.backup_list, 1)
        box.addWidget(label("Restore requires the same connected library, with Rekordbox closed. Any later library changes block restoration to protect newer work.", "muted", True))
        box.addWidget(button("Restore selected backup", self.restore_backup))
        box.addWidget(button("Recover interrupted session", self.recover_session))
        return page

    def fail(self, error):
        QMessageBox.warning(self, "Rekordbox Manager", str(error))

    def choose_database_path(self):
        candidates = discover_databases()
        initial = str(self.startup_database) if self.startup_database else (str(candidates[0]) if candidates else str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, "Choose Rekordbox master.db", initial,
                                            "Rekordbox library (master.db);;Database (*.db)")
        return path

    def connect_library(self):
        path = self.choose_database_path()
        if not path:
            return
        try:
            self.set_library(RekordboxLibrary(Path(path)))
        except Exception as exc:
            self.fail(exc)

    def set_library(self, library):
        self.player.stop()
        self.library = library
        self.mode.setText("DEMO · safe to explore" if library.demo else ("GRID + CUE IMPORT" if library.writable else "READ-ONLY PREVIEW"))
        if not library.demo:
            self.fix_grid.setChecked(library.writable)
        self.fix_grid.setEnabled(library.demo or library.writable)
        self.fix_grid.setToolTip("Correct small timing/drift errors before finding drops. Check bar starts with the metronome; automatic correction does not identify musical drops reliably.")
        self.notice.setText("Generated audio and a separate demo library. Apply/restore never touch Rekordbox." if library.demo else library.write_reason + " Regular playlists only; smart playlists are not yet supported.")
        self.playlists.blockSignals(True)
        self.playlists.clear()
        for key, name in library.playlists.items():
            self.playlists.addItem(name, key)
        self.playlists.blockSignals(False)
        return self.load_tracks()

    def load_tracks(self):
        self.player.stop()
        if not self.library:
            return
        try:
            self.tracks = self.library.tracks(self.playlists.currentData()) if self.playlists.count() else []
            self.invalidate()
            self.status.setText(f"{len(self.tracks)} tracks loaded. Audio and library source are read-only during analysis.")
            return True
        except Exception as exc:
            self.tracks = []
            self.invalidate()
            self.fail(exc)
            return False

    def invalidate(self):
        self.proposals = []
        self.current = -1
        self.wave.proposal = None
        self.review_title.setText("Select a track after analysing your playlist")
        self.deck_meta.setText("— BPM  ·  — cues")
        self.wave.reset_view()
        self.player.stop()
        self.details.setText("Analyse the playlist to generate proposals. Changing options requires a fresh analysis.")
        self.apply_button.setEnabled(False)
        self.analyse_button.setEnabled(bool(self.tracks) and (self.fix_grid.isChecked() or self.set_cues.isChecked()))
        self.populate_table()
        self.update_details()

    def populate_table(self):
        selected = self.table.currentRow()
        self.table.blockSignals(True)
        rows = []
        for i, track in enumerate(self.tracks):
            proposal = self.proposals[i] if i < len(self.proposals) else None
            cues = proposal.cues if proposal else track.cues
            count = sum(c.kind in ("memory", "memory_loop") for c in cues)
            status = "Ready to analyse"
            if proposal:
                status = "Imported" if proposal.applied else ("Needs attention" if proposal.error else ("Rebuild cues" if proposal.cues_dirty else "Analysed"))
            values = [track.title + "\n" + track.artist, track.genre, f"{track.bpm:g}", f"{count} / 10", status]
            rows.append(values)
        self.track_count.setText(f"{len(self.tracks)} tracks")
        self.table.set_rows(rows)
        if 0 <= selected < len(self.tracks):
            self.table.selectRow(selected)
        self.table.blockSignals(False)

    def set_busy(self, busy):
        self.analysis_busy = busy
        for widget in (self.connect_button, self.playlists, self.fix_grid, self.set_cues, self.replace_cues, self.analyse_button):
            widget.setEnabled(not busy)
        self.fix_grid.setEnabled(not busy and (not self.library or self.library.demo or self.library.writable))
        self.apply_button.setEnabled(False)
        self.progress.setVisible(busy)
        self.update_play_shortcut(None, QApplication.focusWidget())
        self.update_details()

    def start_analysis(self):
        if self.worker and self.worker.isRunning():
            return
        try:
            if not self.library.demo:
                ensure_rekordbox_closed()
            self.invalidate()
            self.set_busy(True)
            self.progress.setRange(0, len(self.tracks))
            self.worker = AnalysisWorker(self.tracks, Options(self.fix_grid.isChecked(), self.set_cues.isChecked(), self.replace_cues.isChecked()))
            self.worker.progress.connect(self.analysis_progress)
            self.worker.result.connect(self.analysis_done)
            self.worker.start()
        except Exception as exc:
            self.set_busy(False)
            self.fail(exc)

    def analysis_progress(self, index, title):
        self.progress.setValue(index)
        self.status.setText(f"Analysing {index + 1} / {len(self.tracks)} · {title}")

    def analysis_done(self, proposals):
        self.proposals = proposals
        self.set_busy(False)
        self.populate_table()
        self.status.setText("Analysis complete. Listen to both drops and review each track; nothing has been written.")
        if proposals:
            self.table.selectRow(0)
            self.select_track()

    def selected(self):
        index = self.table.currentRow()
        return self.proposals[index] if 0 <= index < len(self.proposals) else None

    def select_track(self):
        proposal = self.selected()
        if proposal is None:
            return
        self.current = self.table.currentRow()
        self.player.stop()
        self.metronome.blockSignals(True)
        self.metronome.setChecked(False)
        self.metronome.blockSignals(False)
        self.player.setSource(QUrl.fromLocalFile(str(proposal.track.path)))
        self.review_title.setText(proposal.track.title + "  ·  " + proposal.track.artist)
        self.wave.proposal = proposal
        self.wave.reset_view()
        for spin, value in ((self.first, proposal.first_drop), (self.second, proposal.second_drop)):
            spin.blockSignals(True)
            spin.setMaximum(proposal.track.duration)
            spin.setValue(value or 0)
            spin.setEnabled(proposal.options.set_cues)
            spin.blockSignals(False)
        self.update_details()

    def update_details(self):
        p = self.selected()
        if p:
            count = sum(c.kind in ("memory", "memory_loop") for c in p.cues)
            self.deck_meta.setText(f"{p.track.bpm:g} BPM  ·  {count} / 10 cues")
            text = p.error if p.error else p.grid_note + "\n" + " · ".join(p.warnings)
            if p.cues_dirty:
                text += "\nDrop markers moved — click Rebuild cues to update the countdown markers."
            self.details.setText(text)
            self.details.setToolTip(text)
        dirty = bool(p and p.cues_dirty)
        self.rebuild_button.setText("Rebuild cues — needed" if dirty else "Rebuild cues")
        self.rebuild_button.setToolTip("Drop markers changed. Rebuild to update the cue countdowns before importing." if dirty else "Recalculate cue countdowns from the selected drop markers.")
        if self.rebuild_button.property("needsRebuild") != dirty:
            self.rebuild_button.setProperty("needsRebuild", dirty)
            self.rebuild_button.style().unpolish(self.rebuild_button)
            self.rebuild_button.style().polish(self.rebuild_button)
            self.rebuild_button.update()
        self.rebuild_button.setEnabled(bool(p and p.options.set_cues and not p.error and not p.applied and not getattr(self, "analysis_busy", False)))
        self.align_grid.setEnabled(bool(p and p.options.fix_grid and not p.error and not p.applied and not getattr(self, "analysis_busy", False)))
        count = sum(p.ready_to_apply for p in self.proposals)
        action = ("Import grids + cues to Rekordbox" if any(p.options.fix_grid for p in self.proposals) else "Import cues to Rekordbox") if self.library and not self.library.demo and self.library.writable else "Apply all changes"
        self.apply_button.setText(f"{action} ({count} tracks)" if count else action)
        self.apply_button.setEnabled(bool(count and self.library and self.library.writable
                                          and not getattr(self, "analysis_busy", False)))
        self.apply_button.setToolTip("")
        if self.library and not self.library.writable:
            self.apply_button.setToolTip(self.library.write_reason)

    def anchor_changed(self):
        p = self.selected()
        if p and p.options.set_cues:
            refresh = p.reviewed or not p.cues_dirty
            p.first_drop, p.second_drop = self.first.value(), self.second.value()
            p.cues_dirty = True
            p.applied = False
            p.reviewed = False
            self.wave.update()
            self.update_details()
            if refresh:
                self.populate_table()

    def move_drop_marker(self, number, seconds):
        (self.first if number == 1 else self.second).setValue(seconds)

    def focus_drop(self, number):
        p = self.selected()
        if not p or not p.options.set_cues:
            return
        seconds = p.first_drop if number == 1 else p.second_drop
        if seconds is None:
            return
        self.player.pause()
        self.seek(seconds)
        self.wave.set_zoom(max(16, self.wave.zoom), seconds)

    def align_grid_to_playhead(self):
        p = self.selected()
        if p is None or not p.options.fix_grid or p.error or p.applied:
            return
        try:
            from .grid_writer import align_downbeat
            self.player.pause()
            grid, anchor = align_downbeat(p.grid, self.player.position() / 1000, p.track.duration)
            if p.options.set_cues and p.second_drop is not None and anchor >= p.second_drop:
                raise ValueError("The first drop must be before the second drop.")
            self.metronome.setChecked(False)
            p.grid = grid
            p.grid_note = "Grid aligned to the first drop at the playhead. Check the metronome throughout the track."
            p.reviewed = p.grid_approved = False
            if p.options.set_cues:
                p.first_drop = anchor
                self.first.blockSignals(True)
                self.first.setValue(anchor)
                self.first.blockSignals(False)
                p.cues_dirty = True
            self.wave.update()
            self.populate_table()
            self.update_details()
        except Exception as exc:
            self.fail(exc)

    def rebuild_cues(self):
        p = self.selected()
        if p is None or not p.options.set_cues:
            return
        try:
            first, second = self.first.value(), self.second.value()
            cues, warnings = plan_cues(p.grid, first, second, p.track.duration, p.track.cues,
                                      p.options.replace_memory, preserve_anchors=True)
            p.first_drop, p.second_drop, p.cues = first, second, cues
            p.cues_dirty = False
            p.warnings = p.track.issues + warnings + ["Listen to both drop anchors before applying playlist changes."]
            # Audio/analysis errors cannot be dismissed by merely changing anchors.
            p.reviewed = False
            self.populate_table()
            for spin, value in ((self.first, first), (self.second, second)):
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
            self.wave.update()
            self.update_details()
        except Exception as exc:
            self.fail(exc)

    def show_cues(self):
        p = self.selected()
        if p is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Cue list · " + p.track.title)
        dialog.resize(520, 430)
        box = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n".join(f"{time_text(c.time):>9}   {c.kind:12}   {c.label}" for c in p.cues))
        box.addWidget(text)
        box.addWidget(button("Close", dialog.accept))
        dialog.exec()

    def seek(self, seconds):
        self.player.setPosition(int(seconds * 1000))
        self.wave.set_position(seconds)

    def change_zoom(self):
        self.wave.set_zoom(self.zoom.currentData())

    def update_wave_navigation(self):
        self.zoom.blockSignals(True)
        self.zoom.setCurrentIndex(self.zoom.findData(self.wave.zoom))
        self.zoom.blockSignals(False)
        start, end = self.wave.visible_range()
        self.wave_scroll.blockSignals(True)
        page = max(1, round(10000 / self.wave.zoom))
        self.wave_scroll.setRange(0, 10000 - page)
        self.wave_scroll.setPageStep(page)
        self.wave_scroll.setSingleStep(max(1, page // 4))
        self.wave_scroll.setValue(round(start / self.wave.duration * 10000))
        self.wave_scroll.setEnabled(self.wave.proposal is not None and self.wave.zoom > 1)
        self.wave_scroll.blockSignals(False)

    def pan_waveform(self, value):
        self.wave.pan(value / max(1, self.wave_scroll.maximum()))

    def toggle_metronome(self, enabled):
        p = self.selected()
        if p is None:
            return
        position = self.player.position()
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        if not enabled:
            self.player.setSource(QUrl.fromLocalFile(str(p.track.path)))
            self.player.setPosition(position)
            if playing:
                self.player.play()
            return
        if self.metronome_worker and self.metronome_worker.isRunning():
            return
        cache = self.base / "Preview audio"
        cache.mkdir(exist_ok=True)
        stat = p.track.path.stat()
        preview_grid = (tuple(p.grid.times), tuple(p.grid.positions))
        key = hashlib.sha256((str(p.track.path) + str(stat.st_mtime_ns) + str(stat.st_size) + repr(preview_grid)).encode()).hexdigest()[:24]
        path = cache / (key + ".wav")
        def use_audio(filename, error):
            self.metronome.setEnabled(True)
            if (self.selected() is not p or not self.metronome.isChecked()
                    or preview_grid != (tuple(p.grid.times), tuple(p.grid.positions))):
                return
            if error:
                self.metronome.setChecked(False)
                self.fail(error)
                return
            self.player.setSource(QUrl.fromLocalFile(filename))
            self.player.setPosition(position)
            if playing:
                self.player.play()
            self.status.setText("Metronome follows the proposed grid; accented click is the bar downbeat.")
        if path.exists():
            use_audio(str(path), "")
        else:
            self.player.pause()
            self.metronome.setEnabled(False)
            self.status.setText("Preparing sample-aligned metronome playback…")
            self.metronome_worker = MetronomeWorker(p.track, p.grid, path)
            self.metronome_worker.done.connect(use_audio)
            self.metronome_worker.start()

    def play_position(self, milliseconds):
        self.clock.setText(time_text(milliseconds / 1000))
        self.wave.set_position(milliseconds / 1000)

    def toggle_play(self):
        if self.selected() is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.wave.follow_playhead = True
            self.player.play()

    def apply_changes(self):
        if not self.library or not self.library.writable or getattr(self, "analysis_busy", False):
            return
        candidates = [p for p in self.proposals if p.ready_to_apply]
        if not candidates:
            return
        skipped = [p for p in self.proposals if not p.ready_to_apply and not p.applied]
        live = not self.library.demo
        message = ((f"Import the selected grid/cue changes for {len(candidates)} track(s) into Rekordbox?\n\n"
                    "Check beat timing, bar starts and drop anchors before continuing. Existing hot cues, saved loops and audio will be preserved. "
                    f"A verified database backup and backups of changed analysis files will be saved to:\n{self.backups.directory}\n\n"
                    "Rekordbox must remain closed until import finishes.") if live else
                   (f"Apply changes to {len(candidates)} demo track(s)?\n\n"
                    "Finish listening to the tracks and checking your edits before continuing. "
                    "A verified backup will be created first. Your Rekordbox library will not be touched."))
        if skipped:
            message += f"\n\n{len(skipped)} track(s) will be skipped:\n" + "\n".join(
                f"{p.track.title}: {p.error or 'Rebuild cues after moving drop markers'}" for p in skipped)
        answer = QMessageBox.question(self, "Apply playlist changes", message,
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            # The single final confirmation authorizes the batch. Keep approval
            # local to this write so cancellation/failure never marks UI tracks.
            for p in candidates:
                p.grid.validate()
            confirmed = [replace(p, reviewed=True, grid_approved=p.options.fix_grid) for p in candidates]
            backup = self.library.apply(confirmed, self.backups)
            # Retain skipped marker edits and show imported rows without making
            # the user repeat analysis or accidentally submit them a second time.
            previous = {p.track.id: p for p in self.proposals}
            imported = {p.track.id for p in confirmed}
            selected_id = self.selected().track.id if self.selected() else None
            self.load_tracks()
            if self.tracks and all(t.id in previous for t in self.tracks):
                self.proposals = [previous[t.id] for t in self.tracks]
                for track, proposal in zip(self.tracks, self.proposals):
                    proposal.track = track
                    if track.id in imported:
                        proposal.applied = True
                self.populate_table()
                index = next((i for i, t in enumerate(self.tracks) if t.id == selected_id), 0)
                self.table.selectRow(index)
                self.update_details()
            self.status.setText((f"Imported changes for {len(confirmed)} tracks. You can now open Rekordbox. " if live else
                                 f"Applied changes to {len(confirmed)} demo tracks. ")
                                + f"{len(skipped)} skipped. Backup: {backup.name}")
            completion = (f"Changes imported successfully for {len(confirmed)} track(s).\n\n"
                          "You can now open Rekordbox." if live else
                          f"Changes applied successfully to {len(confirmed)} demo track(s).")
            if skipped:
                completion += f"\n\n{len(skipped)} track(s) were skipped and have not been imported."
            QMessageBox.information(self, "Import complete" if live else "Changes complete",
                                    completion, QMessageBox.Ok)
        except Exception as exc:
            self.fail(exc)

    def show_backups(self):
        self.tabs.setCurrentIndex(1)
        self.backup_path.setText(str(self.backups.directory))
        self.backup_list.clear()
        self.backup_entries = self.backups.list()
        for path, record in self.backup_entries:
            size = sum(e.get("bytes", 0) for e in record.get("files", [])) / 1024
            self.backup_list.addItem(f"{path.name}\n{record.get('description', '')}  ·  {record.get('state', '')}  ·  {size:,.0f} KB")

    def open_backup_folder(self):
        self.backups.directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.backups.directory)))

    def choose_backup_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Choose backup location", str(self.backups.directory))
        if path:
            self.backups = BackupStore(Path(path))
            self.settings["backups"] = str(self.backups.directory)
            durable_json(self.config_file, self.settings)
            self.show_backups()

    def restore_backup(self):
        if self.worker and self.worker.isRunning():
            self.fail("Wait for analysis to finish before restoring a backup.")
            return
        row = self.backup_list.currentRow()
        if row < 0:
            return
        if not self.library:
            self.fail("Connect the library that belongs to this backup first.")
            return
        path, record = self.backup_entries[row]
        if QMessageBox.question(self, "Restore library snapshot", "Restore this backup? Rekordbox must be closed. Any newer library changes will block restoration.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            if self.library.demo:
                self.backups.restore(path, self.library.root, lambda: None, set(self.library.fingerprints))
                self.library.reload()
            else:
                self.library.restore(self.backups, path)
            self.load_tracks()
            self.show_backups()
            self.status.setText("Library backup restored and verified.")
        except Exception as exc:
            self.fail(exc)

    def recover_session(self):
        if not self.library:
            self.fail("Connect the library before recovering its interrupted session.")
            return
        try:
            if not self.library.demo:
                ensure_rekordbox_closed()
            self.backups.release_stale_lock(self.library.root)
            self.show_backups()
            self.fail("If a backup is marked applying or restoring, select it and restore it before continuing. No library files have been changed by releasing the stale lock.")
        except Exception as exc:
            self.fail(exc)

    def save_diagnostics(self):
        if not self.library:
            self.fail("Connect a library first. Diagnostics include schema details, not track names or file paths.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save compatibility diagnostics", "rekordbox-manager-diagnostics.json", "JSON (*.json)")
        if not path:
            return
        try:
            report = {"manager_version": "0.3.5", "system": platform.system(),
                      "macos": platform.mac_ver()[0], "architecture": platform.machine(),
                      "library_type": "demo" if self.library.demo else "rekordbox",
                      "playlist_count": len(self.library.playlists), "selected_track_count": len(self.tracks),
                      "tracks_with_grid": sum(bool(t.grid.times) for t in self.tracks),
                      "tracks_with_local_audio": sum(t.path.is_file() for t in self.tracks),
                      "live_writes_enabled": bool(not self.library.demo and self.library.writable)}
            if not self.library.demo:
                schema = {}
                with self.library.connect() as db:
                    for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                        name = row[0]
                        if name.startswith("djmd"):
                            escaped = name.replace('"', '""')
                            schema[name] = [{"column": c[1], "type": c[2]} for c in db.execute(f'PRAGMA table_info("{escaped}")')]
                report["schema"] = schema
            durable_json(Path(path), report)
            self.status.setText("Diagnostics saved locally. No track names, audio paths or database key included.")
        except Exception as exc:
            self.fail(exc)

    def closeEvent(self, event):
        if self.metronome_worker and self.metronome_worker.isRunning():
            self.status.setText("Wait for metronome preview generation before closing.")
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.status.setText("Stopping after the current track. Close again when analysis stops.")
            event.ignore()
            return
        self.player.stop()
        event.accept()
