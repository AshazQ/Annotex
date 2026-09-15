"""LabelImg Master's window: layout, actions, and the flow between image and disk.

The shape of it follows ROI Studio on purpose - header with tool docks, the
canvas over a film strip, a side column, a status bar - so moving between the
two tools costs nothing.  The flow to disk follows ROI Studio too: leaving an
image commits whatever is on screen, and a write that fails stops the move
instead of silently dropping the work.
"""

from __future__ import annotations

import json
import os
import traceback

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QDesktopServices, QKeySequence,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup,
                               QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QKeySequenceEdit, QLabel, QLineEdit, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSplitter, QStatusBar, QTextEdit,
                               QVBoxLayout, QWidget)
from PySide6.QtGui import QImageReader

from annotex.core import clipboard
from annotex.core.history import History
from annotex.core.io_safe import FolderLock, folder_is_writable, read_json, write_text_atomic
from annotex.core.session import DraftStore
from annotex.ui import icons
from annotex.ui.dialogs.ai_dialog import AiModelDialog
from annotex.ui.dialogs.common import Dialog
from annotex.ui.dialogs.palette_dialog import CommandPalette, ShortcutSheet
from annotex.ui.filmstrip import FilmStrip
from annotex.ui.palette import install_theme, resolve_theme, toggled_setting
from annotex.ui.widgets import MiniMap, StatsPanel, divider, section_label

from ..config import (APP_NAME, APP_TAGLINE, APP_VERSION, BACKUP_DIR,
                      DRAFT_NAME, FORMAT_EXT, FORMAT_LABELS, FORMAT_VOC,
                      FORMAT_YOLO, FORMATS, HOTKEY_DIGITS, LOCK_NAME,
                      MAX_UNDO_STEPS, PROJECT_KEYS, PROJECT_SETTINGS_NAME,
                      SHIFT_DIGIT_SYMBOLS)
from ..core import exporters, importers
from ..core import report as reporting
from ..core.annotations import (AnnotationFolder, apply_boxes, copy_to_copies,
                                move_to_deleted, scan_images)
from ..core.class_store import (ClassStore, color_for_name,
                                rename_class_in_annotations)
from ..core.model import Box, boxes_match, find_duplicates
from . import shortcuts as sc
from .canvas import T_AI, T_BOX, T_PAN, T_SELECT, BoxCanvas
from .dialogs.batch_dialog import APPLY_BACKGROUND, APPLY_BOXES, BatchApplyDialog
from .dialogs.class_manager import ClassManagerDialog
from .dialogs.label_dialog import LabelDialog
from .dialogs.review_dialog import DashboardDialog, ReviewDialog
from .dialogs.settings_dialog import SettingsDialog
from .dialogs.transfer_dialog import CocoExportDialog, ImportDialog, ImportReviewDialog
from .dialogs.welcome_dialog import AboutDialog, WelcomeDialog
from .panels import ActiveClassChip, BoxListPanel, ClassPalette

TOOL_ACTIONS = {"tool_select": T_SELECT, "tool_box": T_BOX, "tool_pan": T_PAN,
                "tool_ai": T_AI}
TEXT_INPUTS = (QLineEdit, QAbstractSpinBox, QPlainTextEdit, QTextEdit, QKeySequenceEdit)


def qt_probe(path):
    """(height, width, depth) exactly as LabelImg has always recorded it:
    decoded by Qt with EXIF orientation applied, depth from isGrayscale()."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        return None
    return (image.height(), image.width(), 1 if image.isGrayscale() else 3)


def _box_state(box):
    return {"label": box.label, "x0": box.x0, "y0": box.y0, "x1": box.x1,
            "y1": box.y1, "difficult": box.difficult, "locked": box.locked,
            "visible": box.visible}


class LabelImgWindow(QMainWindow):

    def __init__(self, settings, app, host=None, class_store=None):
        super().__init__()
        self.settings = settings
        self.app = app
        self.host = host
        if host is not None:
            settings.data["theme"] = host.theme_setting
        self.theme = resolve_theme(settings.get("theme", "dark"), app, tool="labelimg")

        # ── state ─────────────────────────────────────────
        self.folder = ""
        self.image_files = []
        self.index = 0
        self.image_shape = None
        self.current_pixmap = None
        self.io = None
        self.save_dir = ""
        self.index_map = {}              # rel -> Summary | None
        self.saved = {}                  # rel -> [Box] as on disk
        self.saved_verified = {}
        self.force_write = set()
        self.verified = False
        self.dirty = False
        self.read_only = False
        self._loading = False
        self._status_level = "info"
        self._batch = {}                 # per-folder overrides, this session only

        self.class_store = class_store or ClassStore.load_or_create()
        wanted = settings.get("class_project", "")
        if wanted and wanted in self.class_store.projects:
            self.class_store.set_active_project(wanted)
        self.current_class = settings.get("last_class", "") or None
        self.class_hotkeys = {}
        self.hotkey_order = []
        self.fmt = settings.get("label_format", FORMAT_VOC)
        if self.fmt not in FORMATS:
            self.fmt = FORMAT_VOC

        self.lock = FolderLock(LOCK_NAME, APP_VERSION)
        self.draft = DraftStore(DRAFT_NAME, serializer=_box_state)
        self.history = History(MAX_UNDO_STEPS)
        self.assistant = None            # the AI helper, built on first use
        self._ai_offered = False         # the model chooser is offered once

        self.setWindowTitle("%s %s" % (APP_NAME, APP_VERSION))
        self.setMinimumSize(1120, 700)
        self.setWindowIcon(icons.app_icon(self.theme["accent"], self.theme["appBg"], "box"))

        self._build_actions()
        self._build_ui()
        self._build_menus()
        self._apply_theme()
        self._apply_settings()
        self.refresh_class_ui()

        self._autosave = QTimer(self)
        self._autosave.timeout.connect(self._write_draft)
        self._autosave.start(max(5, int(settings.get("autosave_seconds", 20))) * 1000)

        if host is None:
            self._restore_geometry()
        else:
            self.menuBar().setNativeMenuBar(False)
        self.app.installEventFilter(self)
        self._install_clipboard_bridge()
        self._sync_actions()
        self._status("Open a folder of images to begin  ·  Ctrl+U", "info")

    # ══════════════════════════════════════════════════════
    # PREFERENCES
    # ══════════════════════════════════════════════════════
    def pref(self, key, default=None):
        """A setting, with this batch's .labelimg.json taking precedence."""
        if key in self._batch:
            return self._batch[key]
        return self.settings.get(key, default)

    def set_pref(self, key, value) -> None:
        if key in self._batch:
            self._batch[key] = value
        else:
            self.settings.set(key, value)

    # ══════════════════════════════════════════════════════
    # ACTIONS
    # ══════════════════════════════════════════════════════
    def _build_actions(self) -> None:
        self.keys = sc.resolve(self.settings.get("shortcuts", {}))
        self.actions_by_id = {}
        handlers = {
            "open_folder": self.choose_folder,
            "change_save_dir": self.choose_save_dir,
            "reload_folder": self.reload_folder,
            "close_folder": self.close_folder,
            "class_manager": self.open_class_manager,
            "cycle_format": self.cycle_format,
            "next_image": self.next_image,
            "prev_image": self.prev_image,
            "first_image": lambda: self.go_to_index(0),
            "last_image": lambda: self.go_to_index(len(self.image_files) - 1),
            "next_todo": self.next_todo,
            "cancel": lambda: self.canvas.cancel(),
            "undo": self.undo,
            "redo": self.redo,
            "redo_alt": self.redo,
            "delete_box": self.delete_boxes,
            "duplicate_box": lambda: self.canvas.duplicate_selected(),
            "select_all": lambda: self.canvas.select_all(),
            "clear_all": self.clear_all,
            "edit_label": self.edit_label,
            "toggle_difficult": self.toggle_difficult,
            "lock_box": self.toggle_lock,
            "hide_box": self.toggle_hidden,
            "copy_boxes": lambda: self.copy_boxes(cut=False),
            "cut_boxes": lambda: self.copy_boxes(cut=True),
            "paste_boxes": self.paste_boxes,
            "copy_previous": lambda: self.copy_previous(replace=True),
            "append_previous": lambda: self.copy_previous(replace=False),
            "apply_to_images": lambda: self.batch_apply(APPLY_BOXES),
            "background_many": lambda: self.batch_apply(APPLY_BACKGROUND),
            "find_class": lambda: self.palette.focus_search(),
            "next_class": lambda: self.cycle_class(1),
            "prev_class": lambda: self.cycle_class(-1),
            "toggle_sticky": lambda: self._toggle_pref("sticky_class", "toggle_sticky",
                                                       "Keep the last-used class"),
            "toggle_skip_dialog": lambda: self._toggle_pref("skip_label_dialog",
                                                            "toggle_skip_dialog",
                                                            "Skip the label dialog"),
            "save": self.save_current,
            "accept_frame": self.accept_frame,
            "mark_background": self.mark_background,
            "verify_image": self.toggle_verified,
            "toggle_auto_advance": lambda: self._toggle_pref(
                "auto_advance_on_save", "toggle_auto_advance", "Auto-advance after saving"),
            "import_annotations": self.import_annotations,
            "export_coco": self.export_coco,
            "restore_backup": self.restore_from_backup,
            "save_project_settings": self.save_project_settings,
            "delete_image": self.delete_image,
            "copy_image": self.copy_image,
            "zoom_in": lambda: self.canvas.zoom_in(),
            "zoom_out": lambda: self.canvas.zoom_out(),
            "zoom_fit": lambda: self.canvas.fit_to_view(),
            "zoom_width": lambda: self.canvas.fit_to_width(),
            "zoom_actual": lambda: self.canvas.set_zoom(1.0),
            "zoom_selection": lambda: self.canvas.zoom_to_selection(),
            "zoom_all": lambda: self.canvas.zoom_to_all(),
            "brighten": lambda: self.set_brightness(self.canvas.brightness + 10),
            "darken": lambda: self.set_brightness(self.canvas.brightness - 10),
            "reset_brightness": lambda: self.set_brightness(50),
            "toggle_labels": lambda: self._toggle_pref("show_labels", "toggle_labels",
                                                       "Class names on boxes"),
            "toggle_square": lambda: self._toggle_pref("draw_square", "toggle_square",
                                                       "Always draw squares"),
            "toggle_side": self.toggle_side,
            "toggle_theme": self.toggle_theme,
            "toggle_minimap": lambda: self._toggle_pref("show_minimap", "toggle_minimap",
                                                        "Minimap"),
            "toggle_crosshair": lambda: self._toggle_pref("show_crosshair",
                                                          "toggle_crosshair", "Crosshair"),
            "review_mode": self.open_review,
            "dashboard": self.open_dashboard,
            "open_report": self.write_report,
            "ai_model": self.open_ai_model,
            "settings": self.open_settings,
            "shortcuts_sheet": self.open_shortcuts,
            "command_palette": self.open_palette,
            "welcome": lambda: self.show_welcome(force=True),
            "about": self.open_about,
        }
        for action_id, label, _default, _cat, _icon, desc in sc.ACTIONS:
            action = QAction(label, self)
            action.setObjectName(action_id)
            if desc:
                action.setToolTip(desc)
                action.setStatusTip(desc)
            key = self.keys.get(action_id, "")
            if key:
                action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            handler = handlers.get(action_id)
            if handler is not None:
                action.triggered.connect(self._guard(handler))
            if action_id in TOOL_ACTIONS or action_id in sc.CHECKABLE:
                action.setCheckable(True)
            self.actions_by_id[action_id] = action
            self.addAction(action)
        for action_id, tool in TOOL_ACTIONS.items():
            self.actions_by_id[action_id].triggered.connect(
                lambda _c=False, t=tool: self.set_tool(t))

        for key, delta in (("Left", (-1, 0)), ("Right", (1, 0)), ("Up", (0, -1)),
                           ("Down", (0, 1)), ("Shift+Left", (-10, 0)),
                           ("Shift+Right", (10, 0)), ("Shift+Up", (0, -10)),
                           ("Shift+Down", (0, 10))):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda d=delta: self.canvas.nudge_selected(*d))

    def _guard(self, handler):
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
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(10)
        root.addWidget(self._build_header())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        root.addWidget(self.splitter, 1)

        canvas_column = QWidget()
        canvas_layout = QVBoxLayout(canvas_column)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(8)
        self.canvas_frame = QFrame()
        self.canvas_frame.setObjectName("Card")
        frame_layout = QVBoxLayout(self.canvas_frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)
        self.canvas = BoxCanvas()
        self.canvas.set_colour_provider(self.colour_for)
        frame_layout.addWidget(self.canvas)
        canvas_layout.addWidget(self.canvas_frame, 1)
        self.filmstrip = FilmStrip()
        self.filmstrip.empty_text = "No folder open"
        canvas_layout.addWidget(self.filmstrip)
        self.splitter.addWidget(canvas_column)

        self.side = self._build_side()
        self.splitter.addWidget(self.side)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([1000, 340])

        self._build_statusbar()
        self._wire()

    def _tool_button(self, action_id, checkable=False) -> QPushButton:
        action = self.act(action_id)
        button = QPushButton()
        button.setObjectName("Tool")
        button.setCheckable(checkable)
        button.setFixedSize(34, 32)
        button.setIconSize(QSize(19, 19))
        key = self.keys.get(action_id, "")
        button.setToolTip("%s%s" % (action.text(), ("   [%s]" % key) if key else ""))
        return button

    def _dock(self) -> tuple:
        frame = QFrame()
        frame.setObjectName("Toolbar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(3)
        return frame, layout

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(10)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title_label = QLabel(APP_TAGLINE)
        self.title_label.setObjectName("Title")
        self.folder_label = QLabel("No folder open")
        self.folder_label.setObjectName("Subtitle")
        titles.addWidget(self.title_label)
        titles.addWidget(self.folder_label)
        layout.addLayout(titles)
        self.image_chip = QLabel("")
        self.image_chip.setObjectName("Subtitle")
        layout.addWidget(self.image_chip)
        layout.addStretch(1)

        self.tool_bar, tools = self._dock()
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_buttons = {}
        for action_id, tool in TOOL_ACTIONS.items():
            button = self._tool_button(action_id, checkable=True)
            button.clicked.connect(lambda _c=False, t=tool: self.set_tool(t))
            self.tool_group.addButton(button)
            self.tool_buttons[tool] = button
            tools.addWidget(button)
        layout.addWidget(self.tool_bar)

        self.quick_bar, quick = self._dock()
        self.quick_buttons = {}
        for action_id in ("undo", "redo", "delete_box", "duplicate_box",
                          "append_previous", "clear_all"):
            button = self._tool_button(action_id)
            button.clicked.connect(self.act(action_id).trigger)
            self.quick_buttons[action_id] = button
            quick.addWidget(button)
        layout.addWidget(self.quick_bar)

        self.window_bar, window_row = self._dock()
        self.window_buttons = {}
        for action_id in ("class_manager", "review_mode", "dashboard", "settings",
                          "shortcuts_sheet"):
            button = self._tool_button(action_id)
            button.clicked.connect(self.act(action_id).trigger)
            self.window_buttons[action_id] = button
            window_row.addWidget(button)
        layout.addWidget(self.window_bar)
        return header

    def _build_side(self) -> QWidget:
        """Lists scroll; progress and the save buttons stay pinned below them,
        so the actions are always one click away however tall the lists get."""
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(440)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(14, 14, 14, 6)
        layout.setSpacing(12)

        self.minimap = MiniMap()
        layout.addWidget(self.minimap)
        self.active_chip = ActiveClassChip()
        layout.addWidget(self.active_chip)
        self.palette = ClassPalette()
        layout.addWidget(self.palette, 3)
        self.box_panel = BoxListPanel()
        layout.addWidget(self.box_panel, 2)
        scroll.setWidget(holder)

        footer = QWidget()
        foot = QVBoxLayout(footer)
        foot.setContentsMargins(14, 6, 14, 14)
        foot.setSpacing(10)
        foot.addWidget(divider())
        self.stats_panel = StatsPanel(fields=(
            ("total", "Images", "title", None),
            ("labelled", "Labelled", "good", "good"),
            ("background", "Background", "sub", "info"),
            ("todo", "Remaining", "accent", "border")))
        self.stats_panel.set_tooltip("labelled", "TAI - images with an annotation file "
                                                 "that has boxes")
        self.stats_panel.set_tooltip("background", "BAI - annotated images with zero "
                                                   "boxes (background)")
        foot.addWidget(self.stats_panel)

        format_row = QHBoxLayout()
        format_row.setSpacing(8)
        format_row.addWidget(section_label("Save as"))
        self.format_box = QComboBox()
        for fmt in FORMATS:
            self.format_box.addItem(FORMAT_LABELS[fmt], fmt)
        self.format_box.currentIndexChanged.connect(
            lambda _i: self.set_format(self.format_box.currentData(), from_user=True))
        format_row.addWidget(self.format_box, 1)
        foot.addLayout(format_row)
        self.save_dir_label = QLabel("")
        self.save_dir_label.setObjectName("Subtitle")
        foot.addWidget(self.save_dir_label)

        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self.act("save").trigger)
        foot.addWidget(self.save_button)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.accept_button = QPushButton("Accept  ⏎")
        self.accept_button.setToolTip("Save this frame as it is and go to the next [Enter]")
        self.accept_button.clicked.connect(self.act("accept_frame").trigger)
        self.background_button = QPushButton("Background")
        self.background_button.setToolTip("Nothing to label here - save it empty [N]")
        self.background_button.clicked.connect(self.act("mark_background").trigger)
        self.verify_button = QPushButton("Verified")
        self.verify_button.setCheckable(True)
        self.verify_button.setToolTip("Mark this image as checked [Space]")
        self.verify_button.clicked.connect(self.act("verify_image").trigger)
        for button in (self.accept_button, self.background_button, self.verify_button):
            buttons.addWidget(button)
        foot.addLayout(buttons)

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        outer.addWidget(footer)
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
        self.brightness_label = QLabel("")
        self.brightness_label.setObjectName("Mono")
        bar.addPermanentWidget(self.brightness_label)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("Mono")
        bar.addPermanentWidget(self.zoom_label)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("Subtitle")
        self.progress_label.setToolTip("Position in the folder  ·  TAI = images with an "
                                       "annotation file  ·  BAI = annotated images with "
                                       "zero boxes (background)")
        bar.addPermanentWidget(self.progress_label)

    def _wire(self) -> None:
        canvas = self.canvas
        canvas.boxesChanged.connect(self._on_boxes_changed)
        canvas.selectionChanged.connect(self._on_selection_changed)
        canvas.statusMessage.connect(self._status)
        canvas.zoomChanged.connect(lambda pct: self.zoom_label.setText("%d%%" % round(pct)))
        canvas.cursorMoved.connect(lambda x, y: self.coord_label.setText("x %d  y %d" % (x, y)))
        canvas.viewChanged.connect(self._refresh_minimap)
        canvas.boxDrawn.connect(self._guard_arg(self.on_box_drawn))
        canvas.editLabelRequested.connect(lambda _i: self.edit_label())
        canvas.contextMenuRequested.connect(self._show_context_menu)
        canvas.toolFinished.connect(self.set_tool)
        canvas.aiPromptChanged.connect(self._guard(self.refresh_ai_preview))
        canvas.aiAccepted.connect(self._guard(self.accept_ai_preview))

        self.filmstrip.imagePicked.connect(self.go_to_index)
        self.minimap.navigateTo.connect(canvas.center_on)
        self.palette.classChosen.connect(self._on_palette_class)
        self.palette.manageRequested.connect(self.open_class_manager)

        panel = self.box_panel
        panel.selectionRequested.connect(self._select_from_panel)
        panel.visibilityToggled.connect(lambda idx, v: canvas.set_visible(idx, v))
        panel.lockToggled.connect(lambda idx, v: canvas.set_locked(idx, v))
        panel.difficultToggled.connect(lambda idx, v: canvas.set_difficult(idx, v))
        panel.editRequested.connect(self.edit_label)
        panel.duplicateRequested.connect(lambda: canvas.duplicate_selected())
        panel.deleteRequested.connect(self.delete_boxes)

    def _guard_arg(self, handler):
        def run(value):
            try:
                handler(value)
            except Exception as exc:
                self._report_exception(exc)
        return run

    def _build_menus(self) -> None:
        bar = self.menuBar()

        batch = bar.addMenu("&Batch")
        for action_id in ("open_folder", "change_save_dir", "reload_folder", "close_folder"):
            batch.addAction(self.act(action_id))
        batch.addSeparator()
        self.recent_menu = batch.addMenu("Recent folders")
        self._rebuild_recent()
        batch.addSeparator()
        batch.addAction(self.act("class_manager"))
        formats = batch.addMenu("Save format")
        self.format_group = QActionGroup(self)
        self.format_actions = {}
        for fmt in FORMATS:
            action = QAction(FORMAT_LABELS[fmt], self)
            action.setCheckable(True)
            action.triggered.connect(lambda _c=False, f=fmt: self.set_format(f, from_user=True))
            self.format_group.addAction(action)
            self.format_actions[fmt] = action
            formats.addAction(action)
        formats.addSeparator()
        formats.addAction(self.act("cycle_format"))
        batch.addSeparator()
        for action_id in ("import_annotations", "export_coco"):
            batch.addAction(self.act(action_id))
        batch.addSeparator()
        for action_id in ("restore_backup", "save_project_settings"):
            batch.addAction(self.act(action_id))
        batch.addSeparator()
        for action_id in ("delete_image", "copy_image"):
            batch.addAction(self.act(action_id))
        batch.addSeparator()
        quit_action = QAction("Quit", self)
        if self.host is not None:
            home_action = QAction("Back to Home\tCtrl+Shift+H", self)
            home_action.triggered.connect(self.host.go_home)
            batch.addAction(home_action)
            quit_action.triggered.connect(self.host.quit)
        else:
            quit_action.setShortcut(QKeySequence.StandardKey.Quit)
            quit_action.triggered.connect(self.close)
        batch.addAction(quit_action)

        edit = bar.addMenu("&Edit")
        for group in (("undo", "redo"),
                      ("delete_box", "duplicate_box", "select_all", "clear_all"),
                      ("edit_label", "toggle_difficult", "lock_box", "hide_box"),
                      ("copy_boxes", "cut_boxes", "paste_boxes"),
                      ("copy_previous", "append_previous", "apply_to_images",
                       "background_many")):
            for action_id in group:
                edit.addAction(self.act(action_id))
            edit.addSeparator()

        tools = bar.addMenu("&Tools")
        for action_id in list(TOOL_ACTIONS) + ["cancel"]:
            tools.addAction(self.act(action_id))

        classes = bar.addMenu("&Classes")
        for action_id in ("find_class", "next_class", "prev_class"):
            classes.addAction(self.act(action_id))
        classes.addSeparator()
        for action_id in ("toggle_sticky", "toggle_skip_dialog"):
            classes.addAction(self.act(action_id))

        save = bar.addMenu("&Save")
        for action_id in ("save", "accept_frame", "mark_background", "verify_image"):
            save.addAction(self.act(action_id))
        save.addSeparator()
        save.addAction(self.act("toggle_auto_advance"))

        view = bar.addMenu("&View")
        for group in (("zoom_in", "zoom_out", "zoom_fit", "zoom_width", "zoom_actual",
                       "zoom_selection", "zoom_all"),
                      ("brighten", "darken", "reset_brightness"),
                      ("toggle_labels", "toggle_square", "toggle_minimap",
                       "toggle_crosshair", "toggle_side", "toggle_theme")):
            for action_id in group:
                view.addAction(self.act(action_id))
            view.addSeparator()

        go = bar.addMenu("&Go")
        for action_id in ("next_image", "prev_image", "first_image", "last_image", "next_todo"):
            go.addAction(self.act(action_id))

        window = bar.addMenu("&Window")
        for action_id in ("review_mode", "dashboard", "open_report"):
            window.addAction(self.act(action_id))
        window.addSeparator()
        window.addAction(self.act("ai_model"))
        window.addSeparator()
        for action_id in ("settings", "command_palette", "shortcuts_sheet"):
            window.addAction(self.act(action_id))
        window.addSeparator()
        for action_id in ("welcome", "about"):
            window.addAction(self.act(action_id))

    def _rebuild_recent(self) -> None:
        self.recent_menu.clear()
        recent = [f for f in (self.settings.get("recent_folders") or []) if os.path.isdir(f)]
        if not recent:
            empty = QAction("Nothing yet", self)
            empty.setEnabled(False)
            self.recent_menu.addAction(empty)
            return
        for folder in recent:
            action = QAction(folder, self)
            action.triggered.connect(lambda _c=False, f=folder: self.open_folder(f))
            self.recent_menu.addAction(action)
        self.recent_menu.addSeparator()
        clear = QAction("Clear the list", self)
        clear.triggered.connect(lambda: (self.settings.set("recent_folders", []),
                                         self._rebuild_recent()))
        self.recent_menu.addAction(clear)

    # ══════════════════════════════════════════════════════
    # KEYS THE REGISTRY CANNOT HOLD
    # ══════════════════════════════════════════════════════
    def eventFilter(self, obj, event):
        kind = event.type()
        if kind not in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride):
            return False
        if not self.isVisible() or QApplication.activeModalWidget() is not None \
                or QApplication.activePopupWidget() is not None:
            return False
        focus = QApplication.focusWidget()
        if kind == QEvent.Type.ShortcutOverride:
            # Ctrl+C in the class search must copy the text, not the boxes.
            if sc.steals_from_text_field(event, focus, TEXT_INPUTS + (QComboBox,)):
                event.accept()
                return True
            return False
        if focus is None or obj is not focus:
            return False
        if focus is not self and not self.isAncestorOf(focus):
            return False
        if isinstance(focus, TEXT_INPUTS) or (isinstance(focus, QComboBox)
                                              and focus.isEditable()):
            return False
        try:
            return self.handle_key(event)
        except Exception as exc:
            self._report_exception(exc)
            return True

    def handle_key(self, event) -> bool:
        """Enter accepts the frame; 1-0 and Shift+1-0 pick classes."""
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                       | Qt.KeyboardModifier.MetaModifier) or self.canvas.is_drawing():
                return False
            # With a proposal on screen, Enter keeps that - accepting the whole
            # frame and moving on would throw it away.
            if self.canvas.tool == T_AI and self.canvas.ai_preview is not None:
                self.accept_ai_preview()
                return True
            self.accept_frame()
            return True
        index = self._hotkey_index(event)
        if index is None:
            return False
        self.assign_class_by_index(index)
        return True

    @staticmethod
    def _hotkey_index(event):
        mods = event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                   | Qt.KeyboardModifier.MetaModifier):
            return None
        shifted = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        key = event.key()
        digit = None
        if Qt.Key.Key_0.value <= int(key.value if hasattr(key, "value") else key) \
                <= Qt.Key.Key_9.value:
            digit = chr(int(key.value if hasattr(key, "value") else key))
        elif shifted:
            digit = SHIFT_DIGIT_SYMBOLS.get(event.text())
        if digit is None:
            return None
        base = HOTKEY_DIGITS.index(digit)
        return base + (len(HOTKEY_DIGITS) if shifted else 0)

    # ══════════════════════════════════════════════════════
    # THEME & SETTINGS
    # ══════════════════════════════════════════════════════
    def _apply_theme(self) -> None:
        icons.clear_cache()
        install_theme(self, self.app, self.theme, self.host is not None)
        theme = self.theme
        self.setWindowIcon(icons.app_icon(theme["accent"], theme["appBg"], "box"))
        for widget in (self.canvas, self.filmstrip, self.minimap, self.stats_panel,
                       self.box_panel, self.palette, self.active_chip):
            widget.set_theme(theme)
        for action_id, tool in TOOL_ACTIONS.items():
            self.tool_buttons[tool].setIcon(icons.dual_icon(
                sc.BY_ID[action_id][4], theme["text"], theme["onAccent"], 19))
        for action_id, button in self.quick_buttons.items():
            colour = theme["danger"] if action_id in ("delete_box", "clear_all") else theme["text"]
            button.setIcon(icons.icon(sc.BY_ID[action_id][4], colour, 19))
        for action_id, button in self.window_buttons.items():
            name = sc.BY_ID[action_id][4]
            if action_id == "toggle_theme":
                name = "sun" if theme["name"] == "dark" else "moon"
            button.setIcon(icons.icon(name, theme["text"], 19))
        for action_id, action in self.actions_by_id.items():
            action.setIcon(icons.icon(sc.BY_ID[action_id][4], theme["text"], 16))
        self._paint_status()
        self._refresh_state_chip()
        self.refresh_class_ui() if hasattr(self, "palette") and self.class_hotkeys else None
        for widget in self.findChildren(QWidget) + [self]:
            try:
                widget.style().unpolish(widget)
                widget.style().polish(widget)
            except Exception:
                continue

    def _apply_settings(self) -> None:
        self.canvas.set_options(
            show_crosshair=bool(self.pref("show_crosshair", True)),
            show_coordinates=bool(self.pref("show_coordinates", True)),
            snap_to_edges=bool(self.pref("snap_to_edges", True)),
            snap_to_boxes=bool(self.pref("snap_to_boxes", True)),
            fill_opacity=int(self.pref("box_opacity", 18)),
            line_width=int(self.pref("box_line_width", 2)),
            show_labels=bool(self.pref("show_labels", True)),
            draw_square=bool(self.pref("draw_square", False)))
        self.minimap.setVisible(bool(self.pref("show_minimap", True)))
        self.coord_label.setVisible(bool(self.pref("show_coordinates", True)))
        for action_id, key in (("toggle_sticky", "sticky_class"),
                               ("toggle_skip_dialog", "skip_label_dialog"),
                               ("toggle_auto_advance", "auto_advance_on_save"),
                               ("toggle_labels", "show_labels"),
                               ("toggle_square", "draw_square"),
                               ("toggle_minimap", "show_minimap"),
                               ("toggle_crosshair", "show_crosshair")):
            self.act(action_id).setChecked(bool(self.pref(key)))
        self.save_button.setText("Save and next" if self.pref("auto_advance_on_save")
                                 else "Save")
        self._sync_format_widgets()
        if hasattr(self, "_autosave"):
            interval = max(5, int(self.settings.get("autosave_seconds", 20))) * 1000
            if self._autosave.interval() != interval:
                self._autosave.setInterval(interval)

    def _toggle_pref(self, key, action_id, label) -> None:
        value = not bool(self.pref(key))
        self.set_pref(key, value)
        self._apply_settings()
        self._status("%s: %s" % (label, "on" if value else "off"), "info")

    def tool_apply_theme(self, name) -> None:
        self.settings.set("theme", name)
        self.theme = resolve_theme(name, self.app, tool="labelimg")
        self._apply_theme()
        self._refresh_side()

    def toggle_theme(self) -> None:
        name = toggled_setting(self.theme)
        if self.host is not None:
            self.host.request_theme(name)
        else:
            self.tool_apply_theme(name)
        self._status("Switched to the %s theme" % name, "info")

    def toggle_side(self) -> None:
        self.side.setVisible(not self.side.isVisible())

    def set_brightness(self, value) -> None:
        self.canvas.set_brightness(value)
        level = self.canvas.brightness
        self.brightness_label.setText("" if level == 50 else "brightness %d%%" % (level * 2))

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
        if not hasattr(self, "state_chip"):
            return
        rel = self.current_name()
        theme = self.theme
        if self.read_only:
            text, colour = "read-only", theme["warn"]
        elif self.dirty:
            text, colour = "● write failed", theme["danger"]
        elif rel is None:
            text, colour = "", theme["sub"]
        elif self._matches_saved(rel):
            if self.canvas.boxes:
                text, colour = "● saved", theme["good"]
            else:
                text, colour = "○ background", theme["sub"]
        elif rel not in self.saved and not self.canvas.boxes and not self.verified:
            text, colour = "· not started", theme["sub"]
        else:
            text, colour = "● unsaved", theme["accent"]
        if self.verified and rel is not None:
            text += "  ✓ verified"
        self.state_chip.setText(text)
        self.state_chip.setStyleSheet("color: %s;" % colour)

    # ══════════════════════════════════════════════════════
    # CLASSES
    # ══════════════════════════════════════════════════════
    def project(self):
        return self.class_store.active_project()

    def colour_for(self, label) -> str:
        entry = self.project().by_name(label) if label else None
        return entry.color if entry is not None else color_for_name(label or "?")

    def refresh_class_ui(self) -> None:
        project = self.project()
        active = project.active_classes()
        self.class_hotkeys = {}
        self.hotkey_order = [entry.name for entry in active]
        for position, entry in enumerate(active[:2 * len(HOTKEY_DIGITS)]):
            digit = HOTKEY_DIGITS[position % len(HOTKEY_DIGITS)]
            self.class_hotkeys[entry.name] = digit if position < len(HOTKEY_DIGITS) \
                else "Shift+" + digit
        deprecated = len(project) - len(active)
        summary = "%s · %d" % (project.name, len(active))
        if deprecated:
            summary += " (+%d old)" % deprecated
        self.palette.set_entries(active, self.class_hotkeys, summary)
        if self.current_class and project.by_name(self.current_class) is None:
            self.current_class = None
        if self.current_class:
            self.palette.select_name(self.current_class)
        self._refresh_active_chip()
        self.canvas.update()
        self._refresh_side()

    def _refresh_active_chip(self) -> None:
        name = self.current_class
        self.active_chip.set_class(name, self.colour_for(name) if name else "",
                                   self.class_hotkeys.get(name, "") if name else "")

    def register_class(self, name):
        project = self.project()
        entry = project.by_name(name)
        if entry is not None:
            return entry
        entry = project.merge_name(name)
        self.class_store.save()
        self.refresh_class_ui()
        self._status("Added class \"%s\" (ID %d) to project \"%s\""
                     % (entry.name, entry.id, project.name), "good")
        return entry

    def ensure_classes(self, labels) -> None:
        project = self.project()
        missing = [label for label in labels if label and project.by_name(label) is None]
        if not missing:
            return
        for label in missing:
            project.merge_name(label)
        self.class_store.save()
        self.refresh_class_ui()

    def set_current_class(self, name, announce=True) -> None:
        if not name:
            return
        self.current_class = name
        self.settings.set("last_class", name)
        self.palette.select_name(name)
        self._refresh_active_chip()
        if announce:
            key = self.class_hotkeys.get(name)
            self._status("Active class: %s%s" % (name, "   [%s]" % key if key else ""), "info")

    def apply_class_choice(self, name) -> None:
        selected = self.canvas.selected_indices()
        if selected and not self.read_only:
            changed = self.canvas.relabel(selected, name)
            if changed:
                self._status("%d box(es) changed to %s" % (changed, name), "good")
        self.set_current_class(name, announce=not selected)

    def assign_class_by_index(self, index) -> None:
        if not (0 <= index < len(self.hotkey_order)):
            self._status("No class is bound to that key", "warning")
            return
        self.apply_class_choice(self.hotkey_order[index])

    def cycle_class(self, step) -> None:
        if not self.hotkey_order:
            return
        if self.current_class in self.hotkey_order:
            position = (self.hotkey_order.index(self.current_class) + step) % len(self.hotkey_order)
        else:
            position = 0
        self.apply_class_choice(self.hotkey_order[position])

    def _on_palette_class(self, name) -> None:
        self.apply_class_choice(name)
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def ask_label(self, current="", title="Class for the new box"):
        label = LabelDialog.ask(self, self.project().active_classes(), current, title)
        if label:
            self.register_class(label)
        return label

    def on_box_drawn(self, box) -> None:
        if self.pref("skip_label_dialog", True) and self.current_class:
            label = self.current_class
        else:
            label = self.ask_label(self.current_class or "")
            if not label:
                self._status("Box discarded - no class chosen", "info")
                self.canvas.update()
                return
        box.label = label
        if self.canvas.add_box(box):
            if self.pref("sticky_class", True):
                self.set_current_class(label, announce=False)
            key = self.class_hotkeys.get(label)
            self._status("Box added as %s%s" % (label, "   [%s]" % key if key else ""), "good")

    def edit_label(self) -> None:
        selected = self.canvas.selected_indices()
        if not selected:
            self._status("Select a box first", "warning")
            return
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        current = self.canvas.boxes[selected[0]].label
        label = self.ask_label(current, "Change class")
        if label:
            self.canvas.relabel(selected, label)
            if self.pref("sticky_class", True):
                self.set_current_class(label, announce=False)

    def open_class_manager(self) -> None:
        if not self._commit_current():
            return
        dialog = ClassManagerDialog(self, self.class_store, self.annotation_dirs())
        accepted = dialog.exec() == Dialog.DialogCode.Accepted
        if accepted:
            for old, new in dialog.renames + dialog.reassignments:
                self.apply_class_rename(old, new)
            self.class_store.save()
            self.settings.set("class_project", self.class_store.active_project_name)
        else:
            self.class_store = ClassStore.load_or_create(self.class_store.path)
        self.refresh_class_ui()
        if self.fmt == FORMAT_YOLO:
            self.regenerate_classes_txt()
        if self.io is not None:
            self.index_map = self.io.build_index(self.image_files)
            self._refresh_filmstrip()
            self._update_stats()

    def annotation_dirs(self):
        if self.io is None:
            return []
        dirs = []
        for rel in self.image_files:
            for directory in self.io.search_dirs(rel):
                if directory not in dirs:
                    dirs.append(directory)
        return dirs

    def apply_class_rename(self, old, new) -> None:
        if not old or old == new:
            return
        indices = [i for i, box in enumerate(self.canvas.boxes) if box.label == old]
        if indices:
            self.canvas.relabel(indices, new)
        for boxes in self.saved.values():
            for box in boxes:
                if box.label == old:
                    box.label = new
        changed = rename_class_in_annotations(self.annotation_dirs(), old, new)
        if self.io is not None:
            for rel in self.image_files:
                self.io.accept_external(rel) if rel in self.io.stamps else None
        if changed:
            self._status("Renamed \"%s\" to \"%s\" in %d annotation file(s)"
                         % (old, new, len(changed)), "good")

    def regenerate_classes_txt(self) -> None:
        if self.io is None:
            return
        for directory in {self.io.target_dir(rel) for rel in self.image_files[:1]} | (
                {self.save_dir} if self.save_dir else set()):
            if directory and os.path.isdir(directory):
                try:
                    self.class_store.export_txt(os.path.join(directory, "classes.txt"))
                except Exception:
                    pass

    # ══════════════════════════════════════════════════════
    # FORMAT
    # ══════════════════════════════════════════════════════
    def set_format(self, fmt, from_user=False) -> None:
        if fmt not in FORMATS:
            return
        changed = fmt != self.fmt
        self.fmt = fmt
        if from_user:
            self.set_pref("label_format", fmt)
            if changed:
                self._status("New saves are written as %s" % FORMAT_LABELS[fmt], "info")
        self._sync_format_widgets()
        self._refresh_chip()

    def cycle_format(self) -> None:
        position = (FORMATS.index(self.fmt) + 1) % len(FORMATS)
        self.set_format(FORMATS[position], from_user=True)

    def _sync_format_widgets(self) -> None:
        if not hasattr(self, "format_box"):
            return
        self.format_box.blockSignals(True)
        self.format_box.setCurrentIndex(max(0, self.format_box.findData(self.fmt)))
        self.format_box.blockSignals(False)
        if hasattr(self, "format_actions"):
            self.format_actions[self.fmt].setChecked(True)
        where = os.path.basename(self.save_dir) if self.save_dir else "beside the images"
        self.save_dir_label.setText("Annotations: %s   ·   Ctrl+R to change" % where)
        self.save_dir_label.setToolTip(self.save_dir or "Saved next to each image")

    # ══════════════════════════════════════════════════════
    # FOLDERS
    # ══════════════════════════════════════════════════════
    def choose_folder(self) -> None:
        start = self.folder or (self.settings.get("recent_folders") or [""])[0]
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder of images",
                                                  start or os.path.expanduser("~"))
        if folder:
            self.open_folder(folder)

    def open_folder(self, folder) -> None:
        folder = os.path.abspath(str(folder))
        if self.folder and not self._commit_current():
            return
        if not os.path.isdir(folder):
            self._status("That folder no longer exists", "danger")
            return

        writable, why = folder_is_writable(folder)
        if not writable:
            answer = QMessageBox.question(
                self, "Read-only folder",
                "This folder cannot be written to:\n%s\n\nOpen it read-only? You "
                "can look at the annotations but not change them." % why)
            if answer != QMessageBox.StandardButton.Yes:
                return

        lock_note = ""
        if writable:
            acquired, message = self.lock.acquire(folder)
            if not acquired:
                answer = QMessageBox.question(
                    self, "Folder in use",
                    "%s\n\nTwo sessions saving the same annotations can overwrite "
                    "each other's work.\nOpen it anyway?" % message)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                self.lock.acquire(folder, force=True)
                lock_note = "lock overridden - close the other session"
            elif message:
                lock_note = message
        elif self.lock.held:
            self.lock.release()

        self.read_only = not writable
        self.canvas.read_only = self.read_only
        self.folder = folder
        self._batch = {}
        project_note = self._load_project_settings(folder)
        save_dir = self._batch.get("save_dir", "")
        self.save_dir = (os.path.normpath(os.path.join(folder, save_dir))
                         if save_dir else "")
        if self.save_dir and not os.path.isdir(self.save_dir):
            project_note += "  ·  the batch's annotation folder is missing"
            self.save_dir = ""
        self.fmt = self.pref("label_format", self.fmt)
        self._apply_settings()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.io = AnnotationFolder(folder, self.save_dir)
            self.image_files = scan_images(folder)
            self.index_map = self.io.build_index(self.image_files)
        finally:
            QApplication.restoreOverrideCursor()
        self.saved, self.saved_verified, self.force_write = {}, {}, set()
        self.dirty = False
        self.index = 0

        self.draft.bind(folder)
        self.folder_label.setText(folder)
        self.settings.push_recent(folder)
        self._rebuild_recent()

        self._warn_about_stem_collisions()
        annotated = sum(1 for s in self.index_map.values() if s is not None)
        if not self.image_files:
            self._status("No supported images in this folder", "warning")
        else:
            message = "%d image(s), %d already annotated" % (len(self.image_files), annotated)
            extras = [n for n in (lock_note, project_note.strip(" ·")) if n]
            if extras:
                message += "  ·  " + "  ·  ".join(extras)
            self._status(message, "warning" if lock_note else "good")
        self._refresh_filmstrip()
        self._load_image(0)
        self._offer_draft()
        self._sync_format_widgets()
        self._sync_actions()

    def _warn_about_stem_collisions(self) -> None:
        """One shared annotation folder plus two images called the same thing
        in different sub-folders means the second would overwrite the first.
        Say so now rather than after a day's work."""
        if self.io is None or not self.save_dir:
            return
        clashes = self.io.stem_collisions(self.image_files)
        if not clashes:
            return
        examples = []
        for _stem, names in sorted(clashes.items())[:3]:
            examples.append("  ·  ".join(names[:3]))
        QMessageBox.warning(
            self, "Two images would share one annotation file",
            "%d image name(s) appear more than once in this batch's sub-folders, "
            "and the annotations all go into one folder, so they would overwrite "
            "each other:\n\n%s\n\nSave the annotations beside the images "
            "(Ctrl+R, then choose the image folder) or rename the images."
            % (len(clashes), "\n".join(examples)))
        self._status("%d image name(s) repeat across sub-folders - annotations in "
                     "one folder would overwrite each other" % len(clashes), "danger")

    def reload_folder(self) -> None:
        if not self.folder:
            return
        if not self._commit_current():
            return
        rel = self.current_name()
        folder, self.folder = self.folder, ""
        self.open_folder(folder)
        if rel in self.image_files:
            self.go_to_name(rel)

    def close_folder(self) -> None:
        if not self.folder:
            return
        if not self._commit_current():
            return
        self.lock.release()
        self.folder = ""
        self.io = None
        self.image_files = []
        self.index_map, self.saved, self.saved_verified = {}, {}, {}
        self.canvas.load_image(None)
        self.canvas.verified = False
        self.verified = False
        self.filmstrip.clear()
        self.folder_label.setText("No folder open")
        self.image_chip.setText("")
        self._batch = {}
        self._apply_settings()
        self._refresh_side()
        self._update_stats()
        self._sync_actions()
        self._status("Folder closed", "info")

    def choose_save_dir(self) -> None:
        if not self.folder:
            self._status("Open a folder first", "warning")
            return
        if not self._commit_current():
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Where should annotations be saved? (pick the image folder for "
                  "'beside the images')", self.save_dir or self.folder)
        if not folder:
            return
        self.set_save_dir(folder)

    def set_save_dir(self, folder) -> None:
        folder = os.path.abspath(folder)
        self.save_dir = "" if folder == self.folder else folder
        self.io = AnnotationFolder(self.folder, self.save_dir)
        self.index_map = self.io.build_index(self.image_files)
        self.saved, self.saved_verified, self.force_write = {}, {}, set()
        self._warn_about_stem_collisions()
        if "save_dir" in self._batch:
            self._batch["save_dir"] = os.path.relpath(self.save_dir, self.folder) \
                if self.save_dir else ""
        self._sync_format_widgets()
        self._refresh_filmstrip()
        self._load_image(self.index)
        self._status("Annotations are now saved %s" % (
            "in %s" % self.save_dir if self.save_dir else "beside the images"), "good")

    # ══════════════════════════════════════════════════════
    # IMAGES
    # ══════════════════════════════════════════════════════
    def current_name(self):
        if self.image_files and 0 <= self.index < len(self.image_files):
            return self.image_files[self.index]
        return None

    def _load_image(self, index) -> None:
        self._loading = True
        notes = []
        try:
            if not self.image_files:
                self.canvas.load_image(None)
                self.canvas.verified = False
                self.current_pixmap, self.image_shape = None, None
                self.verified = False
                self.image_chip.setText("")
                self.minimap.set_image(None, (0, 0))
                return
            self.index = max(0, min(int(index), len(self.image_files) - 1))
            rel = self.image_files[self.index]
            path = self.io.image_path(rel)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                reader = QImageReader(path)
                reader.setAutoTransform(True)
                image = reader.read()
            finally:
                QApplication.restoreOverrideCursor()
            if image.isNull():
                self._status("Cannot read %s - skipping it" % rel, "warning")
                self.image_files.pop(self.index)
                self.index_map.pop(rel, None)
                self._refresh_filmstrip()
                if self.image_files:
                    QTimer.singleShot(0, lambda: self._load_image(self.index))
                else:
                    self.canvas.load_image(None)
                return

            pixmap = QPixmap.fromImage(image)
            self.current_pixmap = pixmap
            self.image_shape = (image.height(), image.width(),
                                1 if image.isGrayscale() else 3)
            result = self.io.read(rel, self.image_shape)
            notes.extend(result.notes)
            if result.found:
                self.saved[rel] = [b.copy() for b in result.boxes]
                self.saved_verified[rel] = result.verified
                if result.adjusted:
                    self.force_write.add(rel)
                if result.fmt and result.fmt != self.fmt:
                    self.set_format(result.fmt)
                    notes.append("this image is saved as %s" % FORMAT_LABELS[result.fmt])
            else:
                self.saved.pop(rel, None)
                self.saved_verified.pop(rel, None)
            self.verified = result.verified if result.found else False
            self.canvas.load_image(pixmap, result.boxes)
            self.canvas.verified = self.verified
            self.history.reset(self.canvas.snapshot())
            self.minimap.set_image(pixmap, (image.width(), image.height()))
            self.filmstrip.set_index(self.index)
            self._refresh_chip()
        finally:
            self._loading = False
        if self.canvas.tool == T_AI and not self.enter_ai_tool():
            self.set_tool(T_SELECT)
        self._refresh_side()
        self._update_stats()
        self._refresh_minimap()
        self._sync_actions()
        self.canvas.setFocus()
        if notes:
            self._status("  ·  ".join(notes), "warning")

    def _refresh_chip(self) -> None:
        rel = self.current_name()
        if rel is None or self.image_shape is None:
            self.image_chip.setText("")
            return
        parts = [os.path.basename(rel), "%d x %d" % (self.image_shape[1], self.image_shape[0]),
                 {FORMAT_VOC: "VOC", FORMAT_YOLO: "YOLO"}.get(self.fmt, "CreateML")]
        if self.save_dir:
            parts.append("→ %s" % os.path.basename(self.save_dir))
        self.image_chip.setText("  ·  ".join(parts))

    def go_to_index(self, index) -> None:
        if not self.image_files:
            return
        index = max(0, min(int(index), len(self.image_files) - 1))
        if index == self.index and self.canvas.has_image():
            return
        if not self._commit_current():
            return
        self._load_image(index)

    def go_to_name(self, rel) -> None:
        if rel in self.image_files:
            self.go_to_index(self.image_files.index(rel))

    def next_image(self) -> None:
        if not self.image_files:
            self._status("No folder open", "warning")
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

    def next_todo(self) -> None:
        if not self.image_files:
            return
        if not self._commit_current():
            return
        for offset in range(1, len(self.image_files) + 1):
            candidate = (self.index + offset) % len(self.image_files)
            if self.index_map.get(self.image_files[candidate]) is None \
                    and candidate != self.index:
                self._load_image(candidate)
                return
        self._status("Every image has an annotation", "good")

    def _advance(self) -> None:
        if self.index < len(self.image_files) - 1:
            self._load_image(self.index + 1)
        else:
            self._status("That was the last image - the folder is done", "good")
            self._update_stats()

    # ══════════════════════════════════════════════════════
    # CANVAS FEEDBACK
    # ══════════════════════════════════════════════════════
    def _on_boxes_changed(self, label) -> None:
        if self._loading:
            return
        self.history.push(str(label or "Edit"), self.canvas.snapshot())
        self._refresh_side()
        self._sync_actions()

    def _on_selection_changed(self) -> None:
        self._refresh_side()
        self._sync_actions()

    def _select_from_panel(self, indices) -> None:
        self.canvas.selection = set(indices)
        self.canvas.update()
        self.canvas.selectionChanged.emit()

    def _refresh_side(self) -> None:
        if not hasattr(self, "box_panel"):
            return
        self.box_panel.refresh(self.canvas.boxes, self.canvas.selection, self.colour_for)
        self.verify_button.blockSignals(True)
        self.verify_button.setChecked(self.verified)
        self.verify_button.blockSignals(False)
        self._refresh_state_chip()
        self._refresh_minimap()

    def _refresh_minimap(self) -> None:
        if self.minimap.isVisible() and self.canvas.has_image():
            self.minimap.set_view(self.canvas.visible_image_rect(),
                                  [b for b in self.canvas.boxes if b.visible])

    def set_tool(self, tool) -> None:
        if tool == T_AI and self.canvas.tool != T_AI and not self.enter_ai_tool():
            tool = T_SELECT
        self.canvas.set_tool(tool)
        button = self.tool_buttons.get(tool)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        for action_id, mapped in TOOL_ACTIONS.items():
            self.act(action_id).setChecked(mapped == tool)
        hints = {T_SELECT: "Select - drag a box to move it, drag a handle to resize, "
                           "double-click to change its class",
                 T_BOX: "Box - drag out a new box; hold Ctrl for a square",
                 T_PAN: "Pan - drag the image (middle-drag works with any tool)",
                 T_AI: "AI select - click the object; right-click excludes, drag a "
                       "rough box to narrow it down, Enter keeps the proposal"}
        self._status(hints.get(tool, ""), "info")

    def _show_context_menu(self, global_pos) -> None:
        if not self.canvas.has_image():
            return
        menu = QMenu(self)
        if not self.canvas.selection:
            for action_id in ("paste_boxes", "copy_boxes", "select_all"):
                menu.addAction(self.act(action_id))
            menu.exec(global_pos)
            return
        for action_id in ("edit_label", "toggle_difficult", "lock_box", "hide_box"):
            menu.addAction(self.act(action_id))
        classes = menu.addMenu("Set class")
        for entry in self.project().active_classes():
            key = self.class_hotkeys.get(entry.name, "")
            action = classes.addAction("%s%s" % (entry.name, "\t%s" % key if key else ""))
            action.triggered.connect(lambda _c=False, n=entry.name: self.apply_class_choice(n))
        menu.addSeparator()
        for action_id in ("copy_boxes", "cut_boxes", "paste_boxes"):
            menu.addAction(self.act(action_id))
        menu.addSeparator()
        for action_id in ("duplicate_box", "delete_box", "zoom_selection"):
            menu.addAction(self.act(action_id))
        menu.exec(global_pos)

    # ══════════════════════════════════════════════════════
    # EDITING
    # ══════════════════════════════════════════════════════
    def undo(self) -> None:
        result = self.history.undo()
        if result is None:
            self._status("Nothing to undo", "info")
            return
        label, snapshot = result
        self.canvas.set_boxes(snapshot)
        self._refresh_side()
        self._sync_actions()
        self._status("Undid: %s" % label, "info")

    def redo(self) -> None:
        result = self.history.redo()
        if result is None:
            self._status("Nothing to redo", "info")
            return
        label, snapshot = result
        self.canvas.set_boxes(snapshot)
        self._refresh_side()
        self._sync_actions()
        self._status("Redid: %s" % label, "info")

    def delete_boxes(self) -> None:
        removed = self.canvas.delete_selected()
        if removed:
            self._status("%d box(es) deleted - Ctrl+Z brings them back" % removed, "good")

    def clear_all(self) -> None:
        if not self.canvas.boxes:
            self._status("Nothing to clear", "info")
            return
        if self.pref("confirm_clear_all", True):
            answer = QMessageBox.question(
                self, "Clear every box",
                "Remove all %d box(es) from this image?\n\nCtrl+Z brings them back."
                % len(self.canvas.boxes))
            if answer != QMessageBox.StandardButton.Yes:
                return
        count = self.canvas.clear_all()
        self._status("%d box(es) cleared - Ctrl+Z brings them back" % count, "good")

    def toggle_difficult(self) -> None:
        boxes = self.canvas.selected_boxes()
        if not boxes:
            self._status("Select a box first", "warning")
            return
        self.canvas.set_difficult(self.canvas.selected_indices(),
                                  not all(b.difficult for b in boxes))

    def toggle_lock(self) -> None:
        boxes = self.canvas.selected_boxes()
        if not boxes:
            self._status("Select a box first", "warning")
            return
        self.canvas.set_locked(self.canvas.selected_indices(), not all(b.locked for b in boxes))

    def toggle_hidden(self) -> None:
        indices = self.canvas.selected_indices()
        if not indices:
            self._status("Select a box first", "warning")
            return
        # Anything hidden in the selection comes back; otherwise hide it all.
        show = any(not self.canvas.boxes[i].visible for i in indices)
        self.canvas.set_visible(indices, show)
        if show:
            self._status("%d box(es) shown again" % len(indices), "good")
        else:
            self._status("%d box(es) hidden - they are still saved.  The eye in the "
                         "box list brings them back" % len(indices), "info")

    def _boxes_for(self, rel):
        """The saved boxes of any image, reading it if this session has not."""
        if rel == self.current_name():
            return [b.copy() for b in self.canvas.boxes], self.verified
        if rel in self.saved:
            return [b.copy() for b in self.saved[rel]], self.saved_verified.get(rel, False)
        fmt, path = self.io.find(rel)
        if not fmt:
            return [], False
        shape = qt_probe(self.io.image_path(rel))
        if not shape:
            return [], False
        result = self.io.read_path(path, fmt, rel, shape)
        return result.boxes, result.verified

    def copy_previous(self, replace=True) -> None:
        if not self.canvas.has_image():
            return
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        if self.index <= 0:
            self._status("There is no previous image", "warning")
            return
        previous = self.image_files[self.index - 1]
        boxes, _verified = self._boxes_for(previous)
        width, height = self.image_shape[1], self.image_shape[0]
        usable = [clean for clean, _msg in (b.validated(width, height) for b in boxes)
                  if clean is not None]
        if not usable:
            self._status("%s has no boxes to copy" % previous, "warning")
            return
        if replace:
            self.canvas.boxes = []
        added = self.canvas.add_boxes(usable, "Copy boxes from previous image"
                                      if replace else "Add boxes from previous image")
        self._status("%s %d box(es) from %s" % ("Copied" if replace else "Added",
                                                 added, previous), "good")

    # ══════════════════════════════════════════════════════
    # CLIPBOARD  (copy boxes here, paste them on another image)
    # ══════════════════════════════════════════════════════
    def _install_clipboard_bridge(self) -> None:
        """Mirror the annotation clipboard onto the system one, so a copy
        made here can be pasted in LabelImg Shapes - or in this tool after a
        restart."""
        def read_text():
            board = QApplication.clipboard()
            return board.text() if board is not None else ""

        def write_text(text):
            board = QApplication.clipboard()
            if board is not None:
                board.setText(text)

        try:
            clipboard.set_bridge(read_text, write_text)
            board = QApplication.clipboard()
            if board is not None:
                # Something copied in another window shows up at once, and
                # the cached answer never goes stale.
                board.dataChanged.connect(self._on_clipboard_changed)
        except Exception:
            pass

    def _on_clipboard_changed(self) -> None:
        try:
            clipboard.invalidate()
            self._sync_actions()
        except Exception:
            pass

    @staticmethod
    def _to_payload_item(box) -> dict:
        return {"label": box.label, "difficult": bool(box.difficult),
                "x0": float(box.x0), "y0": float(box.y0),
                "x1": float(box.x1), "y1": float(box.y1),
                "bounds": [float(box.x0), float(box.y0), float(box.x1), float(box.y1)]}

    @staticmethod
    def _from_payload_item(item):
        """A Box out of anything on the clipboard - including a polygon or a
        circle copied in LabelImg Shapes, which arrives as its bounds."""
        try:
            bounds = [float(v) for v in item["bounds"]]
        except Exception:
            return None
        label = str(item.get("label", "") or "")
        return Box(label, bounds[0], bounds[1], bounds[2], bounds[3],
                   bool(item.get("difficult", False)))

    def copy_boxes(self, cut=False) -> None:
        """Copy the selection - or everything, when nothing is selected."""
        if not self.canvas.has_image():
            self._status("No image open", "warning")
            return
        boxes = self.canvas.selected_boxes()
        whole = False
        if not boxes:
            boxes, whole = list(self.canvas.boxes), True
        if not boxes:
            self._status("There is nothing on this image to copy", "warning")
            return
        if cut and self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        width = self.image_shape[1] if self.image_shape else 0
        height = self.image_shape[0] if self.image_shape else 0
        clipboard.copy(clipboard.KIND_BOXES,
                       [self._to_payload_item(b) for b in boxes], (width, height),
                       source=os.path.basename(self.current_name() or ""))
        removed = 0
        if cut:
            if whole:
                removed = self.canvas.clear_all()
            else:
                removed = self.canvas.delete_selected()
        self._sync_actions()
        self._status("%s %d box(es)%s  ·  Ctrl+V pastes them onto another image"
                     % ("Cut" if cut else "Copied", removed if cut else len(boxes),
                        " (the whole image - nothing was selected)"
                        if whole and not cut else ""), "good")

    def paste_boxes(self) -> None:
        if not self._writable_image():
            return
        payload = clipboard.content()
        if not payload or not len(payload):
            self._status("Nothing has been copied yet - select boxes and press Ctrl+C",
                         "warning")
            return
        width = self.image_shape[1] if self.image_shape else 0
        height = self.image_shape[0] if self.image_shape else 0
        items, fx, fy = payload.scale_to((width, height))
        boxes = [box for box in (self._from_payload_item(i) for i in items)
                 if box is not None]
        if not boxes:
            self._status("What was copied cannot become boxes", "warning")
            return
        self.ensure_classes(b.label for b in boxes if b.label)
        added = self.canvas.add_boxes(boxes, "Paste boxes")
        if not added:
            self._status("Nothing could be pasted - the boxes fall outside this image",
                         "warning")
            return
        notes = []
        if abs(fx - 1.0) > 1e-6 or abs(fy - 1.0) > 1e-6:
            notes.append("scaled to this image")
        if added < len(boxes):
            notes.append("%d did not fit" % (len(boxes) - added))
        if payload.kind != clipboard.KIND_BOXES:
            notes.append("from LabelImg Shapes, as bounding boxes")
        self._status("Pasted %d box(es)%s" % (added, "  ·  " + "; ".join(notes)
                                              if notes else ""),
                     "warning" if len(notes) > 1 else "good")

    # ══════════════════════════════════════════════════════
    # AI  (Segment Anything)
    # ══════════════════════════════════════════════════════
    def ai(self):
        """The assistant, built the first time it is actually wanted."""
        if self.assistant is None:
            from annotex.ui.ai_assist import SamAssistant
            self.assistant = SamAssistant(self.settings, self)
            self.assistant.stateChanged.connect(self._status)
            self.assistant.ready.connect(lambda _t: self._on_ai_ready())
            self.assistant.failed.connect(self._on_ai_failed)
        return self.assistant

    def _on_ai_ready(self) -> None:
        self.canvas.set_ai_preview(self.canvas.ai_preview, busy=False)
        if self.canvas.has_ai_prompt():
            self.refresh_ai_preview()

    def _on_ai_failed(self, message) -> None:
        self.canvas.set_ai_preview(None, busy=False)
        self._status(str(message).replace("\n", "  "), "danger")

    def enter_ai_tool(self) -> bool:
        """Turn the AI tool on for the image on screen.  False means it could
        not be turned on, and the caller should fall back to Select."""
        if not self.canvas.has_image():
            self._status("Open an image first", "warning")
            return False
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return False
        assistant = self.ai()
        ok, why = assistant.usable()
        if not ok:
            self._status(str(why).replace("\n", "  ")
                         + "   ·   Settings → AI chooses one", "warning")
            # Offer the chooser once; after that the status line is enough,
            # so pressing the key again is not a dialog every time.
            if not self._ai_offered:
                self._ai_offered = True
                answer = QMessageBox.question(
                    self, "AI select",
                    "%s\n\nChoose a model now?" % why,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes)
                if answer == QMessageBox.StandardButton.Yes:
                    self.open_ai_model()
                    ok, _why = assistant.usable()
            if not ok:
                return False
        rel = self.current_name()
        if rel is None:
            return False
        image = self.current_pixmap.toImage() if self.current_pixmap is not None else None
        if image is None or image.isNull():
            self._status("This image cannot be handed to the model", "warning")
            return False
        assistant.prepare(assistant.token_for(self.io.image_path(rel)), image)
        self.canvas.set_ai_preview(None, busy=assistant.is_busy())
        return True

    def refresh_ai_preview(self) -> None:
        canvas = self.canvas
        if canvas.tool != T_AI:
            return
        points, box = canvas.ai_prompt()
        if not points and box is None:
            canvas.set_ai_preview(None)
            return
        assistant = self.ai()
        canvas.set_ai_preview(canvas.ai_preview, busy=True)
        QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        try:
            result, why = assistant.predict(points, box)
        finally:
            QApplication.restoreOverrideCursor()
        if result is None:
            canvas.set_ai_preview(None, busy=assistant.is_busy())
            self._status(str(why).replace("\n", "  "), "warning")
            return
        found = assistant.box_from(result)
        if not found:
            canvas.set_ai_preview(None)
            self._status("The AI found nothing there - click the object itself, or "
                         "right-click to exclude part of it", "warning")
            return
        preview = Box(self.current_class or "", *found)
        clean, _messages = preview.rounded().validated(self.image_shape[1],
                                                       self.image_shape[0])
        canvas.set_ai_preview(clean if clean is not None else preview.rounded())
        self._status("AI proposal %s  ·  Enter keeps it, more clicks refine it, "
                     "Esc drops it" % preview.describe(), "info")

    def accept_ai_preview(self) -> None:
        canvas = self.canvas
        preview = canvas.ai_preview
        if preview is None:
            self._status("Click the object first", "warning")
            return
        if self.pref("skip_label_dialog", True) and self.current_class:
            label = self.current_class
        else:
            label = self.ask_label(self.current_class or "", "Class for the AI box")
            if not label:
                self._status("Proposal dropped - no class chosen", "info")
                return
        box = preview.copy()
        box.label = label
        if not canvas.add_box(box, "AI box"):
            return
        if self.pref("sticky_class", True):
            self.set_current_class(label, announce=False)
        if not self.pref("ai_keep_prompt", False):
            canvas.clear_ai(quiet=True)
        self._status("AI box added as %s  ·  click the next object" % label, "good")

    def open_ai_model(self) -> None:
        dialog = AiModelDialog(self, self.ai(), self.theme)
        dialog.exec()
        if dialog.changed:
            self._ai_offered = False
            self.canvas.set_ai_preview(None)
            if self.canvas.tool == T_AI and not self.enter_ai_tool():
                self.set_tool(T_SELECT)
            self._sync_actions()

    # ══════════════════════════════════════════════════════
    # SAVING
    # ══════════════════════════════════════════════════════
    def _matches_saved(self, rel) -> bool:
        if rel not in self.saved or rel in self.force_write:
            return False
        return (boxes_match(self.saved[rel], self.canvas.boxes)
                and self.saved_verified.get(rel, False) == self.verified)

    def _commit_current(self) -> bool:
        """Save whatever is on screen before leaving the image.

        An image nobody touched stays without an annotation, exactly as
        LabelImg left it.  Returns False when a write failed, so the caller
        stays put rather than navigating away from work that is not on disk."""
        rel = self.current_name()
        if rel is None or not self.folder or self.read_only or self.io is None \
                or not self.canvas.has_image():
            return True
        if self._matches_saved(rel):
            return True
        if rel not in self.saved and not self.canvas.boxes and not self.verified:
            return True
        return self._write_current(rel)

    def _write_current(self, rel) -> bool:
        width, height = self.image_shape[1], self.image_shape[0]
        keep, notes = [], []
        for position, box in enumerate(self.canvas.boxes):
            clean, messages = box.validated(width, height)
            if clean is None:
                notes.append("box %d dropped (%s)" % (position + 1, "; ".join(messages)))
                continue
            keep.append(clean)
        duplicates = find_duplicates(keep)
        if duplicates:
            notes.append("%d box(es) repeat another box of the same class" % len(duplicates))
        self.ensure_classes(b.label for b in keep)

        if self.io.changed_externally(rel):
            answer = QMessageBox.question(
                self, "The annotation changed on disk",
                "The annotation for %s has been modified since this session read it "
                "- another session or another person may have written to it.\n\n"
                "Overwrite it with what is on screen?\n\nThe version on disk is kept "
                "in %s." % (rel, BACKUP_DIR),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self._set_dirty(True)
                self._status("Not saved - the file on disk is newer. Reload the "
                             "folder (F5) to see it.", "warning")
                return False
            self.io.accept_external(rel)

        project = self.project()
        report = self.io.write(rel, keep, self.fmt, self.image_shape, self.verified,
                               project.ordered_names_for_yolo(), project.id_map())
        if not report.ok:
            self._set_dirty(True)
            self._status(report.summary(), "danger")
            return False

        self._set_dirty(False)
        state = {(round(b.x0), round(b.y0), round(b.x1), round(b.y1), b.label)
                 for b in self.canvas.boxes}
        if len(keep) != len(self.canvas.boxes) or state != {
                (round(b.x0), round(b.y0), round(b.x1), round(b.y1), b.label) for b in keep}:
            self.canvas.set_boxes(keep, keep_selection=True)
        self.saved[rel] = [b.copy() for b in keep]
        self.saved_verified[rel] = self.verified
        self.force_write.discard(rel)
        self.index_map[rel] = self.io.summarise(rel)
        self.history.reset(self.canvas.snapshot())
        self.draft.clear()
        notes.extend(report.warnings)
        message = "Saved %d box(es) for %s" % (len(keep), os.path.basename(rel))
        self._status(message + ("  ·  " + "; ".join(notes[:2]) if notes else ""),
                     "warning" if notes else "good")
        self._refresh_filmstrip()
        self._update_stats()
        self._refresh_side()
        self._sync_actions()
        return True

    def _set_dirty(self, value) -> None:
        self.dirty = bool(value)
        self._refresh_state_chip()

    def _writable_image(self) -> bool:
        if self.current_name() is None or not self.canvas.has_image():
            self._status("No image open", "warning")
            return False
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return False
        return True

    def save_current(self) -> None:
        if not self._writable_image():
            return
        if not self._write_current(self.current_name()):
            return
        if self.pref("auto_advance_on_save", False):
            self._advance()

    def accept_frame(self) -> None:
        """Enter: the boxes are right as they are - save and move on.  Works
        on an empty frame too, which is how a false positive becomes
        background."""
        if not self._writable_image():
            return
        count = len(self.canvas.boxes)
        if not self._write_current(self.current_name()):
            return
        if self.index < len(self.image_files) - 1:
            self._load_image(self.index + 1)
            self._status("Accepted %d box(es) - next image" % count, "good")
        else:
            self._status("Accepted %d box(es) - that was the last image" % count, "good")

    def mark_background(self) -> None:
        if not self._writable_image():
            return
        if self.canvas.boxes:
            answer = QMessageBox.question(
                self, "Mark as background",
                "This image has %d box(es).\n\nRemove them and save it as background?"
                % len(self.canvas.boxes))
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.canvas.clear_all()
        if not self._write_current(self.current_name()):
            return
        self._advance()

    def toggle_verified(self) -> None:
        if not self._writable_image():
            return
        self.verified = not self.verified
        self.canvas.verified = self.verified
        self.canvas.update()
        if not self._write_current(self.current_name()):
            self.verified = not self.verified
            self.canvas.verified = self.verified
            self.canvas.update()
            return
        self._status("Marked as %s" % ("verified" if self.verified else "not verified"), "good")

    # ══════════════════════════════════════════════════════
    # BATCH OPERATIONS
    # ══════════════════════════════════════════════════════
    def batch_apply(self, action=APPLY_BOXES) -> None:
        if not self.image_files or self.io is None:
            self._status("No folder open", "warning")
            return
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        if not self._commit_current():
            return
        rel = self.current_name()
        boxes = [b.copy() for b in self.canvas.boxes]
        dialog = BatchApplyDialog(self, self.image_files, rel, self._statuses(),
                                  len(boxes), action)
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        if dialog.overwrite:
            answer = QMessageBox.question(
                self, "Replace existing annotations",
                "Some of the chosen images already have an annotation.\n\nReplace "
                "them? The current versions are kept in %s." % BACKUP_DIR)
            if answer != QMessageBox.StandardButton.Yes:
                return
        chosen = boxes if dialog.action == APPLY_BOXES else []
        self.ensure_classes(b.label for b in chosen)
        project = self.project()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            done, skipped, notes = apply_boxes(self.io, dialog.selected, chosen, self.fmt,
                                               qt_probe, project.ordered_names_for_yolo(),
                                               project.id_map())
        finally:
            QApplication.restoreOverrideCursor()
        for name in done:
            self.saved.pop(name, None)
            self.saved_verified.pop(name, None)
            self.index_map[name] = self.io.summarise(name)
        if rel in done:
            self._load_image(self.index)
        self._refresh_filmstrip()
        self._update_stats()
        message = "%s %d image(s)" % ("Boxes applied to" if chosen else
                                      "Marked as background:", len(done))
        if skipped:
            message += "  ·  %d skipped (%s)" % (len(skipped), "; ".join(notes[:2]))
        self._status(message, "warning" if skipped else "good")

    def delete_image(self) -> None:
        rel = self.current_name()
        if rel is None or self.io is None:
            self._status("No image open", "warning")
            return
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        answer = QMessageBox.question(
            self, "Move image out of the batch",
            "Move %s and its annotation into deleted_images?\n\nNothing is erased; "
            "move them back to restore them." % rel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        ok, message, _moved = move_to_deleted(self.io, rel)
        if not ok:
            self._status("Could not move the image: %s" % message, "danger")
            return
        self.image_files.pop(self.index)
        for cache in (self.index_map, self.saved, self.saved_verified):
            cache.pop(rel, None)
        self.draft.clear()
        self._refresh_filmstrip()
        self._load_image(min(self.index, len(self.image_files) - 1))
        self._status("%s %s" % (os.path.basename(rel), message), "good")

    def copy_image(self) -> None:
        rel = self.current_name()
        if rel is None or self.io is None:
            self._status("No image open", "warning")
            return
        ok, detail = copy_to_copies(self.io, rel)
        if ok:
            self._status("Image copied to %s" % detail, "good")
        else:
            self._status("Could not copy the image: %s" % detail, "danger")

    # ══════════════════════════════════════════════════════
    # RECOVERY
    # ══════════════════════════════════════════════════════
    def restore_from_backup(self) -> None:
        rel = self.current_name()
        if rel is None or self.io is None or self.image_shape is None:
            self._status("No image open", "warning")
            return
        result = self.io.read_backup(rel, self.image_shape)
        if not result.found:
            self._status("There is no backup for this image yet", "warning")
            return
        summary = "%d box(es)" % len(result.boxes) if result.boxes else "a background decision"
        answer = QMessageBox.question(
            self, "Restore from backup",
            "The backup holds %s for %s.\n\nReplace what is on screen with it? Nothing "
            "is written until you save or move on." % (summary, rel))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.canvas.boxes = []
        if not self.canvas.add_boxes(result.boxes, "Restore from backup"):
            self.canvas.set_boxes([])
            self.history.push("Restore from backup", self.canvas.snapshot())
        self.verified = result.verified
        self.canvas.verified = self.verified
        self._refresh_side()
        self._status("Restored %s from the backup - Ctrl+S keeps it" % summary, "warning")

    def _load_project_settings(self, folder) -> str:
        data = read_json(os.path.join(folder, PROJECT_SETTINGS_NAME), None)
        if not isinstance(data, dict):
            return ""
        applied = 0
        for key in PROJECT_KEYS:
            if key in data:
                self._batch[key] = data[key]
                applied += 1
        note = ""
        wanted = self._batch.get("class_project")
        if wanted:
            if wanted in self.class_store.projects:
                self.class_store.set_active_project(wanted)
                self.refresh_class_ui()
            else:
                note = "  ·  class project \"%s\" is not on this machine" % wanted
        return ("%d batch setting(s) from %s" % (applied, PROJECT_SETTINGS_NAME)
                if applied else "") + note

    def save_project_settings(self) -> None:
        if not self.folder:
            self._status("No folder open", "warning")
            return
        payload = {key: self.pref(key) for key in PROJECT_KEYS
                   if key not in ("save_dir", "class_project")}
        payload["label_format"] = self.fmt
        payload["class_project"] = self.class_store.active_project_name
        payload["save_dir"] = os.path.relpath(self.save_dir, self.folder) if self.save_dir else ""
        payload["_note"] = ("Settings for this batch. Anyone who opens this folder in "
                            "LabelImg Master picks these up for the session.")
        ok, err = write_text_atomic(os.path.join(self.folder, PROJECT_SETTINGS_NAME),
                                    json.dumps(payload, indent=2), verify_json=True,
                                    keep_backup=False)
        if ok:
            self._batch.update({k: v for k, v in payload.items() if k in PROJECT_KEYS})
            self._status("Batch settings written to %s" % PROJECT_SETTINGS_NAME, "good")
        else:
            self._status("Could not write the batch settings: %s" % err, "danger")

    def _write_draft(self) -> None:
        rel = self.current_name()
        if rel is None or self.read_only or not self.folder or self._matches_saved(rel):
            return
        if rel not in self.saved and not self.canvas.boxes and not self.verified:
            return
        try:
            self.draft.save(rel, self.canvas.boxes, "",
                            extra={"verified": self.verified, "format": self.fmt})
        except Exception:
            pass

    def _offer_draft(self) -> None:
        pending = self.draft.pending()
        if not pending:
            return
        rel = pending.get("image_name", "")
        if rel not in self.image_files:
            self.draft.clear()
            return
        answer = QMessageBox.question(
            self, "Unsaved work recovered",
            "Unsaved boxes for %s were left behind by an earlier session (%s).\n\n"
            "Restore them?" % (rel, pending.get("saved_at", "unknown")))
        if answer != QMessageBox.StandardButton.Yes:
            self.draft.clear()
            return
        self.go_to_name(rel)
        boxes = []
        for entry in pending.get("shapes", []):
            try:
                boxes.append(Box(entry.get("label", ""), entry["x0"], entry["y0"],
                                 entry["x1"], entry["y1"], entry.get("difficult", False),
                                 entry.get("locked", False), entry.get("visible", True)))
            except (KeyError, TypeError, ValueError):
                continue
        self.canvas.set_boxes(boxes)
        self.history.push("Recover draft", self.canvas.snapshot())
        self.verified = bool((pending.get("extra") or {}).get("verified", self.verified))
        self.canvas.verified = self.verified
        self.draft.clear()
        self._refresh_side()
        self._status("Draft restored - review it and save", "warning")

    # ══════════════════════════════════════════════════════
    # IMPORT / EXPORT / REPORT
    # ══════════════════════════════════════════════════════
    def import_annotations(self) -> None:
        if not self.folder or self.io is None:
            self._status("Open a folder first", "warning")
            return
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        if not self._commit_current():
            return
        dialog = ImportDialog(self, self.folder)
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            incoming, notes = importers.read_folder(dialog.folder, self.folder,
                                                    self.image_files, qt_probe)
            current = {}
            for rel in incoming:
                if self.index_map.get(rel) is not None:
                    current[rel] = self._boxes_for(rel)[0]
            result = importers.merge(current, incoming, dialog.strategy)
            result.notes.extend(notes)
        finally:
            QApplication.restoreOverrideCursor()
        if not incoming:
            self._status("No annotations in that folder match these images", "warning")
            return
        review = ImportReviewDialog(self, result, FORMAT_LABELS[self.fmt])
        if review.exec() != Dialog.DialogCode.Accepted:
            return
        project = self.project()
        self.ensure_classes(b.label for boxes in result.merged.values() for b in boxes)
        written, failed = 0, []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for rel, boxes in result.merged.items():
                shape = self.image_shape if rel == self.current_name() else \
                    qt_probe(self.io.image_path(rel))
                if not shape:
                    failed.append(rel)
                    continue
                verified = self._boxes_for(rel)[1] if self.index_map.get(rel) else False
                report = self.io.write(rel, boxes, self.fmt, shape, verified,
                                       project.ordered_names_for_yolo(), project.id_map())
                if report.ok:
                    written += 1
                    self.saved.pop(rel, None)
                    self.index_map[rel] = self.io.summarise(rel)
                else:
                    failed.append(rel)
        finally:
            QApplication.restoreOverrideCursor()
        if self.current_name() in result.merged:
            self._load_image(self.index)
        self._refresh_filmstrip()
        self._update_stats()
        message = "Imported %d annotation(s)" % written
        if result.conflicts:
            message += "  ·  %d conflict(s) resolved by '%s'" % (len(result.conflicts),
                                                                 dialog.strategy)
        if failed:
            message += "  ·  %d failed" % len(failed)
        self._status(message, "warning" if failed else "good")

    def export_coco(self) -> None:
        if not self.folder or self.io is None:
            self._status("Open a folder first", "warning")
            return
        if not self._commit_current():
            return
        usage = {}
        for summary in self.index_map.values():
            for label in (summary.labels if summary else []):
                usage[label] = usage.get(label, 0) + 1
        self.ensure_classes(usage)
        dialog = CocoExportDialog(self, self.project().sorted_classes(), usage)
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            report, counts = exporters.export_coco(self.io, self.image_files, self.project(),
                                                   qt_probe, dialog.chosen_classes,
                                                   dialog.include_background)
        finally:
            QApplication.restoreOverrideCursor()
        if report.ok:
            message = "COCO written: %d image(s), %d box(es) → %s" % (
                counts["images"], counts["annotations"],
                os.path.relpath(report.written[0], self.folder))
            if report.warnings:
                message += "  ·  " + report.warnings[0]
            self._status(message, "warning" if report.warnings else "good")
        else:
            self._status(report.summary(), "danger")

    def _stats(self):
        return reporting.build_stats(self.index_map, self.image_files, self.project(),
                                     self.folder)

    def write_report(self, quiet=False) -> None:
        if not self.folder:
            self._status("No folder open", "warning")
            return
        stats = self._stats()
        report = reporting.write_report(stats, self.folder)
        reporting.write_summary_json(stats, self.folder)
        if not report.ok:
            self._status(report.summary(), "danger")
            return
        if quiet:
            return
        self._status("Report written to %s" % os.path.basename(report.written[0]), "good")
        QDesktopServices.openUrl(QUrl.fromLocalFile(report.written[0]))

    # ══════════════════════════════════════════════════════
    # WINDOWS
    # ══════════════════════════════════════════════════════
    def _statuses(self):
        out = {}
        for rel in self.image_files:
            summary = self.index_map.get(rel)
            if summary is None:
                out[rel] = "todo"
            elif summary.verified:
                out[rel] = "verified"
            else:
                out[rel] = summary.status
        return out

    def open_review(self) -> None:
        if not self.image_files:
            self._status("No folder open", "warning")
            return
        if not self._commit_current():
            return

        def loader(rel):
            reader = QImageReader(self.io.image_path(rel))
            reader.setAutoTransform(True)
            image = reader.read()
            if image.isNull():
                return None, [], False, "Image could not be read"
            boxes, verified = self._boxes_for(rel)
            return QPixmap.fromImage(image), boxes, verified, ""

        dialog = ReviewDialog(self, self.image_files, self._statuses(), loader,
                              self.colour_for, self.theme)
        dialog.jumpRequested.connect(self.go_to_name)

        def verify(rel):
            if rel == self.current_name():
                self.toggle_verified()
            else:
                if self.index_map.get(rel) is None:
                    self._status("%s has no annotation to verify yet" % rel, "warning")
                    return
                boxes, verified = self._boxes_for(rel)
                shape = qt_probe(self.io.image_path(rel))
                project = self.project()
                report = self.io.write(rel, boxes, self.fmt, shape, not verified,
                                       project.ordered_names_for_yolo(), project.id_map())
                if not report.ok:
                    self._status(report.summary(), "danger")
                    return
                self.saved.pop(rel, None)
                self.index_map[rel] = self.io.summarise(rel)
            dialog.set_status(rel, self._statuses().get(rel, "todo"))
            self._refresh_filmstrip()
            self._update_stats()

        dialog.verifyRequested.connect(verify)
        dialog.exec()

    def open_dashboard(self) -> None:
        if not self.folder:
            self._status("No folder open", "warning")
            return
        if not self._commit_current():
            return
        dialog = DashboardDialog(self, self._stats(), self.theme)
        dialog.reportRequested.connect(self.write_report)
        dialog.exec()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self, self.settings)
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        values = dialog.result_values()
        for key in list(values):
            if key in self._batch:
                self._batch[key] = values.pop(key)
        self.settings.update(values)
        self._rebind_shortcuts()
        if self.host is not None:
            self.host.request_theme(self.settings.get("theme", "dark"))
        else:
            self.tool_apply_theme(self.settings.get("theme", "dark"))
        if not self.folder:
            self.fmt = self.settings.get("label_format", self.fmt)
        self._apply_settings()
        self._refresh_side()
        self._status("Settings saved", "good")

    def _rebind_shortcuts(self) -> None:
        self.keys = sc.resolve(self.settings.get("shortcuts", {}))
        for action_id, action in self.actions_by_id.items():
            key = self.keys.get(action_id, "")
            action.setShortcut(QKeySequence(key) if key else QKeySequence())
        for buttons in (self.quick_buttons, self.window_buttons):
            for action_id, button in buttons.items():
                key = self.keys.get(action_id, "")
                button.setToolTip("%s%s" % (self.act(action_id).text(),
                                            ("   [%s]" % key) if key else ""))
        for action_id, tool in TOOL_ACTIONS.items():
            key = self.keys.get(action_id, "")
            self.tool_buttons[tool].setToolTip("%s%s" % (self.act(action_id).text(),
                                                         ("   [%s]" % key) if key else ""))

    def open_palette(self) -> None:
        enabled = {action_id: action.isEnabled()
                   for action_id, action in self.actions_by_id.items()}
        dialog = CommandPalette(self, sc.ACTIONS, self.keys, enabled, self.theme)
        dialog.commandChosen.connect(
            lambda action_id: QTimer.singleShot(0, self.act(action_id).trigger)
            if self.act(action_id).isEnabled() else None)
        dialog.exec()

    def open_shortcuts(self) -> None:
        ShortcutSheet(self, sc.ACTIONS, self.keys, self.theme, sc.MOUSE_HINT,
                      sc.FIXED).exec()

    def open_about(self) -> None:
        from PySide6.QtCore import qVersion
        try:
            from lxml import etree
            lxml_version = ".".join(str(p) for p in etree.LXML_VERSION[:3])
        except Exception:
            lxml_version = "missing"
        AboutDialog(self, [("Version", APP_VERSION), ("Qt", qVersion()),
                           ("lxml", lxml_version),
                           ("Class store", self.class_store.path),
                           ("Settings file", str(self.settings.path))],
                    self.theme).exec()

    def show_welcome(self, force=False) -> None:
        if not force and self.settings.get("first_run_done"):
            return
        dialog = WelcomeDialog(self, self.theme)
        dialog.exec()
        self.settings.set("first_run_done", not dialog.show_again())

    # ══════════════════════════════════════════════════════
    # REFRESH
    # ══════════════════════════════════════════════════════
    def _refresh_filmstrip(self) -> None:
        self.filmstrip.set_batch(self.folder, self.image_files, self._statuses())
        self.filmstrip.set_index(self.index)

    def _update_stats(self) -> None:
        total = len(self.image_files)
        labelled = sum(1 for s in self.index_map.values() if s is not None and s.labels)
        background = sum(1 for s in self.index_map.values() if s is not None and not s.labels)
        annotated = labelled + background
        self.stats_panel.set_values(total, labelled, background, max(0, total - annotated))
        self.filmstrip.set_statuses(self._statuses())
        if total:
            self.progress_label.setText("Image %d / %d   ·   TAI %d/%d   ·   BAI %d/%d" % (
                self.index + 1, total, annotated, total, background, annotated or total))
        else:
            self.progress_label.setText("")
        self._refresh_state_chip()

    def _sync_actions(self) -> None:
        has_batch = bool(self.image_files)
        has_image = self.canvas.has_image()
        selection = self.canvas.selection
        writable = has_image and not self.read_only
        for action_id in ("reload_folder", "close_folder", "change_save_dir",
                          "import_annotations", "export_coco", "review_mode",
                          "dashboard", "open_report",
                          "save_project_settings", "next_image", "prev_image",
                          "first_image", "last_image", "next_todo"):
            self.act(action_id).setEnabled(has_batch)
        for action_id in ("save", "accept_frame", "mark_background", "verify_image",
                          "clear_all", "copy_previous", "append_previous", "select_all",
                          "apply_to_images", "background_many", "restore_backup",
                          "delete_image"):
            self.act(action_id).setEnabled(writable)
        self.act("copy_image").setEnabled(has_image)
        self.act("copy_boxes").setEnabled(has_image and bool(self.canvas.boxes))
        self.act("cut_boxes").setEnabled(writable and bool(self.canvas.boxes))
        self.act("paste_boxes").setEnabled(writable and clipboard.count() > 0)
        for action_id in ("delete_box", "duplicate_box", "edit_label", "toggle_difficult",
                          "lock_box", "hide_box", "zoom_selection"):
            self.act(action_id).setEnabled(writable and bool(selection))
        for action_id in ("zoom_in", "zoom_out", "zoom_fit", "zoom_width", "zoom_actual",
                          "zoom_all", "brighten", "darken", "reset_brightness"):
            self.act(action_id).setEnabled(has_image)
        self.act("undo").setEnabled(self.history.can_undo)
        self.act("redo").setEnabled(self.history.can_redo)
        self.act("redo_alt").setEnabled(self.history.can_redo)
        for action_id, button in self.quick_buttons.items():
            button.setEnabled(self.act(action_id).isEnabled())
        for button in (self.save_button, self.accept_button, self.background_button,
                       self.verify_button):
            button.setEnabled(writable)
        for tool, button in self.tool_buttons.items():
            enabled = has_image and (tool not in (T_BOX, T_AI) or not self.read_only)
            button.setEnabled(enabled)
            self.act(next(a for a, t in TOOL_ACTIONS.items() if t == tool)).setEnabled(enabled)

    # ══════════════════════════════════════════════════════
    # LIFECYCLE
    # ══════════════════════════════════════════════════════
    def tool_activated(self) -> None:
        self.canvas.setFocus()
        self.show_welcome()

    def tool_deactivating(self) -> bool:
        try:
            committed = self._commit_current()
        except Exception as exc:
            self._report_exception(exc)
            committed = False
        if not committed or self.dirty:
            answer = QMessageBox.question(
                self, "Unsaved work",
                "The last write did not complete, so this image is not on disk.\n\n"
                "Leave anyway? A draft is kept and offered back when you return.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self._write_draft()
        return True

    def tool_open(self, folder) -> None:
        self.open_folder(folder)

    def tool_close(self) -> bool:
        if getattr(self, "_closed", False):
            return True
        try:
            committed = self._commit_current()
        except Exception as exc:
            self._report_exception(exc)
            committed = False
        if not committed or self.dirty:
            answer = QMessageBox.question(
                self, "Unsaved work",
                "The last write did not complete, so this image is not on disk.\n\n"
                "Close anyway? A draft is kept and offered back next time.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            self._write_draft()
            if self.host is None:
                self.settings.set("window_geometry",
                                  bytes(self.saveGeometry().toBase64()).decode("ascii"))
            self.settings.set("class_project", self.class_store.active_project_name)
            self.settings.save()
            self.class_store.save()
            self.filmstrip.shutdown()
            if self.assistant is not None:
                self.assistant.shutdown()
            self.lock.release()
            self.app.removeEventFilter(self)
        except Exception:
            pass
        self._closed = True
        return True

    def _restore_geometry(self) -> None:
        try:
            raw = self.settings.get("window_geometry", "") if "window_geometry" in \
                self.settings.data else ""
            if raw:
                self.restoreGeometry(QByteArray.fromBase64(raw.encode("ascii")))
                return
            screen = self.app.primaryScreen().availableGeometry()
            self.resize(min(1600, int(screen.width() * 0.86)),
                        min(1000, int(screen.height() * 0.86)))
        except Exception:
            self.resize(1280, 820)

    def closeEvent(self, event):
        if self.tool_close():
            event.accept()
        else:
            event.ignore()
