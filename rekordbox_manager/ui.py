from __future__ import annotations

from dataclasses import asdict, replace
from copy import deepcopy
from collections import OrderedDict
import json
from pathlib import Path
import math
import platform
import soundfile as sf

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QTimer, QEvent, QObject
from PySide6.QtGui import QDesktopServices, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QComboBox, QFileDialog, QMessageBox, QStackedWidget, QFrame,
    QDoubleSpinBox, QProgressBar, QSplitter, QListWidget, QListView, QStyledItemDelegate, QDialog, QTextEdit,
    QScrollArea, QScrollBar, QSizePolicy, QApplication, QLineEdit, QPlainTextEdit, QAbstractSpinBox, QTabBar, QToolTip,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from .models import Grid, Options, Proposal
from .waveform import Waveform
from .waveform_data import rekordbox_waveforms
from .dialogs import ImportDialog, PlaylistDialog, review_reason
from .cues import plan_cues
from .analysis import analyse, rebuild_proposal, review_confirmation_error, confirm_proposal_review
from .attacks import match_attack
from .backups import BackupStore, durable_json
from .guards import SafetyError, ensure_rekordbox_closed
from .library import RekordboxLibrary
from .organiser_ui import OrganiserTab
from .organiser_queue import OrganiserQueue
from .organiser_writer import apply_plan
from .import_queue import ImportQueue, import_snapshot
from .imports_ui import ImportsTab
from .track_list import ElidedLabel, TrackList, track_columns
from .playlist_browser import PlaylistBrowser
from .cue_audit import audit_track, audit_key, CueAuditResult
from .cue_overview import CueOverview
from .overview_loader import OverviewWorker, overview_key
from .paths import data_dir, discover_databases
from . import __version__


STYLE = """
QWidget { background: #1a1b1d; color: #e7e8ea; font-family: 'Inter', '.AppleSystemUIFont', 'Segoe UI'; font-size: 12px; }
QLabel { background: transparent; }
QMainWindow { background: #1a1b1d; }
QTabBar::tab { background: #222426; color: #a7abb1; padding: 10px 22px; border-bottom: 2px solid #393c40; }
QTabBar::tab:selected { color: #e7e8ea; background: #30373e; border-bottom: 2px solid #739fc9; }
QTabBar::tab:hover { background: #36393d; }
QLineEdit { background: #181a1c; border: 1px solid #484c51; border-radius: 3px; padding: 6px; }
QLabel#eyebrow { color: #a3a7ad; font-size: 11px; font-weight: 600; letter-spacing: 2px; }
QLabel#title { font-size: 29px; font-weight: 650; }
QLabel#section { font-size: 17px; font-weight: 600; }
QLabel#muted { color: #a7abb1; }
QFrame#card { background: #222426; border: 1px solid #393c40; border-radius: 10px; }
QFrame#connectionCard { background: #202225; border: 1px solid #393d42; border-radius: 12px; }
QFrame#databaseCard { background: transparent; border: 0; }
QLabel#databaseState { font-size: 16px; font-weight: 600; }
QLabel#databaseState[state="saved"], QLabel#databaseState[state="selected"] { color: #a8cbea; }
QLabel#databaseState[state="unavailable"], QLabel#databaseState[state="failed"] { color: #e4bd79; }
QLabel#gateTitle { font-size: 32px; font-weight: 650; }
QLabel#gateDescription { color: #a7abb1; font-size: 14px; }
QFrame#gateDivider { background: #393d42; border: 0; max-height: 1px; }
QPushButton#libraryBrowse { background: transparent; border: 1px solid #484b50; border-radius: 5px; padding: 7px 12px; }
QPushButton#libraryBrowse:hover { background: #2b2d30; border-color: #739fc9; }
QPushButton { background: #2b2d30; border: 1px solid #484b50; border-radius: 3px; padding: 6px 10px; font-weight: 550; }
QPushButton:hover { background: #36393d; border-color: #7ca7d0; }
QPushButton:disabled { color: #777b81; background: #232528; border-color: #35383c; }
QPushButton#primary { background: #739fc9; color: #101820; border: 0; }
QPushButton#prepareToggle:checked { background: #739fc9; color: #101820; border-color: #739fc9; }
QPushButton#prepareToggle:checked:hover { background: #91b5d7; border-color: #91b5d7; }
QPushButton#prepareToggle:disabled { background: #232528; color: #777b81; border-color: #35383c; }
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
QCheckBox::indicator, QTreeWidget::indicator { width: 17px; height: 17px; border: 1px solid #7e858d; border-radius: 4px; background: #202225; }
QCheckBox::indicator:checked, QTreeWidget::indicator:checked { background: #739fc9; border: 1px solid #739fc9; image: url("@CHECK_ICON@"); }
QCheckBox::indicator:checked:disabled { background: #7d8791; border-color: #7d8791; }
QPushButton#track { background: #1a1c1e; text-align: left; padding: 0; border: 0; border-bottom: 1px solid #303236; border-radius: 0; }
QPushButton#track[alternate="true"] { background: #212326; }
QPushButton#track:hover { background: #303338; }
QPushButton#track QLabel { background: transparent; font-weight: 400; }
QPushButton#track:focus { border: 1px solid #739fc9; }
QFrame#deck { background: #151719; border: 1px solid #3a3d41; }
QWidget[deckControls="true"] { background: transparent; }
QFrame#browser { background: #181a1c; border: 1px solid #3a3d41; }
QWidget#columnHeader { background: #2b2d30; border-bottom: 1px solid #45494e; }
QWidget#columnHeader QLabel { color: #b2b6bc; font-size: 11px; }
QLabel#brand { font-size: 15px; font-weight: 650; }
QLabel#transportClock { font-size: 19px; font-weight: 600; color: #d6dce2; }
QLabel#deckTitle { font-size: 15px; font-weight: 600; }
QSplitter::handle:hover { background: #739fc9; }
QPushButton#track:checked { background: #30373e; border-left: 3px solid #739fc9; }
QPushButton#track[needsReview="true"] { background: #293640; border-bottom-color: #3b4853; }
QPushButton#track[needsReview="true"] QLabel { color: #e7e8ea; }
QPushButton#track[needsReview="true"]:hover { background: #334550; }
QPushButton#track[needsReview="true"]:checked { background: #405568; border-left: 3px solid #91b5d7; }
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


def preparation_toggle(title, checked=False):
    control = QPushButton()
    control.setObjectName("prepareToggle")
    control.setCheckable(True)
    def update_text(on):
        control.setText(f"{title} · {'On' if on else 'Off'}")
    control.toggled.connect(update_text)
    control.setChecked(checked)
    update_text(checked)
    return control


def time_text(seconds: float) -> str:
    return f"{int(seconds) // 60}:{seconds % 60:05.2f}"


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


class CueAuditWorker(QThread):
    progress = Signal(int, str)
    result = Signal(object)

    def __init__(self, tracks, tolerance_ms, cache):
        super().__init__()
        self.tracks, self.tolerance_ms, self.cache = tracks, tolerance_ms, cache
        self.cache_hits = 0
        self.cached_at_start = dict(cache)

    def run(self):
        results = {}
        for index, track in enumerate(self.tracks):
            if self.isInterruptionRequested():
                break
            self.progress.emit(index, track.title)
            try:
                key = audit_key(track, self.tolerance_ms)
                if key in self.cached_at_start:
                    checked = self.cached_at_start.pop(key)
                    self.cache.pop(key, None)
                    self.cache_hits += 1
                else:
                    checked = audit_track(track, self.tolerance_ms)
                if audit_key(track, self.tolerance_ms) != key:
                    checked = CueAuditResult('Unavailable', tuple(c for c in track.cues if c.kind == 'memory'), reason='Source files changed during the check. Reconnect and scan again.')
                else:
                    self.cache[key] = checked
                    while len(self.cache) > 256:
                        self.cache.popitem(last=False)
                results[track.id] = checked
            except Exception as exc:
                results[track.id] = CueAuditResult('Unavailable', tuple(c for c in track.cues if c.kind == 'memory'), reason=str(exc))
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


class _HoverTooltipFilter(QObject):
    """Suppress hover popups, including dynamically created rows and dialogs."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.ToolTip:
            return True
        return super().eventFilter(watched, event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Keep this application-owned filter separate from the temporary Cue
        # transport filter, which is removed when the Cue button is released.
        app = QApplication.instance()
        if not hasattr(app, '_hover_tooltip_filter'):
            app._hover_tooltip_filter = _HoverTooltipFilter(app)
            app.installEventFilter(app._hover_tooltip_filter)
        QToolTip.hideText()
        self.setWindowTitle("Rekordbox Manager · Preview")
        self.resize(1280, 870)
        self.setMinimumSize(1050, 720)
        self.library = None
        self.playlist_ids = ()
        self.import_queue = ImportQueue()
        self.organiser_queue = OrganiserQueue()
        self.audit_results = {}
        self.audit_drafts = {}
        self.audit_kept = {}
        self.audit_cache = OrderedDict()
        self.row_previews = []
        self.overview_cache = OrderedDict()
        self.overview_worker = None
        self.overview_jobs = []
        self.overview_keys = []
        self.startup_database = None
        self.proposals: list[Proposal] = []
        self.tracks = []
        self.ignored_track_count = 0
        self.loaded_playlist_tracks = {}
        self.analysis_scope = None
        self.worker = None
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
        self.cue_position = 0.0
        self.cue_held = False
        self.cue_source = QUrl()
        self.audio = QAudioOutput(self)
        self.audio.setVolume(.5)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self.play_position)
        self.player.errorOccurred.connect(lambda error, text: self.status.setText("Playback unavailable: " + text))
        self.player.errorOccurred.connect(lambda *args: self.cancel_cue(return_to_cue=False))
        self.player.sourceChanged.connect(lambda *args: self.cancel_cue(return_to_cue=False))
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
                   and self.tabs.currentWidget() is self.manager_tab)
        widget = focused
        while widget is not None and enabled:
            if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, PlaylistBrowser)):
                enabled = False
            widget = widget.parentWidget()
        self.play_shortcut.setEnabled(enabled and not getattr(self, "analysis_busy", False))
        navigation_enabled = enabled and not getattr(self, "analysis_busy", False)
        widget = focused
        while widget is not None and navigation_enabled:
            if isinstance(widget, QComboBox):
                navigation_enabled = False
            widget = widget.parentWidget()
        for shortcut in self.track_shortcuts:
            shortcut.setEnabled(navigation_enabled)

    def focus_transport(self):
        """Return completed actions to deck shortcuts without stealing another window's focus."""
        if (QApplication.activeWindow() is self and self.pages.currentWidget() is self.workspace
                and self.tabs.currentWidget() is self.manager_tab and not getattr(self, 'analysis_busy', False)):
            self.wave.setFocus(Qt.OtherFocusReason)
            self.update_play_shortcut(None, self.wave)

    def navigate_track(self, step):
        if (not self.tracks or getattr(self, "analysis_busy", False)
                or self.pages.currentWidget() is not self.workspace or self.tabs.currentWidget() is not self.manager_tab):
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
        outer.setContentsMargins(40, 32, 40, 32)
        outer.addStretch()
        content = QWidget()
        content.setMaximumWidth(640)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        brand = QHBoxLayout()
        brand.addWidget(label("REKORDBOX MANAGER", "eyebrow"))
        brand.addStretch()
        brand.addWidget(label(f"{__version__} · Preview", "muted"))
        column.addLayout(brand)
        column.addSpacing(26)
        column.addWidget(label("Connect your library", "gateTitle"))
        column.addSpacing(8)
        column.addWidget(label("Prepare tracks, check cues and organise your playlists.", "gateDescription", True))
        column.addSpacing(26)
        card = QFrame()
        card.setObjectName("connectionCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(24, 24, 24, 24)
        box.setSpacing(0)
        self.startup_database_card = QFrame()
        self.startup_database_card.setObjectName("databaseCard")
        database_box = QVBoxLayout(self.startup_database_card)
        database_box.setContentsMargins(0, 0, 0, 0)
        database_box.setSpacing(10)
        library_row = QHBoxLayout()
        self.startup_database_heading = label("", "databaseState", True)
        library_row.addWidget(self.startup_database_heading, 1)
        self.startup_browse = button("Choose database…", self.choose_startup_database)
        self.startup_browse.setObjectName("libraryBrowse")
        library_row.addWidget(self.startup_browse)
        database_box.addLayout(library_row)
        self.startup_database_help = label("", "muted", True)
        database_box.addWidget(self.startup_database_help)
        self.startup_database_label = label("No database selected", "muted", True)
        self.startup_database_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        database_box.addWidget(self.startup_database_label)
        box.addWidget(self.startup_database_card)
        box.addSpacing(24)
        divider = QFrame()
        divider.setObjectName("gateDivider")
        divider.setFixedHeight(1)
        box.addWidget(divider)
        box.addSpacing(20)
        self.confirm = QCheckBox("Rekordbox is closed and my library is backed up.")
        self.confirm.setToolTip("Close Rekordbox normally before connecting. The app also checks for running Rekordbox processes.")
        box.addWidget(self.confirm)
        box.addSpacing(18)
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
        self.continue_button.setMinimumHeight(42)
        self.update_startup_ready()
        self.confirm.toggled.connect(self.update_startup_ready)
        box.addWidget(self.continue_button)
        column.addWidget(card)
        column.addSpacing(18)
        note = label("Local processing · Automatic backups before import", "muted")
        note.setAlignment(Qt.AlignCenter)
        column.addWidget(note)
        centred = QHBoxLayout()
        centred.addStretch()
        centred.addWidget(content, 1)
        centred.addStretch()
        outer.addLayout(centred)
        outer.addStretch()
        return page

    def set_startup_database_state(self, state):
        self.startup_database_state = state
        heading, help_text = {
            "empty": ("No library selected", "Choose your Rekordbox master.db database to get started."),
            "saved": ("Saved library", "Your previously connected library is ready to reconnect."),
            "selected": ("Library selected", "Connect to load your playlists and saved track analysis."),
            "unavailable": ("Saved library unavailable", "The saved file could not be found. Reconnect its drive and choose the database again."),
            "connecting": ("Connecting to your library…", "Checking the database and loading your playlists."),
            "failed": ("Connection needs attention", "Your selection is kept. Check the message below, then retry or change the database."),
        }[state]
        self.startup_status.setVisible(state in ("connecting", "failed"))
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
            self.playlist_browser.tree.setFocus()
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
        toolbar.addWidget(label(f"{__version__} · Preview", "muted"))
        toolbar.addStretch()
        self.navigation = QTabBar()
        self.navigation.setAccessibleName("App functions")
        self.navigation.setExpanding(False)
        self.navigation.setDrawBase(False)
        toolbar.addWidget(self.navigation)
        layout.addLayout(toolbar)
        self.tabs = QStackedWidget()
        self.manager_tab = self.build_manager()
        self.imports_tab = ImportsTab(self.import_queue, self.organiser_queue)
        self.imports_tab.import_requested.connect(self.import_queued_tracks)
        self.imports_tab.review_requested.connect(self.review_queued_track)
        self.usage_tab = OrganiserTab(queue=self.organiser_queue)
        self.usage_tab.busy_changed.connect(self.refresh_imports)
        self.usage_tab.add_requested.connect(self.add_unfiled_tracks)
        self.usage_tab.drafts_changed.connect(self.refresh_imports)
        self.imports_tab.organiser.import_requested.connect(self.import_organiser_changes)
        self.imports_tab.organiser.changed.connect(self.organiser_drafts_changed)
        self.backups_tab = self.build_backups()
        self.settings_tab = self.build_settings()
        # New functions own their page and state; navigation never rebuilds Manager.
        for title, widget in (("Manager", self.manager_tab), ("Imports", self.imports_tab), ("Organiser", self.usage_tab),
                              ("Backups", self.backups_tab), ("Settings", self.settings_tab)):
            self.tabs.addWidget(widget)
            self.navigation.addTab(title)
        self.navigation.currentChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.navigation.setCurrentIndex)
        self.tabs.currentChanged.connect(self.workspace_tab_changed)
        layout.addWidget(self.tabs, 1)
        return page

    def workspace_tab_changed(self):
        if self.tabs.currentWidget() is not self.manager_tab:
            self.cancel_cue()
            self.player.pause()
        if self.tabs.currentWidget() is self.backups_tab:
            self.refresh_backups()
        if self.tabs.currentWidget() is self.imports_tab:
            self.sync_import_queue()
            self.refresh_imports()

    def build_manager(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
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
        self.wave.setFocusPolicy(Qt.StrongFocus)
        self.wave.setMinimumHeight(150)
        self.wave.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.wave.seek.connect(self.seek)
        self.wave.anchor_moved.connect(self.move_drop_marker)
        self.wave.drag_started.connect(self.player.pause)
        self.original_wave = Waveform()
        self.original_wave.setFocusPolicy(Qt.StrongFocus)
        self.original_wave.setMinimumHeight(95)
        self.original_wave.seek.connect(self.seek)
        self.original_wave.view_changed.connect(self.sync_from_original_wave)
        self.original_wave_box = QWidget()
        self.original_wave_box.setProperty('deckControls', True)
        original_box = QVBoxLayout(self.original_wave_box)
        original_box.setContentsMargins(0, 0, 0, 0)
        original_box.setSpacing(0)
        original_box.addWidget(label('Original', 'muted'))
        original_box.addWidget(self.original_wave, 1)
        deck_box.addWidget(self.original_wave_box, 1)
        self.original_wave_box.hide()
        self.proposed_wave_box = QWidget()
        self.proposed_wave_box.setProperty('deckControls', True)
        proposed_box = QVBoxLayout(self.proposed_wave_box)
        proposed_box.setContentsMargins(0, 0, 0, 0)
        proposed_box.setSpacing(0)
        self.proposed_wave_label = label('Proposed', 'muted')
        self.proposed_wave_label.hide()
        proposed_box.addWidget(self.proposed_wave_label)
        proposed_box.addWidget(self.wave, 1)
        deck_box.addWidget(self.proposed_wave_box, 1)
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
        self.cue_button = button('Cue', lambda: None)
        self.cue_button.setAccessibleName('Hold Cue to audition; release to return')
        self.cue_button.setToolTip('While paused, seek to set the temporary cue. Hold Cue to play; release to pause and return. During playback, Cue auditions from the last cue position. This does not create a saved memory cue.')
        self.cue_button.setEnabled(False)
        self.cue_button.pressed.connect(self.press_cue)
        self.cue_button.released.connect(self.release_cue)
        playback.addWidget(self.cue_button)
        self.clock = label("0:00.00", "transportClock")
        self.clock.setMinimumWidth(95)
        playback.addWidget(self.clock)
        playback.addStretch()
        self.clock.setToolTip("Space: play / pause · ↑/↓: tracks")
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
        anchors.setContentsMargins(0, 0, 0, 0)
        anchors.setSpacing(4)
        self.first = QDoubleSpinBox()
        self.second = QDoubleSpinBox()
        for spin in (self.first, self.second):
            spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
            spin.setDecimals(3)
            spin.setRange(0, 3600)
            spin.setSuffix(" s")
            spin.setSingleStep(.1)
            spin.setFixedWidth(80)
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
        playback.insertWidget(3, label("Snap", "muted"))
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
        playback.insertWidget(4, self.marker_snap)
        self.rebuild_button = button("Rebuild cues", self.rebuild_cues)
        self.rebuild_button.setObjectName("rebuildCues")
        self.rebuild_button.setEnabled(False)
        anchors.addWidget(self.rebuild_button)
        self.keep_original_button = button("Keep original cues", self.keep_original_cues)
        self.keep_original_button.setToolTip("Leave saved cues and grid unchanged and remove this track from Imports, including any previously queued preparation.")
        anchors.addWidget(self.keep_original_button)
        self.keep_original_button.hide()
        self.confirm_review_button = button("Confirm review", self.confirm_review, True)
        self.confirm_review_button.setEnabled(False)
        anchors.addWidget(self.confirm_review_button)
        self.anchor_controls = QWidget()
        self.anchor_controls.setProperty('deckControls', True)
        self.anchor_controls.setLayout(anchors)
        for control in self.anchor_controls.findChildren(QPushButton):
            control.setStyleSheet('padding: 6px 6px;')
        # Native Windows button minimums can redistribute the drop controls when
        # the review actions change. Keep these fixed-label controls text-sized.
        for control in (zoom_first, kick_first, zoom_second, kick_second):
            control.ensurePolished()
            control.setFixedWidth(control.fontMetrics().horizontalAdvance(control.text()) + 16)
        for index in (0, 5):
            anchors.itemAt(index).widget().setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        deck_box.addWidget(self.anchor_controls)
        self.grid_anchor_controls = QWidget()
        self.grid_anchor_controls.setProperty('deckControls', True)
        grid_controls = QHBoxLayout(self.grid_anchor_controls)
        grid_controls.setContentsMargins(0, 0, 0, 0)
        grid_controls.setSpacing(4)
        self.grid_anchor_controls.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        grid_controls.addWidget(label("Beat grid", "muted"))
        self.grid_left = button('‹', lambda: self.nudge_grid(-1))
        self.grid_right = button('›', lambda: self.nudge_grid(1))
        for name, control in (('left', self.grid_left), ('right', self.grid_right)):
            control.setAccessibleName(f'Shift beat grid {name}')
            control.setToolTip(f'Shift the proposed grid {name} by 10 ms. Shift-click: 1 ms. BPM and drop markers stay fixed; rebuild cues afterwards.')
            control.setFixedWidth(30)
            grid_controls.addWidget(control)
        self.grid_anchor_buttons = []
        for number in (1, 2):
            control = button(f"Align to Drop {number}", lambda checked=False, n=number: self.align_grid_to_drop(n))
            control.setToolTip(f"Keep Drop {number} at its chosen time and move a bar start onto it. Rebuild cues and check the other drop. BPM stays unchanged.")
            self.grid_anchor_buttons.append(control)
            grid_controls.addWidget(control)
        for control in self.grid_anchor_controls.findChildren(QPushButton):
            control.setStyleSheet("padding: 6px 6px;")
        playback.insertSpacing(3, 12)
        playback.insertWidget(4, self.grid_anchor_controls)

        self.edit_feedback = label('', 'muted')
        self.edit_feedback.setWordWrap(True)
        self.edit_feedback.hide()
        deck_box.addWidget(self.edit_feedback)
        self.deck_splitter.addWidget(deck)

        browser = QFrame()
        browser.setObjectName("browser")
        browser_box = QVBoxLayout(browser)
        browser_box.setContentsMargins(0, 0, 0, 0)
        browser_box.setSpacing(0)
        self.choose_playlists_button = button("Select multiple…", self.choose_playlists)
        self.choose_playlists_button.setToolTip("Choose several playlists to prepare together.")
        self.choose_playlists_button.setEnabled(False)
        self.fix_grid = preparation_toggle("Fix beat grid")
        self.set_cues = preparation_toggle("Set memory cues", True)
        self.replace_cues = preparation_toggle("Replace memory cues")
        self.replace_cues.setToolTip("On: replace existing memory cues. Off: keep existing memory cues and fill free slots. Saved loops and hot cues are preserved.")
        for widget in (self.fix_grid, self.set_cues, self.replace_cues):
            widget.toggled.connect(self.invalidate)
        self.ignore_cued = preparation_toggle("Ignore cued tracks")
        self.ignore_cued.setToolTip("On: skip tracks with saved memory cues, hot cues or loops; exclude them from preparation and import. Off: show all tracks.")
        self.ignore_cued.toggled.connect(self.change_ignore_cued)
        self.review_controls = QWidget()
        review_row = QHBoxLayout(self.review_controls)
        review_row.setContentsMargins(10, 7, 10, 7)
        self.review_filter = QComboBox()
        self.review_filter.setAccessibleName("Track review filter")
        self.review_filter.addItems(["All tracks (0)", "Needs review only (0)"])
        self.review_filter.setToolTip("Choose Needs review only to hide tracks that are ready or already imported.")
        review_row.addWidget(label("Show"))
        self.review_filter.currentIndexChanged.connect(self.filter_review_tracks)
        self.review_filter.activated.connect(lambda: QTimer.singleShot(0, self.focus_transport))
        review_row.addWidget(self.review_filter)
        self.review_summary = ElidedLabel("", "muted")
        review_row.addWidget(self.review_summary, 1)
        self.auto_cue_button = button("Auto cue review tracks", self.auto_cue_review_tracks)
        self.auto_cue_button.setToolTip("Retry cues for tracks needing review using their existing Rekordbox grids. No grid changes or import. Manual drop edits are kept and excluded from automatic retry. Uncertain results remain flagged.")
        review_row.addWidget(self.auto_cue_button)
        browser_box.addWidget(self.review_controls)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        browser_box.addWidget(self.progress)
        header = QWidget()
        header.setObjectName("columnHeader")
        header.setFixedHeight(25)
        columns = track_columns(header, ["#", "WAVEFORM / CUES", "TRACK TITLE", "ARTIST", "BPM", "MEMORY", "STATUS"])
        columns.setContentsMargins(10, 0, 19, 0)  # match the track scrollbar gutter
        browser_box.addWidget(header)
        self.table = TrackList()
        self.table.itemSelectionChanged.connect(self.select_track)
        self.table.setMinimumHeight(112)
        browser_box.addWidget(self.table, 1)
        self.playlist_browser = PlaylistBrowser()
        self.playlist_browser.layout().addWidget(self.choose_playlists_button)
        self.playlist_browser.playlist_selected.connect(lambda identity: self.set_playlist_selection((identity,)))
        self.library_splitter = QSplitter(Qt.Horizontal)
        self.library_splitter.setChildrenCollapsible(False)
        self.library_splitter.setHandleWidth(6)
        self.library_splitter.setAccessibleName("Resize playlist folders and tracks")
        self.library_splitter.addWidget(self.playlist_browser)
        self.library_splitter.addWidget(browser)
        self.library_splitter.setStretchFactor(0, 0)
        self.library_splitter.setStretchFactor(1, 1)
        self.library_splitter.setSizes([230, 1000])
        self.deck_splitter.addWidget(self.library_splitter)
        self.deck_splitter.setStretchFactor(0, 0)
        self.deck_splitter.setStretchFactor(1, 1)
        self.deck_splitter.setSizes([340, 390])
        box.addWidget(self.deck_splitter, 1)
        self.status = ElidedLabel("No changes have been made.", "muted")
        box.addWidget(self.status)
        self.preparation_controls = QWidget()
        self.preparation_controls.setAccessibleName("Playlist preparation options and scan")
        footer = QHBoxLayout(self.preparation_controls)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(6)
        self.scan_mode = QComboBox()
        self.scan_mode.setAccessibleName("Playlist scan mode")
        self.scan_mode.addItems(["Prepare tracks", "Check saved cues"])
        self.scan_mode.setToolTip("Prepare changes for import, or compare existing memory cues without changing them.")
        self.scan_mode.currentIndexChanged.connect(self.change_scan_mode)
        self.scan_mode.activated.connect(lambda: QTimer.singleShot(0, self.focus_transport))
        footer.addWidget(self.scan_mode)
        for control in (self.fix_grid, self.set_cues, self.replace_cues, self.ignore_cued):
            footer.addWidget(control)
        self.audit_tolerance = QDoubleSpinBox()
        self.audit_tolerance.setDecimals(0)
        self.audit_tolerance.setRange(1, 250)
        self.audit_tolerance.setValue(50)
        self.audit_tolerance.setPrefix("Tolerance: ")
        self.audit_tolerance.setSuffix(" ms")
        self.audit_tolerance.setAccessibleName("Saved cue comparison tolerance in milliseconds")
        self.audit_tolerance.setToolTip("Maximum timing difference for a matching memory cue. Changing this clears current check results; scan again.")
        self.audit_tolerance.valueChanged.connect(self.clear_audit_results)
        footer.addWidget(self.audit_tolerance)
        self.audit_tolerance.hide()
        self.cancel_scan_button = button("Cancel scan", self.cancel_scan)
        footer.addWidget(self.cancel_scan_button)
        self.cancel_scan_button.hide()
        footer.addStretch()
        self.analyse_button = button("Scan && prepare playlist", self.start_analysis, True)
        self.analyse_button.setEnabled(False)
        footer.addWidget(self.analyse_button)
        box.addWidget(self.preparation_controls)
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
        self.original_wave.set_style(self.wave.waveform_style)
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
        box.addWidget(label("The last connected database is remembered for next time. Reconnecting or changing libraries clears the Imports queue, analysis and marker edits after confirmation.", "muted", True))
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
        box.addWidget(button("← Back to playlist", lambda: self.tabs.setCurrentWidget(self.manager_tab)))
        return page

    def change_waveform_style(self, index):
        style = self.waveform_style_combo.currentData()
        self.wave.set_style(style)
        self.original_wave.set_style(style)
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
        box.addWidget(button("← Back to playlist", lambda: self.tabs.setCurrentWidget(self.manager_tab)))
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
        if not self.confirm_discard_preparation('Reconnect or change library'):
            return False
        self.player.stop()
        self.import_queue.reset(library)
        self.organiser_queue.reset(library)
        self.queued_review_only = False
        self.library = library
        self.audit_cache.clear()
        self.audit_kept.clear()
        self.audit_results.clear()
        self.imports_tab.message.setText('')
        self.refresh_imports()
        self.usage_tab.set_library(library)
        self.settings_library_label.setText(str(getattr(library, "path", "Connected library")))
        self.settings_feedback.setText("")
        if not library.demo:
            self.fix_grid.setChecked(library.writable)
        self.fix_grid.setEnabled(library.demo or library.writable)
        self.fix_grid.setToolTip("With memory cues enabled, shift the grid to the last edited drop without changing BPM, then check the other drop. Manually edited markers stay fixed on rebuild. Grid-only analysis uses conservative timing suggestions. Check the grid against the waveform before import.")
        self.playlist_ids = tuple(library.playlists)[:1]
        self.playlist_browser.set_library(library)
        self.choose_playlists_button.setEnabled(bool(library.playlists))
        return self.load_tracks()

    def refresh_library_playlists(self):
        self.playlist_ids = tuple(key for key in self.playlist_ids if key in self.library.playlists) or tuple(self.library.playlists)[:1]
        self.playlist_browser.set_library(self.library)
        self.choose_playlists_button.setEnabled(bool(self.library.playlists))

    def selected_playlist_ids(self):
        return self.playlist_ids

    def choose_playlists(self):
        if not self.library or getattr(self, "analysis_busy", False):
            return
        dialog = PlaylistDialog(self, self.library.playlists, self.selected_playlist_ids(),
                                getattr(self.library, "playlist_paths", None))
        if dialog.exec() != QDialog.Accepted:
            return
        self.set_playlist_selection(dialog.selected_ids())

    def set_playlist_selection(self, identities):
        identities = tuple(dict.fromkeys(identities))
        if not identities or (identities == self.selected_playlist_ids() and not getattr(self, 'queued_review_only', False)):
            return
        if any(identity not in self.library.playlists for identity in identities):
            raise ValueError("A selected playlist is no longer available.")
        self.queued_review_only = False
        self.playlist_ids = identities
        self.load_tracks()

    def load_tracks(self):
        self.queued_review_only = False
        self.player.stop()
        if not self.library:
            return
        try:
            tracks = {}
            membership = {}
            identities = self.selected_playlist_ids()
            self.playlist_browser.set_selected(identities)
            for identity in identities:
                playlist_tracks = self.library.tracks(identity)
                membership[identity] = (self.library.playlists[identity], frozenset(t.id for t in playlist_tracks))
                for track in playlist_tracks:
                    tracks.setdefault(track.id, track)
            ignored = {identity for identity, track in tracks.items() if not self.audit_mode() and self.ignore_cued.isChecked() and track.cues}
            self.ignored_track_count = len(ignored)
            self.tracks = [track for identity, track in tracks.items() if identity not in ignored]
            self.loaded_playlist_tracks = {key: (name, ids - ignored) for key, (name, ids) in membership.items()}
            self.invalidate(discard_current=False)
            cached = [self.import_queue.entries.get(t.id) for t in self.tracks]
            if not self.audit_mode() and cached and all(cached) and any(not entry.proposal.applied for entry in cached):
                self.proposals = [entry.proposal for entry in cached]
                self.tracks = [p.track for p in self.proposals]
                self.capture_analysis_scope()
                self.populate_table()
                self.table.selectRow(0)
                self.select_track()
            ignored_note = f" {len(ignored)} tracks with existing cues ignored." if ignored else ""
            self.status.setText(f"{len(self.tracks)} unique tracks from {len(identities)} playlist(s)." + ignored_note +
                                (" Session preparations restored; ready tracks are in Imports." if self.proposals else
                                 " Ready to scan and prepare using the selected options." if self.tracks else " No tracks to prepare."))
            return True
        except Exception as exc:
            self.tracks = []
            self.ignored_track_count = 0
            self.loaded_playlist_tracks = {}
            self.invalidate(discard_current=False)
            self.fail(exc)
            return False

    def audit_mode(self):
        return hasattr(self, 'scan_mode') and self.scan_mode.currentIndex() == 1

    def current_audit(self):
        index = self.table.currentRow()
        return self.audit_results.get(self.tracks[index].id) if self.audit_mode() and 0 <= index < len(self.tracks) else None

    def original_cues_kept(self, identity):
        checked = self.audit_results.get(identity)
        return bool(checked and identity in self.audit_kept and self.audit_kept[identity] == checked.source_key)

    def audit_replacement_queued(self, identity):
        draft = self.audit_drafts.get(identity)
        entry = self.import_queue.entries.get(identity)
        return bool(draft and entry and entry.proposal is draft and draft.reviewed and draft.ready_to_apply)

    def audit_needs_review(self, identity):
        checked = self.audit_results.get(identity)
        if not checked or self.original_cues_kept(identity):
            return False
        draft = self.audit_drafts.get(identity)
        if self.audit_replacement_queued(identity) or (draft and draft.applied):
            return False
        # Editing an accepted replacement revokes readiness even if the original scan matched.
        return bool(checked.flagged or (draft and (draft.cues_dirty or draft.first_drop_edited or draft.second_drop_edited or draft.manual_grid is not None)))

    def change_scan_mode(self):
        audit = self.audit_mode()
        self.keep_original_button.setVisible(audit)
        self.player.stop()
        self.anchor_controls.setVisible(True)
        self.audit_tolerance.setVisible(audit)
        for control in (self.fix_grid, self.set_cues, self.replace_cues, self.ignore_cued):
            control.setVisible(not audit)
        self.review_filter.blockSignals(True)
        self.review_filter.clear()
        self.review_filter.addItems(['All tracks', 'Flagged only', 'Cue differences', 'Cues match', 'No memory cues', 'Inconclusive', 'Not checked'] if audit else ['All tracks', 'Needs review only'])
        self.review_filter.blockSignals(False)
        if self.library:
            self.load_tracks()
        else:
            self.invalidate(discard_current=False)
        if audit:
            self.status.setText('Check saved memory cues against the app pattern. Preparation options do not apply; nothing will be changed or queued for import.')

    def clear_audit_results(self):
        if self.audit_mode() and not getattr(self, 'analysis_busy', False):
            self.audit_results = {}
            self.audit_drafts = {}
            self.populate_table()
            self.select_track()

    def cancel_scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.cancel_scan_button.setEnabled(False)
            self.status.setText('Stopping after the current track. Completed results will be kept.')

    def start_cue_audit(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.library or not self.tracks:
            return
        try:
            if not self.library.demo:
                ensure_rekordbox_closed()
            if not self.load_tracks():
                return
            self.set_busy(True)
            self.progress.setRange(0, len(self.tracks))
            worker = CueAuditWorker(list(self.tracks), int(self.audit_tolerance.value()), self.audit_cache)
            self.worker = worker
            worker.progress.connect(lambda index, title: (self.progress.setValue(index), self.status.setText(f'Checking saved cues {index + 1} / {len(self.tracks)} · {title}')))
            def done(results):
                self.audit_results = results
                self.set_busy(False)
                self.populate_table()
                self.select_track()
                self.focus_transport()
                state = 'Stopped' if worker.isInterruptionRequested() else 'Check complete'
                self.status.setText(f'{state}: {len(results)} / {len(self.tracks)} tracks checked · {worker.cache_hits} reused · saved cues unchanged; nothing added to Imports.')
            worker.result.connect(done)
            worker.start()
        except Exception as exc:
            self.set_busy(False)
            self.fail(exc)

    def update_audit_overlay(self, *args):
        checked = self.current_audit()
        index = self.table.currentRow()
        self.wave.comparison_active = self.audit_mode() and 0 <= index < len(self.tracks)
        self.wave.saved_cues = tuple(self.tracks[index].cues) if self.wave.comparison_active else ()
        draft = self.selected() if checked else None
        self.wave.comparison_cues = tuple(c for c in draft.cues if c.kind == 'memory') if draft else checked.suggested if checked else ()
        self.wave.cue_view = 'suggested' if self.wave.comparison_cues else 'saved'
        self.wave.update()
        self.update_original_wave()

    def update_original_wave(self):
        p = self.wave.proposal
        index = self.table.currentRow()
        compare = bool(self.audit_mode() and p is not None and 0 <= index < len(self.tracks)
                       and p.track.id == self.tracks[index].id and self.wave.comparison_cues)
        self.original_wave_box.setVisible(compare)
        self.proposed_wave_label.setVisible(compare)
        self.wave.setMinimumHeight(115 if compare else 150)
        if not compare:
            self.original_wave.proposal = None
        else:
            track = self.tracks[index]
            self.original_wave.proposal = replace(p, options=Options(False, False), grid=track.grid,
                cues=track.cues.copy(), first_drop=None, second_drop=None)
            self.original_wave.comparison_active = True
            self.original_wave.cue_view = 'saved'
            self.original_wave.saved_cues = tuple(track.cues)
            self.original_wave.comparison_cues = ()
        self.sync_original_wave()

    def sync_original_wave(self):
        self.original_wave.zoom = self.wave.zoom
        self.original_wave.view_center = self.wave.view_center
        self.original_wave.position = self.wave.position
        self.original_wave.follow_playhead = False
        self.original_wave.update()

    def sync_from_original_wave(self):
        if self.audit_mode():
            self.wave.zoom = self.original_wave.zoom
            self.wave.view_center = self.original_wave.view_center
            self.wave.follow_playhead = False
            self.wave.update()
            self.update_wave_navigation()

    def change_ignore_cued(self):
        if getattr(self, "analysis_busy", False):
            return
        # Re-read saved cues, never filter against this session's proposed cues.
        if self.library:
            self.load_tracks()

    def invalidate(self, *args, discard_current=True):
        if discard_current and not self.audit_mode():
            self.import_queue.forget(t.id for t in self.tracks)
        self.review_filter.blockSignals(True)
        self.review_filter.setCurrentIndex(0)
        self.review_filter.blockSignals(False)
        self.proposals = []
        self.audit_results = {}
        self.audit_drafts = {}
        self.wave.comparison_cues = ()
        self.wave.comparison_active = False
        self.analysis_scope = None
        self.current = -1
        self.wave.proposal = None
        self.original_wave.proposal = None
        self.original_wave.update()
        self.review_title.setText("Select a track to view saved Rekordbox analysis")
        self.wave.reset_view()
        self.player.stop()
        self.analyse_button.setText("Scan && prepare playlists" if len(self.selected_playlist_ids()) > 1 else "Scan && prepare playlist")
        operations = "set memory cues and fix beat grids" if self.fix_grid.isChecked() and self.set_cues.isChecked() else ("fix beat grids" if self.fix_grid.isChecked() else "set memory cues")
        self.analyse_button.setToolTip(f"Scan all tracks in the selected playlists to {operations}, respecting Ignore cued tracks. Reuse saved Rekordbox waveforms, BPM and grid. Review filters do not limit the scan. Review the results, then import from the Imports tab.")
        self.analyse_button.setEnabled(bool(self.tracks) and (self.fix_grid.isChecked() or self.set_cues.isChecked()))
        if self.audit_mode():
            self.analyse_button.setText("Check playlist cues")
            self.analyse_button.setToolTip("Compare saved memory cues with the app pattern. No cues or grids are changed; nothing is added to Imports.")
            self.analyse_button.setEnabled(bool(self.tracks))
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
        self.row_previews = []
        self.overview_keys = [overview_key(track) for track in self.tracks]
        for i, track in enumerate(self.tracks):
            proposal = self.audit_drafts.get(track.id) if self.audit_mode() else self.proposals[i] if i < len(self.proposals) else None
            cues = proposal.cues if proposal else track.cues
            count = sum(c.kind in ("memory", "memory_loop") for c in cues)
            status = "Ready to prepare"
            if proposal:
                status = "Imported" if proposal.applied else ("Needs review" if not proposal.ready_to_apply else ("Reviewed" if proposal.reviewed else "Cues ready" if not proposal.options.fix_grid else "Prepared"))
            checked = self.audit_results.get(track.id) if self.audit_mode() else None
            if self.audit_mode():
                status = checked.status if checked else "Not checked"
                if proposal:
                    if proposal.applied:
                        status = 'Replacement imported'
                    elif proposal.reviewed and proposal.ready_to_apply:
                        status = 'Replacement queued'
                    elif proposal.cues_dirty or proposal.first_drop_edited or proposal.second_drop_edited or proposal.manual_grid is not None:
                        status = 'Review replacement'
            kept = self.audit_mode() and self.original_cues_kept(track.id)
            if kept:
                status = 'Original cues kept'
                count = sum(c.kind in ('memory', 'memory_loop') for c in track.cues)
            preview = CueOverview(track, checked.peaks if checked else proposal.peaks if proposal else (), tuple(c for c in proposal.cues if c.kind == 'memory') if checked and proposal else checked.suggested if checked else ())
            cached_overview = self.overview_cache.get(self.overview_keys[i])
            if cached_overview is not None:
                preview.set_data(cached_overview)
                self.overview_cache.move_to_end(self.overview_keys[i])
            self.row_previews.append(preview)
            values = [track.title + "\n" + track.artist, track.genre, f"{track.bpm:g}", f"{count} / 10", status]
            rows.append(values)
            needs_review = bool(proposal and not proposal.applied and not proposal.ready_to_apply)
            reason = review_reason(proposal) if needs_review else ""
            if needs_review and (proposal.first_drop_edited or proposal.second_drop_edited):
                reason = "Manual edits kept. " + reason
            if self.audit_mode():
                reason = ""
                if self.audit_needs_review(track.id):
                    reason = (review_reason(proposal) if proposal else "") or checked.reason or "Review the edited replacement cues."
            reasons.append(reason)
        self.table.set_rows(rows, reasons, self.row_previews)
        self.queue_overviews()
        visible = [i for i in range(len(self.tracks)) if not self.review_filter.currentIndex() or reasons[i]]
        if self.audit_mode():
            statuses = ('', '', 'Cue differences', 'Cues match', 'No memory cues', 'Inconclusive', 'Not checked')
            mode = self.review_filter.currentIndex()
            visible = [i for i, track in enumerate(self.tracks) if not mode or
                       (mode == 1 and self.audit_needs_review(track.id)) or
                       (mode >= 2 and (self.audit_results[track.id].status if track.id in self.audit_results else 'Not checked') == statuses[mode])]
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

    def queue_overviews(self):
        self.overview_jobs = list({key: deepcopy(track) for key, track in zip(self.overview_keys, self.tracks)
                                  if key not in self.overview_cache}.items())
        if self.overview_worker is not None:
            self.overview_worker.requestInterruption()
        else:
            self.start_overviews()

    def start_overviews(self):
        jobs, self.overview_jobs = self.overview_jobs, []
        jobs = [(key, track) for key, track in jobs if key not in self.overview_cache]
        if not jobs:
            return
        self.overview_worker = OverviewWorker(jobs, self)
        self.overview_worker.loaded.connect(self.overview_loaded)
        self.overview_worker.finished.connect(self.overviews_finished)
        self.overview_worker.start()

    def overview_loaded(self, key, data):
        self.overview_cache[key] = data
        self.overview_cache.move_to_end(key)
        while len(self.overview_cache) > 512:
            self.overview_cache.popitem(last=False)
        # Match current rows by file fingerprint; old playlist results cannot
        # update a different track or a widget removed during a table rebuild.
        for current_key, preview in zip(self.overview_keys, self.row_previews):
            if current_key == key:
                preview.set_data(data)

    def overviews_finished(self):
        self.overview_worker.deleteLater()
        self.overview_worker = None
        self.start_overviews()

    def review_proposals(self):
        return [p for p in self.proposals if not p.applied and not p.ready_to_apply]

    def automatic_review_proposals(self):
        return [p for p in self.review_proposals() if not (p.first_drop_edited or p.second_drop_edited)]

    def refresh_review_controls(self):
        self.auto_cue_button.setVisible(not self.audit_mode())
        if self.audit_mode():
            self.review_controls.show()
            kept_count = sum(self.original_cues_kept(identity) for identity in self.audit_results)
            flagged = sum(self.audit_needs_review(identity) for identity in self.audit_results)
            queued = sum(self.audit_replacement_queued(identity) for identity in self.audit_results)
            matching = sum(r.status == 'Cues match' for r in self.audit_results.values())
            self.review_filter.setItemText(0, f"All tracks ({len(self.tracks)})")
            self.review_filter.setItemText(1, f"Flagged only ({flagged})")
            self.review_summary.setText(f"{len(self.audit_results)} checked · {matching} match · {flagged} flagged" + (f" · {queued} queued" if queued else "") + (f" · {kept_count} originals kept" if kept_count else ""))
            self.review_filter.setEnabled(not getattr(self, "analysis_busy", False))
            return
        remaining = len(self.review_proposals())
        ready = sum(p.ready_to_apply for p in self.proposals)
        imported = sum(p.applied for p in self.proposals)
        self.review_controls.show()
        self.review_filter.setItemText(0, f"All tracks ({len(self.tracks)})")
        self.review_filter.setItemText(1, f"Needs review only ({remaining})")
        self.review_summary.setText(f"{ready} ready · {remaining} need review · {imported} imported" if self.proposals else f"{len(self.tracks)} tracks")
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
        self.wave.comparison_active = False
        self.wave.saved_cues = ()
        self.wave.comparison_cues = ()
        self.update_original_wave()
        self.wave.reset_view()
        self.current = -1
        self.review_title.setText("No tracks match this filter" if self.audit_mode() else "No tracks need review" if self.review_filter.currentIndex() else "Select a track")
        self.review_title.setToolTip("Choose All tracks to view the prepared results." if self.review_filter.currentIndex() else "Select a playlist and track.")

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
        if busy:
            self.cancel_cue()
        self.analysis_busy = busy
        self.scan_mode.setEnabled(not busy)
        self.audit_tolerance.setEnabled(not busy)
        self.cancel_scan_button.setVisible(busy and self.audit_mode())
        self.cancel_scan_button.setEnabled(busy)
        self.playlist_browser.setEnabled(not busy)
        self.choose_playlists_button.setEnabled(not busy and bool(self.library and getattr(self.library, "playlists", {})))
        for widget in (self.connect_button, self.fix_grid, self.set_cues, self.replace_cues, self.ignore_cued, self.analyse_button):
            widget.setEnabled(not busy)
        self.fix_grid.setEnabled(not busy and (not self.library or self.library.demo or self.library.writable))
        self.progress.setVisible(busy)
        self.update_play_shortcut(None, QApplication.focusWidget())
        self.update_details()
        self.refresh_imports()

    def start_analysis(self):
        if self.audit_mode():
            self.start_cue_audit()
            return
        if self.worker and self.worker.isRunning():
            return
        try:
            if not self.library.demo:
                ensure_rekordbox_closed()
            if getattr(self, 'queued_review_only', False) and not self.load_tracks():
                return
            if self.ignore_cued.isChecked():
                if not self.load_tracks() or not self.tracks:
                    return
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
            self.focus_transport()

    def selected(self):
        if self.audit_mode():
            index = self.table.currentRow()
            return self.audit_drafts.get(self.tracks[index].id) if 0 <= index < len(self.tracks) else None
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
        self.cancel_cue(return_to_cue=False)
        self.cue_position = 0.0
        checked = self.current_audit()
        if checked and checked.candidate and checked.playable and not getattr(self, 'analysis_busy', False):
            track = self.tracks[self.table.currentRow()]
            if track.id not in self.audit_drafts:
                try:
                    self.audit_drafts[track.id] = checked.replacement(track)
                except ValueError as exc:
                    self.status.setText(str(exc))
        proposal = self.selected()
        prepared = proposal is not None
        if proposal is None:
            index = self.table.currentRow()
            if not 0 <= index < len(self.tracks):
                return
            checked = self.audit_results.get(self.tracks[index].id) if self.audit_mode() else None
            proposal = checked.preview(self.tracks[index]) if checked else self.saved_preview(self.tracks[index])
        self.current = self.table.currentRow()
        checked = self.current_audit()
        self.update_audit_overlay()
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(proposal.track.path)) if prepared or (checked and checked.playable) else QUrl())
        self.cue_position = max(0., self.playback_offset())
        self.clock.setText("0:00.00")
        self.review_title.setText(proposal.track.title + "  ·  " + proposal.track.artist)
        self.wave.proposal = proposal
        self.update_original_wave()
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
        checked = self.current_audit()
        index = self.table.currentRow()
        kept = bool(checked and 0 <= index < len(self.tracks) and self.original_cues_kept(self.tracks[index].id))
        self.keep_original_button.setText('Original kept' if kept and p and p.options.fix_grid else 'Original cues kept' if kept else 'Keep original' if p and p.options.fix_grid else 'Keep original cues')
        self.keep_original_button.setEnabled(bool(checked and not kept and not (p and p.applied) and not getattr(self, 'analysis_busy', False)))
        playable = (prepared or bool(checked and checked.playable)) and not getattr(self, 'analysis_busy', False)
        self.play.setEnabled(playable)
        self.cue_button.setEnabled(playable)
        if self.audit_mode():
            self.update_audit_overlay()
        self.play.setToolTip("Play / pause (Space)" if prepared or (checked and checked.playable) else "Scan first to check audio timing for playback")
        if p:
            primary = p.error or p.grid_issue or p.review_note or p.grid_note
            notes = ([p.grid_note] if p.grid_note and p.grid_note != primary else []) + p.warnings
            text = primary + "\n" + " · ".join(notes)
            if p.reviewed:
                text = "Review confirmed. " + text
            if p.ready_to_apply and p.options.set_cues and not p.options.fix_grid:
                text = "Cues only — existing Rekordbox grid will be kept. " + text
            if p.cues_dirty and not p.grid_issue:
                pending = "Rebuild needed: keep the manually shifted grid and update cue countdowns." if p.manual_grid is not None else f"Rebuild needed: Drop {p.grid_anchor} will anchor the grid; manually edited markers stay fixed." if p.options.fix_grid else "Rebuild needed: update cue countdowns from your markers."
                text = pending + "\n" + text
            if not self.original_wave_box.isHidden():
                text = 'Original above. Proposed below.\n' + text
            self.review_title.setToolTip(self.review_title.full_text + "\n" + text)
        dirty = bool(p and p.cues_dirty)
        caption = "Rebuild grid + cues" if p and p.options.fix_grid and p.manual_grid is None else "Rebuild cues"
        self.rebuild_button.setText(caption)
        self.rebuild_button.setToolTip("Rebuild from your markers, keeping BPM unchanged. If the other drop is off-grid, keep its exact cue position and flag it for listening. Confirm review accepts the rebuilt result. With Fix beat grid off, only cues change.")
        if self.rebuild_button.property("needsRebuild") != dirty:
            self.rebuild_button.setProperty("needsRebuild", dirty)
            self.rebuild_button.style().unpolish(self.rebuild_button)
            self.rebuild_button.style().polish(self.rebuild_button)
            self.rebuild_button.update()
        can_edit_cues = bool(p and p.options.set_cues and not p.error and not p.applied and not getattr(self, "analysis_busy", False))
        self.edit_feedback.setVisible(bool(p and p.error and not self.audit_mode()))
        self.edit_feedback.setText(('Cannot prepare this track: ' + p.error + (' Enable Replace memory cues and scan again to replace existing memory points.' if p.options.set_cues and not p.options.replace_memory and 'free memory slots' in p.error else '')) if p and p.error else '')
        self.rebuild_button.setEnabled(can_edit_cues)
        review_blocker = review_confirmation_error(p) if prepared and p else "Prepare cues / grid first."
        self.confirm_review_button.setText(('Queued' if p and p.reviewed else 'Use cues + grid' if p and p.options.fix_grid else 'Replace cues') if self.audit_mode() else "Review confirmed" if p and p.reviewed else "Confirm review")
        self.confirm_review_button.setEnabled(bool(prepared and p and not p.reviewed and not review_blocker and not getattr(self, "analysis_busy", False)))
        self.confirm_review_button.setToolTip(review_blocker or (('Queue the proposed cues and grid in Imports after listening.' if p and p.options.fix_grid else 'Queue this memory-cue replacement in Imports after listening. Saved cues change only when you import.') if self.audit_mode() else "Accept the current markers, cues and grid after listening. No timings change; import remains a separate step."))
        self.first.setEnabled(can_edit_cues)
        self.second.setEnabled(can_edit_cues)
        self.grid_anchor_controls.show()
        can_nudge = bool(prepared and p and not p.error and not p.applied and not getattr(self, 'analysis_busy', False))
        self.grid_left.setEnabled(can_nudge)
        self.grid_right.setEnabled(can_nudge)
        self.grid_anchor_controls.setToolTip((p.grid_note.split('. BPM')[0] if p.manual_grid is not None else f"Anchor: Drop {p.grid_anchor} · BPM unchanged") if prepared and p else "")
        for number, control in enumerate(self.grid_anchor_buttons, 1):
            control.setEnabled(can_edit_cues and p.options.fix_grid and
                               (p.first_drop if number == 1 else p.second_drop) is not None)
        for control in self.kick_buttons:
            control.setEnabled(can_edit_cues)
        self.align_grid.setEnabled(bool(p and p.options.fix_grid and not p.error and not p.applied and not getattr(self, "analysis_busy", False)))
        self.sync_import_queue()

    def sync_import_queue(self):
        if self.audit_mode():
            return
        if not self.library or not self.proposals or getattr(self, 'analysis_busy', False):
            return
        try:
            self.import_playlist_breakdown()
            self.import_queue.capture(self.library, self.proposals, self.analysis_scope[2])
        except (SafetyError, OSError):
            # Incomplete or invalidated scans cannot extend the import queue.
            return

    def refresh_imports(self):
        self.imports_tab.busy = bool(getattr(self, 'analysis_busy', False) or self.usage_tab.scanning)
        self.imports_tab.refresh()
        self.usage_tab.set_external_busy(bool(getattr(self, 'analysis_busy', False)))

    def organiser_drafts_changed(self):
        self.usage_tab.refresh_browser()
        self.refresh_imports()

    def add_unfiled_tracks(self, identities):
        page, library = self.usage_tab, self.library
        if not library or page.library is not library or page.scanning or getattr(self, 'analysis_busy', False) or not page.scan:
            return
        try:
            scanned = {t.id: t for t in page.scan.tracks}
            if not identities or not set(identities) <= set(scanned):
                raise SafetyError('Select tracks from the latest scan.')
            view = self.organiser_queue.view(library)
            dialog = PlaylistDialog(self, view.playlists, (), view.playlist_paths, organise=True)
            dialog.setWindowTitle('Queue tracks in playlists')
            if dialog.exec() != QDialog.Accepted:
                return
            self.organiser_queue.add(library, [scanned[key] for key in identities], dialog.selected_ids(), page.scan.fingerprint)
            page.selected_ids.clear()
            page.refresh_browser()
            page.result_note.setText('Tracks queued. Open Imports → Playlist changes to apply them to Rekordbox.')
            self.refresh_imports()
        except Exception as exc:
            page.result_note.setText(str(exc))
            self.fail(exc)

    def import_organiser_changes(self):
        page, library, queue = self.usage_tab, self.library, self.organiser_queue
        if not library or queue.library is not library or page.scanning or getattr(self, 'analysis_busy', False) or not queue.pending():
            return
        try:
            queue.bind(library)
            plan = queue.snapshot()
            view = queue.view(library)
            paths = {}
            for node in view.playlist_nodes:
                paths[node.identity] = paths.get(node.parent_id, '') + (' / ' if node.parent_id else '') + node.name
            count = sum(len(tracks) for _, tracks in plan.assignments)
            confirm = QMessageBox(self)
            confirm.setWindowTitle('Import playlist changes')
            confirm.setIcon(QMessageBox.Question)
            confirm.setText(f'Create {len(plan.nodes)} folders/playlists, move/reorder {len(queue.structure_changes())} items and add {count:,} track assignments?')
            confirm.setInformativeText('The reviewed folder structure and playlist order will be applied. Track memberships, track order within playlists, cues and audio are preserved. '
                                      'A verified backup is created before applying. Show Details lists every change.')
            lines = [('Create folder: ' if node.attribute == 1 else 'Create playlist: ') + paths[node.identity] for node in plan.nodes]
            for key, parent, position in queue.structure_changes():
                lines.append(f'Move/reorder: {paths[key]} — position {position} in {paths.get(parent, "Top level")}')
            for key, tracks in plan.assignments:
                lines.append('Add to ' + paths[key] + ':')
                lines.extend(f'{i}. {title} — {artist} [ID {identity}]' for i, (identity, title, artist) in enumerate(tracks, 1))
            confirm.setDetailedText('\n'.join(lines))
            confirm.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
            confirm.setDefaultButton(QMessageBox.Cancel)
            confirm.button(QMessageBox.Yes).setText('Import playlist changes')
            if confirm.exec() != QMessageBox.Yes:
                return
            if self.library is not library or queue.snapshot() != plan or page.scanning or getattr(self, 'analysis_busy', False):
                raise SafetyError('Drafts or library state changed. Review the import again.')
            self.sync_import_queue()
            backup = apply_plan(library, plan, self.backups)
            # A verified membership-only import preserves pending cue/grid drafts.
            if self.import_queue.library is library and self.import_queue.fingerprint == plan.fingerprint:
                self.import_queue.fingerprint = library.fingerprint
            queue.reset(library)
            self.refresh_library_playlists()
            self.load_tracks()
            page.set_library(library)
            self.refresh_imports()
            self.imports_tab.organiser.message.setText(f'Playlist changes imported. Backup: {backup.name}')
            page.result_note.setText('Playlist changes imported into Rekordbox.')
            page.start_scan()
        except Exception as exc:
            self.imports_tab.organiser.message.setText(str(exc))
            self.fail(exc)

    def review_queued_track(self, identity):
        if getattr(self, 'analysis_busy', False):
            return
        entry = self.import_queue.entries.get(identity)
        if entry is None or self.library is not self.import_queue.library:
            return
        if self.audit_mode():
            self.scan_mode.setCurrentIndex(0)
        source = next((key for key in entry.sources if key in self.library.playlists), None)
        if source is None:
            self.fail('The source playlist is unavailable. Reconnect and prepare the track again.')
            return
        if self.selected_playlist_ids() == (source,):
            self.load_tracks()
        else:
            self.set_playlist_selection((source,))
        index = next((i for i, p in enumerate(self.proposals) if p.track.id == identity), None)
        if index is None:
            # A sibling may have been invalidated/reprepared elsewhere. Review
            # this retained draft without inventing proposals for those siblings.
            self.tracks = [entry.proposal.track]
            self.proposals = [entry.proposal]
            self.loaded_playlist_tracks = {source: (self.library.playlists[source], frozenset([identity]))}
            self.capture_analysis_scope()
            self.queued_review_only = True
            self.populate_table()
            self.status.setText('Reviewing this queued draft. Choose the playlist again or prepare it to load its full track list.')
            index = 0
        self.review_filter.setCurrentIndex(0)
        self.tabs.setCurrentWidget(self.manager_tab)
        self.table.selectRow(index)

    def confirm_discard_preparation(self, action):
        if not self.import_queue.pending() and not self.organiser_queue.pending():
            return True
        return QMessageBox.question(self, action,
            f'{len(self.import_queue.pending())} prepared tracks and {len(self.organiser_queue.nodes)} new folders/playlists, '
            f'plus {len(self.organiser_queue.structure_changes())} structure changes and '
            f'{sum(len(t) for t in self.organiser_queue.assignments.values())} playlist assignments have not been imported. '
            'This session queue is not saved after closing or reconnecting. Discard these preparations?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def import_queued_tracks(self):
        if (not self.library or not self.library.writable or getattr(self, 'analysis_busy', False)
                or self.usage_tab.scanning):
            self.imports_tab.message.setText('Finish or cancel any running scan before importing. The library must support imports.')
            return
        self.sync_import_queue()
        ready = self.import_queue.ready()
        if not ready:
            self.refresh_imports()
            return
        try:
            self.import_queue.validate(self.library)
            # Freeze the exact reviewed payload; later UI changes cannot alter a
            # confirmed import, even when a shared track has several sources.
            candidates = [import_snapshot(entry.proposal) for entry in ready]
            skipped = [entry.proposal for entry in self.import_queue.pending() if not entry.proposal.ready_to_apply]
            breakdown = self.import_queue.breakdown()
            dialog = ImportDialog(self, candidates, skipped, self.backups.directory,
                                  not self.library.demo, len(breakdown), breakdown)
            if dialog.exec() != QDialog.Accepted:
                return
            self.import_queue.validate(self.library)
            if [import_snapshot(entry.proposal) for entry in self.import_queue.ready()] != candidates:
                raise SafetyError('Queued preparations changed. Review the import summary again.')
            if not self.library.demo:
                # A prior verified import reloads the adapter. Re-register only
                # after validating the queue's independent preparation baselines.
                loaded = self.library.tracks_by_ids([p.track.id for p in candidates])
                if {t.id for t in loaded} != {p.track.id for p in candidates}:
                    raise SafetyError('A queued track is no longer in the library.')
                self.import_queue.validate(self.library)
            confirmed = [replace(p, reviewed=True, grid_approved=p.options.fix_grid) for p in candidates]
            previous_fingerprint = getattr(self.library, "fingerprint", None)
            backup = self.library.apply(confirmed, self.backups)
            self.organiser_queue.rebase(previous_fingerprint, self.library)
            self.import_queue.complete([p.track.id for p in confirmed], self.library)
            self.usage_tab.set_library(self.library)
            self.load_tracks()
            self.refresh_imports()
            self.imports_tab.message.setText(f'Imported {len(confirmed)} unique tracks. Playlist membership and order kept. Backup: {backup.name}')
            QMessageBox.information(self, 'Import complete',
                f'{len(confirmed)} tracks imported. {len(skipped)} still need review.\n'
                'Playlist membership and order are unchanged. A backup was created.')
        except Exception as exc:
            self.imports_tab.message.setText(str(exc))
            self.fail(exc)

    def nudge_grid(self, direction):
        p = self.selected()
        if not p or p.applied or p.error or getattr(self, 'analysis_busy', False):
            return
        from .grid_nudge import nudge_grid
        step = .001 if QApplication.keyboardModifiers() & Qt.ShiftModifier else .010
        try:
            self.cancel_cue()
            self.player.pause()
            nudge_grid(p, direction * step)
            if self.audit_mode():
                self.audit_kept.pop(p.track.id, None)
            self.populate_table()
            self.wave.update()
            self.update_details()
            self.status.setText(p.grid_note + ' ' + p.review_note)
            self.focus_transport()
        except (ValueError, SafetyError) as exc:
            self.status.setText(str(exc))

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
        p.manual_grid = None
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
        p = self.displayed()
        if not p or not (p.options.set_cues or self.current_audit()):
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
            p.grid = grid
            p.manual_grid = None
            p.grid_note = "Grid aligned to the first drop at the playhead. Check the grid against the waveform throughout the track."
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

    def advance_to_next_review(self, after):
        if self.audit_mode():
            remaining = [i for i, track in enumerate(self.tracks) if self.audit_needs_review(track.id)]
        else:
            remaining = [i for i, p in enumerate(self.proposals) if not p.applied and not p.ready_to_apply]
        if not remaining:
            self.focus_transport()
            return False
        target = next((i for i in remaining if i > after), remaining[0])
        # A status-specific filter may hide the next unresolved track. Keep the
        # current filter where possible; otherwise show all outstanding reviews.
        if target not in self.table.visible_rows():
            self.review_filter.setCurrentIndex(1)
        if self.table.currentRow() != target:
            self.table.selectRow(target)
        self.focus_transport()
        return True

    def keep_original_cues(self):
        checked = self.current_audit()
        index = self.table.currentRow()
        if not checked or not 0 <= index < len(self.tracks) or getattr(self, 'analysis_busy', False):
            return
        track = self.tracks[index]
        p = self.selected()
        if p and p.applied:
            self.status.setText('This replacement has already been imported. Keeping originals cannot undo an import.')
            return
        # Remove by content ID, so shared tracks disappear from every playlist's queue.
        self.import_queue.forget([track.id])
        self.audit_kept[track.id] = checked.source_key
        if p:
            p.reviewed = False
            p.review_note = 'Original cues kept. Listen before choosing Replace cues.'
        self.populate_table()
        self.refresh_imports()
        more = self.advance_to_next_review(index)
        self.status.setText(('' if more else 'No tracks left to review. ') + f'Original cues kept: {track.title}. Removed from Imports; no saved cues changed.')

    def confirm_review(self):
        p = self.selected()
        if p is None or getattr(self, "analysis_busy", False):
            return
        selected = self.table.currentRow()
        try:
            if self.audit_mode():
                checked = self.current_audit()
                track = self.tracks[self.table.currentRow()]
                if not checked or checked.source_key != audit_key(track, checked.tolerance_ms):
                    raise ValueError('Track or analysis changed since checking. Check the playlist again before replacing cues.')
                membership = {key: (name, frozenset([track.id])) for key, (name, ids) in self.loaded_playlist_tracks.items() if track.id in ids}
                confirm_proposal_review(p)
                try:
                    self.import_queue.capture(self.library, [p], membership)
                except (SafetyError, OSError):
                    p.reviewed = False
                    p.review_note = 'Could not queue replacement. Check the playlist again.'
                    raise
                self.audit_kept.pop(track.id, None)
                self.populate_table()
                self.refresh_imports()
                more = self.advance_to_next_review(selected)
                self.status.setText(('' if more else 'No tracks left to review. ') + f'Replacement queued: {p.track.title}. Import from Imports to replace saved memory cues. Hot cues, loops and playlists are kept.' + (' The proposed beat grid is included.' if p.options.fix_grid else ' The saved beat grid is kept.'))
                return
            confirm_proposal_review(p)
            title = p.track.title
            self.populate_table()
            more = self.advance_to_next_review(selected)
            self.status.setText(('' if more else 'No tracks left to review. ') + f"Review confirmed: {title}. Ready to import; nothing has been written.")
            self.update_details()
        except (ValueError, SafetyError, OSError) as exc:
            self.status.setText(str(exc))
            self.update_details()

    def rebuild_cues(self):
        p = self.selected()
        if p is None or not p.options.set_cues or getattr(self, "analysis_busy", False):
            return
        try:
            self.player.pause()
            p.first_drop, p.second_drop = self.first.value(), self.second.value()
            rebuild_proposal(p, manual=True)
            first, second = p.first_drop, p.second_drop
            message = p.grid_issue or p.review_note
            self.status.setText(message.replace('confirm review', 'choose Use cues + grid' if p.options.fix_grid else 'choose Replace cues') if self.audit_mode() else message)
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

    def eventFilter(self, watched, event):
        if self.cue_held:
            released = event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton
            released = released or (event.type() == QEvent.KeyRelease and event.key() == Qt.Key_Space)
            deactivated = event.type() == QEvent.ApplicationDeactivate or (watched is self and event.type() in (QEvent.WindowDeactivate, QEvent.Hide))
            focus_lost = watched is self.cue_button and event.type() == QEvent.FocusOut
            if released or deactivated or focus_lost:
                self.cancel_cue()
        return super().eventFilter(watched, event)

    def press_cue(self):
        if self.cue_held or not self.cue_button.isEnabled() or getattr(self, 'analysis_busy', False):
            return
        if self.player.playbackState() != QMediaPlayer.PlayingState:
            self.cue_position = max(0., self.player.position() / 1000 + self.playback_offset())
        self.cue_source = self.player.source()
        self.cue_held = True
        QApplication.instance().installEventFilter(self)
        self.seek(self.cue_position, set_cue=False)
        self.wave.follow_playhead = True
        self.player.play()

    def release_cue(self):
        self.cancel_cue()

    def cancel_cue(self, *, return_to_cue=True):
        if not self.cue_held:
            return
        self.cue_held = False
        QApplication.instance().removeEventFilter(self)
        self.player.pause()
        if return_to_cue and self.player.source() == self.cue_source:
            self.wave.follow_playhead = True
            self.seek(self.cue_position, set_cue=False)
        self.wave.follow_playhead = False
        self.cue_button.setDown(False)

    def seek(self, seconds, *, set_cue=True):
        if set_cue and not self.cue_held and self.player.playbackState() != QMediaPlayer.PlayingState:
            self.cue_position = max(0., seconds)
        if self.selected() is not None or (self.current_audit() and self.current_audit().playable):
            self.player.setPosition(max(0, round((seconds - self.playback_offset()) * 1000)))
        self.clock.setText(time_text(seconds))
        self.wave.set_position(seconds)
        self.sync_original_wave()

    def playback_offset(self):
        p = self.displayed()
        return p.track.audio_offset if p and self.player.source() == QUrl.fromLocalFile(str(p.track.path)) else 0.

    def change_zoom(self):
        self.wave.set_zoom(self.zoom.currentData())

    def update_wave_navigation(self):
        self.sync_original_wave()
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

    def play_position(self, milliseconds):
        seconds = max(0., milliseconds / 1000 + self.playback_offset())
        self.clock.setText(time_text(seconds))
        self.wave.set_position(seconds)
        self.sync_original_wave()

    def toggle_play(self):
        if self.cue_held or getattr(self, 'analysis_busy', False):
            return
        if self.selected() is None and not (self.current_audit() and self.current_audit().playable):
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.cue_position = max(0., self.player.position() / 1000 + self.playback_offset())
        else:
            self.wave.follow_playhead = True
            self.player.play()

    def apply_changes(self):
        if self.audit_mode():
            return
        if self.usage_tab.scanning:
            self.fail("Wait for the library usage scan to finish or cancel it before importing changes.")
            return
        if not self.library or not self.library.writable or getattr(self, "analysis_busy", False):
            return
        candidates = [p for p in self.proposals if p.ready_to_apply]
        if not candidates:
            return
        skipped = [p for p in self.proposals if not p.ready_to_apply and not p.applied]
        live = not self.library.demo
        try:
            breakdown = self.import_playlist_breakdown()
            self.sync_import_queue()
            if hasattr(self.library, 'fingerprint'):
                self.import_queue.validate(self.library, {p.track.id for p in candidates})
        except SafetyError as exc:
            self.fail(exc)
            return
        dialog = ImportDialog(self, candidates, skipped, self.backups.directory, live,
                              len(self.selected_playlist_ids()), breakdown)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            self.import_playlist_breakdown()
            if hasattr(self.library, 'fingerprint'):
                self.import_queue.validate(self.library, {p.track.id for p in candidates})
            if candidates != [p for p in self.proposals if p.ready_to_apply]:
                raise SafetyError("Import results changed. Review the import summary again.")
            scan_scope = self.analysis_scope
            # The single final confirmation authorizes the batch. Keep approval
            # local to this write so cancellation/failure never marks UI tracks.
            for p in candidates:
                p.grid.validate()
            confirmed = [replace(p, reviewed=True, grid_approved=p.options.fix_grid) for p in candidates]
            previous_fingerprint = getattr(self.library, "fingerprint", None)
            backup = self.library.apply(confirmed, self.backups)
            self.organiser_queue.rebase(previous_fingerprint, self.library)
            self.import_queue.complete([p.track.id for p in confirmed], self.library)
            self.usage_tab.set_library(self.library)
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
        self.tabs.setCurrentWidget(self.backups_tab)
        self.refresh_backups()

    def refresh_backups(self):
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
        if self.usage_tab.scanning:
            self.fail("Wait for the library usage scan to finish or cancel it before restoring a backup.")
            return
        if getattr(self, "analysis_busy", False) or (self.worker and self.worker.isRunning()):
            self.fail("Wait for analysis to finish before restoring a backup.")
            return
        row = self.backup_list.currentRow()
        if row < 0:
            return
        if not self.library:
            self.fail("Connect the library that belongs to this backup first.")
            return
        path, record = self.backup_entries[row]
        if QMessageBox.question(self, "Restore library snapshot", "Restore this backup? Rekordbox must be closed. Any newer library changes will block restoration. Restoring clears queued cue edits, playlist drafts and marker edits.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            if self.library.demo:
                self.backups.restore(path, self.library.root, lambda: None, set(self.library.fingerprints))
                self.library.reload()
            else:
                self.library.restore(self.backups, path)
            self.import_queue.reset(self.library)
            self.organiser_queue.reset(self.library)
            self.refresh_library_playlists()
            self.refresh_imports()
            self.usage_tab.set_library(self.library)
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
            report = {"manager_version": __version__, "system": platform.system(),
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
        self.cancel_cue()
        if self.usage_tab.scanning:
            self.usage_tab.cancel_scan()
            self.usage_tab.message.setText("Stopping the scan. Close again when it finishes.")
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.status.setText("Stopping after the current track. Close again when preparation stops.")
            event.ignore()
            return
        if not self.confirm_discard_preparation('Close Rekordbox Manager'):
            event.ignore()
            return
        self.overview_jobs = []
        if self.overview_worker:
            self.overview_worker.requestInterruption()
            if not self.overview_worker.wait(3000):
                self.status.setText('Stopping waveform previews. Close again in a moment.')
                event.ignore()
                return
        self.player.stop()
        event.accept()
