"""LabelImg Master's settings."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QLabel, QMessageBox,
                               QSlider, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from fluxbox.ui.dialogs.common import Dialog, card, hint, row
from fluxbox.ui.dialogs.keys import KeyBindingsEditor

from ...config import DEFAULT_SETTINGS, FORMAT_LABELS, FORMATS
from .. import shortcuts as sc


class SettingsDialog(Dialog):
    def __init__(self, parent, settings):
        super().__init__(parent, "Settings",
                         "Remembered per user. A batch can override the "
                         "workflow settings with Batch → Save these settings "
                         "for this batch.", width=660, height=580)
        self.settings = settings
        self._result = {}

        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self.tabs.addTab(self._appearance_tab(), "Appearance")
        self.tabs.addTab(self._workflow_tab(), "Workflow")
        self.tabs.addTab(self._drawing_tab(), "Drawing")
        self.keys = KeyBindingsEditor(sc.ACTIONS, settings.get("shortcuts", {}),
                                      sc.RESERVED)
        self.tabs.addTab(self.keys, "Shortcuts")

        self.add_button("Restore defaults", slot=self._restore)
        self.add_button("Cancel", slot=self.reject)
        self.add_button("Save", primary=True, slot=self._save)

    def _check(self, text, key) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(bool(self.settings.get(key, DEFAULT_SETTINGS.get(key))))
        return box

    def _appearance_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        frame, inner = card("Theme")
        self.theme_box = QComboBox()
        self.theme_box.addItem("Follow the system", "system")
        self.theme_box.addItem("Dark", "dark")
        self.theme_box.addItem("Light", "light")
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(
            self.settings.get("theme", "dark"))))
        inner.addWidget(row(QLabel("Appearance"), None, self.theme_box))
        inner.addWidget(hint("The theme is shared by every tool in the suite."))
        layout.addWidget(frame)

        frame2, inner2 = card("Canvas")
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 70)
        self.opacity.setValue(int(self.settings.get("box_opacity", 18)))
        self.opacity_label = QLabel("%d%%" % self.opacity.value())
        self.opacity.valueChanged.connect(lambda v: self.opacity_label.setText("%d%%" % v))
        inner2.addWidget(row(QLabel("Box fill"), self.opacity, self.opacity_label))
        self.line_width = QSpinBox()
        self.line_width.setRange(1, 8)
        self.line_width.setSuffix(" px")
        self.line_width.setValue(int(self.settings.get("box_line_width", 2)))
        inner2.addWidget(row(QLabel("Outline width"), None, self.line_width))
        self.show_labels = self._check("Show class names on the boxes", "show_labels")
        self.crosshair = self._check("Show crosshair guides while drawing", "show_crosshair")
        self.coords = self._check("Show the cursor position in the status bar",
                                  "show_coordinates")
        self.minimap = self._check("Show the minimap", "show_minimap")
        for widget in (self.show_labels, self.crosshair, self.coords, self.minimap):
            inner2.addWidget(widget)
        layout.addWidget(frame2)
        layout.addStretch(1)
        return page

    def _workflow_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        frame, inner = card("Labelling")
        self.skip_dialog = self._check(
            "Skip the label dialog - new boxes take the active class", "skip_label_dialog")
        self.sticky = self._check(
            "Keep the last-used class for the next box", "sticky_class")
        self.auto_advance = self._check(
            "Move to the next image after saving", "auto_advance_on_save")
        self.confirm_clear = self._check(
            "Ask before clearing every box on an image", "confirm_clear_all")
        for widget in (self.skip_dialog, self.sticky, self.auto_advance, self.confirm_clear):
            inner.addWidget(widget)
        layout.addWidget(frame)

        frame2, inner2 = card("Files")
        self.format_box = QComboBox()
        for fmt in FORMATS:
            self.format_box.addItem(FORMAT_LABELS[fmt], fmt)
        self.format_box.setCurrentIndex(max(0, self.format_box.findData(
            self.settings.get("label_format"))))
        inner2.addWidget(row(QLabel("Save new annotations as"), None, self.format_box))
        inner2.addWidget(hint("An image that already has an annotation keeps its "
                              "format when it is opened, as LabelImg always did."))
        self.autosave = QSpinBox()
        self.autosave.setRange(5, 300)
        self.autosave.setSingleStep(5)
        self.autosave.setSuffix(" seconds")
        self.autosave.setValue(int(self.settings.get("autosave_seconds", 20)))
        inner2.addWidget(row(QLabel("Draft unsaved work every"), None, self.autosave))
        layout.addWidget(frame2)
        layout.addStretch(1)
        return page

    def _drawing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        frame, inner = card("Snapping")
        self.snap_edges = self._check("Snap to the image border", "snap_to_edges")
        self.snap_boxes = self._check("Snap to the edges of other boxes", "snap_to_boxes")
        inner.addWidget(self.snap_edges)
        inner.addWidget(self.snap_boxes)
        layout.addWidget(frame)
        frame2, inner2 = card("Shape")
        self.square = self._check("Always draw squares (or hold Ctrl while drawing)",
                                  "draw_square")
        inner2.addWidget(self.square)
        layout.addWidget(frame2)
        layout.addStretch(1)
        return page

    def _restore(self) -> None:
        answer = QMessageBox.question(self, "Restore defaults",
                                      "Reset every setting on every tab to its default?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._result = dict(DEFAULT_SETTINGS)
        for key in ("recent_folders", "last_class", "class_project"):
            self._result[key] = self.settings.get(key)
        self._result["first_run_done"] = True
        self.accept()

    def _save(self) -> None:
        self._result = {
            "theme": self.theme_box.currentData(),
            "box_opacity": self.opacity.value(),
            "box_line_width": self.line_width.value(),
            "show_labels": self.show_labels.isChecked(),
            "show_crosshair": self.crosshair.isChecked(),
            "show_coordinates": self.coords.isChecked(),
            "show_minimap": self.minimap.isChecked(),
            "skip_label_dialog": self.skip_dialog.isChecked(),
            "sticky_class": self.sticky.isChecked(),
            "auto_advance_on_save": self.auto_advance.isChecked(),
            "confirm_clear_all": self.confirm_clear.isChecked(),
            "label_format": self.format_box.currentData(),
            "autosave_seconds": self.autosave.value(),
            "snap_to_edges": self.snap_edges.isChecked(),
            "snap_to_boxes": self.snap_boxes.isChecked(),
            "draw_square": self.square.isChecked(),
            "shortcuts": self.keys.overrides(),
        }
        self.accept()

    def result_values(self) -> dict:
        return dict(self._result)
