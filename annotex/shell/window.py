"""The one window of Annotex.

A slim bar across the top - Home, a tab for each tool you have opened, the
background-jobs indicator and the theme switch - over a stack holding the
Home dashboard and every opened tool.  Tools are created the first time they
are opened and then kept, so switching back and forth keeps each one exactly
where it was, and jobs started in one tool keep running while you use another.

Before a tool is hidden it is asked to put its work on disk
(tool_deactivating), and before the window closes every open tool is asked in
turn (tool_close) and running jobs are confirmed, so nothing is lost by
navigating or quitting.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QProcess, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QMainWindow, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..ui import style
from ..ui import design
from ..ui.dialogs import messages
from ..config import SUITE_NAME, ShellSettings
from ..ui import icons
from ..ui.dialogs.common import Dialog
from ..ui.jobs import JobManager, JobQueuePanel
from ..ui.palette import install_theme, resolve_theme, toggled_setting, with_tool
from . import registry
from .home import HomePage


class JobsDialog(Dialog):
    def __init__(self, parent, manager):
        super().__init__(parent, "Background jobs",
                         "Every job from every tool. They keep running while you work.",
                         width=720, height=520)
        self.body.addWidget(JobQueuePanel(manager, None), 1)
        self.add_close_button()


class ShellWindow(QMainWindow):
    def __init__(self, app, settings=None, tools=None):
        super().__init__()
        self.app = app
        self.settings = settings or ShellSettings()
        self.tools = list(tools if tools is not None else registry.TOOLS)
        self.pages = {}
        self.jobs = JobManager(self)
        self.theme_setting = str(self.settings.get("theme", "dark") or "dark")
        self.theme = resolve_theme(self.theme_setting, app)

        self.setWindowTitle(SUITE_NAME)
        # Small enough for a laptop at 150 % scaling; the tools lay themselves
        # out to whatever room there is.
        self.setMinimumSize(640, 460)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        design.margins(root, "s", "m", "0", "m")
        root.setSpacing(0)
        root.addWidget(self._build_bar())

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.home = HomePage(self.tools)
        self.home.openRequested.connect(lambda tool_id: self.open_tool(tool_id))
        self.home.folderRequested.connect(self._open_tool_folder)
        self.home.forgetRequested.connect(self.forget_folder)
        self.home.themeToggleRequested.connect(self.toggle_theme)
        self.stack.addWidget(self.home)

        self.jobs.jobAdded.connect(lambda _job: self._sync_jobs())
        self.jobs.jobChanged.connect(lambda _job: self._sync_jobs())

        self._build_actions()
        self._apply_theme()
        self._restore_geometry()
        self.home.refresh()
        self._sync_tabs()
        self._sync_jobs()
        QTimer.singleShot(0, self._measure_screen)

    # ══════════════════════════════════════════════════════
    # LAYOUT
    # ══════════════════════════════════════════════════════
    def _build_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("SuiteBar")
        layout = QHBoxLayout(bar)
        design.margins(layout, "xs", "s")
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
        self.tab_holders = {}
        self.tab_closers = {}
        for number, spec in enumerate(self.tools, start=1):
            # A tab and the button that closes it travel together, so the
            # whole pair appears when the tool opens and goes when it closes.
            holder = QWidget()
            holder.setObjectName("SuiteTabHolder")
            pair = QHBoxLayout(holder)
            design.margins(pair, "0")
            pair.setSpacing(0)
            tab = QPushButton(spec.name)
            tab.setObjectName("SuiteTab")
            tab.setCheckable(True)
            tab.setIconSize(QSize(design.ICON["s"], design.ICON["s"]))
            tab.setToolTip("%s%s" % (spec.name, "  [Ctrl+%d]" % number if number <= 9 else ""))
            tab.clicked.connect(lambda _c=False, t=spec.id: self.open_tool(t))
            pair.addWidget(tab)
            closer = QPushButton()
            closer.setObjectName("SuiteTabClose")
            closer.setIconSize(QSize(design.ICON["s"], design.ICON["s"]))
            closer.setToolTip("Close %s  [Ctrl+W]  ·  unsaved work is offered first" % spec.name)
            closer.clicked.connect(lambda _c=False, t=spec.id: self.close_tool(t))
            pair.addWidget(closer)
            holder.setVisible(False)
            self.tab_group.addButton(tab)
            self.tool_tabs[spec.id] = tab
            self.tab_closers[spec.id] = closer
            self.tab_holders[spec.id] = holder
            layout.addWidget(holder)

        layout.addStretch(1)
        self.jobs_button = QPushButton("")
        self.jobs_button.setObjectName("SuiteTab")
        self.jobs_button.setToolTip("Background jobs from every tool")
        self.jobs_button.clicked.connect(self.show_jobs)
        layout.addWidget(self.jobs_button)
        self.display_button = QPushButton("")
        self.display_button.setObjectName("SuiteTab")
        self.display_button.setToolTip("Display - interface size for the whole of Annotex")
        self.display_button.setIconSize(QSize(16, 16))
        self.display_button.clicked.connect(self.show_display)
        layout.addWidget(self.display_button)
        return bar

    def _build_actions(self) -> None:
        for text, key, slot in (("Home", "Ctrl+Shift+H", self.go_home),
                                ("Jobs", "Ctrl+J", self.show_jobs),
                                ("Close tool", "Ctrl+W", self.close_current_tool)):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(slot)
            self.addAction(action)
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        quit_action.triggered.connect(self.quit)
        self.addAction(quit_action)
        for number, spec in enumerate(self.tools[:9], start=1):
            action = QAction(spec.name, self)
            action.setShortcut(QKeySequence("Ctrl+%d" % number))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(lambda _c=False, t=spec.id: self.open_tool(t))
            self.addAction(action)
        guide = QAction("Style guide", self)
        guide.setShortcut(QKeySequence("Ctrl+Alt+Shift+D"))
        guide.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        guide.triggered.connect(self.show_style_guide)
        self.addAction(guide)
        self.home_theme_action = QAction("Switch theme", self.home)
        self.home_theme_action.setShortcut(QKeySequence("Ctrl+T"))
        self.home_theme_action.triggered.connect(self.toggle_theme)
        self.home.addAction(self.home_theme_action)

    # ══════════════════════════════════════════════════════
    # THEME
    # ══════════════════════════════════════════════════════
    def request_theme(self, name) -> None:
        self.theme_setting = str(name or "dark")
        self.settings.set("theme", self.theme_setting)
        self.theme = resolve_theme(self.theme_setting, self.app)
        self._apply_theme()

    def toggle_theme(self) -> None:
        self.request_theme(toggled_setting(self.theme))

    def _apply_theme(self) -> None:
        icons.clear_cache()
        theme = self.theme
        install_theme(self, self.app, theme, hosted=False)
        self.setWindowIcon(icons.app_icon(theme["accent"], theme["appBg"], "suite"))
        self.bar_mark.setPixmap(icons.mark_pixmap("suite", theme["accent"], theme["surfaceAlt"], 22))
        self.home_tab.setIcon(icons.dual_icon("home", theme["sub"], theme["title"], 16))
        for spec in self.tools:
            tool_theme = with_tool(theme, spec.id)
            tab = self.tool_tabs[spec.id]
            tab.setIcon(icons.dual_icon(spec.icon, tool_theme["accent"], tool_theme["accent"], 16))
            self.tab_closers[spec.id].setIcon(icons.icon("cross", theme["muted"], design.ICON["s"]))
            style.set_tool(tab, spec.id)
        self.jobs_button.setIcon(icons.icon("history", theme["sub"], 16))
        self.display_button.setIcon(icons.icon("display", theme["sub"], 16))
        self.home.set_theme(theme)
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
            messages.warn(self, SUITE_NAME, "%s could not be started:\n\n%s" % (spec.name, exc))
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
            folder = QFileDialog.getExistingDirectory(self, "Choose a folder", os.path.expanduser("~"))
            if not folder:
                return
        self.open_tool(tool_id, folder)

    def forget_folder(self, tool_id, folder) -> None:
        """Take a folder off a tool's recent list (Home's remove buttons)."""
        from .registry import forget_in
        # An open tool holds its own copy of the list and saves it when it
        # closes, so change that copy first or the folder comes straight back.
        page = self.pages.get(tool_id)
        settings = getattr(page, "settings", None)
        if settings is not None:
            try:
                forget_in(settings, folder)
                rebuild = getattr(page, "_rebuild_recent", None)
                if rebuild is not None:
                    rebuild()
            except Exception:
                pass
        spec = next((s for s in self.tools if s.id == tool_id), None)
        if spec is not None and spec.forget is not None:
            try:
                spec.forget(folder)
            except Exception:
                pass
        self.home.refresh()

    def close_tool(self, tool_id) -> bool:
        """Close one tool and free what it holds - its folder lock, its
        images - the same way quitting does.  Unsaved work is offered back
        first, and saying no leaves the tool open."""
        page = self.pages.get(tool_id)
        if page is None:
            return True
        if self.current_tool_id() == tool_id and not self._leave_current():
            self._sync_tabs()
            return False
        closer = getattr(page, "tool_close", None)
        try:
            if closer is not None and not closer():
                self._sync_tabs()
                return False
        except Exception:
            pass
        was_current = self.stack.currentWidget() is page
        self.pages.pop(tool_id, None)
        self.stack.removeWidget(page)
        page.setParent(None)
        page.deleteLater()
        if was_current:
            # Fall back to another open tool, or Home when that was the last.
            remaining = next(iter(self.pages), None)
            if remaining is None:
                self.stack.setCurrentWidget(self.home)
                self.home.refresh()
            else:
                self.stack.setCurrentWidget(self.pages[remaining])
                self.settings.set("last_tool", remaining)
        self._sync_tabs()
        return True

    def close_current_tool(self) -> bool:
        current = self.current_tool_id()
        return True if current is None else self.close_tool(current)

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
            self.tab_holders[tool_id].setVisible(tool_id in self.pages)
            tab.setChecked(tool_id == current)
        spec = next((s for s in self.tools if s.id == current), None)
        self.setWindowTitle("%s  —  %s" % (SUITE_NAME, spec.name) if spec else SUITE_NAME)

    # ══════════════════════════════════════════════════════
    # JOBS
    # ══════════════════════════════════════════════════════
    def show_jobs(self) -> None:
        JobsDialog(self, self.jobs).exec()

    def _sync_jobs(self) -> None:
        active = self.jobs.active()
        if active:
            running = [j for j in active if j.state == "running"]
            percent = int(100 * running[0].progress) if running else 0
            self.jobs_button.setText("%d job(s)  ·  %d%%" % (len(active), percent))
        elif self.jobs.jobs:
            self.jobs_button.setText("Jobs done")
        self.jobs_button.setVisible(bool(self.jobs.jobs))

    # ══════════════════════════════════════════════════════
    # LIFECYCLE
    # ══════════════════════════════════════════════════════
    def show_display(self) -> None:
        from .display import DisplayDialog
        dialog = DisplayDialog(self, self.settings)
        if not dialog.exec():
            return
        before = self.settings.get("ui_scale", "auto")
        chosen = dialog.chosen()
        self.settings.set("ui_scale", chosen)
        if dialog.restart_requested:
            self.restart()
        elif chosen != before:
            messages.inform(self, "Display",
                                    "The new interface size is used the next time Annotex starts.")

    def show_style_guide(self) -> None:
        from .style_guide import StyleGuideDialog
        StyleGuideDialog(self, self.theme).exec()

    def _measure_screen(self) -> None:
        """Work out what Automatic means on the screen in use, for next start."""
        try:
            from ..config import auto_factor
            screen = self.screen() or self.app.primaryScreen()
            area = screen.availableGeometry()
            applied = float(os.environ.get("QT_SCALE_FACTOR") or 1.0)
            factor = auto_factor(area.width() * applied, area.height() * applied)
            if abs(float(self.settings.get("auto_scale", 1.0) or 1.0) - factor) > 0.001:
                self.settings.set("auto_scale", factor)
        except Exception:
            pass

    def restart(self) -> bool:
        """Close as quitting does - every tool saves, jobs are confirmed - then
        start Annotex again.  False when the close was cancelled."""
        from .display import restart_command
        if not self.close():
            return False
        program, arguments, folder = restart_command()
        try:
            QProcess.startDetached(program, arguments, folder)
        except Exception:
            pass
        self.app.quit()
        return True

    def quit(self) -> None:
        self.close()

    def _restore_geometry(self) -> None:
        try:
            raw = self.settings.get("window_geometry", "")
            if raw:
                self.restoreGeometry(QByteArray.fromBase64(raw.encode("ascii")))
                # Saved on a bigger screen, or at a smaller interface size:
                # never come back larger than the screen now in use.
                area = (self.screen() or self.app.primaryScreen()).availableGeometry()
                if self.width() > area.width() or self.height() > area.height():
                    self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
                    self.move(area.topLeft())
                return
            screen = self.app.primaryScreen().availableGeometry()
            self.resize(min(1640, int(screen.width() * 0.88)), min(1020, int(screen.height() * 0.88)))
        except Exception:
            self.resize(1320, 860)

    def closeEvent(self, event):
        active = self.jobs.active()
        if active:
            answer = messages.ask(
                self, "Jobs still running",
                "%d job(s) are still running or queued.\n\nCancel them and quit? Unfinished "
                "outputs are removed; finished ones are kept." % len(active))
            if not answer:
                event.ignore()
                return
            self.jobs.cancel_all()
            self.jobs.wait(20)
        for page in list(self.pages.values()):
            closer = getattr(page, "tool_close", None)
            try:
                if closer is not None and not closer():
                    event.ignore()
                    return
            except Exception:
                continue
        try:
            self.settings.set("window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
        except Exception:
            pass
        event.accept()
