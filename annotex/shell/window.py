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
                               QLabel, QMainWindow, QPushButton, QScrollArea, QStackedWidget,
                               QStyle, QStyleOptionButton, QStylePainter, QVBoxLayout, QWidget)

from ..ui import style
from ..ui import design
from ..ui.dialogs import messages
from ..config import (STARTUP_ALL, STARTUP_HOME, STARTUP_LAST, SUITE_NAME,
                      ShellSettings)
from ..core.sessions import SessionStore
from ..ui import icons
from ..ui.dialogs.common import Dialog
from ..ui.jobs import JobManager, JobQueuePanel
from ..ui.palette import install_theme, resolve_theme, toggled_setting, with_tool
from . import registry
from .home import HomePage

# How often every open tool is asked where it has got to.  The same twenty
# seconds the labelling tools already autosave on, so a checkpoint costs
# nothing that was not already being paid.
SESSION_CHECKPOINT_MS = 20 * 1000


class JobsDialog(Dialog):
    def __init__(self, parent, manager):
        super().__init__(parent, "Background jobs",
                         "Every job from every tool. They keep running while you work.",
                         width=720, height=520)
        self.body.addWidget(JobQueuePanel(manager, None), 1)
        self.add_close_button()


class ToolTab(QPushButton):
    """A tool's tab in the top bar.

    A plain button squeezed narrower than its text shows the middle of the
    word and no ellipsis, so with several tools open "LabelImg Master" and
    "LabelImg Shapes" both read as "belImg".  This one cuts the name properly
    and keeps enough room to be worth reading; the strip it sits in scrolls
    once even that no longer fits."""

    TEXT_ROOM = 62                       # px kept for the name before scrolling

    def __init__(self, text):
        super().__init__(text)
        self._full = text

    def setText(self, text) -> None:
        self._full = text
        super().setText(text)

    def full_text(self) -> str:
        return self._full

    def _text_room(self, width) -> int:
        room = width - 22
        if not self.icon().isNull():
            room -= self.iconSize().width() + 6
        return max(0, room)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        icon = self.iconSize().width() + 6 if not self.icon().isNull() else 0
        return QSize(min(hint.width(), self.TEXT_ROOM + icon + 22), hint.height())

    def paintEvent(self, _event) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideRight, self._text_room(option.rect.width()))
        QStylePainter(self).drawControl(QStyle.ControlElement.CE_PushButton, option)


class ShellWindow(QMainWindow):
    def __init__(self, app, settings=None, tools=None):
        super().__init__()
        self.app = app
        self.settings = settings or ShellSettings()
        self.tools = list(tools if tools is not None else registry.TOOLS)
        self.pages = {}
        self.jobs = JobManager(self)
        self.sessions = SessionStore()
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
        self.home.sessionsRequested.connect(self.show_sessions)
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

        # Where every tool has got to, written down every so often.  Asking
        # the tools on a timer catches a folder opened any way at all -
        # through Home, the tool's own browse button, the command line - and
        # means a run cut short by a power cut still left a usable record.
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(SESSION_CHECKPOINT_MS)
        self._session_timer.timeout.connect(self._checkpoint_sessions)
        self._session_timer.start()

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

        # The tabs live in a strip that scrolls, so opening every tool can
        # never push one out of reach or squeeze the names to nothing.
        self.tab_back = QPushButton("‹")
        self.tab_back.setObjectName("SuiteTabScroll")
        self.tab_back.setToolTip("Earlier tools")
        self.tab_back.setFixedWidth(22)
        self.tab_back.clicked.connect(lambda: self._scroll_tabs(-140))
        self.tab_back.setVisible(False)
        layout.addWidget(self.tab_back)

        self.tab_scroll = QScrollArea()
        self.tab_scroll.setObjectName("SuiteTabStrip")
        self.tab_scroll.setWidgetResizable(True)
        self.tab_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tab_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        strip = QWidget()
        strip.setObjectName("SuiteTabHolder")
        strip_layout = QHBoxLayout(strip)
        design.margins(strip_layout, "0")
        strip_layout.setSpacing(4)
        self.tab_scroll.setWidget(strip)
        layout.addWidget(self.tab_scroll, 1)

        self.tab_forward = QPushButton("›")
        self.tab_forward.setObjectName("SuiteTabScroll")
        self.tab_forward.setToolTip("Later tools")
        self.tab_forward.setFixedWidth(22)
        self.tab_forward.clicked.connect(lambda: self._scroll_tabs(140))
        self.tab_forward.setVisible(False)
        layout.addWidget(self.tab_forward)

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
            tab = ToolTab(spec.name)
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
            strip_layout.addWidget(holder)

        strip_layout.addStretch(1)
        # The strip must not make the bar any taller than the tabs in it.
        tall = max([h.sizeHint().height() for h in self.tab_holders.values()] or [26])
        self.tab_scroll.setFixedHeight(tall)
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
        self.help_button = QPushButton("")
        self.help_button.setObjectName("SuiteTab")
        self.help_button.setToolTip("Diagnostics  [F1]  ·  what this machine has, and "
                                    "where the logs are")
        self.help_button.setIconSize(QSize(16, 16))
        self.help_button.clicked.connect(self.show_diagnostics)
        layout.addWidget(self.help_button)
        return bar

    def _build_actions(self) -> None:
        # Shell keys a tool is allowed to claim for itself.  A tool that binds
        # the same key (ROI Studio and LabelImg Master use Ctrl+W to close the
        # batch and Ctrl+1 to zoom) would otherwise never see it: the shell's
        # ApplicationShortcut outranks the tool's WindowShortcut and swallows
        # it silently.  _sync_shortcuts turns these off while such a tool is
        # showing, so the tool's own key wins and everywhere else is unchanged.
        self._yielding_actions = []
        for text, key, slot in (("Home", "Ctrl+Shift+H", self.go_home),
                                ("Jobs", "Ctrl+J", self.show_jobs),
                                ("Diagnostics", "F1", self.show_diagnostics),
                                ("Close tool", "Ctrl+W", self.close_current_tool)):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(slot)
            self.addAction(action)
            if key == "Ctrl+W":
                self._yielding_actions.append(action)
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
            self._yielding_actions.append(action)
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
        self.help_button.setIcon(icons.icon("help", theme["sub"], 16))
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
        # Continue is built from the sessions now, so a folder removed from
        # the recent list would otherwise stay on Home regardless.
        try:
            self.sessions.forget(tool_id, folder)
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
        # Written down before the tool is asked to close, while it still
        # knows which image it was on.
        found = self._page_session(page)
        closer = getattr(page, "tool_close", None)
        try:
            if closer is not None and not closer():
                self._sync_tabs()
                return False
        except Exception:
            pass
        if found is not None:
            folder, state = found
            try:
                self.sessions.end(tool_id, folder, **{
                    name: state[name] for name in
                    ("last_image", "active_seconds", "view", "tool") if name in state})
            except Exception:
                pass
        self._drop_page(tool_id, page)
        return True

    def _drop_page(self, tool_id, page) -> None:
        """Take a tool that has already closed out of the window."""
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
                activated = getattr(self.pages[remaining], "tool_activated", None)
                if activated is not None:
                    try:
                        activated()
                    except Exception:
                        pass
        self._sync_tabs()

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
        self._sync_shortcuts()
        # After the strip has been laid out, not before: a tab that has only
        # just appeared has no geometry yet, so neither scrolling to it nor
        # asking whether anything overflows would give the right answer.
        QTimer.singleShot(0, self._sync_tab_strip)

    # ── the tab strip ─────────────────────────────────────
    def _scroll_tabs(self, by) -> None:
        bar = self.tab_scroll.horizontalScrollBar()
        bar.setValue(bar.value() + int(by))
        self._sync_tab_strip()

    def _sync_tab_strip(self, current=None) -> None:
        """Show the arrows only when there is something past the edge, and
        keep the tool you are in where you can see it."""
        if current is None:
            current = self.current_tool_id()
        tab = self.tool_tabs.get(current)
        if tab is not None and tab.isVisible():
            self.tab_scroll.ensureWidgetVisible(tab, 40, 0)
        bar = self.tab_scroll.horizontalScrollBar()
        overflowing = bar.maximum() > 0
        self.tab_back.setVisible(overflowing)
        self.tab_forward.setVisible(overflowing)
        self.tab_back.setEnabled(bar.value() > bar.minimum())
        self.tab_forward.setEnabled(bar.value() < bar.maximum())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_tab_strip)

    def _sync_shortcuts(self) -> None:
        """Let the tool on show keep any shell key it binds itself.

        A disabled action does not consume its shortcut, so the tool's own
        action receives the key instead.  The tab and its close button call
        straight into the shell, so nothing becomes unreachable by mouse."""
        page = self.stack.currentWidget()
        claimed = set()
        if page is not None and page is not self.home:
            for action in page.findChildren(QAction):
                for sequence in action.shortcuts():
                    text = sequence.toString()
                    if text:
                        claimed.add(text)
        for action in getattr(self, "_yielding_actions", ()):
            action.setEnabled(action.shortcut().toString() not in claimed)

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

    # ══════════════════════════════════════════════════════
    # SESSIONS
    # ══════════════════════════════════════════════════════
    def _page_session(self, page):
        """What a tool says about where it has got to, or None.

        A tool that has not been taught to answer keeps working exactly as
        it did; it simply has nothing to restore."""
        asker = getattr(page, "session_state", None)
        if asker is None:
            return None
        try:
            state = asker()
        except Exception:
            return None
        if not isinstance(state, dict):
            return None
        folder = str(state.get("folder") or "")
        return (folder, state) if folder and os.path.isdir(folder) else None

    def _checkpoint_sessions(self, closing: bool = False) -> None:
        for tool_id, page in list(self.pages.items()):
            found = self._page_session(page)
            if found is None:
                continue
            folder, state = found
            fields = {name: state[name] for name in
                      ("last_image", "active_seconds", "view", "tool")
                      if name in state}
            try:
                if closing:
                    self.sessions.end(tool_id, folder, **fields)
                else:
                    self.sessions.update(tool_id, folder, **fields)
            except Exception:
                continue

    def _remember_open_tools(self) -> None:
        """Which tools were showing, so "everything I had open" can mean it.

        The tool in front goes last, because restoring walks the list and
        whatever is opened last is what ends up on screen."""
        current = self.current_tool_id()
        order = [t for t in self.pages if t != current]
        if current:
            order.append(current)
        try:
            self.sessions.set_open_tools(order)
        except Exception:
            pass

    def restore_startup(self) -> str:
        """Open what the Startup setting asks for.  Returns what it did.

        Called once, after the window is up, and only when no tool was named
        on the command line - an explicit request always wins."""
        try:
            choice = str(self.settings.get("startup", STARTUP_HOME) or STARTUP_HOME)
        except Exception:
            choice = STARTUP_HOME
        if choice == STARTUP_ALL:
            wanted = [t for t in self._stored_open_tools()
                      if any(s.id == t for s in self.tools)]
        elif choice == STARTUP_LAST:
            last = str(self.settings.get("last_tool", "") or "")
            wanted = [last] if last and any(s.id == last for s in self.tools) else []
        else:
            wanted = []
        opened = []
        for tool_id in wanted:
            if self._resume_tool(tool_id):
                opened.append(tool_id)
        if not opened:
            self.go_home()
            return STARTUP_HOME
        return choice

    def _stored_open_tools(self):
        try:
            return self.sessions.open_tools()
        except Exception:
            return []

    def _resume_tool(self, tool_id) -> bool:
        """Reopen one tool with the folder and image it last had.

        A folder that has gone - an unplugged drive, a batch that was
        renamed - costs a line in the status bar, not a wall of errors, and
        the tool still opens so somebody can pick another one."""
        record = None
        try:
            found = self.sessions.recent(limit=1, tool_ids=[tool_id])
            record = found[0] if found else None
        except Exception:
            record = None
        folder = record.folder if record is not None else ""
        page = self.open_tool(tool_id, folder or None)
        if page is None:
            return False
        if record is not None and folder:
            self._restore_into(page, record)
        return True

    @staticmethod
    def _restore_into(page, record) -> None:
        """Hand a tool back the rest of its session, once its folder is open.

        Only the rest: the folder itself went through open_tool, so the lock
        and the read-only handling are the ones that have always run."""
        restore = getattr(page, "restore_session", None)
        if restore is None:
            return
        try:
            restore({"folder": record.folder, "last_image": record.last_image,
                     "view": dict(record.view), "tool": dict(record.tool)})
        except Exception:
            pass

    def offer_recovery(self) -> bool:
        """Offer back a run that did not finish.  True if something reopened.

        A record with no closing time is one whose window went away without
        being closed: a crash, a power cut, a process killed.  Somebody who
        has just lost a window wants to be asked, once, about the folder
        they were in - not to find Home and have to remember."""
        if not self.settings.get("offer_recovery", True):
            return False
        try:
            unfinished = [s for s in self.sessions.unfinished()
                          if not any(s.tool_id == t for t in self.pages)]
        except Exception:
            return False
        if not unfinished:
            return False
        record = unfinished[0]
        spec = next((s for s in self.tools if s.id == record.tool_id), None)
        if spec is None:
            return False
        where = record.last_image or record.progress_text() or "that folder"
        answer = messages.ask(
            self, "Pick up where you left off?",
            "%s closed unexpectedly while you were working in %s.\n\nYou were on %s.  "
            "Nothing on disk was lost - open it again?" % (SUITE_NAME, record.name, where),
            confirm="Open it", cancel="Not now")
        if not answer:
            # Asked and declined: close the record so the same folder is not
            # offered every single start from now on.
            try:
                self.sessions.end(record.tool_id, record.folder)
            except Exception:
                pass
            return False
        return self._resume_tool(record.tool_id)

    def show_sessions(self) -> None:
        from .sessions_dialog import SessionsDialog
        dialog = SessionsDialog(self, self.sessions, self.tools, self.settings)
        dialog.resumeRequested.connect(self._open_tool_folder)
        dialog.exec()
        self.home.refresh()

    def show_diagnostics(self) -> None:
        """What this machine has, and where it writes things down.

        The answers `--check` and `--selftest` give, for somebody who
        downloaded a built application and has no terminal to ask from."""
        from .diagnostics import DiagnosticsDialog
        DiagnosticsDialog(self).exec()

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
        start Annotex again.  False when the restart did not happen."""
        from .display import restart_command
        program, arguments, folder = restart_command()
        # Look before leaping.  Closing first and only then discovering that
        # nothing can be started took Annotex off the screen with nothing
        # coming back - it simply vanished, and the person who had asked for a
        # new interface size was left thinking it had crashed.  Nothing is
        # closed until there is something to come back to; the size is safely
        # saved either way.
        if not os.path.isfile(program):
            messages.warn(self, "Display",
                          "Annotex cannot find the program it would start itself with:\n\n%s\n\n"
                          "The new interface size is saved, and will be used the next time you "
                          "start Annotex yourself." % program)
            return False
        if not self.close():
            return False
        started = False
        try:
            started = bool(QProcess.startDetached(program, arguments, folder))
        except Exception:
            started = False
        if not started:
            self.show()
            messages.warn(self, "Display",
                          "Annotex could not start itself again, so it has stayed open.\n\n"
                          "The new interface size is saved. Close Annotex and start it again "
                          "when you are ready.")
            return False
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
        # Which tools were open, and where each had got to, written down
        # while they are all still here to ask.
        self._remember_open_tools()
        self._checkpoint_sessions(closing=True)
        closed = []
        for tool_id, page in list(self.pages.items()):
            closer = getattr(page, "tool_close", None)
            try:
                if closer is not None and not closer():
                    # Quitting stops here - but the tools before this one have
                    # already saved, let go of their folders and shut down.
                    # Left in place they would look open and not be, so they
                    # go the way closing their tab takes them.
                    for done_id, done_page in closed:
                        self._drop_page(done_id, done_page)
                    event.ignore()
                    return
            except Exception:
                pass
            closed.append((tool_id, page))
        try:
            self._session_timer.stop()
        except Exception:
            pass
        try:
            self.settings.set("window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
        except Exception:
            pass
        event.accept()
