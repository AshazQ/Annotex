"""The one window of the suite.

A slim bar across the top - Home, a tab per tool, the theme switch - over a
stack holding the Home dashboard and every tool that has been opened.  Tools
are created the first time they are opened and then kept, so switching back
and forth keeps each one exactly where it was.

Before a tool is hidden it is asked to put its work on disk
(tool_deactivating), and before the window closes every open tool is asked in
turn (tool_close), so nothing is lost by navigating or quitting.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..config import SUITE_NAME, ShellSettings
from ..ui import icons
from ..ui.palette import apply_palette, resolve_theme, stylesheet
from . import registry
from .home import HomePage


class ShellWindow(QMainWindow):
    def __init__(self, app, settings=None, tools=None):
        super().__init__()
        self.app = app
        self.settings = settings or ShellSettings()
        self.tools = list(tools if tools is not None else registry.TOOLS)
        self.pages = {}
        self.theme_setting = str(self.settings.get("theme", "dark") or "dark")
        self.theme = resolve_theme(self.theme_setting, app)

        self.setWindowTitle(SUITE_NAME)
        self.setMinimumSize(1120, 720)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 0)
        root.setSpacing(0)
        root.addWidget(self._build_bar())

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.home = HomePage(self.tools)
        self.home.openRequested.connect(lambda tool_id: self.open_tool(tool_id))
        self.home.folderRequested.connect(self._open_tool_folder)
        self.home.themeToggleRequested.connect(self.toggle_theme)
        self.stack.addWidget(self.home)

        self._build_actions()
        self._apply_theme()
        self._restore_geometry()
        self.home.refresh()
        self._sync_tabs()

    # ══════════════════════════════════════════════════════
    # LAYOUT
    # ══════════════════════════════════════════════════════
    def _build_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("SuiteBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 5, 8, 5)
        layout.setSpacing(4)

        self.bar_mark = QLabel()
        self.bar_mark.setFixedSize(22, 22)
        layout.addWidget(self.bar_mark)
        name = QLabel(SUITE_NAME)
        name.setObjectName("SuiteName")
        layout.addWidget(name)
        layout.addSpacing(14)

        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.home_tab = QPushButton("Home")
        self.home_tab.setObjectName("SuiteTab")
        self.home_tab.setCheckable(True)
        self.home_tab.setIconSize(QSize(16, 16))
        self.home_tab.setToolTip("Home  [Ctrl+Shift+H]")
        self.home_tab.clicked.connect(self.go_home)
        self.tab_group.addButton(self.home_tab)
        layout.addWidget(self.home_tab)

        self.tool_tabs = {}
        for number, spec in enumerate(self.tools, start=1):
            tab = QPushButton(spec.name)
            tab.setObjectName("SuiteTab")
            tab.setCheckable(True)
            tab.setIconSize(QSize(16, 16))
            tab.setToolTip("%s  [Ctrl+%d]" % (spec.name, number))
            tab.clicked.connect(lambda _c=False, t=spec.id: self.open_tool(t))
            self.tab_group.addButton(tab)
            self.tool_tabs[spec.id] = tab
            layout.addWidget(tab)

        layout.addStretch(1)
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("Tool")
        self.theme_button.setFixedSize(32, 30)
        self.theme_button.setIconSize(QSize(18, 18))
        self.theme_button.setToolTip("Switch light / dark for every tool")
        self.theme_button.clicked.connect(self.toggle_theme)
        layout.addWidget(self.theme_button)
        return bar

    def _build_actions(self) -> None:
        home = QAction("Home", self)
        home.setShortcut(QKeySequence("Ctrl+Shift+H"))
        home.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        home.triggered.connect(self.go_home)
        self.addAction(home)

        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        quit_action.triggered.connect(self.quit)
        self.addAction(quit_action)

        for number, spec in enumerate(self.tools, start=1):
            action = QAction(spec.name, self)
            action.setShortcut(QKeySequence("Ctrl+%d" % number))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(lambda _c=False, t=spec.id: self.open_tool(t))
            self.addAction(action)

        # On Home there is no tool to own Ctrl+T, so the shell does.
        self.home_theme_action = QAction("Switch theme", self.home)
        self.home_theme_action.setShortcut(QKeySequence("Ctrl+T"))
        self.home_theme_action.triggered.connect(self.toggle_theme)
        self.home.addAction(self.home_theme_action)

    # ══════════════════════════════════════════════════════
    # THEME
    # ══════════════════════════════════════════════════════
    def request_theme(self, name) -> None:
        """Any tool calls this; every tool follows."""
        self.theme_setting = str(name or "dark")
        self.settings.set("theme", self.theme_setting)
        self.theme = resolve_theme(self.theme_setting, self.app)
        self._apply_theme()

    def toggle_theme(self) -> None:
        self.request_theme("light" if self.theme["name"] == "dark" else "dark")

    def _apply_theme(self) -> None:
        icons.clear_cache()
        apply_palette(self.app, self.theme)
        self.app.setStyleSheet(stylesheet(self.theme))
        self.setWindowIcon(icons.app_icon(self.theme["accent"], self.theme["appBg"], "suite"))
        self.bar_mark.setPixmap(icons.mark_pixmap("suite", self.theme["accent"],
                                                  self.theme["surfaceAlt"], 22))
        self.home_tab.setIcon(icons.dual_icon("home", self.theme["sub"],
                                              self.theme["title"], 16))
        for spec in self.tools:
            self.tool_tabs[spec.id].setIcon(
                icons.icon("polygon" if spec.mark == "polygon" else "rect",
                           self.theme["sub"], 16))
        self.theme_button.setIcon(icons.icon("sun" if self.theme["name"] == "dark"
                                             else "moon", self.theme["text"], 18))
        self.home.set_theme(self.theme)
        for page in self.pages.values():
            apply = getattr(page, "tool_apply_theme", None)
            if apply is not None:
                try:
                    apply(self.theme_setting)
                except Exception:
                    pass

    # ══════════════════════════════════════════════════════
    # NAVIGATION
    # ══════════════════════════════════════════════════════
    def current_tool_id(self):
        widget = self.stack.currentWidget()
        for tool_id, page in self.pages.items():
            if page is widget:
                return tool_id
        return None

    def _leave_current(self) -> bool:
        widget = self.stack.currentWidget()
        if widget is self.home or widget is None:
            return True
        leave = getattr(widget, "tool_deactivating", None)
        try:
            return bool(leave()) if leave is not None else True
        except Exception:
            return True

    def page_for(self, tool_id):
        page = self.pages.get(tool_id)
        if page is not None:
            return page
        spec = next((s for s in self.tools if s.id == tool_id), None)
        if spec is None or spec.create is None:
            return None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            page = spec.create(self)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, SUITE_NAME,
                                "%s could not be started:\n\n%s" % (spec.name, exc))
            return None
        QApplication.restoreOverrideCursor()
        self.pages[tool_id] = page
        self.stack.addWidget(page)
        return page

    def open_tool(self, tool_id, folder=None):
        current = self.current_tool_id()
        if current != tool_id and not self._leave_current():
            self._sync_tabs()
            return None
        page = self.page_for(tool_id)
        if page is None:
            self._sync_tabs()
            return None
        if current != tool_id:
            self.stack.setCurrentWidget(page)
            self.settings.set("last_tool", tool_id)
            activated = getattr(page, "tool_activated", None)
            if activated is not None:
                activated()
        if folder:
            opener = getattr(page, "tool_open", None)
            if opener is not None:
                opener(folder)
        self._sync_tabs()
        return page

    def _open_tool_folder(self, tool_id, folder) -> None:
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "Choose a folder of images",
                                                      os.path.expanduser("~"))
            if not folder:
                return
        self.open_tool(tool_id, folder)

    def go_home(self) -> None:
        if self.stack.currentWidget() is self.home:
            self._sync_tabs()
            return
        if not self._leave_current():
            self._sync_tabs()
            return
        self.stack.setCurrentWidget(self.home)
        self.home.refresh()
        self._sync_tabs()

    def _sync_tabs(self) -> None:
        current = self.current_tool_id()
        self.home_tab.setChecked(current is None)
        for tool_id, tab in self.tool_tabs.items():
            tab.setChecked(tool_id == current)
        spec = next((s for s in self.tools if s.id == current), None)
        self.setWindowTitle("%s  —  %s" % (SUITE_NAME, spec.name) if spec else SUITE_NAME)

    # ══════════════════════════════════════════════════════
    # LIFECYCLE
    # ══════════════════════════════════════════════════════
    def quit(self) -> None:
        self.close()

    def _restore_geometry(self) -> None:
        try:
            raw = self.settings.get("window_geometry", "")
            if raw:
                self.restoreGeometry(QByteArray.fromBase64(raw.encode("ascii")))
                return
            screen = self.app.primaryScreen().availableGeometry()
            self.resize(min(1640, int(screen.width() * 0.88)),
                        min(1020, int(screen.height() * 0.88)))
        except Exception:
            self.resize(1320, 860)

    def closeEvent(self, event):
        for page in list(self.pages.values()):
            closer = getattr(page, "tool_close", None)
            try:
                if closer is not None and not closer():
                    event.ignore()
                    return
            except Exception:
                continue
        try:
            self.settings.set("window_geometry",
                              bytes(self.saveGeometry().toBase64()).decode("ascii"))
        except Exception:
            pass
        event.accept()
