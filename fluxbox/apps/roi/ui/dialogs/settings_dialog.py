"""Settings: appearance, drawing, printed previews, safety, delivery, keys."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QHBoxLayout, QHeaderView, QKeySequenceEdit,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QSlider, QSpinBox,
                               QTabWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ...config import CANON_COLUMNS
from .. import shortcuts as sc
from .common import ColourButton, Dialog, card, hint, row


class SettingsDialog(Dialog):
    """Everything configurable, grouped so nothing needs hunting for."""

    def __init__(self, parent, settings):
        super().__init__(parent, "Settings",
                         "Changes apply immediately and are remembered per user.",
                         width=680, height=560)
        self.settings = settings
        self._result = {}

        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self.tabs.addTab(self._appearance_tab(), "Appearance")
        self.tabs.addTab(self._drawing_tab(), "Drawing")
        self.tabs.addTab(self._printed_tab(), "Printed ROIs")
        self.tabs.addTab(self._output_tab(), "Output")
        self.tabs.addTab(self._delivery_tab(), "Delivery")
        self.tabs.addTab(self._keys_tab(), "Shortcuts")

        self.add_button("Restore defaults", slot=self._restore)
        self.add_button("Cancel", slot=self.reject)
        self.add_button("Save", primary=True, slot=self._save)

    # ══════════════════════════════════════════════════════
    def _appearance_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        frame, inner = card("Theme")
        self.theme_box = QComboBox()
        self.theme_box.addItem("Follow the system", "system")
        self.theme_box.addItem("Dark", "dark")
        self.theme_box.addItem("Light", "light")
        index = self.theme_box.findData(self.settings.get("theme", "dark"))
        self.theme_box.setCurrentIndex(max(0, index))
        inner.addWidget(row(QLabel("Appearance"), None, self.theme_box))
        layout.addWidget(frame)

        frame2, inner2 = card("Canvas")
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 80)
        self.opacity.setValue(int(self.settings.get("roi_opacity", 28)))
        self.opacity_label = QLabel()
        self.opacity.valueChanged.connect(
            lambda v: self.opacity_label.setText("%d%%" % v))
        self.opacity_label.setText("%d%%" % self.opacity.value())
        inner2.addWidget(row(QLabel("ROI fill opacity"), self.opacity,
                             self.opacity_label, stretch_last=False))

        self.line_width = QSpinBox()
        self.line_width.setRange(1, 8)
        self.line_width.setValue(int(self.settings.get("roi_line_width", 2)))
        self.line_width.setSuffix(" px")
        inner2.addWidget(row(QLabel("ROI outline width"), None, self.line_width))

        self.crosshair = QCheckBox("Show crosshair guides while drawing")
        self.crosshair.setChecked(bool(self.settings.get("show_crosshair", True)))
        self.coords = QCheckBox("Show the cursor position in the status bar")
        self.coords.setChecked(bool(self.settings.get("show_coordinates", True)))
        self.minimap = QCheckBox("Show the minimap")
        self.minimap.setChecked(bool(self.settings.get("show_minimap", True)))
        for widget in (self.crosshair, self.coords, self.minimap):
            inner2.addWidget(widget)
        layout.addWidget(frame2)
        layout.addStretch(1)
        return page

    # ══════════════════════════════════════════════════════
    def _drawing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        frame, inner = card("Snapping")
        self.snap_edges = QCheckBox("Snap to the image edges")
        self.snap_edges.setChecked(bool(self.settings.get("snap_to_edges", True)))
        self.snap_shapes = QCheckBox("Snap to points on other ROIs")
        self.snap_shapes.setChecked(bool(self.settings.get("snap_to_shapes", True)))
        inner.addWidget(self.snap_edges)
        inner.addWidget(self.snap_shapes)
        inner.addWidget(hint("Snapping pulls a new point onto an edge or an "
                             "existing vertex when it comes within a few "
                             "pixels. Hold nothing special - it just helps."))
        layout.addWidget(frame)

        frame2, inner2 = card("Workflow")
        self.auto_advance = QCheckBox(
            "Move to the next image automatically after saving")
        self.auto_advance.setChecked(
            bool(self.settings.get("auto_advance_on_save", True)))
        self.confirm_clear = QCheckBox(
            "Ask before clearing every ROI on an image")
        self.confirm_clear.setChecked(
            bool(self.settings.get("confirm_clear_all", True)))
        inner2.addWidget(self.auto_advance)
        inner2.addWidget(self.confirm_clear)
        layout.addWidget(frame2)

        frame3, inner3 = card("Recovery")
        self.autosave = QSpinBox()
        self.autosave.setRange(5, 300)
        self.autosave.setSingleStep(5)
        self.autosave.setSuffix(" seconds")
        self.autosave.setValue(int(self.settings.get("autosave_seconds", 20)))
        inner3.addWidget(row(QLabel("Draft every"), None, self.autosave))
        inner3.addWidget(hint("Unsaved work is written to a small draft file "
                              "on this interval. If the application or the "
                              "machine stops unexpectedly, the draft is "
                              "offered back the next time you open the "
                              "folder."))
        layout.addWidget(frame3)
        layout.addStretch(1)
        return page

    # ══════════════════════════════════════════════════════
    def _printed_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        frame, inner = card("Burnt-in preview images")
        inner.addWidget(hint("These settings change only the copies written "
                             "into printed_roi. What you see while drawing is "
                             "unaffected."))
        self.printed_colour = ColourButton(
            self.settings.get("printed_roi_colour", "#00dc64"))
        inner.addWidget(row(QLabel("ROI colour"), None, self.printed_colour))

        self.printed_label_colour = ColourButton(
            self.settings.get("printed_label_colour", "#ffff00"))
        inner.addWidget(row(QLabel("Label colour"), None,
                            self.printed_label_colour))

        self.printed_alpha = QSlider(Qt.Orientation.Horizontal)
        self.printed_alpha.setRange(0, 200)
        self.printed_alpha.setValue(
            int(self.settings.get("printed_roi_fill_alpha", 70)))
        self.printed_alpha_label = QLabel()
        self.printed_alpha.valueChanged.connect(
            lambda v: self.printed_alpha_label.setText(str(v)))
        self.printed_alpha_label.setText(str(self.printed_alpha.value()))
        inner.addWidget(row(QLabel("Fill strength"), self.printed_alpha,
                            self.printed_alpha_label))

        self.printed_width = QSpinBox()
        self.printed_width.setRange(1, 12)
        self.printed_width.setSuffix(" px")
        self.printed_width.setValue(
            int(self.settings.get("printed_roi_line_width", 3)))
        inner.addWidget(row(QLabel("Outline width"), None, self.printed_width))
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    # ══════════════════════════════════════════════════════
    def _output_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        frame, inner = card("Spreadsheet layout")
        self.layout_box = QComboBox()
        self.layout_box.addItem("Full - every column", False)
        self.layout_box.addItem("Compact - site view", True)
        self.layout_box.setCurrentIndex(
            1 if self.settings.get("use_site_format", False) else 0)
        inner.addWidget(row(QLabel("Column set"), None, self.layout_box))
        inner.addWidget(hint("The full layout carries pixel and normalised "
                             "coordinates plus the image size. The compact "
                             "layout carries the normalised coordinates only. "
                             "Both write the same JSON."))
        layout.addWidget(frame)

        frame2, inner2 = card("Custom column order")
        inner2.addWidget(hint("Tick the columns to write and drag to reorder "
                              "them. Leave every box clear to use the layout "
                              "chosen above."))
        self.columns = QListWidget()
        self.columns.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove)
        self.columns.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.columns.setMaximumHeight(210)
        chosen = list(self.settings.get("export_columns", []) or [])
        ordered = chosen + [c for c in CANON_COLUMNS if c not in chosen]
        for name in ordered:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in chosen
                               else Qt.CheckState.Unchecked)
            self.columns.addItem(item)
        inner2.addWidget(self.columns)
        layout.addWidget(frame2)
        layout.addStretch(1)
        return page

    # ══════════════════════════════════════════════════════
    def _delivery_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        frame, inner = card("Send exports to an endpoint")
        self.push_enabled = QCheckBox("Post the JSON after every export")
        self.push_enabled.setChecked(
            bool(self.settings.get("api_push_enabled", False)))
        inner.addWidget(self.push_enabled)

        self.push_url = QLineEdit(str(self.settings.get("api_push_url", "")))
        self.push_url.setPlaceholderText("https://example.com/api/roi")
        inner.addWidget(row(QLabel("Endpoint"), self.push_url, stretch_last=True))

        self.push_header = QLineEdit(str(self.settings.get("api_push_header", "")))
        self.push_header.setPlaceholderText("Authorization: Bearer <token>")
        inner.addWidget(row(QLabel("Extra header"), self.push_header,
                            stretch_last=True))

        self.push_timeout = QSpinBox()
        self.push_timeout.setRange(3, 120)
        self.push_timeout.setSuffix(" seconds")
        self.push_timeout.setValue(int(self.settings.get("api_push_timeout", 15)))
        inner.addWidget(row(QLabel("Timeout"), None, self.push_timeout))

        inner.addWidget(hint("The endpoint receives one POST with the full "
                             "annotation record as JSON. Failures are "
                             "retried twice and then reported - they never "
                             "block saving, and the files on disk are always "
                             "written first."))
        layout.addWidget(frame)
        layout.addStretch(1)
        return page

    # ══════════════════════════════════════════════════════
    def _keys_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.addWidget(hint("Double-click a shortcut to change it. Clearing "
                              "one leaves that command available from the "
                              "menus and the command palette."))

        overrides = dict(self.settings.get("shortcuts", {}) or {})
        self.keys = sc.resolve(overrides)
        self.key_table = QTableWidget(0, 3)
        self.key_table.setHorizontalHeaderLabels(["Command", "Category", "Key"])
        self.key_table.verticalHeader().setVisible(False)
        self.key_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.key_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        head = self.key_table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.key_table.doubleClicked.connect(self._edit_key)

        for action_id, label, _default, category, _icon, _desc in sc.ACTIONS:
            index = self.key_table.rowCount()
            self.key_table.insertRow(index)
            name = QTableWidgetItem(label)
            name.setData(Qt.ItemDataRole.UserRole, action_id)
            self.key_table.setItem(index, 0, name)
            self.key_table.setItem(index, 1, QTableWidgetItem(category))
            self.key_table.setItem(index, 2,
                                   QTableWidgetItem(self.keys.get(action_id, "")))
        layout.addWidget(self.key_table, 1)

        buttons = QHBoxLayout()
        clear = QPushButton("Clear shortcut")
        clear.clicked.connect(self._clear_key)
        reset = QPushButton("Reset all to defaults")
        reset.clicked.connect(self._reset_keys)
        buttons.addWidget(clear)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return page

    def _current_action(self):
        index = self.key_table.currentRow()
        if index < 0:
            return None, None
        item = self.key_table.item(index, 0)
        return index, item.data(Qt.ItemDataRole.UserRole)

    def _edit_key(self) -> None:
        index, action_id = self._current_action()
        if action_id is None:
            return
        dialog = _KeyCapture(self, sc.label(action_id),
                            self.keys.get(action_id, ""))
        if dialog.exec() != Dialog.DialogCode.Accepted:
            return
        chosen = dialog.value()
        if chosen and chosen in sc.RESERVED:
            QMessageBox.information(self, "Reserved key",
                                    "%s is used by the canvas itself." % chosen)
            return
        for other_id, key in self.keys.items():
            if other_id != action_id and key and key == chosen:
                answer = QMessageBox.question(
                    self, "Already used",
                    "%s is already bound to \"%s\".\n\nMove it to \"%s\"?"
                    % (chosen, sc.label(other_id), sc.label(action_id)))
                if answer != QMessageBox.StandardButton.Yes:
                    return
                self.keys[other_id] = ""
                self._refresh_key_row(other_id)
                break
        self.keys[action_id] = chosen
        self.key_table.item(index, 2).setText(chosen)

    def _refresh_key_row(self, action_id) -> None:
        for index in range(self.key_table.rowCount()):
            item = self.key_table.item(index, 0)
            if item.data(Qt.ItemDataRole.UserRole) == action_id:
                self.key_table.item(index, 2).setText(self.keys.get(action_id, ""))
                return

    def _clear_key(self) -> None:
        index, action_id = self._current_action()
        if action_id is None:
            return
        self.keys[action_id] = ""
        self.key_table.item(index, 2).setText("")

    def _reset_keys(self) -> None:
        self.keys = sc.resolve({})
        for index in range(self.key_table.rowCount()):
            action_id = self.key_table.item(index, 0).data(
                Qt.ItemDataRole.UserRole)
            self.key_table.item(index, 2).setText(self.keys.get(action_id, ""))

    # ══════════════════════════════════════════════════════
    def _restore(self) -> None:
        answer = QMessageBox.question(
            self, "Restore defaults",
            "Reset every setting on every tab to its default?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        from ...config import DEFAULT_SETTINGS
        keep = {"recent_folders": self.settings.get("recent_folders", []),
                "first_run_done": True}
        self._result = dict(DEFAULT_SETTINGS)
        self._result.update(keep)
        self.accept()

    def _save(self) -> None:
        chosen_columns = []
        for index in range(self.columns.count()):
            item = self.columns.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                chosen_columns.append(item.text())

        overrides = {}
        for action_id, _label, default, _cat, _icon, _desc in sc.ACTIONS:
            key = self.keys.get(action_id, default)
            if key != default:
                overrides[action_id] = key

        self._result = {
            "theme": self.theme_box.currentData(),
            "roi_opacity": self.opacity.value(),
            "roi_line_width": self.line_width.value(),
            "show_crosshair": self.crosshair.isChecked(),
            "show_coordinates": self.coords.isChecked(),
            "show_minimap": self.minimap.isChecked(),
            "snap_to_edges": self.snap_edges.isChecked(),
            "snap_to_shapes": self.snap_shapes.isChecked(),
            "auto_advance_on_save": self.auto_advance.isChecked(),
            "confirm_clear_all": self.confirm_clear.isChecked(),
            "autosave_seconds": self.autosave.value(),
            "printed_roi_colour": self.printed_colour.colour(),
            "printed_label_colour": self.printed_label_colour.colour(),
            "printed_roi_fill_alpha": self.printed_alpha.value(),
            "printed_roi_line_width": self.printed_width.value(),
            "use_site_format": bool(self.layout_box.currentData()),
            "export_columns": chosen_columns,
            "api_push_enabled": self.push_enabled.isChecked(),
            "api_push_url": self.push_url.text().strip(),
            "api_push_header": self.push_header.text().strip(),
            "api_push_timeout": self.push_timeout.value(),
            "shortcuts": overrides,
        }
        self.accept()

    def result_values(self) -> dict:
        return dict(self._result)


class _KeyCapture(Dialog):
    """Press the key you want."""

    def __init__(self, parent, label, current):
        super().__init__(parent, "Set shortcut",
                         "Press the key combination for \"%s\"." % label,
                         width=420)
        self.editor = QKeySequenceEdit()
        if current:
            self.editor.setKeySequence(QKeySequence(current))
        self.body.addWidget(self.editor)
        self.body.addWidget(hint("Press Escape to clear it."))
        self.add_button("Cancel", slot=self.reject)
        self.add_button("Set", primary=True, slot=self.accept)

    def value(self) -> str:
        return self.editor.keySequence().toString(
            QKeySequence.SequenceFormat.PortableText)
