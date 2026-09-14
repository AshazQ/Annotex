"""The page every media tool is built on.

Header with the tool's name and a small tool dock, the tool's own content in
a horizontal splitter, and the job queue underneath - the same furniture as
ROI Studio and LabelImg Master, so every tool in Annotex feels like one
product.  A tool subclasses it and fills in build().
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QFrame, QSizePolicy, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QScrollArea, QSplitter, QStatusBar,
                               QVBoxLayout, QWidget)

from ..config import JsonSettings, first_writable, user_data_dir
from . import icons
from .jobs import JobManager, JobQueuePanel
from .palette import install_theme, resolve_theme, toggled_setting
from .theme_picker import theme_menu


def tool_settings(tool_id, defaults, path=None):
    folder = first_writable([user_data_dir() / tool_id])
    merged = {"theme": "dark"}
    merged.update(defaults)
    return JsonSettings(path or (folder / "settings.json"), merged)


class MediaToolPage(QMainWindow):
    TOOL_ID = ""
    TOOL_NAME = ""
    TAGLINE = ""
    MARK = "box"
    DEFAULTS = {}

    def __init__(self, app, host=None, settings=None, jobs=None):
        super().__init__()
        self.app = app
        self.host = host
        self.settings = settings or tool_settings(self.TOOL_ID, self.DEFAULTS)
        if host is not None:
            self.settings.data["theme"] = host.theme_setting
        self.theme = resolve_theme(self.settings.get("theme", "dark"), app, tool=self.TOOL_ID)
        self.jobs = jobs or getattr(host, "jobs", None) or JobManager(self)
        self._status_level = "info"
        self._header_buttons = []

        self.setWindowTitle(self.TOOL_NAME)
        self.setMinimumSize(1000, 640)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(self.TOOL_NAME)
        title.setObjectName("Title")
        self.subtitle = QLabel(self.TAGLINE)
        self.subtitle.setObjectName("Subtitle")
        self.subtitle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        titles.addWidget(title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.dock = QFrame()
        self.dock.setObjectName("Toolbar")
        self.dock_layout = QHBoxLayout(self.dock)
        self.dock_layout.setContentsMargins(6, 5, 6, 5)
        self.dock_layout.setSpacing(3)
        header.addWidget(self.dock)
        root.addLayout(header)

        self.vertical = QSplitter(Qt.Orientation.Vertical)
        self.vertical.setChildrenCollapsible(False)
        self.vertical.setHandleWidth(8)
        root.addWidget(self.vertical, 1)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.vertical.addWidget(self.splitter)

        queue_card = QFrame()
        queue_card.setObjectName("Card")
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(14, 10, 14, 10)
        self.queue = JobQueuePanel(self.jobs, self.TOOL_ID)
        queue_layout.addWidget(self.queue)
        self.vertical.addWidget(queue_card)
        self.vertical.setStretchFactor(0, 1)
        self.vertical.setStretchFactor(1, 0)
        self.vertical.setSizes([860, 120])

        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.setStatusBar(bar)
        self.status_label = QLabel("")
        self.status_label.setObjectName("Hint")
        bar.addWidget(self.status_label, 1)
        self.jobs_label = QLabel("")
        self.jobs_label.setObjectName("Subtitle")
        bar.addPermanentWidget(self.jobs_label)
        self.jobs.jobChanged.connect(lambda _job: self._sync_jobs_label())
        self.jobs.jobAdded.connect(lambda _job: self._sync_jobs_label())

        self.build()
        self.dock.setVisible(bool(self._header_buttons))
        self._build_menus()
        self._apply_theme()
        if host is None:
            self.resize(1400, 900)
        else:
            self.menuBar().setNativeMenuBar(False)
        self._sync_jobs_label()

    # ── for subclasses ────────────────────────────────────
    def build(self) -> None:
        raise NotImplementedError

    def add_paths(self, paths) -> None:
        pass

    def browse_files(self) -> None:
        pass

    def browse_folder(self) -> None:
        pass

    def on_theme(self, theme) -> None:
        pass

    def extra_menus(self, bar) -> None:
        pass

    def card(self, stretch=False) -> tuple:
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        return frame, layout

    def scroll_card(self) -> tuple:
        """A card whose content scrolls - for option panels."""
        frame = QFrame()
        frame.setObjectName("Card")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)
        scroll.setWidget(holder)
        outer.addWidget(scroll)
        return frame, layout

    def add_dock_button(self, icon_name, tip, slot) -> QPushButton:
        button = QPushButton()
        button.setObjectName("Tool")
        button.setFixedSize(34, 32)
        button.setIconSize(QSize(19, 19))
        button.setToolTip(tip)
        button.clicked.connect(slot)
        self.dock_layout.addWidget(button)
        self._header_buttons.append((button, icon_name))
        return button

    def submit(self, job):
        job.tool = self.TOOL_ID
        self.jobs.submit(job)
        self.status("Queued: %s" % job.title, "info")
        return job

    def status(self, message, level="info") -> None:
        self._status_level = level
        self.status_label.setText(str(message))
        names = {"info": "Hint", "good": "HintGood", "warning": "HintWarn", "danger": "HintDanger"}
        self.status_label.setObjectName(names.get(level, "Hint"))
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def ask(self, title, text) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    # ── menus & theme ─────────────────────────────────────
    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        for text, key, slot in (("Add files…", "Ctrl+O", self.browse_files),
                                ("Add folder…", "Ctrl+Shift+O", self.browse_folder)):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(slot)
            file_menu.addAction(action)
            self.addAction(action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        if self.host is not None:
            home = QAction("Back to Home\tCtrl+Shift+H", self)
            home.triggered.connect(self.host.go_home)
            file_menu.addAction(home)
            quit_action.triggered.connect(self.host.quit)
        else:
            quit_action.setShortcut(QKeySequence.StandardKey.Quit)
            quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        self.extra_menus(bar)
        view = bar.addMenu("&View")
        theme = QAction("Switch light / dark", self)
        theme.setShortcut(QKeySequence("Ctrl+T"))
        theme.triggered.connect(self.toggle_theme)
        view.addAction(theme)
        self.addAction(theme)
        view.addMenu(theme_menu(self, self.settings.get("theme", "dark"), self.choose_theme))
        jobs = bar.addMenu("&Jobs")
        cancel = QAction("Cancel this tool's jobs", self)
        cancel.triggered.connect(lambda: self.jobs.cancel_all(self.TOOL_ID))
        jobs.addAction(cancel)
        clear = QAction("Clear finished jobs", self)
        clear.triggered.connect(lambda: self.jobs.clear_finished(self.TOOL_ID))
        jobs.addAction(clear)

    def toggle_theme(self) -> None:
        self.choose_theme(toggled_setting(self.theme))

    def choose_theme(self, name) -> None:
        if self.host is not None:
            self.host.request_theme(name)
        else:
            self.tool_apply_theme(name)

    def theme_setting_for_menu(self):
        return self.settings.get("theme", "dark")

    def tool_apply_theme(self, name) -> None:
        self.settings.set("theme", name)
        self.theme = resolve_theme(name, self.app, tool=self.TOOL_ID)
        self._apply_theme()

    def _apply_theme(self) -> None:
        theme = self.theme
        install_theme(self, self.app, theme, self.host is not None)
        self.setWindowIcon(icons.app_icon(theme["accent"], theme["appBg"], self.MARK))
        for button, name in self._header_buttons:
            if name == "moon":
                name = "sun" if theme["name"] == "dark" else "moon"
            button.setIcon(icons.icon(name, theme["text"], 19))
        self.on_theme(theme)

    def _sync_jobs_label(self) -> None:
        active = self.jobs.active(self.TOOL_ID)
        self.jobs_label.setText("%d job(s) running" % len(active) if active else "")

    # ── suite contract ────────────────────────────────────
    def tool_activated(self) -> None:
        pass

    def tool_deactivating(self) -> bool:
        return True                      # jobs keep running in the background

    def tool_open(self, folder) -> None:
        self.add_paths([folder])

    def shutdown(self) -> None:
        pass

    def tool_close(self) -> bool:
        if self.host is None and self.jobs.active(self.TOOL_ID):
            if not self.ask("Jobs still running",
                            "%d job(s) are still running. Cancel them and close?"
                            % len(self.jobs.active(self.TOOL_ID))):
                return False
            self.jobs.cancel_all(self.TOOL_ID)
            self.jobs.wait(15)
        self.settings.save()
        self.shutdown()
        return True

    def closeEvent(self, event):
        if self.tool_close():
            event.accept()
        else:
            event.ignore()
