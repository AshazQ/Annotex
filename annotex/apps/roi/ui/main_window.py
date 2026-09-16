"""The main window: layout, actions, and the flow between image and disk."""

from __future__ import annotations

import json
import os
import traceback

from PySide6.QtCore import (QObject, QRunnable, QSize, Qt, QThreadPool, QTimer,
                            Signal, Slot)
from PySide6.QtGui import QAction, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea, QSplitter, QStatusBar,
                               QVBoxLayout, QWidget)

from ....ui import style
from ....ui import design
from ....ui.dialogs import messages
from ..config import (APP_NAME, APP_TAGLINE, APP_VERSION, FULL_VIEW, IMG_EXTS,
                      NO_ROI_DIR, OUTPUT_DIRS, PRINTED_DIR,
                      PROJECT_SETTINGS_NAME, SITE_VIEW)
from ..core import exporters, geometry as geo, imaging, importers, push
from ..core import report as reporting
from ..core.history import History
from ..core.io_safe import (FolderLock, WriteReport, ensure_dir,
                            folder_is_writable, read_json, write_text_atomic)
from ..core.model import Shape, polys_to_shapes, shapes_to_kinds, shapes_to_polys
from ..core.session import AuditLog, DraftStore, SessionTimer
from ..core.store import HAS_XLSX, AnnotationStore
from . import icons, shortcuts as sc
from .canvas import (Canvas, T_CIRCLE, T_LASSO, T_PAN, T_POLYGON, T_RECT,
                     T_SELECT)
from .dialogs.batch_dialog import BatchApplyDialog
from .dialogs.common import Dialog
from .dialogs.palette_dialog import CommandPalette, ShortcutSheet
from .dialogs.review_dialog import DashboardDialog, HistoryDialog, ReviewDialog
from .dialogs.settings_dialog import SettingsDialog
from .dialogs.transfer_dialog import ExportDialog, ImportDialog
from .dialogs.welcome_dialog import AboutDialog, WelcomeDialog
from .filmstrip import FilmStrip
from .palette import apply_palette, resolve_theme, stylesheet  # noqa: F401
from annotex.ui.palette import install_theme, toggled_setting
from annotex.ui import keymap
from annotex.ui.workspace import ElidedLabel, ToolRail, assemble
from .panels import (CommentBox, MiniMap, RoiListPanel, StatsPanel,
                     VertexInspector, divider)

TOOL_ACTIONS = {
    "tool_select": T_SELECT, "tool_polygon": T_POLYGON, "tool_rect": T_RECT,
    "tool_circle": T_CIRCLE, "tool_lasso": T_LASSO, "tool_pan": T_PAN,
}


class _PushSignals(QObject):
    done = Signal(object)


class _PushTask(QRunnable):
    """Deliver the JSON without blocking the UI."""

    def __init__(self, url, payload, header, timeout, signals):
        super().__init__()
        self.url, self.payload = url, payload
        self.header, self.timeout = header, timeout
        self.signals = signals
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        result = push.push_json(self.url, self.payload, self.header,
                                self.timeout)
        try:
            self.signals.done.emit(result)
        except RuntimeError:
            pass


class MainWindow(QMainWindow):

    def __init__(self, settings, app, host=None):
        super().__init__()
        self.settings = settings
        self.app = app
        # Inside the suite the shell owns the theme and the window frame;
        # standalone (the tests, or a direct launch) the window owns both.
        self.host = host
        if host is not None:
            settings.data["theme"] = host.theme_setting
        self.theme = resolve_theme(settings.get("theme", "dark"), app, tool="roi")

        # ── state ─────────────────────────────────────────
        self.folder = ""
        self.image_files = []
        self.index = 0
        self.current_pixmap = None
        self.image_size = (0, 0)

        self.store = AnnotationStore()
        self.lock = FolderLock()
        self.draft = DraftStore()
        self.audit = AuditLog()
        self.timer = SessionTimer()
        self.history = History()

        self.saved_shapes = {}          # name -> [Shape]
        self.no_roi_saved = set()
        self.comments = {}
        self.dirty = False
        self.read_only = False
        self._loading = False
        self._status_level = "info"

        self._push_signals = _PushSignals()
        self._push_signals.done.connect(self._push_finished)
        self._pool = QThreadPool()

        self.setWindowTitle("%s %s" % (APP_NAME, APP_VERSION))
        self.setMinimumSize(640, 440)
        self.setWindowIcon(icons.app_icon(self.theme["accent"],
                                          self.theme["appBg"]))

        self._build_actions()
        self._build_ui()
        self._build_menus()
        self._apply_theme()
        self._apply_settings()

        self._autosave = QTimer(self)
        self._autosave.timeout.connect(self._write_draft)
        self._autosave.start(max(5, int(settings.get("autosave_seconds", 20))) * 1000)

        if host is None:
            self._restore_geometry()
        else:
            self.menuBar().setNativeMenuBar(False)
        self._sync_actions()
        self._status("Open a batch folder to begin  ·  Ctrl+O", "info")

    # ══════════════════════════════════════════════════════
    # ACTIONS
    # ══════════════════════════════════════════════════════
    def _build_actions(self) -> None:
        self.keys = sc.resolve(self.settings.get("shortcuts", {}))
        self.actions_by_id = {}
        handlers = {
            "open_folder": self.choose_folder,
            "reload_folder": self.reload_folder,
            "close_folder": self.close_folder,
            "next_image": self.next_image,
            "prev_image": self.prev_image,
            "first_image": lambda: self.go_to_index(0),
            "last_image": lambda: self.go_to_index(len(self.image_files) - 1),
            "delete_image": self.delete_image,
            "finish_shape": lambda: self.canvas.finish_draft(),
            "cancel_shape": lambda: self.canvas.cancel_draft(),
            "undo_point": lambda: self.canvas.undo_draft_point(),
            "undo": self.undo,
            "redo": self.redo,
            "redo_alt": self.redo,
            "delete_roi": lambda: self.canvas.delete_selected(),
            "remove_vertex": lambda: self.canvas.remove_hovered_vertex(),
            "duplicate_roi": lambda: self.canvas.duplicate_selected(),
            "select_all": lambda: self.canvas.select_all(),
            "clear_all": self.clear_all,
            "copy_previous": self.copy_from_previous,
            "lock_roi": self.toggle_lock,
            "batch_apply": lambda: self.batch_apply("rois"),
            "batch_no_roi": lambda: self.batch_apply("no_roi"),
            "restore_backup": self.restore_from_backup,
            "save_project_settings": self.save_project_settings,
            "align_left": lambda: self.canvas.align_selected("left"),
            "align_hcentre": lambda: self.canvas.align_selected("hcentre"),
            "align_right": lambda: self.canvas.align_selected("right"),
            "align_top": lambda: self.canvas.align_selected("top"),
            "align_vcentre": lambda: self.canvas.align_selected("vcentre"),
            "align_bottom": lambda: self.canvas.align_selected("bottom"),
            "distribute_h": lambda: self.canvas.distribute_selected(True),
            "distribute_v": lambda: self.canvas.distribute_selected(False),
            "equalise": lambda: self.canvas.equalise_selected(),
            "save_roi": self.save_current,
            "mark_no_roi": self.mark_no_roi,
            "export_now": self.export_now,
            "export_formats": self.export_formats,
            "import_annotations": self.import_annotations,
            "push_api": lambda: self.push_to_endpoint(manual=True),
            "zoom_in": lambda: self.canvas.zoom_in(),
            "zoom_out": lambda: self.canvas.zoom_out(),
            "zoom_fit": lambda: self.canvas.fit_to_view(),
            "zoom_actual": lambda: self.canvas.set_zoom(1.0),
            "zoom_selection": lambda: self.canvas.zoom_to_selection(),
            "zoom_all_rois": lambda: self.canvas.zoom_to_all_shapes(),
            "toggle_theme": self.toggle_theme,
            "toggle_minimap": self.toggle_minimap,
            "toggle_crosshair": self.toggle_crosshair,
            "review_mode": self.open_review,
            "dashboard": self.open_dashboard,
            "open_report": self.write_report,
            "history_log": self.open_history,
            "settings": self.open_settings,
            "shortcuts_sheet": self.open_shortcuts,
            "command_palette": self.open_palette,
            "about": self.open_about,
        }
        for action_id, label, _default, _cat, icon_name, desc in sc.ACTIONS:
            action = QAction(label, self)
            action.setObjectName(action_id)
            if desc:
                action.setToolTip(desc)
                action.setStatusTip(desc)
            action.setShortcuts([QKeySequence(k) for k in
                                 keymap.sequences("roi", action_id, self.keys.get(action_id, ""))])
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            handler = handlers.get(action_id)
            if handler is not None:
                action.triggered.connect(self._guard(handler))
            if action_id in TOOL_ACTIONS:
                action.setCheckable(True)
            self.actions_by_id[action_id] = action
            self.addAction(action)

        for action_id in TOOL_ACTIONS:
            self.actions_by_id[action_id].triggered.connect(
                lambda _checked=False, a=action_id: self.set_tool(TOOL_ACTIONS[a]))

        # Arrow keys nudge; they stay out of the remappable set on purpose.
        for keys, delta in ((("Left",), (-1, 0)), (("Right",), (1, 0)),
                            (("Up",), (0, -1)), (("Down",), (0, 1))):
            shortcut = QShortcut(QKeySequence(keys[0]), self)
            shortcut.activated.connect(
                lambda d=delta: self.canvas.nudge_selected(*d))
        for keys, delta in ((("Shift+Left",), (-10, 0)),
                            (("Shift+Right",), (10, 0)),
                            (("Shift+Up",), (0, -10)),
                            (("Shift+Down",), (0, 10))):
            shortcut = QShortcut(QKeySequence(keys[0]), self)
            shortcut.activated.connect(
                lambda d=delta: self.canvas.nudge_selected(*d))

    def _guard(self, handler):
        """Wrap a handler so an unexpected error becomes a status line."""
        def run(*_args, **_kw):
            try:
                handler()
            except Exception as exc:
                self._report_exception(exc)
        return run

    def _report_exception(self, exc) -> None:
        try:
            import sys
            sys.stderr.write("".join(traceback.format_exception(
                type(exc), exc, exc.__traceback__)))
        except Exception:
            pass
        self._status("Recovered from an error: %s" % exc, "danger")

    def act(self, action_id) -> QAction:
        return self.actions_by_id[action_id]

    # ══════════════════════════════════════════════════════
    # LAYOUT
    # ══════════════════════════════════════════════════════
    def _build_ui(self) -> None:
        """The image first: the tools in a pill rail on the left, the side panel
        folding into a strip on the right, and the filmstrip folding under a
        one-line bar that carries the batch and image details."""
        self.canvas_frame = QFrame()
        self.canvas_frame.setObjectName("Card")
        frame_layout = QVBoxLayout(self.canvas_frame)
        design.margins(frame_layout, "xs")
        self.canvas = Canvas()
        frame_layout.addWidget(self.canvas)
        self.filmstrip = FilmStrip()

        self.title_label = QLabel(APP_TAGLINE, self)
        self.title_label.hide()
        self.folder_label = ElidedLabel("No batch loaded")
        self.folder_label.setObjectName("Subtitle")
        self.site_chip = QLabel("")
        self.site_chip.setObjectName("Subtitle")
        self.site_chip.setVisible(False)

        self.workspace = assemble(self, self._build_rail(), self.canvas_frame, self.filmstrip,
                                  self._build_side(), self.settings,
                                  info=((self.folder_label, 1), (self.site_chip, 0)),
                                  side_width=330, shortcut="Ctrl+Shift+L",
                                  on_prev=self.act("prev_image").trigger,
                                  on_next=self.act("next_image").trigger)
        self.splitter = self.workspace.splitter
        self.side = self.workspace.side
        # What stays within reach while the panel is folded away.
        self.strip_buttons = {}
        for action_id in ("save_roi", "mark_no_roi"):
            button = self._rail_button(action_id)
            button.clicked.connect(self.act(action_id).trigger)
            self.strip_buttons[action_id] = button
            self.side.add_strip_button(button)

        self._build_statusbar()
        self._wire_canvas()

    def _rail_button(self, action_id, checkable=False) -> QPushButton:
        action = self.act(action_id)
        button = QPushButton()
        button.setObjectName("Tool")
        button.setCheckable(checkable)
        button.setIconSize(QSize(design.ICON["l"], design.ICON["l"]))
        key = self.keys.get(action_id, "")
        button.setToolTip("%s%s" % (action.text(), ("   [%s]" % key) if key else ""))
        return button

    def _build_rail(self) -> ToolRail:
        """Every button the header held, top to bottom in a pill: drawing
        tools, then editing, then the windows."""
        rail = ToolRail()
        self.tool_buttons = {}
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        for action_id, tool in TOOL_ACTIONS.items():
            button = self._rail_button(action_id, checkable=True)
            button.clicked.connect(lambda _c=False, t=tool: self.set_tool(t))
            self.tool_group.addButton(button)
            self.tool_buttons[tool] = button
            rail.add(button)
        rail.add_separator()
        self.quick_buttons = {}
        for action_id in ("undo", "redo", "delete_roi", "duplicate_roi",
                          "clear_all", "copy_previous", "delete_image"):
            button = self._rail_button(action_id)
            button.clicked.connect(self.act(action_id).trigger)
            self.quick_buttons[action_id] = button
            rail.add(button)
        rail.add_separator()
        self.window_buttons = {}
        for action_id in ("review_mode", "dashboard", "settings", "shortcuts_sheet"):
            button = self._rail_button(action_id)
            button.clicked.connect(self.act(action_id).trigger)
            self.window_buttons[action_id] = button
            rail.add(button)
        return rail

    def _build_side(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(430)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        layout = QVBoxLayout(holder)
        design.margins(layout, "m")
        layout.setSpacing(design.SPACE["m"])

        self.minimap = MiniMap()
        layout.addWidget(self.minimap)

        self.roi_panel = RoiListPanel()
        layout.addWidget(self.roi_panel)

        self.vertex_panel = VertexInspector()
        layout.addWidget(self.vertex_panel)

        self.comment_box = CommentBox()
        layout.addWidget(self.comment_box)

        layout.addWidget(divider())
        self.stats_panel = StatsPanel()
        layout.addWidget(self.stats_panel)
        layout.addStretch(1)

        self.save_button = QPushButton("Save and continue")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self.act("save_roi").trigger)
        layout.addWidget(self.save_button)

        buttons = QHBoxLayout()
        buttons.setSpacing(design.SPACE["s"])
        self.no_roi_button = QPushButton("No ROI")
        self.no_roi_button.clicked.connect(self.act("mark_no_roi").trigger)
        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.act("export_now").trigger)
        buttons.addWidget(self.no_roi_button)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)

        scroll.setWidget(holder)
        outer = QVBoxLayout(panel)
        # Inset, so the scroll bar stays inside the panel's rounded corners.
        design.margins(outer, "xs")
        outer.addWidget(scroll)
        return panel

    def _build_statusbar(self) -> None:
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.setStatusBar(bar)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Hint")
        bar.addWidget(self.status_label, 1)

        self.state_chip = QLabel("")
        self.state_chip.setObjectName("Subtitle")
        bar.addPermanentWidget(self.state_chip)

        self.coord_label = QLabel("")
        self.coord_label.setObjectName("Mono")
        bar.addPermanentWidget(self.coord_label)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("Mono")
        bar.addPermanentWidget(self.zoom_label)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("Subtitle")
        bar.addPermanentWidget(self.progress_label)

        self.session_label = QLabel("")
        self.session_label.setObjectName("Subtitle")
        bar.addPermanentWidget(self.session_label)

        self._session_timer = QTimer(self)
        self._session_timer.timeout.connect(self._refresh_session)
        self._session_timer.start(20000)

    def _wire_canvas(self) -> None:
        self.canvas.shapesChanged.connect(self._on_shapes_changed)
        self.canvas.selectionChanged.connect(self._on_selection_changed)
        self.canvas.statusMessage.connect(self._status)
        self.canvas.zoomChanged.connect(
            lambda pct: self.zoom_label.setText("%d%%" % round(pct)))
        self.canvas.cursorMoved.connect(
            lambda x, y: self.coord_label.setText("x %d  y %d" % (x, y)))
        self.canvas.viewChanged.connect(self._refresh_minimap)

        self.filmstrip.imagePicked.connect(self.go_to_index)
        self.roi_panel.selectionRequested.connect(self._select_from_panel)
        self.roi_panel.visibilityToggled.connect(self.canvas.set_shape_visible)
        self.roi_panel.lockToggled.connect(self.canvas.set_shape_locked)
        self.roi_panel.deleteRequested.connect(
            lambda: self.canvas.delete_selected())
        self.roi_panel.duplicateRequested.connect(
            lambda: self.canvas.duplicate_selected())
        self.vertex_panel.vertexEdited.connect(self.canvas.replace_vertex)
        self.minimap.navigateTo.connect(self.canvas.center_on)

    def _build_menus(self) -> None:
        bar = self.menuBar()

        batch = bar.addMenu("&Batch")
        for action_id in ("open_folder", "reload_folder", "close_folder"):
            batch.addAction(self.act(action_id))
        batch.addSeparator()
        self.recent_menu = batch.addMenu("Recent folders")
        self._rebuild_recent()
        batch.addSeparator()
        for action_id in ("export_now", "export_formats", "import_annotations",
                          "push_api"):
            batch.addAction(self.act(action_id))
        batch.addSeparator()
        for action_id in ("restore_backup", "save_project_settings"):
            batch.addAction(self.act(action_id))
        batch.addSeparator()
        quit_action = QAction("Quit", self)
        if self.host is not None:
            home_action = QAction("Back to Home\tCtrl+Shift+H", self)
            home_action.triggered.connect(self.host.go_home)
            batch.addAction(home_action)
            # The shell owns Ctrl+Q; binding it here too would make the key
            # ambiguous and neither would fire.
            quit_action.triggered.connect(self.host.quit)
        else:
            quit_action.setShortcut(QKeySequence.StandardKey.Quit)
            quit_action.triggered.connect(self.close)
        batch.addAction(quit_action)

        edit = bar.addMenu("&Edit")
        for action_id in ("undo", "redo", "delete_roi", "duplicate_roi",
                          "select_all", "clear_all", "copy_previous",
                          "lock_roi"):
            edit.addAction(self.act(action_id))
        edit.addSeparator()
        for action_id in ("batch_apply", "batch_no_roi"):
            edit.addAction(self.act(action_id))
        arrange = edit.addMenu("Arrange")
        for action_id in ("align_left", "align_hcentre", "align_right",
                          "align_top", "align_vcentre", "align_bottom",
                          "distribute_h", "distribute_v", "equalise"):
            arrange.addAction(self.act(action_id))

        tools = bar.addMenu("&Tools")
        for action_id in TOOL_ACTIONS:
            tools.addAction(self.act(action_id))
        tools.addSeparator()
        for action_id in ("finish_shape", "cancel_shape", "undo_point"):
            tools.addAction(self.act(action_id))

        view = bar.addMenu("&View")
        for action_id in ("zoom_in", "zoom_out", "zoom_fit", "zoom_actual",
                          "zoom_selection", "zoom_all_rois"):
            view.addAction(self.act(action_id))
        view.addSeparator()
        for action_id in ("toggle_theme", "toggle_minimap", "toggle_crosshair"):
            view.addAction(self.act(action_id))

        go = bar.addMenu("&Go")
        for action_id in ("next_image", "prev_image", "first_image",
                          "last_image"):
            go.addAction(self.act(action_id))

        window = bar.addMenu("&Window")
        for action_id in ("review_mode", "dashboard", "open_report",
                          "history_log"):
            window.addAction(self.act(action_id))
        window.addSeparator()
        for action_id in ("settings", "command_palette", "shortcuts_sheet"):
            window.addAction(self.act(action_id))
        window.addSeparator()
        tour = QAction("Show the welcome tour", self)
        tour.triggered.connect(lambda: self.show_welcome(force=True))
        window.addAction(tour)
        window.addAction(self.act("about"))

    def _rebuild_recent(self) -> None:
        self.recent_menu.clear()
        recent = [f for f in self.settings.get("recent_folders", [])
                  if os.path.isdir(f)]
        if not recent:
            empty = QAction("Nothing yet", self)
            empty.setEnabled(False)
            self.recent_menu.addAction(empty)
            return
        for folder in recent:
            action = QAction(folder, self)
            action.triggered.connect(
                lambda _c=False, f=folder: self.open_folder(f))
            self.recent_menu.addAction(action)
        self.recent_menu.addSeparator()
        clear = QAction("Clear the list", self)
        clear.triggered.connect(lambda: (self.settings.set("recent_folders", []),
                                         self._rebuild_recent()))
        self.recent_menu.addAction(clear)

    # ══════════════════════════════════════════════════════
    # THEME & SETTINGS
    # ══════════════════════════════════════════════════════
    def _apply_theme(self) -> None:
        icons.clear_cache()
        install_theme(self, self.app, self.theme, self.host is not None)
        self.setWindowIcon(icons.app_icon(self.theme["accent"],
                                          self.theme["appBg"]))
        self.canvas.set_theme(self.theme)
        self.filmstrip.set_theme(self.theme)
        self.minimap.set_theme(self.theme)
        self.roi_panel.set_theme(self.theme)
        self.stats_panel.set_theme(self.theme)
        self.workspace.apply_theme(self.theme)
        for action_id, button in self.strip_buttons.items():
            button.setIcon(icons.icon(sc.BY_ID[action_id][4], self.theme["text"], 19))

        for action_id, tool in TOOL_ACTIONS.items():
            name = sc.BY_ID[action_id][4]
            self.tool_buttons[tool].setIcon(
                icons.dual_icon(name, self.theme["text"],
                                self.theme["onAccent"], 19))
        for action_id, button in self.quick_buttons.items():
            colour = (self.theme["danger"] if action_id in ("delete_roi",
                                                            "clear_all", "delete_image")
                      else self.theme["text"])
            button.setIcon(icons.icon(sc.BY_ID[action_id][4], colour, 19))
        for action_id, button in self.window_buttons.items():
            name = sc.BY_ID[action_id][4]
            if action_id == "toggle_theme":
                name = "sun" if self.theme["name"] == "dark" else "moon"
            button.setIcon(icons.icon(name, self.theme["text"], 19))
        for action_id, action in self.actions_by_id.items():
            action.setIcon(icons.icon(sc.BY_ID[action_id][4],
                                      self.theme["text"], 16))
        self._paint_status()
        self._refresh_state_chip()
        self._repolish()

    def _repolish(self) -> None:
        """Re-apply the stylesheet to the live widget tree.

        Setting an application stylesheet marks widgets dirty but only
        restyles them on the next event-loop turn; doing it explicitly means
        a theme change is visible in the same frame as the click."""
        widgets = self.findChildren(QWidget)
        widgets.append(self)
        for widget in widgets:
            try:
                style = widget.style()
                style.unpolish(widget)
                style.polish(widget)
                widget.update()
            except Exception:
                continue

    def _apply_settings(self) -> None:
        settings = self.settings
        self.canvas.set_options(
            show_crosshair=bool(settings.get("show_crosshair", True)),
            show_coordinates=bool(settings.get("show_coordinates", True)),
            snap_to_edges=bool(settings.get("snap_to_edges", True)),
            snap_to_shapes=bool(settings.get("snap_to_shapes", True)),
            fill_opacity=int(settings.get("roi_opacity", 28)),
            line_width=int(settings.get("roi_line_width", 2)))
        self.minimap.setVisible(bool(settings.get("show_minimap", True)))
        self.coord_label.setVisible(bool(settings.get("show_coordinates", True)))
        interval = max(5, int(settings.get("autosave_seconds", 20))) * 1000
        if hasattr(self, "_autosave") and self._autosave.interval() != interval:
            self._autosave.setInterval(interval)

    def _view_columns(self):
        chosen = [c for c in (self.settings.get("export_columns") or [])]
        if chosen:
            return chosen
        return list(SITE_VIEW if self.settings.get("use_site_format")
                    else FULL_VIEW)

    def toggle_theme(self) -> None:
        name = toggled_setting(self.theme)
        if self.host is not None:
            self.host.request_theme(name)       # every tool follows
        else:
            self.tool_apply_theme(name)
        self._status("Switched to the %s theme" % name, "info")

    def toggle_minimap(self) -> None:
        visible = not self.minimap.isVisible()
        self.minimap.setVisible(visible)
        self.settings.set("show_minimap", visible)

    def toggle_crosshair(self) -> None:
        value = not self.canvas.show_crosshair
        self.canvas.set_options(show_crosshair=value)
        self.settings.set("show_crosshair", value)
        self._status("Crosshair %s" % ("on" if value else "off"), "info")

    # ══════════════════════════════════════════════════════
    # STATUS
    # ══════════════════════════════════════════════════════
    def _status(self, message, level="info") -> None:
        self._status_level = level
        self.status_label.setText(str(message))
        self._paint_status()

    def _paint_status(self) -> None:
        names = {"info": "Hint", "good": "HintGood", "warning": "HintWarn",
                 "danger": "HintDanger"}
        self.status_label.setObjectName(names.get(self._status_level, "Hint"))
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _refresh_state_chip(self) -> None:
        name = self.current_name()
        if self.read_only:
            text, colour = "read-only", "warn"
        elif self.dirty:
            text, colour = "● write failed", "danger"
        elif name is None:
            text, colour = "", "sub"
        elif self.canvas.shapes and self._shapes_match_saved(name):
            text, colour = "● saved", "good"
        elif self.canvas.shapes:
            text, colour = "● unsaved", "accent"
        elif name in self.no_roi_saved:
            text, colour = "○ no ROI", "sub"
        else:
            text, colour = "· empty", "sub"
        self.state_chip.setText(text)
        style.set_tone(self.state_chip, colour)

    def _refresh_session(self) -> None:
        self.session_label.setText(self.timer.summary())

    # ══════════════════════════════════════════════════════
    # FOLDER
    # ══════════════════════════════════════════════════════
    def choose_folder(self) -> None:
        start = self.folder or (self.settings.get("recent_folders") or [""])[0]
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the folder of images", start or os.path.expanduser("~"))
        if folder:
            self.open_folder(folder)

    def open_folder(self, folder) -> None:
        folder = os.path.abspath(str(folder))
        if self.folder and not self._commit_current():
            return
        if not os.path.isdir(folder):
            self._status("That folder no longer exists", "danger")
            return
        try:
            names = os.listdir(folder)
        except OSError as exc:
            self._status("Cannot read the folder: %s" % exc, "danger")
            return

        writable, why = folder_is_writable(folder)
        if not writable:
            answer = messages.ask(
                self, "Read-only folder",
                "This folder cannot be written to:\n%s\n\nOpen it read-only?\n"
                "You will be able to look at existing annotations but not "
                "save changes." % why)
            if not answer:
                return

        lock_note = ""
        if writable:
            acquired, message = self.lock.acquire(folder)
            if not acquired:
                answer = messages.ask(
                    self, "Folder in use",
                    "%s\n\nOpening it anyway can corrupt the outputs.\n"
                    "Continue?" % message)
                if not answer:
                    self._relock_current()
                    return
                self.lock.acquire(folder, force=True)
                lock_note = "lock overridden - close the other session"
            elif message:
                lock_note = message
        elif self.lock.held:
            self.lock.release()

        self.read_only = not writable
        self.folder = folder
        # ROIs waiting for their image's size belong to the folder they came
        # from, not to an image of the same name in this one.
        self._pending_norm = {}
        self.image_files = sorted(
            (f for f in names
             if f.lower().endswith(IMG_EXTS) and f not in OUTPUT_DIRS
             and os.path.isfile(os.path.join(folder, f))),
            key=geo.natural_key)

        if writable:
            for name in OUTPUT_DIRS:
                if not ensure_dir(os.path.join(folder, name)):
                    self._status("Could not create the %s folder" % name,
                                 "danger")
                    return

        self.index = 0
        self.saved_shapes = {}
        self.no_roi_saved = set()
        self.comments = {}
        self.dirty = False
        self.canvas.read_only = self.read_only

        project_note = self._load_project_settings(folder)
        self.store.bind(folder)
        notes = self.store.load()
        self.draft.bind(folder)
        self.audit.bind(folder)
        self.audit.enabled = writable
        self._rebuild_from_store()

        self.folder_label.setText(folder)
        self.settings.push_recent(folder)
        self._rebuild_recent()
        self.audit.record("open_folder", detail="%d image(s)"
                          % len(self.image_files))

        extras = [n for n in (notes[-1] if notes else "", lock_note,
                              project_note, self._missing_key_note()) if n]
        if not self.image_files:
            self._status("No supported images in this folder", "warning")
        else:
            message = "%d image(s) loaded" % len(self.image_files)
            if extras:
                message += "  ·  " + "  ·  ".join(extras)
            self._status(message, "warning" if lock_note else "good")

        self._refresh_filmstrip()
        self._load_image(0)
        self._offer_draft()
        self._sync_actions()

    def _relock_current(self) -> None:
        """Asking for another folder let go of this one's lock; the other
        was not opened after all, so take it back."""
        if self.folder and not self.read_only and not self.lock.held:
            self.lock.acquire(self.folder)

    def reload_folder(self) -> None:
        if not self.folder:
            self._status("No batch loaded", "warning")
            return
        if not self._commit_current():
            return
        folder = self.folder
        self.folder = ""
        self.open_folder(folder)

    def close_folder(self) -> None:
        if not self.folder:
            return
        if not self._commit_current():
            return
        self.lock.release()
        self.folder = ""
        self.image_files = []
        self.saved_shapes = {}
        self.no_roi_saved = set()
        self.comments = {}
        self.canvas.load_image(None)
        self.filmstrip.clear()
        self.folder_label.setText("No batch loaded")
        self.site_chip.setVisible(False)
        self._refresh_side()
        self._update_stats()
        self._sync_actions()
        self._status("Batch closed", "info")

    def _rebuild_from_store(self) -> None:
        known = set(self.image_files)
        for row in self.store.rows:
            name = row["image_name"]
            if name not in known:
                match = self._match_basename(name)
                if match:
                    name = match
            if not name:
                continue
            if row.get("comment"):
                self.comments[name] = row["comment"]
            kind = row.get("row_type")
            if kind == "no_roi":
                self.no_roi_saved.add(name)
                continue
            if kind == "comment":
                continue
            polys = geo.parse_multi_polys(row.get("pixel_coords", ""))
            width = int(row.get("image_width") or 0)
            height = int(row.get("image_height") or 0)
            if not polys:
                norm = geo.parse_multi_polys(row.get("normalized_coords", ""))
                if norm and width and height:
                    polys = geo.norm_to_polys(norm, width, height)
                elif norm:
                    # size unknown until the image is opened; keep normalised
                    self.saved_shapes.setdefault(name, [])
                    self._pending_norm = getattr(self, "_pending_norm", {})
                    self._pending_norm[name] = norm
                    continue
            if polys:
                kinds = geo.parse_shape_types(row.get("shape_types", ""),
                                              len(polys))
                self.saved_shapes.setdefault(name, []).extend(
                    polys_to_shapes(polys, kinds))

    def _match_basename(self, name):
        stem = os.path.splitext(str(name))[0]
        for candidate in self.image_files:
            if os.path.splitext(candidate)[0] == stem:
                return candidate
        return None

    def _missing_key_note(self) -> str:
        bad = [f for f in self.image_files
               if "_" not in os.path.splitext(f)[0]
               or not geo.cam_digits(geo.extract_site_cam(f)[1])]
        if not bad:
            return ""
        return ("%d filename(s) have no camera number - their roi_key is the "
                "site id alone (e.g. %s)" % (len(bad), geo.make_roi_key(bad[0])))

    # ══════════════════════════════════════════════════════
    # IMAGES
    # ══════════════════════════════════════════════════════
    def current_name(self):
        if self.image_files and 0 <= self.index < len(self.image_files):
            return self.image_files[self.index]
        return None

    def _load_image(self, index) -> None:
        self._loading = True
        try:
            if not self.image_files:
                self.canvas.load_image(None)
                self.current_pixmap = None
                self.site_chip.setVisible(False)
                self.comment_box.clear()
                self._refresh_side()
                self._update_stats()
                return

            self.index = max(0, min(int(index), len(self.image_files) - 1))
            name = self.image_files[self.index]
            path = os.path.join(self.folder, name)

            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                pixmap = QPixmap(path)
            finally:
                QApplication.restoreOverrideCursor()

            if pixmap.isNull():
                self._status("Cannot read %s - skipping it" % name, "warning")
                self.image_files.pop(self.index)
                self._refresh_filmstrip()
                if self.image_files:
                    QTimer.singleShot(0, lambda: self._load_image(self.index))
                else:
                    self.canvas.load_image(None)
                return

            self.current_pixmap = pixmap
            self.image_size = (pixmap.width(), pixmap.height())
            shapes = self._shapes_for(name)
            self.canvas.load_image(pixmap, shapes)
            self.history.reset(self.canvas.snapshot())
            self.comment_box.set_text(self.comments.get(name, ""))
            self.minimap.set_image(pixmap, self.image_size)

            site, cam = geo.extract_site_cam(name)
            self.site_chip.setText("%s  ·  %s  ·  %d x %d"
                                   % (site, cam or "no cam", pixmap.width(),
                                      pixmap.height()))
            self.site_chip.setVisible(True)
            self.filmstrip.set_index(self.index)
        finally:
            self._loading = False
        self._refresh_side()
        self._update_stats()
        self._refresh_minimap()
        self.canvas.setFocus()

    def _shapes_for(self, name):
        """Saved shapes for this image, converting any normalised-only rows
        now that the real size is known."""
        pending = getattr(self, "_pending_norm", {})
        if name in pending and self.image_size[0]:
            polys = geo.norm_to_polys(pending.pop(name), *self.image_size)
            self.saved_shapes[name] = polys_to_shapes(polys)
        return [s.copy() for s in self.saved_shapes.get(name, [])]

    def go_to_index(self, index) -> None:
        if not self.image_files:
            return
        index = max(0, min(int(index), len(self.image_files) - 1))
        if index == self.index:
            return
        if not self._commit_current():
            return
        self._load_image(index)

    def go_to_name(self, name) -> None:
        if name in self.image_files:
            self.go_to_index(self.image_files.index(name))

    def next_image(self) -> None:
        if not self.image_files:
            self._status("No batch loaded", "warning")
            return
        if not self._commit_current():
            return
        if self.index >= len(self.image_files) - 1:
            self._status("That was the last image", "good")
            self._update_stats()
            return
        self._load_image(self.index + 1)

    def prev_image(self) -> None:
        if not self.image_files:
            return
        if self.index <= 0:
            self._status("Already at the first image", "info")
            return
        if not self._commit_current():
            return
        self._load_image(self.index - 1)

    # ══════════════════════════════════════════════════════
    # CANVAS FEEDBACK
    # ══════════════════════════════════════════════════════
    def _on_shapes_changed(self, label) -> None:
        if self._loading:
            return
        self.history.push(str(label or "Edit"), self.canvas.snapshot())
        self.timer.touch()
        self._refresh_side()
        self._sync_actions()

    def _on_selection_changed(self) -> None:
        self._refresh_side()
        self._sync_actions()

    def _select_from_panel(self, index, additive) -> None:
        if index < 0:
            self.canvas.clear_selection()
        else:
            self.canvas.select_index(index, additive)

    def _refresh_side(self) -> None:
        shapes = self.canvas.shapes
        selection = self.canvas.selection
        self.roi_panel.refresh(shapes, selection)
        if selection:
            index = sorted(selection)[0]
            self.vertex_panel.show_shape(index, shapes[index]
                                         if index < len(shapes) else None)
        else:
            self.vertex_panel.show_shape(-1, None)
        self._refresh_state_chip()
        self._refresh_minimap()

    def _refresh_minimap(self) -> None:
        if self.minimap.isVisible() and self.canvas.has_image():
            self.minimap.set_view(self.canvas.visible_image_rect(),
                                  self.canvas.shapes)

    def set_tool(self, tool) -> None:
        self.canvas.set_tool(tool)
        button = self.tool_buttons.get(tool)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        for action_id, mapped in TOOL_ACTIONS.items():
            self.act(action_id).setChecked(mapped == tool)
        hints = {
            T_SELECT: "Select - drag a vertex, drag inside to move, "
                      "double-click an edge to add a point, Ctrl+click one to "
                      "remove it",
            T_POLYGON: "Polygon - click to place points, click the first "
                       "point or press Enter to close",
            T_RECT: "Rectangle - drag out the box",
            T_CIRCLE: "Circle - drag out the shape",
            T_LASSO: "Freehand - hold the button and trace; the path is "
                     "simplified when you let go",
            T_PAN: "Pan - drag the image (hold Space with any tool)",
        }
        self._status(hints.get(tool, ""), "info")

    # ══════════════════════════════════════════════════════
    # UNDO / REDO
    # ══════════════════════════════════════════════════════
    def undo(self) -> None:
        if self.canvas.undo_draft_point():
            return
        result = self.history.undo()
        if result is None:
            self._status("Nothing to undo", "info")
            return
        label, snapshot = result
        self.canvas.set_shapes(snapshot)
        self._refresh_side()
        self._sync_actions()
        self._status("Undid: %s" % label, "info")

    def redo(self) -> None:
        result = self.history.redo()
        if result is None:
            self._status("Nothing to redo", "info")
            return
        label, snapshot = result
        self.canvas.set_shapes(snapshot)
        self._refresh_side()
        self._sync_actions()
        self._status("Redid: %s" % label, "info")

    def clear_all(self) -> None:
        if not self.canvas.shapes:
            self._status("Nothing to clear", "info")
            return
        if self.settings.get("confirm_clear_all", True):
            answer = messages.ask(
                self, "Clear every ROI",
                "Remove all %d ROI(s) from this image?\n\nCtrl+Z brings them "
                "back." % len(self.canvas.shapes))
            if not answer:
                return
        self.canvas.clear_all()

    def toggle_lock(self) -> None:
        shapes = self.canvas.selected_shapes()
        if not shapes:
            self._status("Select an ROI first", "warning")
            return
        self.canvas.set_selected_locked(not all(s.locked for s in shapes))

    def copy_from_previous(self) -> None:
        if self.index <= 0:
            self._status("There is no previous image", "warning")
            return
        previous = self.image_files[self.index - 1]
        shapes = self.saved_shapes.get(previous)
        if not shapes:
            self._status("%s has no saved ROIs to copy" % previous, "warning")
            return
        added = self.canvas.add_shapes(shapes, "Copy ROIs from previous image")
        if added:
            self._status("Copied %d ROI(s) from %s" % (added, previous), "good")
        else:
            self._status("Nothing could be copied", "warning")

    # ══════════════════════════════════════════════════════
    # SAVING
    # ══════════════════════════════════════════════════════
    def _shapes_match_saved(self, name) -> bool:
        saved = self.saved_shapes.get(name)
        if saved is None:
            return False
        current = self.canvas.shapes
        if len(saved) != len(current):
            return False
        return all(a.points == b.points and a.kind == b.kind
                   for a, b in zip(saved, current))

    def _has_saved_roi(self, name) -> bool:
        return bool(self.saved_shapes.get(name))

    def save_current(self) -> None:
        name = self.current_name()
        if name is None:
            self._status("No image loaded", "warning")
            return
        if self.read_only:
            self._status("This batch is open read-only", "warning")
            return
        self.canvas.finish_draft(quiet=True)
        if not self.canvas.shapes:
            self._status("Nothing drawn - press N to file this under no_roi",
                         "warning")
            return
        if self._write_roi(name):
            self.timer.count_image(len(self.canvas.shapes))
            self._status("Saved %d ROI(s) for %s"
                         % (len(self.canvas.shapes), name), "good")
            if self.settings.get("auto_advance_on_save", True):
                self._advance()

    def delete_image(self) -> None:
        """Take the image on screen out of the batch: it moves into
        deleted_images (with any printed_roi / no_roi copy of it), and its rows
        leave the spreadsheet and JSON.  Nothing is erased."""
        import shutil
        name = self.current_name()
        if name is None:
            self._status("No image loaded", "warning")
            return
        if self.read_only:
            self._status("This batch is open read-only", "warning")
            return
        answer = messages.ask(
            self, "Move image out of the batch",
            "Move %s into deleted_images?\n\nIts ROIs are taken out of the batch outputs too. "
            "Nothing is erased: move the image back and annotate it again to restore it." % name)
        if not answer:
            return
        target = os.path.join(self.folder, "deleted_images")

        def free_name(file_name):
            stem, ext = os.path.splitext(file_name)
            candidate, counter = os.path.join(target, file_name), 2
            while os.path.exists(candidate):
                candidate = os.path.join(target, "%s_%d%s" % (stem, counter, ext))
                counter += 1
            return candidate

        try:
            os.makedirs(target, exist_ok=True)
            shutil.move(os.path.join(self.folder, name), free_name(name))
        except OSError as exc:
            self._status("Could not move the image: %s" % exc, "danger")
            return
        for sub in OUTPUT_DIRS:
            copy = os.path.join(self.folder, sub, name)
            if os.path.isfile(copy):
                try:
                    shutil.move(copy, free_name("%s_%s" % (sub, name)))
                except OSError:
                    pass
        self.store.purge(name)
        self.saved_shapes.pop(name, None)
        self.no_roi_saved.discard(name)
        self.comments.pop(name, None)
        report = self._flush()
        self.dirty = False
        self.image_files.pop(self.index)
        self._refresh_filmstrip()
        self._load_image(min(self.index, max(0, len(self.image_files) - 1)))
        if getattr(report, "ok", True):
            self._status("%s moved to deleted_images" % name, "good")
        else:
            self._status("%s moved to deleted_images, but the outputs could not be rewritten"
                         % name, "warning")

    def mark_no_roi(self) -> None:
        name = self.current_name()
        if name is None:
            self._status("No image loaded", "warning")
            return
        if self.read_only:
            self._status("This batch is open read-only", "warning")
            return
        if self.canvas.shapes:
            answer = messages.ask(
                self, "Mark as no_roi",
                "This image has %d ROI(s).\n\nDiscard them and file it under "
                "%s?" % (len(self.canvas.shapes), NO_ROI_DIR))
            if not answer:
                return
        self.canvas.set_shapes([])
        if self._write_no_roi(name):
            self.timer.count_image(0)
            self._status("%s filed under %s" % (name, NO_ROI_DIR), "good")
            if self.settings.get("auto_advance_on_save", True):
                self._advance()

    def _advance(self) -> None:
        if self.index < len(self.image_files) - 1:
            self._load_image(self.index + 1)
        else:
            self._status("That was the last image - the batch is done", "good")
            self._update_stats()

    def _write_roi(self, name) -> bool:
        width, height = self.image_size
        keep, notes = [], []
        for position, shape in enumerate(self.canvas.shapes):
            clean, problems = shape.validated(width, height)
            if clean is None:
                notes.append("ROI %d dropped (%s)"
                             % (position + 1, "; ".join(problems)))
                continue
            if problems:
                notes.append("ROI %d: %s" % (position + 1, "; ".join(problems)))
            keep.append(clean)

        if not keep:
            self._status("Nothing valid to save: %s"
                         % ("; ".join(notes) or "no usable ROI"), "danger")
            return False

        self.canvas.set_shapes(keep, keep_selection=True)
        comment = self.comment_box.text()
        self.comments[name] = comment
        polys = shapes_to_polys(keep)
        kinds = shapes_to_kinds(keep)
        norm = geo.polys_to_norm(polys, width, height)

        self.store.purge(name)
        self.store.add(AnnotationStore.make_row(
            name, "roi", polys, norm, comment, width, height, kinds))

        report = self._flush()
        if not report.ok:
            return False

        self.saved_shapes[name] = [s.copy() for s in keep]
        self.no_roi_saved.discard(name)

        side = self._write_image_copies(name, keep)
        if side.warnings:
            notes.extend(side.warnings)
        if side.errors:
            notes.extend(side.errors)

        self.history.reset(self.canvas.snapshot())
        self.draft.clear()
        self.audit.record("save_roi", name, "%d ROI(s)" % len(keep),
                          shapes=kinds)
        if notes:
            self._status(report.summary() + "  ·  " + "; ".join(notes[:2]),
                         "warning")
        self._refresh_filmstrip()
        self._update_stats()
        self._sync_actions()
        return True

    def _write_no_roi(self, name) -> bool:
        comment = self.comment_box.text()
        self.comments[name] = comment
        width, height = self.image_size
        self.store.purge(name)
        self.store.add(AnnotationStore.make_row(
            name, "no_roi", [], [], comment, width, height))

        report = self._flush()
        if not report.ok:
            return False

        self.no_roi_saved.add(name)
        self.saved_shapes.pop(name, None)
        source = os.path.join(self.folder, name)
        imaging.copy_into(source, os.path.join(self.folder, NO_ROI_DIR), name)
        imaging.remove_from(os.path.join(self.folder, PRINTED_DIR), name)

        self.history.reset(self.canvas.snapshot())
        self.draft.clear()
        self.audit.record("mark_no_roi", name, comment)
        self._refresh_filmstrip()
        self._update_stats()
        self._sync_actions()
        return True

    def _write_image_copies(self, name, shapes) -> WriteReport:
        """The burnt-in preview.  Its colour is a setting and applies here
        only - never to the live canvas."""
        source = os.path.join(self.folder, name)
        printed = os.path.join(self.folder, PRINTED_DIR, name)
        imaging.remove_from(os.path.join(self.folder, NO_ROI_DIR), name)
        return imaging.write_preview(
            source, printed, [s.points for s in shapes],
            colour=self.settings.get("printed_roi_colour", "#00dc64"),
            fill_alpha=int(self.settings.get("printed_roi_fill_alpha", 70)),
            line_width=int(self.settings.get("printed_roi_line_width", 3)),
            label_colour=self.settings.get("printed_label_colour", "#ffff00"))

    def _flush(self) -> WriteReport:
        if not self._confirm_external_change():
            report = WriteReport()
            report.errors.append("write cancelled - the file on disk is newer")
            self._set_dirty(True)
            self._status(report.summary(), "warning")
            return report
        report = self.store.flush(self._view_columns())
        if report.ok:
            self._set_dirty(False)
            self._status(report.summary(),
                         "warning" if report.warnings else "good")
        else:
            self._set_dirty(True)
            self._status(report.summary(), "danger")
        return report

    def _confirm_external_change(self) -> bool:
        """Someone changed the spreadsheet since we read it - ask first."""
        if not self.store.changed_externally():
            return True
        answer = messages.ask(
            self, "The spreadsheet changed on disk",
            "%s has been modified since this session read it - another "
            "session or another person may have written to it.\n\n"
            "Overwrite it with what is in this window?\n\n"
            "The previous contents stay available as the .bak copy."
            % os.path.basename(self.store.xlsx_path), default=False)
        if answer:
            self.store.touch_stamp()          # accept it and move on
            self.audit.record("overwrite_external",
                              detail="user chose to overwrite")
            return True
        return False

    def _set_dirty(self, value) -> None:
        self.dirty = bool(value)
        self._refresh_state_chip()

    def _commit_current(self) -> bool:
        """Save whatever is on screen before leaving the image.

        Returns False when a write failed, so the caller stays put rather than
        navigating away from work that is not on disk."""
        name = self.current_name()
        if name is None or not self.folder or self.read_only:
            return True
        self.canvas.finish_draft(quiet=True)
        comment = self.comment_box.text()
        previous_comment = self.comments.get(name, "")

        if self.canvas.shapes:
            unchanged = (self._shapes_match_saved(name)
                         and comment == previous_comment
                         and self._has_saved_roi(name))
            if unchanged:
                return True
            return self._write_roi(name)

        self.comments[name] = comment
        if not self._has_saved_roi(name):
            if name not in self.no_roi_saved or comment != previous_comment:
                return self._write_no_roi(name)
            return True
        return self._write_no_roi(name)

    # ══════════════════════════════════════════════════════
    # BATCH OPERATIONS
    # ══════════════════════════════════════════════════════
    def batch_apply(self, default_action="rois") -> None:
        """Apply the current ROIs, or a no_roi decision, to many images.

        The images are written straight to the store without being opened, so
        a hundred frames of a fixed camera take one pass rather than a
        hundred."""
        if not self.image_files:
            self._status("No batch loaded", "warning")
            return
        if self.read_only:
            self._status("This batch is open read-only", "warning")
            return
        if not self._commit_current():
            return

        name = self.current_name()
        shapes = [s.copy() for s in self.canvas.shapes]
        dialog = BatchApplyDialog(self, self.image_files, name,
                                  self._statuses(), len(shapes),
                                  default_action)
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        if dialog.overwrite:
            answer = messages.ask(
                self, "Replace existing work",
                "Some of the chosen images already have a saved decision.\n\n"
                "Replace them?")
            if not answer:
                return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            done, skipped, notes = self._apply_to_images(
                dialog.selected, shapes if dialog.action == "rois" else None)
        finally:
            QApplication.restoreOverrideCursor()

        report = self._flush()
        if not report.ok:
            return
        self.audit.record("batch_apply", detail="%s -> %d image(s)"
                          % (dialog.action, done))
        self._refresh_filmstrip()
        self._update_stats()
        message = "Applied to %d image(s)" % done
        if skipped:
            message += "  ·  %d skipped (%s)" % (skipped, "; ".join(notes[:2]))
        self._status(message, "warning" if skipped else "good")

    def _apply_to_images(self, names, shapes):
        """Write rows for a list of images.  `shapes` None means no_roi."""
        done, skipped, notes = 0, 0, []
        comment = ""
        for name in names:
            path = os.path.join(self.folder, name)
            if shapes is None:
                size = self.image_size if name == self.current_name() else \
                    imaging.image_size(path)
                self.store.purge(name)
                self.store.add(AnnotationStore.make_row(
                    name, "no_roi", [], [], comment, size[0], size[1]))
                self.no_roi_saved.add(name)
                self.saved_shapes.pop(name, None)
                imaging.copy_into(path, os.path.join(self.folder, NO_ROI_DIR),
                                  name)
                imaging.remove_from(os.path.join(self.folder, PRINTED_DIR), name)
                done += 1
                continue

            width, height = imaging.image_size(path)
            if not width or not height:
                skipped += 1
                notes.append("%s could not be read" % name)
                continue
            keep = []
            for shape in shapes:
                clean, _messages = shape.copy().validated(width, height)
                if clean is not None:
                    keep.append(clean)
            if not keep:
                skipped += 1
                notes.append("%s: no ROI fitted the image" % name)
                continue
            polys = shapes_to_polys(keep)
            norm = geo.polys_to_norm(polys, width, height)
            self.store.purge(name)
            self.store.add(AnnotationStore.make_row(
                name, "roi", polys, norm, comment, width, height,
                shapes_to_kinds(keep)))
            self.saved_shapes[name] = [s.copy() for s in keep]
            self.no_roi_saved.discard(name)
            self._write_image_copies(name, keep)
            done += 1
        return done, skipped, notes

    # ══════════════════════════════════════════════════════
    # RECOVERY
    # ══════════════════════════════════════════════════════
    def restore_from_backup(self) -> None:
        """Bring this image's annotation back from the rolling .bak copy."""
        name = self.current_name()
        if name is None or not self.folder:
            self._status("No image loaded", "warning")
            return
        backup = self.store.xlsx_path + ".bak"
        if not os.path.isfile(backup):
            self._status("There is no backup for this batch yet", "warning")
            return

        result = importers.read_annotation_file(backup)
        if not result.ok:
            self._status(result.summary(), "danger")
            return
        rows = [r for r in result.rows if r["image_name"] == name]
        if not rows:
            self._status("The backup has nothing for %s" % name, "warning")
            return

        row = rows[0]
        polys = geo.parse_multi_polys(row.get("pixel_coords", ""))
        if not polys:
            norm = geo.parse_multi_polys(row.get("normalized_coords", ""))
            if norm and self.image_size[0]:
                polys = geo.norm_to_polys(norm, *self.image_size)
        kinds = geo.parse_shape_types(row.get("shape_types", ""), len(polys))
        shapes = polys_to_shapes(polys, kinds)

        summary = ("%d ROI(s)" % len(shapes)) if shapes else "a no_roi decision"
        answer = messages.ask(
            self, "Restore from backup",
            "The backup holds %s for %s.\n\nReplace what is on screen with "
            "it?\n\nNothing is written until you save." % (summary, name))
        if not answer:
            return

        self.canvas.set_shapes(shapes)
        self.history.push("Restore from backup", self.canvas.snapshot())
        self.comment_box.set_text(row.get("comment", ""))
        self._refresh_side()
        self._sync_actions()
        self.audit.record("restore_backup", name, summary)
        self._status("Restored %s from the backup - press S to keep it"
                     % summary, "warning")

    # ══════════════════════════════════════════════════════
    # PER-BATCH SETTINGS
    # ══════════════════════════════════════════════════════
    PROJECT_KEYS = ("use_site_format", "export_columns", "printed_roi_colour",
                    "printed_label_colour", "printed_roi_fill_alpha",
                    "printed_roi_line_width", "roi_opacity", "roi_line_width",
                    "snap_to_edges", "snap_to_shapes", "auto_advance_on_save",
                    "confirm_clear_all")

    def _load_project_settings(self, folder) -> str:
        """Apply a .roi_studio.json living beside the images.

        Batch-level settings win for this session only - they are never
        written back into the user's own preferences."""
        path = os.path.join(str(folder), PROJECT_SETTINGS_NAME)
        data = read_json(path, None)
        wanted = {key: data[key] for key in self.PROJECT_KEYS
                  if isinstance(data, dict) and key in data}
        had = bool(getattr(self.settings, "overrides", None))
        apply = getattr(self.settings, "apply_overrides", None)
        if apply is not None:
            applied = apply(wanted)
        else:                                   # a plain settings store
            self.settings.data.update(wanted)
            applied = len(wanted)
        if applied or had:
            self._apply_settings()
        if not applied:
            return ""
        return "%d batch setting(s) applied from %s" % (applied,
                                                        PROJECT_SETTINGS_NAME)

    def save_project_settings(self) -> None:
        if not self.folder:
            self._status("No batch loaded", "warning")
            return
        payload = {key: self.settings.get(key) for key in self.PROJECT_KEYS}
        payload["_note"] = ("Settings for this batch. Anyone who opens this "
                            "folder in ROI Studio picks these up.")
        path = os.path.join(self.folder, PROJECT_SETTINGS_NAME)
        ok, err = write_text_atomic(path, json.dumps(payload, indent=2),
                                    verify_json=True, keep_backup=False)
        if ok:
            self.audit.record("save_project_settings")
            self._status("Batch settings written to %s" % PROJECT_SETTINGS_NAME,
                         "good")
        else:
            self._status("Could not write the batch settings: %s" % err,
                         "danger")

    # ══════════════════════════════════════════════════════
    # DRAFTS
    # ══════════════════════════════════════════════════════
    def _write_draft(self) -> None:
        if self.read_only or not self.folder:
            return
        name = self.current_name()
        if name is None:
            return
        if self._shapes_match_saved(name) and \
                self.comment_box.text() == self.comments.get(name, ""):
            return
        try:
            self.draft.save(name, self.canvas.shapes, self.comment_box.text())
        except Exception:
            pass

    def _offer_draft(self) -> None:
        pending = self.draft.pending()
        if not pending:
            return
        name = pending.get("image_name", "")
        if name not in self.image_files:
            self.draft.clear()
            return
        answer = messages.ask(
            self, "Unsaved work recovered",
            "A draft for %s was left behind by an earlier session "
            "(%s).\n\nRestore it?" % (name, pending.get("saved_at", "unknown")))
        if not answer:
            self.draft.clear()
            return
        self.go_to_name(name)
        shapes = [Shape(points=[tuple(p) for p in entry.get("points", [])],
                        kind=entry.get("kind", "polygon"))
                  for entry in pending.get("shapes", [])]
        if shapes:
            self.canvas.set_shapes(shapes)
            self.history.push("Recover draft", self.canvas.snapshot())
        self.comment_box.set_text(pending.get("comment", ""))
        self.draft.clear()
        self._refresh_side()
        self._status("Draft restored - review it and save", "warning")

    # ══════════════════════════════════════════════════════
    # EXPORT
    # ══════════════════════════════════════════════════════
    def export_now(self) -> None:
        if not self.folder:
            self._status("No batch loaded", "warning")
            return
        if self.read_only:
            self._status("This batch is open read-only", "warning")
            return
        if not self._commit_current():
            return
        report = self._flush()
        if not report.ok:
            return
        full, _map, _warn = self.store.build_json()
        self.write_report(quiet=True)
        self.audit.record("export", detail="%d roi_key(s)" % full["roi_count"])
        self._status(
            "Exported %d roi_key(s), %d polygon(s), %d no_roi  ·  %s"
            % (full["roi_count"], full["total_polygons"], full["no_roi_count"],
               report.names()), "good")
        if self.settings.get("api_push_enabled"):
            self.push_to_endpoint()

    def export_formats(self) -> None:
        if not self.folder:
            self._status("No batch loaded", "warning")
            return
        if not self._commit_current():
            return
        dialog = ExportDialog(self, self.store.rows, self.folder)
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            report = exporters.run_exports(dialog.chosen_formats,
                                           dialog.chosen_rows, self.folder)
        finally:
            QApplication.restoreOverrideCursor()
        self.audit.record("export_formats",
                          detail=", ".join(dialog.chosen_formats))
        if report.ok:
            self._status("Wrote %s" % ", ".join(
                os.path.basename(p) for p in report.written), "good")
        else:
            self._status(report.summary(), "danger")

    def import_annotations(self) -> None:
        if not self.folder:
            self._status("Open a batch folder first", "warning")
            return
        # The import reloads the image on screen from the merged rows, so
        # what is drawn on it now goes to disk first rather than vanishing.
        if not self._commit_current():
            return
        dialog = ImportDialog(self, self.folder)
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = importers.import_and_merge(dialog.paths, dialog.strategy)
        finally:
            QApplication.restoreOverrideCursor()

        if not result.ok:
            self._status(result.summary(), "danger")
            return
        if dialog.replace_all:
            self.store.rows = list(result.rows)
        else:
            merged = importers.merge_rows(
                [self.store.rows, result.rows],
                ["this batch", "imported"], dialog.strategy)
            self.store.rows = merged.rows
            result.conflicts.extend(merged.conflicts)

        self.saved_shapes = {}
        self.no_roi_saved = set()
        self.comments = {}
        self._pending_norm = {}
        self._rebuild_from_store()
        self._load_image(self.index)
        self._refresh_filmstrip()
        self._update_stats()
        self.audit.record("import", detail="%d row(s) from %d file(s)"
                          % (len(result.rows), len(dialog.paths)))

        message = result.summary() + "  ·  nothing written yet, export to save"
        if result.conflicts:
            names = ", ".join(c["image_name"] for c in result.conflicts[:3])
            message += "  ·  conflicts: %s" % names
        self._status(message, "warning" if result.conflicts else "good")

    def push_to_endpoint(self, manual: bool = False) -> None:
        url = str(self.settings.get("api_push_url", "")).strip()
        ok, why = push.validate_url(url)
        if not ok:
            if manual:
                self._status("Cannot send: %s - set one in Settings → Delivery"
                             % why, "warning")
            return
        full, roi_map, _warn = self.store.build_json()
        payload = push.build_payload(full, roi_map, self.folder)
        self._status("Sending to the endpoint…", "info")
        self._pool.start(_PushTask(
            url, payload, str(self.settings.get("api_push_header", "")),
            int(self.settings.get("api_push_timeout", 15)),
            self._push_signals))

    @Slot(object)
    def _push_finished(self, result) -> None:
        self.audit.record("push", detail=result.summary())
        self._status(result.summary(), "good" if result.ok else "danger")

    def write_report(self, quiet: bool = False) -> None:
        if not self.folder:
            self._status("No batch loaded", "warning")
            return
        session = {"elapsed": self.timer.elapsed_text(),
                   "images": self.timer.images_done,
                   "per_hour": self.timer.per_hour(),
                   "shapes": self.timer.shapes_drawn}
        report, _stats = reporting.write_report(
            self.store.rows, self.folder, self.image_files, session)
        reporting.write_coverage_json(self.store.rows, self.folder,
                                      self.image_files)
        if not report.ok:
            self._status(report.summary(), "danger")
            return
        if quiet:
            return
        path = report.written[0]
        self._status("Report written to %s" % os.path.basename(path), "good")
        self._open_path(path)

    def _open_path(self, path) -> None:
        """Open a file with whatever the desktop uses.  Never raises."""
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as exc:
            self._status("Could not open %s (%s)"
                         % (os.path.basename(str(path)), exc), "warning")

    # ══════════════════════════════════════════════════════
    # WINDOWS
    # ══════════════════════════════════════════════════════
    def _statuses(self):
        out = {}
        for name in self.image_files:
            if self.saved_shapes.get(name):
                out[name] = "roi"
            elif name in self.no_roi_saved:
                out[name] = "no_roi"
            else:
                out[name] = "todo"
        return out

    def open_review(self) -> None:
        if not self.image_files:
            self._status("No batch loaded", "warning")
            return
        if not self._commit_current():
            return
        dialog = ReviewDialog(self, self.folder, self.image_files,
                              self._statuses(), self.theme)
        dialog.jumpRequested.connect(self.go_to_name)
        dialog.exec()

    def open_dashboard(self) -> None:
        if not self.folder:
            self._status("No batch loaded", "warning")
            return
        session = {"elapsed": self.timer.elapsed_text(),
                   "images": self.timer.images_done,
                   "per_hour": self.timer.per_hour()}
        dialog = DashboardDialog(self, self.store.rows, self.folder,
                                 self.image_files, session, self.theme)
        dialog.reportRequested.connect(self.write_report)
        dialog.exec()

    def open_history(self) -> None:
        if not self.folder:
            self._status("No batch loaded", "warning")
            return
        HistoryDialog(self, self.audit.tail(500)).exec()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self, self.settings)
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        values = dialog.result_values()
        self.settings.update(values)
        self.theme = resolve_theme(self.settings.get("theme", "dark"), self.app, tool="roi")
        self._rebind_shortcuts()
        self._apply_theme()
        self._apply_settings()
        self._refresh_side()
        if self.host is not None:
            self.host.request_theme(self.settings.get("theme", "dark"))
        if self.folder:
            self._flush()
        self._status("Settings saved", "good")

    def _rebind_shortcuts(self) -> None:
        self.keys = sc.resolve(self.settings.get("shortcuts", {}))
        for action_id, action in self.actions_by_id.items():
            action.setShortcuts([QKeySequence(k) for k in
                                 keymap.sequences("roi", action_id, self.keys.get(action_id, ""))])
        for tool, button in self.tool_buttons.items():
            for action_id, mapped in TOOL_ACTIONS.items():
                if mapped == tool:
                    key = self.keys.get(action_id, "")
                    button.setToolTip("%s%s" % (self.act(action_id).text(),
                                                ("   [%s]" % key) if key else ""))

    def open_palette(self) -> None:
        enabled = {action_id: action.isEnabled()
                   for action_id, action in self.actions_by_id.items()}
        dialog = CommandPalette(self, self.keys, enabled, self.theme)
        dialog.commandChosen.connect(self._run_command)
        dialog.exec()

    def _run_command(self, action_id) -> None:
        action = self.actions_by_id.get(action_id)
        if action is not None and action.isEnabled():
            QTimer.singleShot(0, action.trigger)

    def open_shortcuts(self) -> None:
        ShortcutSheet(self, self.keys, self.theme).exec()

    def open_about(self) -> None:
        from PySide6.QtCore import qVersion
        extras = [("Version", APP_VERSION),
                  ("Qt", qVersion()),
                  ("Spreadsheet support", "yes" if HAS_XLSX else "openpyxl missing"),
                  ("Image support", "Pillow %s" % getattr(
                      __import__("PIL"), "__version__", "?")
                   if imaging.HAS_PIL else "Pillow missing"),
                  ("Settings file", str(self.settings.path))]
        AboutDialog(self, extras, self.theme).exec()

    def show_welcome(self, force: bool = False) -> None:
        if not force and self.settings.get("first_run_done"):
            return
        dialog = WelcomeDialog(self, self.theme)
        dialog.exec()
        self.settings.set("first_run_done", not dialog.show_again())

    # ══════════════════════════════════════════════════════
    # REFRESH
    # ══════════════════════════════════════════════════════
    def _refresh_filmstrip(self) -> None:
        self.filmstrip.set_batch(self.folder, self.image_files,
                                 self._statuses())
        self.filmstrip.set_index(self.index)

    def _update_stats(self) -> None:
        total = len(self.image_files)
        known = set(self.image_files)
        drawn = len([n for n in known if self.saved_shapes.get(n)])
        no_roi = len([n for n in self.no_roi_saved if n in known])
        remaining = max(0, total - drawn - no_roi)
        self.stats_panel.set_values(total, drawn, no_roi, remaining)
        self.filmstrip.set_statuses(self._statuses())
        if total:
            self.progress_label.setText("Image %d of %d" % (self.index + 1, total))
        else:
            self.progress_label.setText("")
        self._refresh_state_chip()

    def _sync_actions(self) -> None:
        has_batch = bool(self.image_files)
        has_image = self.canvas.has_image()
        has_selection = bool(self.canvas.selection)
        writable = has_image and not self.read_only

        for action_id in ("reload_folder", "close_folder", "export_now",
                          "export_formats", "import_annotations",
                          "review_mode", "dashboard", "open_report",
                          "history_log", "push_api"):
            self.act(action_id).setEnabled(has_batch)
        for action_id in ("next_image", "prev_image", "first_image",
                          "last_image"):
            self.act(action_id).setEnabled(has_batch)
        for action_id in ("save_roi", "mark_no_roi", "clear_all",
                          "copy_previous", "select_all", "batch_apply",
                          "batch_no_roi", "restore_backup",
                          "save_project_settings"):
            self.act(action_id).setEnabled(writable)
        for action_id in ("delete_roi", "duplicate_roi", "lock_roi",
                          "zoom_selection"):
            self.act(action_id).setEnabled(writable and has_selection)
        for action_id in ("align_left", "align_hcentre", "align_right",
                          "align_top", "align_vcentre", "align_bottom",
                          "equalise"):
            self.act(action_id).setEnabled(writable
                                           and len(self.canvas.selection) >= 2)
        for action_id in ("distribute_h", "distribute_v"):
            self.act(action_id).setEnabled(writable
                                           and len(self.canvas.selection) >= 3)
        for action_id in ("zoom_in", "zoom_out", "zoom_fit", "zoom_actual",
                          "zoom_all_rois"):
            self.act(action_id).setEnabled(has_image)
        self.act("undo").setEnabled(self.history.can_undo)
        self.act("redo").setEnabled(self.history.can_redo)
        self.act("redo_alt").setEnabled(self.history.can_redo)

        self.act("undo").setToolTip("Undo %s" % (self.history.undo_label() or ""))
        self.act("redo").setToolTip("Redo %s" % (self.history.redo_label() or ""))
        for action_id, button in (list(self.quick_buttons.items())
                                  + list(getattr(self, "strip_buttons", {}).items())):
            action = self.act(action_id)
            button.setEnabled(action.isEnabled())
            key = self.keys.get(action_id, "")
            tip = action.toolTip() or action.text()
            button.setToolTip("%s%s" % (tip, ("   [%s]" % key) if key else ""))

        self.save_button.setEnabled(writable)
        self.no_roi_button.setEnabled(writable)
        self.export_button.setEnabled(has_batch and not self.read_only)
        for tool, button in self.tool_buttons.items():
            button.setEnabled(has_image and (tool == T_PAN or not self.read_only))

    # ══════════════════════════════════════════════════════
    # WINDOW LIFECYCLE
    # ══════════════════════════════════════════════════════
    def _restore_geometry(self) -> None:
        from PySide6.QtCore import QByteArray
        try:
            raw = self.settings.get("window_geometry", "")
            if raw:
                self.restoreGeometry(QByteArray.fromBase64(raw.encode("ascii")))
            else:
                screen = self.app.primaryScreen().availableGeometry()
                self.resize(min(1600, int(screen.width() * 0.86)),
                            min(1000, int(screen.height() * 0.86)))
        except Exception:
            self.resize(1280, 820)

    def _save_geometry(self) -> None:
        try:
            raw = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.settings.set("window_geometry", raw)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════
    # SUITE
    # ══════════════════════════════════════════════════════
    def tool_apply_theme(self, name) -> None:
        """The shell (or the theme toggle, standalone) sets the theme."""
        self.settings.set("theme", name)
        self.theme = resolve_theme(name, self.app, tool="roi")
        self._apply_theme()
        self._refresh_side()

    def tool_activated(self) -> None:
        self.canvas.setFocus()
        self.show_welcome()

    def tool_deactivating(self) -> bool:
        """Leaving for Home or another tool: put the work on disk first."""
        try:
            committed = self._commit_current()
        except Exception as exc:
            self._report_exception(exc)
            committed = False
        if not committed or self.dirty:
            answer = messages.ask(
                self, "Unsaved work",
                "The last write did not complete, so this image is not on "
                "disk.\n\nLeave anyway? The draft is kept and offered back "
                "when you return.", default=False)
            if not answer:
                return False
        self._write_draft()
        return True

    def tool_open(self, folder) -> None:
        self.open_folder(folder)

    # ══════════════════════════════════════════════════════
    # SESSION
    # ══════════════════════════════════════════════════════
    def session_state(self) -> dict:
        """Where this tool has got to, for the shell to write down.

        Asked on a timer and again on the way out, so it has to be cheap and
        it has to work at any moment - including before a batch is open."""
        return {"folder": self.folder,
                "last_image": self.current_name() or "",
                "active_seconds": self.timer.active_seconds,
                "view": {"side_collapsed": bool(self.side.is_collapsed())},
                "tool": {}}

    def restore_session(self, state) -> None:
        """Pick up a batch where it was left.

        The folder itself has already been opened through the usual path, so
        its lock and its read-only handling are the ones that always run;
        this only has to put the view back."""
        state = state or {}
        view = state.get("view") or {}
        try:
            if bool(view.get("side_collapsed")) != bool(self.side.is_collapsed()):
                self.side.toggle()
        except Exception:
            pass
        name = str(state.get("last_image") or "")
        # An image that has since been deleted or renamed is not an error:
        # the batch still opens, on the first image, as it always did.
        if name and name in self.image_files:
            try:
                self.go_to_name(name)
            except Exception:
                pass

    def tool_close(self) -> bool:
        """The application is closing.  False keeps it open."""
        try:
            committed = self._commit_current()
        except Exception as exc:
            self._report_exception(exc)
            committed = False

        if not committed or self.dirty:
            answer = messages.ask(
                self, "Unsaved work",
                "The last write did not complete, so this image is not on "
                "disk.\n\nClose anyway and lose it?", default=False)
            if not answer:
                return False

        try:
            self._write_draft()
            self.audit.record("close", detail=self.timer.summary())
            if self.host is None:
                self._save_geometry()
            self.settings.save()
            self.filmstrip.shutdown()
            self.lock.release()
        except Exception:
            pass
        return True

    def closeEvent(self, event):
        if self.tool_close():
            event.accept()
        else:
            event.ignore()
