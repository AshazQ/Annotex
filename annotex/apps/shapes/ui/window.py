"""LabelImg Shapes' window.

Laid out like LabelImg Master - header docks, the canvas over a film strip,
a side column, a status bar - so moving between the two costs nothing.
Leaving an image writes what is on screen; a write that fails stops the move
rather than dropping the work.
"""

from __future__ import annotations

import os
import traceback

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QDesktopServices, QImageReader,
                           QKeySequence, QPixmap)
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QFileDialog,
                               QFrame, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit,
                               QMainWindow, QPlainTextEdit, QPushButton,
                               QScrollArea, QSplitter, QStatusBar, QTextEdit, QVBoxLayout,
                               QWidget)

from annotex.apps.labelimg.core.class_store import ClassStore, color_for_name
from annotex.apps.labelimg.ui.dialogs.class_manager import ClassManagerDialog
from annotex.apps.labelimg.ui.dialogs.label_dialog import LabelDialog
from annotex.apps.labelimg.ui.panels import ActiveClassChip, ClassPalette
from annotex.core import clipboard
from annotex.core.history import History
from annotex.core.io_safe import FolderLock, folder_is_writable
from annotex.ui import icons
from annotex.ui.dialogs.ai_dialog import AiModelDialog
from annotex.ui.dialogs.common import Dialog
from annotex.ui.filmstrip import FilmStrip
from annotex.ui.palette import install_theme, resolve_theme, toggled_setting
from annotex.ui import shortcuts as _shared_keys
from annotex.ui.theme_picker import theme_menu
from annotex.ui.widgets import StatsPanel, divider
from annotex.ui.workspace import ElidedLabel, ToolRail, assemble
from annotex.ui import keymap
from ....ui import design
from ....ui.dialogs import messages
from . import shortcuts as shape_keys

from ..config import (APP_NAME, APP_TAGLINE, APP_VERSION, CURVE_SEGMENTS, HOTKEY_DIGITS,
                      KIND_LABELS, KIND_POLYGON, LOCK_NAME, MAX_UNDO_STEPS, TASK_COCO,
                      TASK_OBB, TASK_SEGMENT, class_store_path)
from ..core import export as exporting
from ..core.model import Shape, shapes_match
from ..core.store import read_annotation, rename_label, scan_images, write_annotation
from .canvas import (T_AI, T_CIRCLE, T_ELLIPSE, T_FREEHAND, T_OBB, T_PAN, T_POLYGON,
                     T_SELECT, ShapeCanvas)
from .dialogs import ExportDialog, ShapesSettingsDialog
from .panels import ShapeListPanel

TEXT_INPUTS = (QLineEdit, QAbstractSpinBox, QPlainTextEdit, QTextEdit, QKeySequenceEdit,
               QComboBox)

TOOLS = ((T_SELECT, "Select and edit", "V", "cursor"),
         (T_POLYGON, "Polygon - click points, Enter to close", "P", "polygon"),
         (T_OBB, "Oriented box - drag, then turn it with the round handle", "O", "obb"),
         (T_CIRCLE, "Circle - drag out from the centre", "C", "circle"),
         (T_ELLIPSE, "Ellipse - drag its box, Shift for a circle", "E", "ellipse"),
         (T_FREEHAND, "Freehand - hold and trace the outline", "F", "freehand"),
         (T_AI, "AI select (SAM) - click the object, Enter keeps the outline",
          "S", "magic"),
         (T_PAN, "Pan  (or hold Space)", "H", "hand"))


class ShapesWindow(QMainWindow):

    def __init__(self, settings, app, host=None, class_store=None):
        super().__init__()
        self.settings = settings
        self.app = app
        self.host = host
        if host is not None:
            settings.data["theme"] = host.theme_setting
        self.theme = resolve_theme(settings.get("theme", "dark"), app, tool="shapes")

        self.folder = ""
        self.images = []
        self.index = 0
        self.summary = {}                # rel -> (shape count or None, verified)
        self.saved = None                # shapes on disk for the current image, None = no file
        self.saved_verified = False
        self.verified = False
        self.read_only = False
        self.image_ok = False
        self._status_level = "info"

        self.class_store = class_store or ClassStore.load_or_create(str(class_store_path()))
        wanted = settings.get("class_project", "")
        if wanted and wanted in self.class_store.projects:
            self.class_store.set_active_project(wanted)
        self.current_class = settings.get("last_class", "") or None
        self.class_hotkeys = {}
        self.hotkey_order = []

        self.lock = FolderLock(LOCK_NAME, APP_VERSION)
        self.history = History(MAX_UNDO_STEPS)
        self.assistant = None            # the AI helper, built on first use
        self._ai_offered = False         # the model chooser is offered once

        self.setWindowTitle("%s %s" % (APP_NAME, APP_VERSION))
        self.setMinimumSize(640, 440)
        self.actions_by_id = {}
        self._build_actions()
        self._build_ui()
        self._build_menus()
        self._apply_theme()
        self._apply_settings()
        self.refresh_class_ui()
        if host is None:
            self._restore_geometry()
        else:
            self.menuBar().setNativeMenuBar(False)
        self._install_clipboard_bridge()
        self.app.installEventFilter(self)
        self._sync_actions()
        self._status("Open a folder of images to begin  ·  Ctrl+O", "info")

    # ══════════════════════════════════════════════════════
    # ACTIONS
    # ══════════════════════════════════════════════════════
    def _action(self, action_id, text, keys=(), slot=None, icon="", checkable=False) -> QAction:
        action = QAction(text, self)
        if action_id in shape_keys.BY_ID:
            keys = self._keys_for(action_id)          # the table, and any remaps, decide
        if isinstance(keys, str):
            keys = (keys,)
        if keys:
            action.setShortcuts([QKeySequence(k) for k in keys])
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        action.setCheckable(checkable)
        if slot is not None:
            action.triggered.connect(self._guard(slot))
        action.setData(icon)
        self.addAction(action)
        self.actions_by_id[action_id] = action
        return action

    def act(self, action_id) -> QAction:
        return self.actions_by_id[action_id]

    def _guard(self, handler):
        def run(*_args):
            try:
                handler()
            except Exception as exc:
                traceback.print_exc()
                self._status("Something went wrong: %s" % exc, "danger")
        return run

    def _keys_for(self, action_id):
        """The keys an action answers to: the chosen (or standard) key plus that
        command's second keys.  Space for Verified is tapped on the canvas,
        because holding Space pans - so it is not a window shortcut."""
        found = keymap.sequences("shapes", action_id, self.keys.get(action_id, ""))
        if action_id == "verify":
            found = [key for key in found if key != "Space"]
        return tuple(found)

    def _space_verifies(self) -> bool:
        return self.keys.get("verify", "") == "Space"

    def _on_space_tap(self) -> None:
        if self._space_verifies() and self.canvas.has_image():
            self.act("verify").trigger()

    def _rebind_shortcuts(self) -> None:
        self.keys = shape_keys.resolve(self.settings.get("shortcuts", {}) or {})
        for action_id, action in self.actions_by_id.items():
            if action_id in shape_keys.BY_ID:
                action.setShortcuts([QKeySequence(k) for k in self._keys_for(action_id)])
        buttons = [("tool_" + tool, button) for tool, button in self.tool_buttons.items()]
        buttons += list(self.edit_buttons.items()) + list(self.window_buttons.items())
        buttons += list(self.strip_buttons.items())
        for action_id, button in buttons:
            action = self.act(action_id)
            key = self.keys.get(action_id, "")
            tip = action.toolTip() or action.text()
            button.setToolTip("%s%s" % (tip, ("   [%s]" % key) if key else ""))

    def _build_actions(self) -> None:
        self.keys = shape_keys.resolve(self.settings.get("shortcuts", {}) or {})
        a = self._action
        a("open_folder", "Open folder…", ("Ctrl+O", "Ctrl+U"), self.choose_folder, "folder")
        a("delete_image", "Move image to deleted_images", "Ctrl+Shift+D", self.delete_image,
          "image_remove")
        a("auto_label", "Auto-label with your YOLO model", "Y", self.auto_label, "scan")
        a("prelabel_folder", "Pre-label the folder with YOLO…", "", self.prelabel_folder, "scan")
        a("yolo_model", "YOLO model…", "", self.open_yolo_model, "scan")
        a("save", "Save", "Ctrl+S", self.save_current, "save")
        a("export", "Export YOLO / COCO…", "Ctrl+Shift+E", self.open_export, "export")
        a("next_image", "Next image", ("D", "PgDown"), self.next_image, "next")
        a("prev_image", "Previous image", ("A", "PgUp"), self.prev_image, "prev")
        a("verify", "Mark as verified", "Ctrl+Shift+V", self.toggle_verified, "verified", True)
        a("undo", "Undo", "Ctrl+Z", self.undo, "undo")
        a("redo", "Redo", ("Ctrl+Shift+Z", "Ctrl+Y"), self.redo, "redo")
        a("edit_class", "Change class…", "Ctrl+E", self.edit_label, "tag")
        a("duplicate", "Duplicate", "Ctrl+D", self.duplicate_shapes, "copy")
        a("copy_shapes", "Copy the selected shapes", "Ctrl+C",
          lambda: self.copy_shapes(cut=False), "copy")
        a("cut_shapes", "Cut the selected shapes", "Ctrl+X",
          lambda: self.copy_shapes(cut=True), "copy")
        a("paste_shapes", "Paste copied shapes", "Ctrl+V", self.paste_shapes, "paste")
        a("copy_previous", "Add the previous image's shapes", "Ctrl+Shift+V",
          self.copy_previous, "layers")
        a("ai_model", "AI model (SAM)…", "", self.open_ai_model, "magic")
        a("delete", "Delete", "Delete", self.delete_shapes, "trash")
        a("select_all", "Select all", "Ctrl+A", lambda: self.canvas.select_all(), "grid")
        a("rotate_left", "Rotate 15° left", "[", lambda: self.canvas.rotate_selected(-15), "rotate")
        a("rotate_right", "Rotate 15° right", "]", lambda: self.canvas.rotate_selected(15), "rotate")
        a("clear_all", "Clear all shapes", "Ctrl+Shift+Delete", self.clear_all, "clear")
        a("zoom_in", "Zoom in", ("Ctrl+=", "Ctrl++"), lambda: self.canvas.zoom_in(), "zoom_in")
        a("zoom_out", "Zoom out", "Ctrl+-", lambda: self.canvas.zoom_out(), "zoom_out")
        a("zoom_fit", "Fit to window", "Ctrl+0", lambda: self.canvas.fit_to_view(), "zoom_fit")
        a("zoom_selection", "Zoom to selection", "Ctrl+Shift+0",
          lambda: self.canvas.zoom_to_selection(), "search")
        a("toggle_labels", "Show class names", "L", self.toggle_labels, "tag", True)
        a("toggle_theme", "Switch light / dark", "Ctrl+T", self.toggle_theme, "moon")
        a("class_manager", "Class Manager…", "Ctrl+M", self.open_class_manager, "tag")
        a("settings", "Settings…", "Ctrl+,", self.open_settings, "settings")
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        for tool, text, key, icon in TOOLS:
            action = a("tool_" + tool, text.split(" - ")[0].split("  (")[0], key,
                       lambda t=tool: self.set_tool(t), icon, True)
            action.setToolTip(text)
            self.tool_group.addAction(action)
        self.act("tool_select").setChecked(True)
        for position, digit in enumerate(HOTKEY_DIGITS):
            a("class_%d" % (position + 1), "Class %d" % (position + 1), digit,
              lambda p=position: self.assign_class_by_index(p))

    # ══════════════════════════════════════════════════════
    # LAYOUT
    # ══════════════════════════════════════════════════════
    def _build_ui(self) -> None:
        """The image first: the tools in a pill rail on the left, the side panel
        folding into a strip on the right, and the filmstrip folding under a
        one-line bar that carries the folder."""
        frame = QFrame()
        frame.setObjectName("Card")
        frame_layout = QVBoxLayout(frame)
        design.margins(frame_layout, "xs")
        self.canvas = ShapeCanvas()
        self.canvas.set_colour_provider(self.colour_for)
        frame_layout.addWidget(self.canvas)
        self.canvas_frame = frame
        self.filmstrip = FilmStrip()
        self.filmstrip.empty_text = "No folder open"
        self.folder_label = ElidedLabel(APP_TAGLINE)
        self.folder_label.setObjectName("Subtitle")

        self.workspace = assemble(self, self._build_rail(), frame, self.filmstrip,
                                  self._build_side(), self.settings,
                                  info=((self.folder_label, 1),), side_width=350,
                                  shortcut="Ctrl+Shift+L",
                                  on_prev=self.act("prev_image").trigger,
                                  on_next=self.act("next_image").trigger)
        self.canvas.space_tap_handler = self._on_space_tap
        self.splitter = self.workspace.splitter
        self.side = self.workspace.side
        # What stays within reach while the panel is folded away.
        self.strip_buttons = {}
        for action_id in ("save", "verify"):
            button = self._button_for(action_id)
            self.strip_buttons[action_id] = button
            self.side.add_strip_button(button)

        self._build_statusbar()
        self._wire()

    def _dock(self):
        frame = QFrame()
        frame.setObjectName("Toolbar")
        layout = QHBoxLayout(frame)
        design.margins(layout, "xs", "s")
        layout.setSpacing(design.SPACE["xs"])
        return frame, layout

    def _button_for(self, action_id, checkable=False) -> QPushButton:
        action = self.act(action_id)
        button = QPushButton()
        button.setObjectName("Tool")
        button.setCheckable(checkable)
        button.setFixedSize(34, 32)
        button.setIconSize(QSize(design.ICON["l"], design.ICON["l"]))
        keys = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        tip = action.toolTip() or action.text()
        button.setToolTip("%s%s" % (tip, ("   [%s]" % keys) if keys else ""))
        button.clicked.connect(action.trigger)
        return button

    def _build_rail(self) -> ToolRail:
        """Every button the header held, top to bottom in a pill: drawing
        tools, then editing, then the windows."""
        rail = ToolRail()
        self.tool_buttons = {}
        for tool, _text, _key, _icon in TOOLS:
            button = self._button_for("tool_" + tool, checkable=True)
            self.tool_buttons[tool] = button
            rail.add(button)
        rail.add_separator()
        self.edit_buttons = {}
        for action_id in ("undo", "redo", "duplicate", "copy_shapes", "paste_shapes",
                          "delete", "delete_image"):
            button = self._button_for(action_id)
            self.edit_buttons[action_id] = button
            rail.add(button)
        rail.add_separator()
        self.window_buttons = {}
        for action_id in ("class_manager", "export", "settings"):
            button = self._button_for(action_id)
            self.window_buttons[action_id] = button
            rail.add(button)
        return rail

    def _build_side(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(440)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        layout = QVBoxLayout(holder)
        design.margins(layout, "m", "m", "s", "m")
        layout.setSpacing(12)
        self.active_chip = ActiveClassChip()
        self.active_chip.caption.setText("Next shape")
        layout.addWidget(self.active_chip)
        self.palette = ClassPalette()
        layout.addWidget(self.palette, 5)
        self.shape_panel = ShapeListPanel()
        layout.addWidget(self.shape_panel, 1)
        scroll.setWidget(holder)

        footer = QWidget()
        foot = QVBoxLayout(footer)
        design.margins(foot, "s", "m", "m", "m")
        foot.setSpacing(design.SPACE["s"])
        foot.addWidget(divider())
        self.stats_panel = StatsPanel(fields=(
            ("total", "Images", "title", None),
            ("labelled", "Labelled", "good", "good"),
            ("background", "Background", "sub", "info"),
            ("todo", "Remaining", "accent", "border")))
        foot.addWidget(self.stats_panel)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("Primary")
        self.save_button.setToolTip("Save this image  [Ctrl+S]  ·  an image saved with no "
                                    "shapes counts as background")
        self.save_button.clicked.connect(self.act("save").trigger)
        foot.addWidget(self.save_button)
        buttons = QHBoxLayout()
        buttons.setSpacing(design.SPACE["s"])
        self.prev_button = QPushButton("Previous")
        self.prev_button.setToolTip("Previous image  [A]")
        self.prev_button.clicked.connect(self.act("prev_image").trigger)
        self.next_button = QPushButton("Next")
        self.next_button.setToolTip("Next image  [D]  ·  saves this one")
        self.next_button.clicked.connect(self.act("next_image").trigger)
        self.verify_button = QPushButton("Verified")
        self.verify_button.setCheckable(True)
        self.verify_button.setToolTip("Mark this image as checked  [Ctrl+Shift+V]")
        self.verify_button.clicked.connect(self.act("verify").trigger)
        for button in (self.prev_button, self.next_button, self.verify_button):
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
        design.margins(bar, "0", "m", "0", "s")   # the last chip is not clipped
        self.setStatusBar(bar)
        self.status_label = QLabel("")
        self.status_label.setObjectName("Hint")
        bar.addWidget(self.status_label, 1)
        self.coord_label = QLabel("")
        self.coord_label.setObjectName("Mono")
        bar.addPermanentWidget(self.coord_label)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("Mono")
        bar.addPermanentWidget(self.zoom_label)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("Subtitle")
        bar.addPermanentWidget(self.progress_label)

    def _wire(self) -> None:
        canvas = self.canvas
        canvas.shapesChanged.connect(self._on_shapes_changed)
        canvas.selectionChanged.connect(self._on_selection_changed)
        canvas.statusMessage.connect(self._status)
        canvas.shapeDrawn.connect(self._guard_arg(self.on_shape_drawn))
        canvas.aiPromptChanged.connect(self._guard(self.refresh_ai_preview))
        canvas.aiAccepted.connect(self._guard(self.accept_ai_preview))
        canvas.proposalsAccepted.connect(self._guard(self.accept_proposals))
        canvas.editLabelRequested.connect(self._guard(self.edit_label))
        canvas.zoomChanged.connect(lambda pct: self.zoom_label.setText("%d%%" % round(pct)))
        canvas.cursorMoved.connect(lambda x, y: self.coord_label.setText("x %d  y %d" % (x, y)))
        self.filmstrip.imagePicked.connect(self.go_to_index)
        self.palette.classChosen.connect(self._on_palette_class)
        self.palette.manageRequested.connect(self._guard(self.open_class_manager))
        panel = self.shape_panel
        panel.selectionRequested.connect(lambda rows: canvas.select_indices(rows))
        panel.editRequested.connect(self._guard(self.edit_label))
        panel.duplicateRequested.connect(self._guard(self.duplicate_shapes))
        panel.deleteRequested.connect(self._guard(self.delete_shapes))
        panel.lockToggled.connect(lambda rows, value: (canvas.set_locked(rows, value),
                                                       self._refresh_side()))
        panel.visibilityToggled.connect(lambda rows, value: (canvas.set_visible(rows, value),
                                                             self._refresh_side()))

    def _guard_arg(self, handler):
        def run(value):
            try:
                handler(value)
            except Exception as exc:
                traceback.print_exc()
                self._status("Something went wrong: %s" % exc, "danger")
        return run

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        file_menu.addAction(self.act("open_folder"))
        self.recent_menu = file_menu.addMenu("Recent folders")
        self._rebuild_recent()
        file_menu.addSeparator()
        for action_id in ("save", "verify", "export"):
            file_menu.addAction(self.act(action_id))
        file_menu.addSeparator()
        if self.host is not None:
            home = QAction("Home", self)
            home.triggered.connect(lambda: self.host.go_home())
            file_menu.addAction(home)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(lambda: self.host.quit() if self.host is not None else self.close())
        file_menu.addAction(quit_action)

        edit = bar.addMenu("&Edit")
        for group in (("undo", "redo"), ("edit_class", "duplicate", "delete", "select_all"),
                      ("copy_shapes", "cut_shapes", "paste_shapes", "copy_previous"),
                      ("rotate_left", "rotate_right"), ("clear_all",)):
            for action_id in group:
                edit.addAction(self.act(action_id))
            edit.addSeparator()

        tools = bar.addMenu("&Tools")
        for tool, _text, _key, _icon in TOOLS:
            tools.addAction(self.act("tool_" + tool))
        tools.addSeparator()
        for action_id in ("auto_label", "prelabel_folder", "yolo_model"):
            tools.addAction(self.act(action_id))

        view = bar.addMenu("&View")
        for group in (("zoom_in", "zoom_out", "zoom_fit", "zoom_selection"),
                      ("toggle_labels", "toggle_theme")):
            for action_id in group:
                view.addAction(self.act(action_id))
            view.addSeparator()
        view.addMenu(theme_menu(self, self.settings.get("theme", "dark"), self.choose_theme))

        go = bar.addMenu("&Go")
        go.addAction(self.act("next_image"))
        go.addAction(self.act("prev_image"))

        window = bar.addMenu("&Window")
        window.addAction(self.act("class_manager"))
        window.addAction(self.act("ai_model"))
        window.addAction(self.act("settings"))

    def _rebuild_recent(self) -> None:
        self.recent_menu.clear()
        recent = [f for f in (self.settings.get("recent_folders") or []) if os.path.isdir(f)]
        for folder in recent[:10]:
            action = self.recent_menu.addAction(folder)
            action.triggered.connect(lambda _c=False, f=folder: self.open_folder(f))
        self.recent_menu.setEnabled(bool(recent))

    # ══════════════════════════════════════════════════════
    # KEYS THE REGISTRY CANNOT HOLD
    # ══════════════════════════════════════════════════════
    def eventFilter(self, obj, event):
        """Let a focused text field keep Ctrl+C, Ctrl+V and Ctrl+A, and let the
        keys that finish a shape work wherever the focus is.

        Qt hands window shortcuts the key first, so without this the class
        search box could not be copied out of."""
        try:
            if event.type() == QEvent.Type.KeyPress:
                return self._route_canvas_key(obj, event)
            if event.type() != QEvent.Type.ShortcutOverride or not self.isVisible():
                return False
            if QApplication.activeModalWidget() is not None:
                return False
            focus = QApplication.focusWidget()
            if focus is not None and (focus is self or self.isAncestorOf(focus)) \
                    and _shared_keys.steals_from_text_field(event, focus, TEXT_INPUTS):
                event.accept()
                return True
        except Exception:
            return False
        return False

    def _route_canvas_key(self, obj, event) -> bool:
        """Enter keeps, Esc drops, Backspace and Ctrl+Z take back - for the
        polygon or AI proposal in progress - even after a click on the class
        list, the shape list or the filmstrip moved the focus off the canvas.
        Without this those keys went to that widget and did nothing."""
        if not self.isVisible() or QApplication.activeModalWidget() is not None \
                or QApplication.activePopupWidget() is not None:
            return False
        focus = QApplication.focusWidget()
        if focus is None or obj is not focus or focus is self.canvas:
            return False                     # the canvas handles its own keys
        if focus is not self and not self.isAncestorOf(focus):
            return False
        if isinstance(focus, TEXT_INPUTS):
            return False                     # typing in the class search stays typing
        if event.key() == Qt.Key.Key_Space and not event.modifiers() and \
                not event.isAutoRepeat() and self._space_verifies():
            self._on_space_tap()             # a focused button would otherwise "click"
            return True
        return self.canvas.handle_pending_key(event)

    # ══════════════════════════════════════════════════════
    # THEME & SETTINGS
    # ══════════════════════════════════════════════════════
    def _apply_theme(self) -> None:
        icons.clear_cache()
        theme = self.theme
        install_theme(self, self.app, theme, self.host is not None)
        self.setWindowIcon(icons.app_icon(theme["accent"], theme["appBg"], "shapes"))
        for widget in (self.canvas, self.filmstrip, self.stats_panel, self.palette,
                       self.active_chip, self.shape_panel):
            widget.set_theme(theme)
        self.workspace.apply_theme(theme)
        for tool, button in self.tool_buttons.items():
            button.setIcon(icons.dual_icon(self.act("tool_" + tool).data(), theme["text"],
                                           theme["onAccent"], 19))
        for action_id, button in (list(self.edit_buttons.items()) + list(self.window_buttons.items())
                                  + list(self.strip_buttons.items())):
            colour = theme["danger"] if action_id in ("delete", "delete_image") else theme["text"]
            button.setIcon(icons.icon(self.act(action_id).data(), colour, 19))
        for action in self.actions_by_id.values():
            if action.data():
                action.setIcon(icons.icon(action.data(), theme["text"], 16))
        self._paint_status()
        self._refresh_active_chip()

    def _apply_settings(self) -> None:
        self.canvas.set_options(
            fill_opacity=int(self.settings.get("fill_opacity", 22)),
            line_width=int(self.settings.get("line_width", 2)),
            show_labels=bool(self.settings.get("show_labels", True)),
            show_crosshair=bool(self.settings.get("show_crosshair", True)))
        self.act("toggle_labels").setChecked(bool(self.settings.get("show_labels", True)))

    def tool_apply_theme(self, name) -> None:
        self.settings.set("theme", name)
        self.theme = resolve_theme(name, self.app, tool="shapes")
        self._apply_theme()
        self._refresh_side()

    def toggle_theme(self) -> None:
        name = toggled_setting(self.theme)
        self.choose_theme(name)
        self._status("Switched to the %s theme" % name, "info")

    def choose_theme(self, name) -> None:
        if self.host is not None:
            self.host.request_theme(name)
        else:
            self.tool_apply_theme(name)

    def theme_setting_for_menu(self):
        return self.settings.get("theme", "dark")

    def toggle_labels(self) -> None:
        value = not bool(self.settings.get("show_labels", True))
        self.settings.set("show_labels", value)
        self._apply_settings()

    def open_settings(self) -> None:
        dialog = ShapesSettingsDialog(self, self.settings)
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        self.settings.update(dialog.result_values())
        self._rebind_shortcuts()
        if self.host is not None:
            self.host.request_theme(self.settings.get("theme", "dark"))
        else:
            self.tool_apply_theme(self.settings.get("theme", "dark"))
        self._apply_settings()
        self._status("Settings saved", "good")

    # ══════════════════════════════════════════════════════
    # STATUS
    # ══════════════════════════════════════════════════════
    def _status(self, message, level="info") -> None:
        self._status_level = level
        self.status_label.setText(str(message))
        self._paint_status()

    def _paint_status(self) -> None:
        names = {"info": "Hint", "good": "HintGood", "warning": "HintWarn", "danger": "HintDanger"}
        self.status_label.setObjectName(names.get(self._status_level, "Hint"))
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

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
        self.hotkey_order = [entry.name for entry in active]
        self.class_hotkeys = {entry.name: HOTKEY_DIGITS[i]
                              for i, entry in enumerate(active[:len(HOTKEY_DIGITS)])}
        self.palette.set_entries(active, self.class_hotkeys, "%s · %d" % (project.name, len(active)))
        if self.current_class and project.by_name(self.current_class) is None:
            self.current_class = None
        if self.current_class:
            self.palette.select_name(self.current_class)
        self._refresh_active_chip()
        self.canvas.update()
        self._refresh_side()

    def _refresh_active_chip(self) -> None:
        if not hasattr(self, "active_chip"):
            return
        name = self.current_class
        self.active_chip.set_class(name, self.colour_for(name) if name else "",
                                   self.class_hotkeys.get(name, "") if name else "")

    def register_class(self, name):
        project = self.project()
        entry = project.by_name(name)
        if entry is None:
            entry = project.merge_name(name)
            self.class_store.save()
            self.refresh_class_ui()
            self._status("Added class \"%s\" (ID %d)" % (entry.name, entry.id), "good")
        return entry

    def ensure_classes(self, labels) -> None:
        project = self.project()
        missing = [label for label in labels if label and project.by_name(label) is None]
        if missing:
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
                self._status("%d shape(s) changed to %s" % (changed, name), "good")
        self.set_current_class(name, announce=not selected)

    def assign_class_by_index(self, index) -> None:
        if not (0 <= index < len(self.hotkey_order)):
            self._status("No class is bound to that key", "warning")
            return
        self.apply_class_choice(self.hotkey_order[index])

    def _on_palette_class(self, name) -> None:
        self.apply_class_choice(name)
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def ask_label(self, current="", title="Class for the new shape"):
        label = LabelDialog.ask(self, self.project().active_classes(), current, title)
        if label:
            self.register_class(label)
        return label

    def on_shape_drawn(self, shape) -> None:
        if self.settings.get("skip_label_dialog", True) and self.current_class:
            label = self.current_class
        else:
            label = self.ask_label(self.current_class or "")
            if not label:
                self._status("Shape discarded - no class chosen", "info")
                return
        shape.label = label
        if self.canvas.add_shape(shape, "Draw %s" % KIND_LABELS[shape.kind].lower()):
            if self.settings.get("sticky_class", True):
                self.set_current_class(label, announce=False)
            self._status("%s added as %s" % (KIND_LABELS[shape.kind], label), "good")

    def edit_label(self) -> None:
        selected = self.canvas.selected_indices()
        if not selected:
            self._status("Select a shape first", "warning")
            return
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        label = self.ask_label(self.canvas.shapes[selected[0]].label, "Change class")
        if label:
            self.canvas.relabel(selected, label)
            if self.settings.get("sticky_class", True):
                self.set_current_class(label, announce=False)

    def open_class_manager(self) -> None:
        dialog = ClassManagerDialog(self, self.class_store, search_dirs=[])
        dialog.exec()
        if dialog.changed:
            self._ai_offered = False
            self.apply_class_changes(list(dialog.renames) + list(dialog.reassignments))

    def apply_class_changes(self, pairs) -> None:
        """Save the class store and carry renamed / reassigned classes into
        every shape file of the open folder."""
        self.class_store.save()
        pairs = [(old, new) for old, new in pairs if old != new]
        if pairs and self.folder:
            if not self._commit_current():
                self._status("Could not save this image, so the class change was not "
                             "written to the files", "danger")
            else:
                files = 0
                for old, new in pairs:
                    files += rename_label(self.folder, self.images, old, new)
                if self.current_class in dict(pairs):
                    self.current_class = dict(pairs)[self.current_class]
                self._load_image(self.index)
                self._status("Classes updated in %d file(s)" % files, "good")
        self.refresh_class_ui()

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
            answer = messages.ask(
                self, "Read-only folder",
                "This folder cannot be written to:\n%s\n\nOpen it read-only?" % why)
            if not answer:
                return
        note = ""
        if writable:
            acquired, message = self.lock.acquire(folder)
            if not acquired:
                answer = messages.ask(
                    self, "Folder in use",
                    "%s\n\nTwo sessions saving the same shapes can overwrite each other's "
                    "work.\nOpen it anyway?" % message)
                if not answer:
                    return
                self.lock.acquire(folder, force=True)
                note = "lock overridden - close the other session"
            elif message:
                note = message
        elif self.lock.held:
            self.lock.release()

        self.read_only = not writable
        self.canvas.read_only = self.read_only
        self.folder = folder
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.images = scan_images(folder)
            self.summary = {}
            for rel in self.images:
                self._summarise(rel)
        finally:
            QApplication.restoreOverrideCursor()
        self.index = 0
        self.folder_label.setText(folder + ("   ·   read-only" if self.read_only else ""))
        self.settings.push_recent(folder)
        self._rebuild_recent()

        annotated = sum(1 for count, _v in self.summary.values() if count is not None)
        if not self.images:
            self._status("No supported images in this folder", "warning")
        else:
            message = "%d image(s), %d with shapes files" % (len(self.images), annotated)
            self._status(message + ("  ·  " + note if note else ""), "warning" if note else "good")
        self.filmstrip.set_batch(folder, self.images, self._statuses())
        self._load_image(0)

    def delete_image(self) -> None:
        """Take the image on screen out of the folder: it and its shapes file
        (and backup) move into deleted_images.  Nothing is erased."""
        import shutil
        from ..core.store import annotation_path, backup_path
        rel = self.current_rel()
        if rel is None or not self.folder:
            self._status("No image open", "warning")
            return
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        answer = messages.ask(
            self, "Move image out of the folder",
            "Move %s and its shapes file into deleted_images?\n\nNothing is erased; move "
            "them back to restore them." % rel)
        if not answer:
            return
        target = os.path.join(self.folder, "deleted_images")

        def free_name(name):
            stem, ext = os.path.splitext(name)
            candidate, counter = os.path.join(target, name), 2
            while os.path.exists(candidate):
                candidate = os.path.join(target, "%s_%d%s" % (stem, counter, ext))
                counter += 1
            return candidate

        try:
            os.makedirs(target, exist_ok=True)
            shutil.move(os.path.join(self.folder, rel), free_name(os.path.basename(rel)))
        except OSError as exc:
            self._status("Could not move the image: %s" % exc, "danger")
            return
        left_behind = []
        for extra in (annotation_path(self.folder, rel), backup_path(self.folder, rel)):
            if os.path.isfile(extra):
                try:
                    shutil.move(extra, free_name(os.path.basename(extra)))
                except OSError:
                    left_behind.append(os.path.basename(extra))
        self.images.pop(self.index)
        self.summary.pop(rel, None)
        self.saved = None
        self.history.reset([])
        self.filmstrip.set_batch(self.folder, self.images, self._statuses())
        self._load_image(min(self.index, len(self.images) - 1))
        if left_behind:
            self._status("%s moved to deleted_images, but %s could not be moved"
                         % (os.path.basename(rel), ", ".join(left_behind)), "warning")
        else:
            self._status("%s moved to deleted_images" % os.path.basename(rel), "good")

    def _summarise(self, rel) -> None:
        result = read_annotation(self.folder, rel)
        if not result.found or result.error:
            self.summary[rel] = (None, False)
        else:
            self.summary[rel] = (len(result.shapes), result.verified)

    def _statuses(self):
        out = {}
        for rel in self.images:
            count, verified = self.summary.get(rel, (None, False))
            if count is None:
                out[rel] = "todo"
            elif verified:
                out[rel] = "verified"
            else:
                out[rel] = "labelled" if count else "background"
        return out

    # ══════════════════════════════════════════════════════
    # IMAGES
    # ══════════════════════════════════════════════════════
    def current_rel(self):
        if 0 <= self.index < len(self.images):
            return self.images[self.index]
        return None

    def _load_image(self, index) -> None:
        if not self.images:
            self.canvas.load_image(None)
            self.saved, self.image_ok = None, False
            self.history.reset([])
            self._after_load()
            return
        self.index = max(0, min(int(index), len(self.images) - 1))
        rel = self.images[self.index]
        reader = QImageReader(os.path.join(self.folder, rel))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            self.canvas.load_image(None)
            self.saved, self.image_ok = None, False
            self.history.reset([])
            self._status("%s could not be read: %s" % (rel, reader.errorString()), "danger")
            self._after_load()
            return
        result = read_annotation(self.folder, rel)
        if result.error:
            self._status(result.error + " - it is kept until you change this image", "warning")
        elif result.skipped:
            self._status("%d shape(s) in this file could not be read" % result.skipped, "warning")
        self.ensure_classes({s.label for s in result.shapes})
        self.image_ok = True
        self.saved = [s.copy() for s in result.shapes] if (result.found and not result.error) else None
        self.saved_verified = self.verified = bool(result.verified)
        self.canvas.load_image(QPixmap.fromImage(image), result.shapes)
        self.canvas.fit_to_view()
        self.history.reset(self.canvas.snapshot())
        self._after_load()

    def _after_load(self) -> None:
        if self.canvas.tool == T_AI and not self.enter_ai_tool():
            self.set_tool(T_SELECT)
        self.filmstrip.set_index(self.index)
        self.verify_button.setChecked(self.verified)
        self.act("verify").setChecked(self.verified)
        self._refresh_side()
        self._update_stats()
        self._sync_actions()

    def go_to_index(self, index) -> None:
        if index == self.index and self.image_ok:
            return
        if self._commit_current():
            self._load_image(index)

    def next_image(self) -> None:
        if not self.images:
            return
        if self.index + 1 >= len(self.images):
            if self._commit_current():
                self._status("That was the last image", "info")
            return
        if self._commit_current():
            self._load_image(self.index + 1)

    def prev_image(self) -> None:
        if self.images and self.index > 0 and self._commit_current():
            self._load_image(self.index - 1)

    def set_tool(self, tool) -> None:
        if tool != T_SELECT and tool != T_PAN and not self.canvas.has_image():
            self._status("Open a folder first", "warning")
            tool = T_SELECT
        if tool == T_AI and self.canvas.tool != T_AI and not self.enter_ai_tool():
            tool = T_SELECT
        self.canvas.set_tool(tool)
        self.act("tool_" + tool).setChecked(True)
        for name, button in self.tool_buttons.items():
            button.setChecked(name == tool)
        text = next(t for key, t, _k, _i in TOOLS if key == tool)
        self._status(text, "info")

    # ══════════════════════════════════════════════════════
    # CANVAS FEEDBACK & EDITING
    # ══════════════════════════════════════════════════════
    def _on_shapes_changed(self, label) -> None:
        self.history.push(label, self.canvas.snapshot())
        self._refresh_side()
        self._sync_actions()

    def _on_selection_changed(self) -> None:
        self.shape_panel.set_selection(self.canvas.selected_indices())
        self._sync_actions()

    def _refresh_side(self) -> None:
        if not hasattr(self, "shape_panel"):
            return
        self.shape_panel.set_shapes(self.canvas.shapes, self.colour_for,
                                    self.canvas.selected_indices())

    def undo(self) -> None:
        canvas = self.canvas
        # Mid-shape, Ctrl+Z takes back one click - the last polygon point or
        # AI prompt - rather than the whole shape.  Once there is nothing left
        # to take back it undoes finished shapes as usual.
        if canvas.tool == T_AI and canvas.undo_ai_point():
            self._status("Last AI click undone", "info")
            return
        if canvas.undo_draft_point():
            left = len(canvas._draft)
            self._status("Last point removed  ·  %d left" % left if left
                         else "Last point removed - the shape is empty", "info")
            return
        if canvas.is_drawing():
            canvas.cancel_draft()
            return
        step = self.history.undo()
        if step is None:
            self._status("Nothing to undo", "info")
            return
        label, snapshot = step
        self.canvas.set_shapes(snapshot)
        self._status("Undid: %s" % label, "info")
        self._refresh_side()
        self._sync_actions()

    def redo(self) -> None:
        step = self.history.redo()
        if step is None:
            self._status("Nothing to redo", "info")
            return
        label, snapshot = step
        self.canvas.set_shapes(snapshot)
        self._status("Redid: %s" % label, "info")
        self._refresh_side()
        self._sync_actions()

    def delete_shapes(self) -> None:
        count = self.canvas.delete_selected()
        self._status("%d shape(s) deleted - Ctrl+Z brings them back" % count if count
                     else "Select a shape first", "good" if count else "warning")

    def duplicate_shapes(self) -> None:
        count = self.canvas.duplicate_selected()
        self._status("%d shape(s) duplicated" % count if count else "Select a shape first",
                     "good" if count else "warning")

    def clear_all(self) -> None:
        if not self.canvas.shapes:
            return
        answer = messages.ask(self, "Clear all shapes",
                                      "Remove all %d shapes from this image?\n\nCtrl+Z brings "
                                      "them back." % len(self.canvas.shapes))
        if answer:
            self._status("%d shape(s) cleared" % self.canvas.clear_all(), "good")

    # ══════════════════════════════════════════════════════
    # CLIPBOARD  (copy shapes here, paste them on another image)
    # ══════════════════════════════════════════════════════
    def _install_clipboard_bridge(self) -> None:
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
    def _to_payload_item(shape) -> dict:
        item = shape.to_dict()
        x0, y0, x1, y1 = shape.bounds
        item["bounds"] = [float(x0), float(y0), float(x1), float(y1)]
        return item

    @staticmethod
    def _from_payload_item(item):
        """A Shape out of anything on the clipboard.  A box copied in
        LabelImg Master has no `kind`, so it arrives as its bounds and
        becomes an oriented box with no rotation."""
        if isinstance(item, dict) and item.get("kind"):
            try:
                return Shape.from_dict(item)
            except Exception:
                pass
        try:
            x0, y0, x1, y1 = [float(v) for v in item["bounds"]]
        except Exception:
            return None
        return Shape.obb(str(item.get("label", "") or ""), (x0 + x1) / 2.0,
                         (y0 + y1) / 2.0, abs(x1 - x0), abs(y1 - y0), 0.0)

    def copy_shapes(self, cut=False) -> None:
        if not self.image_ok or not self.canvas.has_image():
            self._status("Open an image first", "warning")
            return
        shapes = self.canvas.selected_shapes()
        whole = False
        if not shapes:
            shapes, whole = list(self.canvas.shapes), True
        if not shapes:
            self._status("There is nothing on this image to copy", "warning")
            return
        if cut and self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        clipboard.copy(clipboard.KIND_SHAPES,
                       [self._to_payload_item(s) for s in shapes],
                       self.canvas.image_size,
                       source=os.path.basename(self.current_rel() or ""))
        removed = 0
        if cut:
            if whole:
                removed = self.canvas.clear_all()
            else:
                removed = self.canvas.delete_selected()
        self._sync_actions()
        self._status("%s %d shape(s)%s  ·  Ctrl+V pastes them onto another image"
                     % ("Cut" if cut else "Copied", removed if cut else len(shapes),
                        " (the whole image - nothing was selected)"
                        if whole and not cut else ""), "good")

    def paste_shapes(self) -> None:
        if not self._writable_image():
            return
        payload = clipboard.content()
        if not payload or not len(payload):
            self._status("Nothing has been copied yet - select shapes and press Ctrl+C",
                         "warning")
            return
        items, fx, fy = payload.scale_to(self.canvas.image_size)
        shapes = [s for s in (self._from_payload_item(i) for i in items) if s is not None]
        if not shapes:
            self._status("What was copied cannot become shapes", "warning")
            return
        self.ensure_classes({s.label for s in shapes if s.label})
        added = self.canvas.add_shapes(shapes, "Paste shapes")
        if not added:
            self._status("Nothing could be pasted - the shapes fall outside this image",
                         "warning")
            return
        notes = []
        if abs(fx - 1.0) > 1e-6 or abs(fy - 1.0) > 1e-6:
            notes.append("scaled to this image")
        if added < len(shapes):
            notes.append("%d did not fit" % (len(shapes) - added))
        if payload.kind != clipboard.KIND_SHAPES:
            notes.append("from LabelImg Master, as oriented boxes")
        self._status("Pasted %d shape(s)%s" % (added, "  ·  " + "; ".join(notes)
                                               if notes else ""),
                     "warning" if len(notes) > 1 else "good")

    def copy_previous(self) -> None:
        """Every shape of the image before this one, added to this one."""
        if not self._writable_image():
            return
        if self.index <= 0:
            self._status("There is no previous image", "warning")
            return
        previous = self.images[self.index - 1]
        result = read_annotation(self.folder, previous)
        if result.error or not result.shapes:
            self._status("%s has no shapes to copy" % previous, "warning")
            return
        self.ensure_classes({s.label for s in result.shapes})
        added = self.canvas.add_shapes([s.copy() for s in result.shapes],
                                       "Add shapes from previous image")
        self._status("Added %d shape(s) from %s" % (added, previous)
                     if added else "Nothing from %s fits this image" % previous,
                     "good" if added else "warning")

    def _writable_image(self) -> bool:
        if not self.image_ok or not self.canvas.has_image():
            self._status("Open an image first", "warning")
            return False
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return False
        return True

    # ══════════════════════════════════════════════════════
    # AI  (Segment Anything)
    # ══════════════════════════════════════════════════════
    def ai(self):
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
        if not self._writable_image():
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
                answer = messages.ask(
                    self, "AI select",
                    "%s\n\nDownload or choose a model now?" % why)
                if answer:
                    self.open_ai_model()
                    ok, _why = assistant.usable()
            if not ok:
                return False
        rel = self.current_rel()
        if rel is None:
            return False
        pixmap = self.canvas.pixmap
        image = pixmap.toImage() if pixmap is not None else None
        if image is None or image.isNull():
            self._status("This image cannot be handed to the model", "warning")
            return False
        assistant.prepare(assistant.token_for(os.path.join(self.folder, rel)), image)
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
        try:
            tolerance = float(self.settings.get("ai_smoothing", 1.2))
        except (TypeError, ValueError):
            tolerance = 1.2
        points_out = assistant.polygon_from(result, tolerance=tolerance)
        if len(points_out) < 3:
            canvas.set_ai_preview(None)
            self._status("The AI found nothing there - click the object itself, or "
                         "right-click to exclude part of it", "warning")
            return
        canvas.set_ai_preview(points_out)
        self._status("AI outline of %d points  ·  Enter keeps it, more clicks refine "
                     "it, Esc drops it" % len(points_out), "info")

    def accept_ai_preview(self) -> None:
        canvas = self.canvas
        if not canvas.ai_preview:
            self._status("Click the object first", "warning")
            return
        if self.settings.get("skip_label_dialog", True) and self.current_class:
            label = self.current_class
        else:
            label = self.ask_label(self.current_class or "", "Class for the AI shape")
            if not label:
                self._status("Proposal dropped - no class chosen", "info")
                return
        shape = Shape.polygon(label, list(canvas.ai_preview), KIND_POLYGON)
        if not canvas.add_shape(shape, "AI polygon"):
            return
        if self.settings.get("sticky_class", True):
            self.set_current_class(label, announce=False)
        if not self.settings.get("ai_keep_prompt", False):
            canvas.clear_ai(quiet=True)
        self._status("AI polygon added as %s  ·  click the next object" % label, "good")

    # ══════════════════════════════════════════════════════
    # AUTO-LABEL (your own YOLO detector)
    # ══════════════════════════════════════════════════════
    def yolo(self):
        if getattr(self, "_yolo", None) is None:
            from annotex.ui.yolo_assist import YoloAssistant
            self._yolo = YoloAssistant(self.settings, self)
            self._yolo.detected.connect(self._guard_arg(self._on_yolo_detected))
            self._yolo.failed.connect(lambda message: self._status(str(message).replace("\n", "  "),
                                                                   "danger"))
        return self._yolo

    def open_yolo_model(self) -> None:
        from annotex.ui.dialogs.yolo_dialog import YoloModelDialog
        dialog = YoloModelDialog(self, self.yolo())
        dialog.exec()
        if dialog.changed:
            path = self.yolo().model_path()
            self._status("YOLO model: %s" % os.path.basename(path) if path else "No YOLO model",
                         "good" if path else "info")

    def _yolo_ready(self) -> bool:
        assistant = self.yolo()
        ok, why = assistant.usable()
        if ok:
            return True
        self._status(str(why).replace("\n", "  "), "warning")
        if not assistant.model_path():
            answer = messages.ask(self, "Auto-label", "%s\n\nChoose a YOLO model now?" % why)
            if answer:
                self.open_yolo_model()
                ok, _why = assistant.usable()
        return ok

    def auto_label(self) -> None:
        rel = self.current_rel()
        pixmap = self.canvas.pixmap
        if rel is None or pixmap is None or not self.canvas.has_image():
            self._status("Open an image first", "warning")
            return
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        if not self._yolo_ready():
            return
        self._yolo_rel = rel
        if self.yolo().detect(rel, pixmap.toImage()):
            self._status("Finding objects with %s…" % os.path.basename(self.yolo().model_path()), "info")

    def _on_yolo_detected(self, found) -> None:
        if self.current_rel() != getattr(self, "_yolo_rel", None):
            return
        if not found:
            self._status("The model found nothing here above %.2f confidence"
                         % self.yolo().confidence(), "warning")
            return
        project_names = [entry.name for entry in self.project().active_classes()]
        mapping = self.yolo().resolve_classes(sorted({d.name for d in found}), project_names, self)
        if mapping is None:
            self._status("Auto-label cancelled", "info")
            return
        items = [{"label": mapping.get(d.name), "score": d.score, "box": (d.x0, d.y0, d.x1, d.y1)}
                 for d in found if mapping.get(d.name)]
        if not items:
            self._status("Every class the model found is set to be ignored", "warning")
            return
        self.canvas.set_proposals(items)
        self._status("%d proposal(s)  ·  click one to drop it  ·  Enter keeps the rest  ·  Esc drops "
                     "them all" % len(items), "info")

    @staticmethod
    def _rectangle(label, box):
        x0, y0, x1, y1 = box
        return Shape.obb(label, (x0 + x1) / 2.0, (y0 + y1) / 2.0, x1 - x0, y1 - y0, 0.0)

    def accept_proposals(self) -> None:
        kept = self.canvas.kept_proposals()
        self.canvas.clear_proposals()
        if not kept:
            self._status("Every proposal was dropped", "info")
            return
        self.ensure_classes({item["label"] for item in kept})
        added = self.canvas.add_shapes([self._rectangle(item["label"], item["box"]) for item in kept],
                                       "Auto-label")
        self._status("%d rectangle(s) added  ·  Ctrl+Z takes them back" % added, "good")

    def prelabel_folder(self) -> None:
        if not self.folder:
            self._status("Open a folder first", "warning")
            return
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        if not self._yolo_ready() or not self._commit_current():
            return
        from annotex.core.ai.yolo import YoloError, read_image_rgb
        from ..core.store import annotation_path, write_annotation
        assistant = self.yolo()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            detector = assistant.detector()
            detector.load()
        except YoloError as exc:
            self._status(str(exc).replace("\n", "  "), "danger")
            return
        finally:
            QApplication.restoreOverrideCursor()
        if not detector.names:
            messages.warn(self, "Pre-label the folder",
                                "This model carries no class names, so its classes cannot be "
                                "matched to yours.  Choose a names file in Tools → YOLO model….")
            return
        mapping = assistant.resolve_classes(detector.names,
                                            [e.name for e in self.project().active_classes()], self)
        if mapping is None:
            return
        wanted = {name for name in mapping.values() if name}
        if not wanted:
            self._status("Every class of the model is set to be ignored", "warning")
            return
        folder = self.folder
        todo = [rel for rel in self.images if not os.path.isfile(annotation_path(folder, rel))]
        if not todo:
            self._status("Every image already has a shapes file", "info")
            return
        answer = messages.ask(
            self, "Pre-label the folder",
            "Run %s over the %d image(s) that have no shapes file yet?\n\nImages that already have "
            "one are never touched, and nothing is written where the model finds nothing."
            % (os.path.basename(assistant.model_path()), len(todo)))
        if not answer:
            return
        self.ensure_classes(wanted)

        def write(rel, found, width, height):
            shapes = [self._rectangle(label, (d.x0, d.y0, d.x1, d.y1)) for label, d in found]
            return write_annotation(folder, rel, shapes, width, height)

        job = assistant.prelabel_job("Pre-label %s" % os.path.basename(folder), todo, mapping,
                                     lambda rel: os.path.isfile(annotation_path(folder, rel)),
                                     lambda rel: read_image_rgb(os.path.join(folder, rel)), write)
        job.tool = "shapes"
        jobs = getattr(self.host, "jobs", None)
        if jobs is None:
            if getattr(self, "_jobs", None) is None:
                from annotex.ui.jobs import JobManager
                self._jobs = JobManager(self)
            jobs = self._jobs
        watched = job.id

        def finished(done):
            if done.id != watched or self.folder != folder:
                return
            for rel in todo:
                self._summarise(rel)
            self.filmstrip.set_statuses(self._statuses())
            current = self.current_rel()
            if current in todo and not self.canvas.shapes and self.history.can_undo is False:
                self._load_image(self.index)            # show what was written for this image
            self._update_stats()
            self._status(done.message, "good" if done.state == "done" and not done.warnings else "warning")

        jobs.jobFinished.connect(finished)
        jobs.submit(job)
        self._status("Pre-labelling %d image(s) in the background" % len(todo), "info")

    def open_ai_model(self) -> None:
        dialog = AiModelDialog(self, self.ai(), self.theme)
        dialog.exec()
        if dialog.changed:
            self.canvas.set_ai_preview(None)
            if self.canvas.tool == T_AI and not self.enter_ai_tool():
                self.set_tool(T_SELECT)
            self._sync_actions()

    # ══════════════════════════════════════════════════════
    # SAVING
    # ══════════════════════════════════════════════════════
    def is_dirty(self) -> bool:
        if not self.image_ok or self.read_only:
            return False
        shapes = self.canvas.shapes
        if self.saved is None:
            return bool(shapes) or self.verified
        return not shapes_match(shapes, self.saved) or self.verified != self.saved_verified

    def _write_current(self) -> bool:
        rel = self.current_rel()
        if rel is None or not self.image_ok:
            return False
        width, height = self.canvas.image_size
        shapes = self.canvas.snapshot()
        ok, error = write_annotation(self.folder, rel, shapes, width, height, self.verified)
        if not ok:
            self._status("Could not save %s: %s" % (rel, error), "danger")
            return False
        self.saved = [s.copy() for s in shapes]
        self.saved_verified = self.verified
        self.summary[rel] = (len(shapes), self.verified)
        self._update_stats()
        return True

    def _commit_current(self) -> bool:
        """Write the image on screen if it changed.  False = the write failed."""
        if self.canvas.is_drawing():
            self.canvas.cancel_draft(quiet=True)
        if not self.is_dirty():
            return True
        return self._write_current()

    def save_current(self) -> None:
        if not self.image_ok:
            self._status("Open an image first", "warning")
            return
        if self.read_only:
            self._status("This folder is open read-only", "warning")
            return
        if self._write_current():
            count = len(self.canvas.shapes)
            self._status("Saved %s  ·  %s" % (self.current_rel(), "%d shape(s)" % count
                                              if count else "background"), "good")

    def toggle_verified(self) -> None:
        if not self.image_ok or self.read_only:
            self.verify_button.setChecked(self.verified)
            return
        self.verified = not self.verified
        self.verify_button.setChecked(self.verified)
        self.act("verify").setChecked(self.verified)
        if self._write_current():
            self._status("Marked verified" if self.verified else "Verified mark removed", "good")

    # ══════════════════════════════════════════════════════
    # EXPORT
    # ══════════════════════════════════════════════════════
    def open_export(self) -> None:
        if not self.folder:
            self._status("Open a folder first", "warning")
            return
        if not self._commit_current():
            return
        annotated = sum(1 for count, _v in self.summary.values() if count is not None)
        dialog = ExportDialog(self, self.settings, len(self.images), annotated)
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.settings.update(values)
        report = self.export_with(values["export_task"], values["curve_segments"],
                                  values["export_background"])
        picked = messages.choose(self, "Export finished" if report.ok else "Export finished with problems",
                                 "%s\n\n%s" % (report.summary(), report.path), ["Open folder"],
                                 detail="\n".join(report.errors),
                                 kind="inform" if report.ok else "warn")
        if picked == "Open folder":
            QDesktopServices.openUrl(QUrl.fromLocalFile(report.path))

    def export_with(self, task=TASK_SEGMENT, segments=CURVE_SEGMENTS, background=True):
        if not self._commit_current():
            raise RuntimeError("the current image could not be saved")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if task == TASK_COCO:
                report = exporting.export_coco(self.folder, self.images, self.project(),
                                               segments, background)
            else:
                report = exporting.export_yolo(self.folder, self.images, self.project(),
                                               TASK_OBB if task == TASK_OBB else TASK_SEGMENT,
                                               segments, background)
        finally:
            QApplication.restoreOverrideCursor()
        self._status("Exported %s" % report.summary(), "good" if report.ok else "warning")
        return report

    # ══════════════════════════════════════════════════════
    # REFRESH
    # ══════════════════════════════════════════════════════
    def _update_stats(self) -> None:
        total = len(self.images)
        labelled = sum(1 for count, _v in self.summary.values() if count)
        background = sum(1 for count, _v in self.summary.values() if count == 0)
        self.stats_panel.set_values(total, labelled, background,
                                    max(0, total - labelled - background))
        self.filmstrip.set_statuses(self._statuses())
        rel = self.current_rel()
        self.progress_label.setText("Image %d / %d   ·   %s" % (self.index + 1, total, rel)
                                    if total and rel else "")

    def _sync_actions(self) -> None:
        has_batch = bool(self.images)
        has_image = self.image_ok and self.canvas.has_image()
        writable = has_image and not self.read_only
        selection = bool(self.canvas.selection)
        for action_id in ("next_image", "prev_image", "export"):
            self.act(action_id).setEnabled(has_batch)
        for action_id in ("save", "verify", "select_all", "clear_all"):
            self.act(action_id).setEnabled(writable)
        self.act("copy_shapes").setEnabled(has_image and bool(self.canvas.shapes))
        self.act("cut_shapes").setEnabled(writable and bool(self.canvas.shapes))
        self.act("paste_shapes").setEnabled(writable and clipboard.count() > 0)
        self.act("copy_previous").setEnabled(writable and self.index > 0)
        for action_id in ("edit_class", "duplicate", "delete", "rotate_left", "rotate_right"):
            self.act(action_id).setEnabled(writable and selection)
        for action_id in ("zoom_in", "zoom_out", "zoom_fit", "zoom_selection"):
            self.act(action_id).setEnabled(has_image)
        self.act("undo").setEnabled(self.history.can_undo)
        self.act("redo").setEnabled(self.history.can_redo)
        for action_id, button in (list(self.edit_buttons.items()) + list(self.window_buttons.items())
                                  + list(self.strip_buttons.items())):
            button.setEnabled(self.act(action_id).isEnabled())
        for tool, button in self.tool_buttons.items():
            button.setEnabled(has_image and (tool in (T_SELECT, T_PAN) or not self.read_only))
        for button in (self.save_button, self.verify_button):
            button.setEnabled(writable)
        self.prev_button.setEnabled(has_batch and self.index > 0)
        self.next_button.setEnabled(has_batch)

    # ══════════════════════════════════════════════════════
    # LIFECYCLE
    # ══════════════════════════════════════════════════════
    def tool_activated(self) -> None:
        self.canvas.setFocus()

    def tool_deactivating(self) -> bool:
        if self._commit_current():
            return True
        answer = messages.ask(
            self, "Unsaved work",
            "This image could not be saved.\n\nLeave anyway? The changes to it will be lost.", default=False)
        return answer

    def tool_open(self, folder) -> None:
        self.open_folder(folder)

    def tool_close(self) -> bool:
        if getattr(self, "_closed", False):
            return True
        if not self._commit_current():
            answer = messages.ask(
                self, "Unsaved work",
                "This image could not be saved.\n\nClose anyway? The changes to it will be lost.", default=False)
            if not answer:
                return False
        try:
            if self.host is None:
                self.settings.data["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.settings.data["class_project"] = self.class_store.active_project_name
            self.settings.save()
            self.class_store.save()
            self.filmstrip.shutdown()
            if self.assistant is not None:
                self.assistant.shutdown()
            self.app.removeEventFilter(self)
            self.lock.release()
        except Exception:
            traceback.print_exc()
        self._closed = True
        return True

    def _restore_geometry(self) -> None:
        try:
            raw = self.settings.get("window_geometry", "")
            if raw:
                self.restoreGeometry(QByteArray.fromBase64(raw.encode("ascii")))
                return
            screen = self.app.primaryScreen().availableGeometry()
            self.resize(min(1600, int(screen.width() * 0.86)), min(1000, int(screen.height() * 0.86)))
        except Exception:
            self.resize(1280, 820)

    def closeEvent(self, event):
        if self.tool_close():
            event.accept()
        else:
            event.ignore()
