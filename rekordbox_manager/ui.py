from __future__ import annotations

from dataclasses import asdict, replace
from copy import deepcopy
import json
from pathlib import Path
import math
import hashlib
import platform
import soundfile as sf

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
from .waveform_data import rekordbox_waveforms
from .dialogs import ImportDialog, PlaylistDialog, review_reason
from .cues import plan_cues
from .analysis import analyse, render_metronome, rebuild_proposal, review_confirmation_error, confirm_proposal_review
from .attacks import match_attack
from .backups import BackupStore, durable_json
from .guards import SafetyError, ensure_rekordbox_closed
from .library import RekordboxLibrary
from .paths import data_dir, discover_databases


STYLE = """
QWidget { background: #1a1b1d; color: #e7e8ea; font-family: 'Inter', '.AppleSystemUIFont', 'Segoe UI'; font-size: 12px; }
QLabel { background: transparent; }
QMainWindow { background: #1a1b1d; }
QLabel#eyebrow { color: #a3a7ad; font-size: 11px; font-weight: 600; letter-spacing: 2px; }
QLabel#title { font-size: 29px; font-weight: 650; }
QLabel#section { font-size: 17px; font-weight: 600; }
QLabel#muted { color: #a7abb1; }
QLabel#badge { background: #292f35; color: #a8bdd1; padding: 5px 9px; border-radius: 3px; }
QFrame#card { background: #222426; border: 1px solid #393c40; border-radius: 10px; }
QFrame#databaseCard { background: #1c2024; border: 1px solid #505963; border-radius: 6px; }
QFrame#databaseCard[state="saved"] { background: #1b2a25; border-color: #568e74; }
QFrame#databaseCard[state="selected"] { border-color: #739fc9; }
QFrame#databaseCard[state="unavailable"], QFrame#databaseCard[state="failed"] { background: #2b251b; border-color: #b18c49; }
QLabel#databaseState { font-size: 18px; font-weight: 650; }
QLabel#databaseState[state="saved"] { color: #99d7b6; }
QLabel#databaseState[state="selected"] { color: #a8cbea; }
QLabel#databaseState[state="unavailable"], QLabel#databaseState[state="failed"] { color: #e4bd79; }
QPushButton { background: #2b2d30; border: 1px solid #484b50; border-radius: 3px; padding: 6px 10px; font-weight: 550; }
QPushButton:hover { background: #36393d; border-color: #7ca7d0; }
QPushButton:disabled { color: #777b81; background: #232528; border-color: #35383c; }
QPushButton#primary { background: #739fc9; color: #101820; border: 0; }
QPushButton#primary:hover { background: #91b5d7; }
QPushButton#primary:disabled { background: #303a44; color: #87939f; }
QPushButton#rebuildCues[needsRebuild="true"] { background: #efb34f; color: #171007; border-color: #ffcd7a; }
QPushButton#rebuildCues[needsRebuild="true"]:hover { background: #ffcb78; }
QPushButton#rebuildCues:disabled { background: #232528; color: #777b81; border-color: #35383c; }
QComboBox, QDoubleSpinBox { background: #181a1c; border: 1px solid #484c51; border-radius: 3px; padding: 4px; min-height: 18px; }
QDoubleSpinBox { padding-right: 6px; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: 0; }
QComboBox QAbstractItemView { background: #25272a; selection-background-color: #35414d; }
QCheckBox { spacing: 9px; background: transparent; padding: 3px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #7e858d; border-radius: 4px; background: #202225; }
QCheckBox::indicator:checked { background: #739fc9; border: 1px solid #739fc9; image: url("@CHECK_ICON@"); }
QCheckBox::indicator:checked:disabled { background: #7d8791; border-color: #7d8791; }
QPushButton#track { background: #1a1c1e; text-align: left; padding: 0; border: 0; border-bottom: 1px solid #303236; border-radius: 0; }
QPushButton#track[alternate="true"] { background: #212326; }
QPushButton#track:hover { background: #303338; }
QPushButton#track QLabel { background: transparent; font-weight: 400; }
QPushButton#track:focus { border: 1px solid #739fc9; }
QFrame#deck { background: #151719; border: 1px solid #3a3d41; }
QFrame#browser { background: #181a1c; border: 1px solid #3a3d41; }
QWidget#columnHeader { background: #2b2d30; border-bottom: 1px solid #45494e; }
QWidget#columnHeader QLabel { color: #b2b6bc; font-size: 11px; }
QLabel#brand { font-size: 15px; font-weight: 650; }
QLabel#transportClock { font-size: 19px; font-weight: 600; color: #d6dce2; }
QLabel#deckTitle { font-size: 15px; font-weight: 600; }
QSplitter::handle:hover { background: #739fc9; }
QPushButton#track:checked { background: #30373e; border-left: 3px solid #739fc9; }
QPushButton#track[needsReview="true"] { background: #e4c66b; border-bottom-color: #b69c4d; }
QPushButton#track[needsReview="true"] QLabel { color: #24200f; }
QPushButton#track[needsReview="true"]:hover { background: #eed688; }
QPushButton#track[needsReview="true"]:checked { background: #f5da7d; border-left: 3px solid #739fc9; }
QListWidget, QTextEdit { background: #1d1f22; border: 1px solid #43474c; border-radius: 6px; padding: 6px; }
QListWidget::item { padding: 9px; }
QListWidget::item:selected { background: #35414d; }
QProgressBar { border: 0; background: #303338; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: #739fc9; }
QSplitter::handle { background: #414449; height: 6px; }
QScrollBar:vertical { background: #1d1f22; width: 9px; }
QScrollBar::handle:vertical { background: #555b63; border-radius: 4px; min-height: 25px; }
QScrollBar:horizontal { background: #1d1f22; height: 14px; }
QScrollBar::handle:horizontal { background: #555b63; border-radius: 4px; min-width: 28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QToolTip { background: #2d3034; color: #e7e8ea; border: 1px solid #626b76; }
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

    def set_rows(self, rows, reasons=None):
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
            reason = reasons[index] if reasons else ""
            item.setFixedHeight(28)
            item.setObjectName('track')
            item.setProperty('alternate', bool(index % 2))
            item.setProperty('needsReview', bool(reason))
            item.setAccessibleName(text + (" · " + reason if reason else ""))
            item.setToolTip(text + ("\n" + reason if reason else ""))
            item.setCheckable(True)
            outer = QVBoxLayout(item)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)
            main_row = QWidget()
            main_row.setAttribute(Qt.WA_TransparentForMouseEvents)
            main_row.setStyleSheet("background: transparent;")
            main_row.setFixedHeight(28)
            track_columns(main_row, [str(index + 1), title, artist, genre, bpm, memory, status])
            outer.addWidget(main_row)
            item.clicked.connect(lambda checked=False, row=index: self.selectRow(row))
            layout.addWidget(item)
            self._buttons.append(item)
        layout.addStretch()
        self.setWidget(content)

    def visible_rows(self):
        return [i for i, item in enumerate(self._buttons) if not item.isHidden()]

    def set_visible_rows(self, indices):
        visible = set(indices)
        for i, item in enumerate(self._buttons):
            item.setVisible(i in visible)
        if self._selected not in visible:
            self._selected = -1

    def currentRow(self):
        return self._selected

    def selectRow(self, index):
        if 0 <= index < len(self._buttons) and not self._buttons[index].isHidden():
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


class CueReviewWorker(QThread):
    progress = Signal(int, str)
    result = Signal(object)

    def __init__(self, proposals):
        super().__init__()
        # Work on detached tracks. Preserve the displayed proposals until done.
        self.jobs = [(p.track.id, deepcopy(p.track), p.options.replace_memory) for p in proposals]

    def run(self):
        results = {}
        for index, (identity, track, replace_memory) in enumerate(self.jobs):
            if self.isInterruptionRequested():
                break
            self.progress.emit(index, track.title)
            results[identity] = analyse(track, Options(False, True, replace_memory))
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
        self.ignored_track_count = 0
        self.loaded_playlist_tracks = {}
        self.analysis_scope = None
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
        self.setStyleSheet(STYLE.replace("@CHECK_ICON@", (Path(__file__).parent / "assets" / "check.svg").as_posix()))
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
        if (not self.tracks or getattr(self, "analysis_busy", False)
                or self.pages.currentWidget() is not self.workspace or self.tabs.currentIndex() != 0):
            return
        current = self.table.currentRow()
        visible = self.table.visible_rows()
        if not visible:
            return
        index = visible[(visible.index(current) + step) % len(visible)] if current in visible else visible[0 if step > 0 else -1]
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
        self.startup_database_card = QFrame()
        self.startup_database_card.setObjectName("databaseCard")
        database_box = QVBoxLayout(self.startup_database_card)
        database_box.setContentsMargins(18, 15, 18, 15)
        self.startup_database_heading = label("", "databaseState", True)
        database_box.addWidget(self.startup_database_heading)
        self.startup_database_help = label("", "muted", True)
        database_box.addWidget(self.startup_database_help)
        self.startup_database_label = label("No database selected", "muted", True)
        database_box.addWidget(self.startup_database_label)
        self.startup_browse = button("Choose database…", self.choose_startup_database)
        database_box.addWidget(self.startup_browse)
        box.addWidget(self.startup_database_card)
        self.startup_status = label("", "muted", True)
        box.addWidget(self.startup_status)
        self.set_startup_database_state("empty")
        remembered = self.settings.get("last_database")
        if isinstance(remembered, str) and remembered:
            try:
                saved = Path(remembered).expanduser()
                if saved.is_absolute() and saved.is_file():
                    self.startup_database = saved
                    self.startup_database_label.setText(str(saved))
                    self.set_startup_database_state("saved")
                else:
                    self.startup_database_label.setText(str(saved))
                    self.set_startup_database_state("unavailable")
            except (OSError, ValueError):
                self.set_startup_database_state("unavailable")
        self.continue_button = button("Connect and continue  →", self.enter, True)
        self.update_startup_ready()
        self.confirm.toggled.connect(self.update_startup_ready)
        box.addWidget(self.continue_button)
        outer.addWidget(card)
        outer.addSpacing(20)
        outer.addWidget(label("PREVIEW 0.3.33  ·  Grid and memory cue import is available for verified Rekordbox installations. Automatic backups cover the database and changed analysis files.", "muted", True))
        outer.addStretch()
        return page

    def set_startup_database_state(self, state):
        self.startup_database_state = state
        heading, help_text = {
            "empty": ("No library selected", "Choose your Rekordbox master.db database to get started."),
            "saved": ("✓ Saved library found", "Your previously connected library is selected. Confirm above, then reconnect below."),
            "selected": ("Database selected", "Confirm above, then connect to load your playlists."),
            "unavailable": ("Saved library unavailable", "The saved file could not be found. Reconnect its drive and choose the database again."),
            "connecting": ("Connecting to your library…", "Checking the database and loading your playlists."),
            "failed": ("Connection needs attention", "Your selection is kept. Check the message below, then retry or change the database."),
        }[state]
        self.startup_database_heading.setText(heading)
        self.startup_database_help.setText(help_text)
        self.startup_browse.setText("Choose database…" if state in ("empty", "unavailable") else "Change database…")
        for widget in (self.startup_database_card, self.startup_database_heading):
            widget.setProperty("state", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def update_startup_ready(self):
        self.continue_button.setText({"saved": "Reconnect saved library  →", "failed": "Retry connection  →"}.get(
            self.startup_database_state, "Connect and continue  →"))
        self.continue_button.setEnabled(self.confirm.isChecked() and self.startup_database is not None)

    def choose_startup_database(self):
        path = self.choose_database_path()
        if path:
            self.startup_database = Path(path)
            self.startup_database_label.setText(str(self.startup_database))
            self.startup_status.setText("")
            self.set_startup_database_state("selected")
            self.update_startup_ready()

    def enter(self):
        if not self.confirm.isChecked() or self.startup_database is None:
            return
        self.continue_button.setEnabled(False)
        self.startup_browse.setEnabled(False)
        self.confirm.setEnabled(False)
        self.set_startup_database_state("connecting")
        self.startup_status.setText("Connecting and loading your playlists…")
        QApplication.processEvents()
        try:
            ensure_rekordbox_closed()
            library = RekordboxLibrary(self.startup_database)
            if not self.set_library(library):
                self.set_startup_database_state("failed")
                self.startup_status.setText("Could not load the library. Check the database and try again.")
                return
            self.remember_database(self.startup_database)
            self.pages.setCurrentWidget(self.workspace)
            self.playlists.setFocus()
            self.startup_status.setText("")
        except Exception as exc:
            self.set_startup_database_state("failed")
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
        toolbar.addWidget(label("0.3.33 · Preview", "muted"))
        toolbar.addStretch()
        self.settings_button = button("Settings", lambda: self.tabs.setCurrentIndex(2))
        toolbar.addWidget(self.settings_button)
        toolbar.addWidget(button("Backups", self.show_backups))
        self.mode = label("No library connected", "badge")
        toolbar.addWidget(self.mode)
        layout.addLayout(toolbar)
        self.tabs = QStackedWidget()
        self.tabs.addWidget(self.build_manager())
        self.tabs.addWidget(self.build_backups())
        self.tabs.addWidget(self.build_settings())
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
        self.review_title = ElidedLabel("Select a track to view saved Rekordbox analysis", "deckTitle")
        heading.addWidget(self.review_title, 1)
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
            spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
            spin.setDecimals(3)
            spin.setRange(0, 3600)
            spin.setSuffix(" s")
            spin.setSingleStep(.1)
            spin.setFixedWidth(96)
            spin.valueChanged.connect(self.anchor_changed)
        self.kick_buttons = []
        anchors.addWidget(label("DROP 1", "deckMeta"))
        anchors.addWidget(self.first)
        zoom_first = button("Zoom 1", lambda: self.focus_drop(1))
        zoom_first.setToolTip("Zoom to drop 1")
        anchors.addWidget(zoom_first)
        kick_first = button("Snap to kick", lambda: self.snap_drop_to_kick(1))
        kick_first.setAccessibleName("Snap drop 1 to kick")
        self.kick_buttons.append(kick_first)
        anchors.addWidget(kick_first)
        anchors.addSpacing(8)
        anchors.addWidget(label("DROP 2", "deckMeta"))
        anchors.addWidget(self.second)
        zoom_second = button("Zoom 2", lambda: self.focus_drop(2))
        zoom_second.setToolTip("Zoom to drop 2")
        anchors.addWidget(zoom_second)
        kick_second = button("Snap to kick", lambda: self.snap_drop_to_kick(2))
        kick_second.setAccessibleName("Snap drop 2 to kick")
        self.kick_buttons.append(kick_second)
        anchors.addWidget(kick_second)
        for control in self.kick_buttons:
            control.setEnabled(False)
            control.setToolTip("Find a distinct nearby kick-like attack (within 0.6 beat, at most 250 ms). Move the marker near the intended kick first. Rebuild afterwards to align the grid when Fix beat grid is enabled.")
        anchors.addStretch()
        anchors.addWidget(label("Snap", "muted"))
        self.marker_snap = QComboBox()
        self.marker_snap.setAccessibleName("Drop marker snapping")
        self.marker_snap.setMinimumWidth(80)
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
        self.confirm_review_button = button("Confirm review", self.confirm_review)
        self.confirm_review_button.setEnabled(False)
        anchors.addWidget(self.confirm_review_button)
        deck_box.addLayout(anchors)
        self.grid_anchor_controls = QWidget()
        grid_controls = QHBoxLayout(self.grid_anchor_controls)
        grid_controls.setContentsMargins(0, 0, 0, 0)
        grid_controls.addWidget(label("Proposed grid", "muted"))
        self.grid_anchor_buttons = []
        for number in (1, 2):
            control = button(f"Align to Drop {number}", lambda checked=False, n=number: self.align_grid_to_drop(n))
            control.setToolTip(f"Keep Drop {number} at its chosen time and move a bar start onto it. Rebuild cues and check the other drop. BPM stays unchanged.")
            self.grid_anchor_buttons.append(control)
            grid_controls.addWidget(control)
        self.grid_anchor_label = label("", "muted")
        grid_controls.addWidget(self.grid_anchor_label)
        grid_controls.addStretch()
        deck_box.addWidget(self.grid_anchor_controls)
        self.grid_anchor_controls.hide()
        self.details = ElidedLabel("Set cues + grid, then listen and adjust the drop markers above.", "muted")
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
        self.choose_playlists_button = button("Choose playlists…", self.choose_playlists)
        self.choose_playlists_button.setEnabled(False)
        row.addWidget(self.choose_playlists_button)
        self.track_count = label("0 tracks", "muted")
        row.addWidget(self.track_count)
        self.analyse_button = button("Set cues + grid", self.start_analysis, True)
        self.analyse_button.setEnabled(False)
        row.addWidget(self.analyse_button)
        controls_box.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(24)
        self.fix_grid = QCheckBox("Fix beat grid")
        self.set_cues = QCheckBox("Set memory cues")
        self.set_cues.setChecked(True)
        self.replace_cues = QCheckBox("Replace existing memory cues")
        self.replace_cues.setToolTip("Saved loops and hot cues are preserved. Unchecked: keep existing memory cues and fill free slots.")
        for widget in (self.fix_grid, self.set_cues, self.replace_cues):
            widget.toggled.connect(self.invalidate)
            row.addWidget(widget)
        self.ignore_cued = QCheckBox("Ignore tracks with existing cues")
        self.ignore_cued.setToolTip("Skip tracks with any saved memory cues, hot cues or loops. Hide them from this list and exclude them from preparation and import. Uncheck to show them again.")
        self.ignore_cued.toggled.connect(self.change_ignore_cued)
        row.addWidget(self.ignore_cued)
        row.addStretch()
        controls_box.addLayout(row)
        self.review_controls = QWidget()
        review_row = QHBoxLayout(self.review_controls)
        review_row.setContentsMargins(0, 0, 0, 0)
        self.review_filter = QComboBox()
        self.review_filter.setAccessibleName("Track review filter")
        self.review_filter.addItems(["All tracks (0)", "Needs review only (0)"])
        self.review_filter.setToolTip("Choose Needs review only to hide tracks that are ready or already imported.")
        review_row.addWidget(label("Show"))
        self.review_filter.currentIndexChanged.connect(self.filter_review_tracks)
        review_row.addWidget(self.review_filter)
        self.review_summary = label("", "muted")
        review_row.addWidget(self.review_summary, 1)
        self.auto_cue_button = button("Auto cue review tracks", self.auto_cue_review_tracks)
        self.auto_cue_button.setToolTip("Retry cues for tracks needing review using their existing Rekordbox grids. No grid changes or import. Manual drop edits are kept and excluded from automatic retry. Uncertain results remain flagged.")
        review_row.addWidget(self.auto_cue_button)
        controls_box.addWidget(self.review_controls)
        self.review_controls.hide()
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

    def build_settings(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(30, 30, 30, 30)
        box.addWidget(label("Settings", "title"))
        box.addSpacing(20)
        box.addWidget(label("Waveform appearance", "section"))
        self.waveform_style_combo = QComboBox()
        self.waveform_style_combo.setAccessibleName("Waveform type")
        for key, (title, description) in Waveform.STYLES.items():
            self.waveform_style_combo.addItem(title, key)
        self.wave.set_style(self.settings.get("waveform_style", "classic"))
        self.waveform_style_combo.setCurrentIndex(self.waveform_style_combo.findData(self.wave.waveform_style))
        box.addWidget(self.waveform_style_combo)
        self.waveform_style_description = label(Waveform.STYLES[self.wave.waveform_style][1], "muted", True)
        box.addWidget(self.waveform_style_description)
        box.addWidget(label("Changes apply immediately and are remembered for next time. Cue markers and beat grids use the same timeline in every view.", "muted", True))
        self.waveform_style_feedback = label("", "muted", True)
        box.addWidget(self.waveform_style_feedback)
        self.waveform_style_combo.currentIndexChanged.connect(self.change_waveform_style)
        box.addSpacing(24)
        box.addWidget(label("Rekordbox library", "section"))
        self.settings_library_label = label("No library connected", "muted", True)
        box.addWidget(self.settings_library_label)
        box.addWidget(label("The last connected database is remembered for next time. Changing libraries clears the current analysis and marker edits.", "muted", True))
        self.connect_button = button("Change library…", self.connect_library)
        box.addWidget(self.connect_button)
        box.addSpacing(24)
        box.addWidget(label("Diagnostics", "section"))
        box.addWidget(label("Save a local compatibility report for troubleshooting. It excludes track names, audio paths and the database key.", "muted", True))
        self.diagnostics_button = button("Save diagnostics…", self.save_diagnostics)
        box.addWidget(self.diagnostics_button)
        self.settings_feedback = label("", "muted", True)
        box.addWidget(self.settings_feedback)
        box.addStretch()
        box.addWidget(button("← Back to playlist", lambda: self.tabs.setCurrentIndex(0)))
        return page

    def change_waveform_style(self, index):
        style = self.waveform_style_combo.currentData()
        self.wave.set_style(style)
        self.waveform_style_description.setText(Waveform.STYLES[self.wave.waveform_style][1])
        self.settings["waveform_style"] = self.wave.waveform_style
        try:
            durable_json(self.config_file, self.settings)
            self.waveform_style_feedback.setText("")
        except OSError as exc:
            self.waveform_style_feedback.setText(f"Waveform changed for this session, but the preference could not be saved: {exc}")

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
            if self.set_library(RekordboxLibrary(Path(path))):
                self.remember_database(Path(path))
        except Exception as exc:
            self.fail(exc)

    def remember_database(self, path):
        """Remember only successful connections; never save the confirmation."""
        self.startup_database = Path(path).resolve()
        self.startup_database_label.setText(str(self.startup_database))
        self.settings_library_label.setText(str(self.startup_database))
        updated = dict(self.settings, last_database=str(self.startup_database))
        try:
            durable_json(self.config_file, updated)
            self.settings = updated
        except OSError:
            self.status.setText("Library connected, but its location could not be saved. You may need to select it again next time.")

    def set_library(self, library):
        self.player.stop()
        self.library = library
        self.settings_library_label.setText(str(getattr(library, "path", "Connected library")))
        self.settings_feedback.setText("")
        self.mode.setText("DEMO · safe to explore" if library.demo else ("GRID + CUE IMPORT" if library.writable else "READ-ONLY PREVIEW"))
        if not library.demo:
            self.fix_grid.setChecked(library.writable)
        self.fix_grid.setEnabled(library.demo or library.writable)
        self.fix_grid.setToolTip("With memory cues enabled, shift the grid to the last edited drop without changing BPM, then check the other drop. Manually edited markers stay fixed on rebuild. Grid-only analysis uses conservative timing suggestions. Check the metronome before import.")
        self.notice.setText("Generated audio and a separate demo library. Apply/restore never touch Rekordbox." if library.demo else library.write_reason + " Regular playlists only; smart playlists are not yet supported.")
        self.playlists.blockSignals(True)
        self.playlists.clear()
        for key, name in library.playlists.items():
            self.playlists.addItem(name, key)
        self.playlists.blockSignals(False)
        self.choose_playlists_button.setEnabled(bool(library.playlists))
        return self.load_tracks()

    def selected_playlist_ids(self):
        value = self.playlists.currentData()
        return value if isinstance(value, tuple) else (() if value is None else (value,))

    def choose_playlists(self):
        if not self.library or getattr(self, "analysis_busy", False):
            return
        dialog = PlaylistDialog(self, self.library.playlists, self.selected_playlist_ids())
        if dialog.exec() != QDialog.Accepted:
            return
        self.set_playlist_selection(dialog.selected_ids())

    def set_playlist_selection(self, identities):
        identities = tuple(dict.fromkeys(identities))
        if not identities or identities == self.selected_playlist_ids():
            return
        if any(identity not in self.library.playlists for identity in identities):
            raise ValueError("A selected playlist is no longer available.")
        self.playlists.blockSignals(True)
        # Keep one combined entry alongside the usual single-playlist choices.
        for index in reversed(range(self.playlists.count())):
            if isinstance(self.playlists.itemData(index), tuple):
                self.playlists.removeItem(index)
        if len(identities) == 1:
            self.playlists.setCurrentIndex(self.playlists.findData(identities[0]))
        else:
            self.playlists.addItem(f"{len(identities)} playlists · combined", identities)
            self.playlists.setCurrentIndex(self.playlists.count() - 1)
        self.playlists.blockSignals(False)
        self.load_tracks()

    def load_tracks(self):
        self.player.stop()
        if not self.library:
            return
        try:
            tracks = {}
            membership = {}
            identities = self.selected_playlist_ids()
            for identity in identities:
                playlist_tracks = self.library.tracks(identity)
                membership[identity] = (self.library.playlists[identity], frozenset(t.id for t in playlist_tracks))
                for track in playlist_tracks:
                    tracks.setdefault(track.id, track)
            ignored = {identity for identity, track in tracks.items() if self.ignore_cued.isChecked() and track.cues}
            self.ignored_track_count = len(ignored)
            self.tracks = [track for identity, track in tracks.items() if identity not in ignored]
            self.loaded_playlist_tracks = {key: (name, ids - ignored) for key, (name, ids) in membership.items()}
            self.playlists.setToolTip("\n".join(self.library.playlists[key] for key in identities))
            self.invalidate()
            ignored_note = f" {len(ignored)} tracks with existing cues ignored." if ignored else ""
            self.status.setText(f"{len(self.tracks)} unique tracks from {len(identities)} playlist(s)." + ignored_note + (" Ready to set cues + grid from Rekordbox analysis." if self.tracks else " No tracks to prepare."))
            return True
        except Exception as exc:
            self.tracks = []
            self.ignored_track_count = 0
            self.loaded_playlist_tracks = {}
            self.invalidate()
            self.fail(exc)
            return False

    def change_ignore_cued(self):
        if getattr(self, "analysis_busy", False):
            return
        # Re-read saved cues, never filter against this session's proposed cues.
        if self.library:
            self.load_tracks()

    def invalidate(self):
        self.review_filter.blockSignals(True)
        self.review_filter.setCurrentIndex(0)
        self.review_filter.blockSignals(False)
        self.proposals = []
        self.analysis_scope = None
        self.current = -1
        self.wave.proposal = None
        self.review_title.setText("Select a track to view saved Rekordbox analysis")
        self.wave.reset_view()
        self.player.stop()
        self.details.setText("Uses Rekordbox waveforms, BPM and grid. Checks audio for drops; review changes before importing.")
        self.apply_button.setEnabled(False)
        self.analyse_button.setText("Set cues + grid" if self.fix_grid.isChecked() and self.set_cues.isChecked() else ("Set grid" if self.fix_grid.isChecked() else "Set cues"))
        self.analyse_button.setToolTip("Reuse saved Rekordbox waveforms, BPM and grid. Check audio for drop timing, then prepare changes for review. Import is a separate step.")
        self.analyse_button.setEnabled(bool(self.tracks) and (self.fix_grid.isChecked() or self.set_cues.isChecked()))
        self.populate_table()
        if self.tracks:
            if self.table.currentRow() < 0:
                self.table.selectRow(0)
            self.select_track()
        self.update_details()

    def populate_table(self):
        selected = self.table.currentRow()
        self.table.blockSignals(True)
        rows, reasons = [], []
        for i, track in enumerate(self.tracks):
            proposal = self.proposals[i] if i < len(self.proposals) else None
            cues = proposal.cues if proposal else track.cues
            count = sum(c.kind in ("memory", "memory_loop") for c in cues)
            status = "Ready to prepare"
            if proposal:
                status = "Imported" if proposal.applied else ("Needs review" if not proposal.ready_to_apply else ("Reviewed" if proposal.reviewed else "Cues ready" if not proposal.options.fix_grid else "Prepared"))
            values = [track.title + "\n" + track.artist, track.genre, f"{track.bpm:g}", f"{count} / 10", status]
            rows.append(values)
            needs_review = bool(proposal and not proposal.applied and not proposal.ready_to_apply)
            reason = review_reason(proposal) if needs_review else ""
            if needs_review and (proposal.first_drop_edited or proposal.second_drop_edited):
                reason = "Manual edits kept. " + reason
            reasons.append(reason)
        self.track_count.setText(f"{len(self.tracks)} tracks" + (f" · {self.ignored_track_count} ignored" if self.ignored_track_count else ""))
        self.table.set_rows(rows, reasons)
        visible = [i for i in range(len(self.tracks)) if not self.review_filter.currentIndex() or reasons[i]]
        self.table.set_visible_rows(visible)
        if visible:
            self.table.selectRow(selected if selected in visible else next((i for i in visible if i > selected), visible[0]))
        self.table.blockSignals(False)
        self.refresh_review_controls()
        if self.table.currentRow() != selected:
            self.select_track()
        if not visible:
            self.clear_track_preview()
        self.update_details()

    def review_proposals(self):
        return [p for p in self.proposals if not p.applied and not p.ready_to_apply]

    def automatic_review_proposals(self):
        return [p for p in self.review_proposals() if not (p.first_drop_edited or p.second_drop_edited)]

    def refresh_review_controls(self):
        remaining = len(self.review_proposals())
        ready = sum(p.ready_to_apply for p in self.proposals)
        imported = sum(p.applied for p in self.proposals)
        self.review_controls.setVisible(bool(self.proposals))
        self.review_filter.setItemText(0, f"All tracks ({len(self.tracks)})")
        self.review_filter.setItemText(1, f"Needs review only ({remaining})")
        self.review_summary.setText(f"{ready} ready · {remaining} need review · {imported} imported")
        count = len(self.automatic_review_proposals())
        self.auto_cue_button.setText(f"Auto cue review tracks ({count})")
        self.auto_cue_button.setEnabled(bool(count) and not getattr(self, "analysis_busy", False))
        self.review_filter.setEnabled(not getattr(self, "analysis_busy", False))

    def filter_review_tracks(self):
        self.populate_table()
        if self.review_filter.currentIndex():
            self.focus_review_drop()

    def clear_track_preview(self):
        self.player.stop()
        self.player.setSource(QUrl())
        self.wave.proposal = None
        self.wave.reset_view()
        self.current = -1
        self.review_title.setText("No tracks need review" if self.review_filter.currentIndex() else "Select a track")
        self.details.setText("Choose All tracks to view the prepared results." if self.review_filter.currentIndex() else "Select a playlist and track.")

    def auto_cue_review_tracks(self):
        if getattr(self, "analysis_busy", False) or (self.worker and self.worker.isRunning()):
            return
        jobs = self.automatic_review_proposals()
        if not jobs:
            return
        try:
            self.import_playlist_breakdown()  # retain the original scan's scope
            if not self.library.demo:
                ensure_rekordbox_closed()
            original = tuple(self.proposals)
            scope = self.analysis_scope
            self.set_busy(True)
            self.progress.setRange(0, len(jobs))
            self.worker = CueReviewWorker(jobs)
            def progress(index, title):
                self.progress.setValue(index)
                self.status.setText(f"Auto cue {index + 1} / {len(jobs)} · {title} · keeping Rekordbox grid")
            def done(results):
                # No partially refreshed list or changed selection can expand scope.
                if self.analysis_scope is not scope or len(self.proposals) != len(original) or any(a is not b for a, b in zip(self.proposals, original)):
                    self.set_busy(False)
                    self.status.setText("Playlist results changed; automatic cue retry was discarded.")
                    return
                self.proposals = [results.get(p.track.id, p) for p in original]
                self.set_busy(False)
                self.populate_table()
                self.select_track()
                resolved = sum(p.ready_to_apply for p in results.values())
                remaining = len(self.review_proposals())
                manual = sum(p.first_drop_edited or p.second_drop_edited for p in self.review_proposals())
                self.status.setText(f"Auto cue complete: {resolved} more ready · {remaining} still need review. Existing grids kept. Nothing imported."
                                    + (f" {manual} tracks with manual edits were left unchanged." if manual else ""))
            self.worker.progress.connect(progress)
            self.worker.result.connect(done)
            self.worker.start()
        except Exception as exc:
            self.set_busy(False)
            self.fail(exc)

    def set_busy(self, busy):
        self.analysis_busy = busy
        self.choose_playlists_button.setEnabled(not busy and bool(self.library and getattr(self.library, "playlists", {})))
        for widget in (self.connect_button, self.playlists, self.fix_grid, self.set_cues, self.replace_cues, self.ignore_cued, self.analyse_button):
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
            if self.ignore_cued.isChecked():
                if not self.load_tracks() or not self.tracks:
                    return
            else:
                self.invalidate()
            self.capture_analysis_scope()
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
        self.status.setText(f"Preparing cues / grid {index + 1} / {len(self.tracks)} · {title}")

    def capture_analysis_scope(self):
        """Freeze playlist membership for this scan, independently of later browsing."""
        self.analysis_scope = (self.library, self.selected_playlist_ids(), dict(self.loaded_playlist_tracks))

    def import_playlist_breakdown(self):
        scope = self.analysis_scope
        if scope is None or scope[0] is not self.library or scope[1] != self.selected_playlist_ids():
            raise SafetyError("Playlist selection changed. Prepare cues / grid for the selected playlists again before importing.")
        membership = scope[2]
        allowed = set().union(*(ids for _, ids in membership.values()))
        proposal_ids = [p.track.id for p in self.proposals]
        if (not membership or set(membership) != set(scope[1]) or
                len(proposal_ids) != len(set(proposal_ids)) or set(proposal_ids) != allowed or
                {t.id for t in self.tracks} != allowed):
            raise SafetyError("These results do not match the scanned playlists. Prepare cues / grid for the selected playlists again before importing.")
        ready = {p.track.id for p in self.proposals if p.ready_to_apply}
        done = {p.track.id for p in self.proposals if p.applied}
        return [(name, len(ids), len(ids & ready), len(ids - ready - done), len(ids & done))
                for name, ids in membership.values()]

    def analysis_done(self, proposals):
        self.proposals = proposals
        self.set_busy(False)
        self.populate_table()
        self.status.setText("Cues / grid prepared from Rekordbox analysis. Listen to both drops and review; nothing has been written.")
        if proposals:
            self.table.selectRow(0)
            self.select_track()

    def selected(self):
        index = self.table.currentRow()
        return self.proposals[index] if 0 <= index < len(self.proposals) else None

    def displayed(self):
        return self.selected() or self.wave.proposal

    def saved_preview(self, track):
        # Header metadata only: browsing must not decode audio or prepare edits.
        duration = track.duration
        if track.analysis_paths:
            try:
                duration = sf.info(str(track.path)).duration
            except (OSError, RuntimeError):
                pass
        preview_track = replace(track, duration=duration)
        data = rekordbox_waveforms(track.analysis_paths, duration)
        note = ("Saved Rekordbox waveform, grid and cues. No changes prepared."
                if data else "Saved detailed waveform unavailable. Set cues / grid to prepare an audio preview.")
        note += " Prepare cues / grid to check audio timing and enable playback."
        return Proposal(preview_track, Options(False, False), track.grid, track.cues.copy(),
                        waveform_data=data, peaks=data.peaks if data else [], grid_note=note)

    def select_track(self):
        proposal = self.selected()
        prepared = proposal is not None
        if proposal is None:
            index = self.table.currentRow()
            if not 0 <= index < len(self.tracks):
                return
            proposal = self.saved_preview(self.tracks[index])
        self.current = self.table.currentRow()
        self.player.stop()
        self.metronome.blockSignals(True)
        self.metronome.setChecked(False)
        self.metronome.blockSignals(False)
        self.player.setSource(QUrl.fromLocalFile(str(proposal.track.path)) if prepared else QUrl())
        self.clock.setText("0:00.00")
        self.review_title.setText(proposal.track.title + "  ·  " + proposal.track.artist)
        self.wave.proposal = proposal
        self.wave.reset_view()
        self.focus_review_drop()
        for spin, value in ((self.first, proposal.first_drop), (self.second, proposal.second_drop)):
            spin.blockSignals(True)
            spin.setMaximum(proposal.track.duration)
            spin.setValue(value or 0)
            spin.setEnabled(proposal.options.set_cues)
            spin.blockSignals(False)
        self.update_details()

    def focus_review_drop(self):
        p = self.selected()
        if (p and not p.applied and not p.ready_to_apply and p.first_drop is not None
                and math.isfinite(p.first_drop) and 0 <= p.first_drop < p.track.duration):
            self.wave.set_zoom(16, p.first_drop)

    def update_details(self):
        self.refresh_review_controls()
        p = self.displayed()
        prepared = self.selected() is not None
        self.play.setEnabled(prepared)
        self.play.setToolTip("Play / pause (Space)" if prepared else "Prepare cues / grid first to check audio timing for playback")
        self.metronome.setEnabled(prepared and not (self.metronome_worker and self.metronome_worker.isRunning()))
        if p:
            primary = p.error or p.grid_issue or p.review_note or p.grid_note
            notes = ([p.grid_note] if p.grid_note and p.grid_note != primary else []) + p.warnings
            text = primary + "\n" + " · ".join(notes)
            if p.reviewed:
                text = "Review confirmed. " + text
            if p.ready_to_apply and p.options.set_cues and not p.options.fix_grid:
                text = "Cues only — existing Rekordbox grid will be kept. " + text
            if p.cues_dirty and not p.grid_issue:
                pending = f"Rebuild needed: Drop {p.grid_anchor} will anchor the grid; manually edited markers stay fixed." if p.options.fix_grid else "Rebuild needed: update cue countdowns from your markers."
                text = pending + "\n" + text
            self.details.setText(text)
            self.details.setToolTip(text)
        dirty = bool(p and p.cues_dirty)
        caption = "Rebuild grid + cues" if p and p.options.fix_grid else "Rebuild cues"
        self.rebuild_button.setText(caption + " — needed" if dirty else caption)
        self.rebuild_button.setToolTip("Rebuild from your markers, keeping BPM unchanged. If the other drop is off-grid, keep its exact cue position and flag it for listening. Confirm review accepts the rebuilt result. With Fix beat grid off, only cues change.")
        if self.rebuild_button.property("needsRebuild") != dirty:
            self.rebuild_button.setProperty("needsRebuild", dirty)
            self.rebuild_button.style().unpolish(self.rebuild_button)
            self.rebuild_button.style().polish(self.rebuild_button)
            self.rebuild_button.update()
        can_edit_cues = bool(p and p.options.set_cues and not p.error and not p.applied and not getattr(self, "analysis_busy", False))
        self.rebuild_button.setEnabled(can_edit_cues)
        review_blocker = review_confirmation_error(p) if prepared and p else "Prepare cues / grid first."
        self.confirm_review_button.setText("Review confirmed" if p and p.reviewed else "Confirm review")
        self.confirm_review_button.setEnabled(bool(prepared and p and not p.reviewed and not review_blocker and not getattr(self, "analysis_busy", False)))
        self.confirm_review_button.setToolTip(review_blocker or "Accept the current markers, cues and grid after listening. No timings change; import remains a separate step.")
        self.first.setEnabled(can_edit_cues)
        self.second.setEnabled(can_edit_cues)
        self.grid_anchor_controls.setVisible(bool(p and p.options.fix_grid and p.options.set_cues))
        self.grid_anchor_label.setText(f"Anchor: Drop {p.grid_anchor} · BPM unchanged" if p else "")
        for number, control in enumerate(self.grid_anchor_buttons, 1):
            control.setEnabled(can_edit_cues and p.options.fix_grid and
                               (p.first_drop if number == 1 else p.second_drop) is not None)
        for control in self.kick_buttons:
            control.setEnabled(can_edit_cues)
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
        if p and p.options.set_cues and not getattr(self, "analysis_busy", False):
            refresh = p.reviewed or not p.cues_dirty
            first, second = self.first.value(), self.second.value()
            if first != p.first_drop:
                p.first_drop_edited = True
                p.grid_anchor = 1
            if second != p.second_drop:
                p.second_drop_edited = True
                p.grid_anchor = 2
            p.first_drop, p.second_drop = first, second
            p.grid_issue = ""
            p.review_note = ""
            if p.options.fix_grid:
                p.grid_note = f"Grid preview needs rebuilding from Drop {p.grid_anchor}."
            p.cues_dirty = True
            p.applied = False
            p.reviewed = False
            p.grid_approved = False
            self.wave.update()
            self.update_details()
            if refresh:
                self.populate_table()

    def move_drop_marker(self, number, seconds):
        if getattr(self, "analysis_busy", False):
            return
        (self.first if number == 1 else self.second).setValue(seconds)

    def select_grid_anchor(self, number):
        """Explicit selection must count even when a marker is already on the kick."""
        p = self.selected()
        if not p or number not in (1, 2):
            return
        p.grid_anchor = number
        if number == 1:
            p.first_drop_edited = True
        else:
            p.second_drop_edited = True
        p.cues_dirty = True
        p.review_note = ""
        p.grid_issue = ""
        p.reviewed = p.grid_approved = False
        if p.options.fix_grid:
            p.grid_note = f"Grid preview needs rebuilding from Drop {number}."

    def align_grid_to_drop(self, number):
        p = self.selected()
        if (number not in (1, 2) or not p or not p.options.fix_grid or not p.options.set_cues or p.error or p.applied
                or getattr(self, "analysis_busy", False)):
            return
        target = p.first_drop if number == 1 else p.second_drop
        if target is None:
            return
        self.select_grid_anchor(number)
        self.rebuild_cues()

    def snap_drop_to_kick(self, number):
        p = self.selected()
        if not p or not p.options.set_cues or p.error or p.applied or getattr(self, "analysis_busy", False):
            return
        target = p.first_drop if number == 1 else p.second_drop
        if target is None:
            self.status.setText(f"Set drop {number} near the intended kick first.")
            return
        match = match_attack(p.attacks, target, p.grid, p.track.duration,
                             lower=p.first_drop if number == 2 and p.first_drop is not None else -1.,
                             upper=p.second_drop if number == 1 else p.track.duration)
        prefix = f"Drop {number}: "
        old_notes = p.drop_notes.copy()
        p.drop_notes = [note for note in p.drop_notes if not note.startswith(prefix)]
        if match.needs_review:
            p.drop_notes.append(prefix + match.note)
        p.warnings = [note for note in p.warnings if note not in old_notes] + p.drop_notes
        if match.time is not None:
            self.player.pause()
            self.move_drop_marker(number, match.time)
            self.select_grid_anchor(number)
            self.seek(match.time)
            self.wave.set_zoom(max(32, self.wave.zoom), match.time)
            self.populate_table()
        next_step = (f"Use Align to Drop {number} to update the grid. " if p.options.fix_grid
                     else "Rebuild cues to use this marker. ") if match.time is not None else ""
        self.status.setText(prefix + next_step + match.note)
        self.update_details()

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
        if p is None or not p.options.fix_grid or p.error or p.applied or getattr(self, "analysis_busy", False):
            return
        try:
            from .grid_writer import align_downbeat
            self.player.pause()
            grid, anchor = align_downbeat(p.grid, self.player.position() / 1000 + self.playback_offset(), p.track.duration)
            if p.options.set_cues and p.second_drop is not None and anchor >= p.second_drop:
                raise ValueError("The first drop must be before the second drop.")
            self.metronome.setChecked(False)
            p.grid = grid
            p.grid_note = "Grid aligned to the first drop at the playhead. Check the metronome throughout the track."
            p.reviewed = p.grid_approved = False
            p.review_note = ""
            if p.options.set_cues:
                p.first_drop = anchor
                p.first_drop_edited = True
                p.grid_anchor = 1
                self.first.blockSignals(True)
                self.first.setValue(anchor)
                self.first.blockSignals(False)
                p.cues_dirty = True
            self.wave.update()
            self.populate_table()
            self.update_details()
        except Exception as exc:
            self.fail(exc)

    def confirm_review(self):
        p = self.selected()
        if p is None or getattr(self, "analysis_busy", False):
            return
        try:
            was_review = not p.ready_to_apply
            selected = self.table.currentRow()
            confirm_proposal_review(p)
            title = p.track.title
            self.populate_table()
            if was_review and not self.review_filter.currentIndex():
                remaining = [i for i, item in enumerate(self.proposals) if not item.applied and not item.ready_to_apply]
                if remaining:
                    self.table.selectRow(next((i for i in remaining if i > selected), remaining[0]))
            self.status.setText(f"Review confirmed: {title}. Ready to import; nothing has been written.")
            self.update_details()
        except (ValueError, SafetyError) as exc:
            self.status.setText(str(exc))
            self.update_details()

    def rebuild_cues(self):
        p = self.selected()
        if p is None or not p.options.set_cues or getattr(self, "analysis_busy", False):
            return
        try:
            self.player.pause()
            self.metronome.setChecked(False)
            p.first_drop, p.second_drop = self.first.value(), self.second.value()
            rebuild_proposal(p, manual=True)
            first, second = p.first_drop, p.second_drop
            self.status.setText(p.grid_issue or p.review_note)
            self.populate_table()
            # The review filter may have advanced to a different track.
            if self.selected() is p:
                for spin, value in ((self.first, first), (self.second, second)):
                    spin.blockSignals(True)
                    spin.setValue(value)
                    spin.blockSignals(False)
            self.wave.update()
            self.update_details()
        except Exception as exc:
            self.fail(exc)

    def show_cues(self):
        p = self.displayed()
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
        if self.selected() is not None:
            self.player.setPosition(max(0, round((seconds - self.playback_offset()) * 1000)))
        self.clock.setText(time_text(seconds))
        self.wave.set_position(seconds)

    def playback_offset(self):
        p = self.selected()
        return p.track.audio_offset if p and self.player.source().toLocalFile() == str(p.track.path) else 0.

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
        position = self.player.position() / 1000 + self.playback_offset()
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        if not enabled:
            self.player.setSource(QUrl.fromLocalFile(str(p.track.path)))
            self.seek(position)
            if playing:
                self.player.play()
            return
        if self.metronome_worker and self.metronome_worker.isRunning():
            return
        cache = self.base / "Preview audio"
        cache.mkdir(exist_ok=True)
        stat = p.track.path.stat()
        preview_grid = (tuple(p.grid.times), tuple(p.grid.positions))
        key = hashlib.sha256((str(p.track.path) + str(stat.st_mtime_ns) + str(stat.st_size) + repr(preview_grid) + str(p.track.audio_offset)).encode()).hexdigest()[:24]
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
            self.seek(position)
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
        seconds = max(0., milliseconds / 1000 + self.playback_offset())
        self.clock.setText(time_text(seconds))
        self.wave.set_position(seconds)

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
        try:
            breakdown = self.import_playlist_breakdown()
        except SafetyError as exc:
            self.fail(exc)
            return
        dialog = ImportDialog(self, candidates, skipped, self.backups.directory, live,
                              len(self.selected_playlist_ids()), breakdown)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.import_playlist_breakdown()
            if candidates != [p for p in self.proposals if p.ready_to_apply]:
                raise SafetyError("Import results changed. Review the import summary again.")
            scan_scope = self.analysis_scope
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
            remaining_ids = {t.id for t in self.tracks}
            if self.tracks and (remaining_ids == set(previous) or
                                (self.ignore_cued.isChecked() and remaining_ids <= set(previous))):
                self.proposals = [previous[t.id] for t in self.tracks]
                if self.ignore_cued.isChecked():
                    self.capture_analysis_scope()
                else:
                    self.analysis_scope = scan_scope
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
            report = {"manager_version": "0.3.33", "system": platform.system(),
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
            self.settings_feedback.setText("Diagnostics saved to " + path)
        except Exception as exc:
            self.fail(exc)

    def closeEvent(self, event):
        if self.metronome_worker and self.metronome_worker.isRunning():
            self.status.setText("Wait for metronome preview generation before closing.")
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.status.setText("Stopping after the current track. Close again when preparation stops.")
            event.ignore()
            return
        self.player.stop()
        event.accept()
