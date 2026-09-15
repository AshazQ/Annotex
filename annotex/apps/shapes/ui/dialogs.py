"""LabelImg Shapes' dialogs: export and settings."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QLabel, QMessageBox,
                               QPushButton, QRadioButton, QSlider, QSpinBox)

from annotex.ui.dialogs.common import Dialog, card, hint, row
from annotex.ui.theme_picker import ThemeCombo

from ..config import (CURVE_SEGMENTS, EXPORT_COCO, EXPORT_YOLO_OBB, EXPORT_YOLO_SEG,
                      TASK_COCO, TASK_OBB, TASK_SEGMENT)

EXPORT_CHOICES = (
    (TASK_SEGMENT, "YOLO segmentation", EXPORT_YOLO_SEG + "/",
     "Every shape as a polygon - circles and ellipses are sampled, an oriented box is "
     "its four corners.  Trains with Ultralytics task=segment."),
    (TASK_OBB, "YOLO oriented boxes", EXPORT_YOLO_OBB + "/",
     "Oriented boxes exactly as drawn; every other shape becomes its tightest rotated "
     "box.  Trains with Ultralytics task=obb."),
    (TASK_COCO, "COCO", EXPORT_COCO + "/annotations.json",
     "One file for the whole folder: segmentation polygons, boxes and areas, plus the "
     "exact shape of every annotation."),
)


class ExportDialog(Dialog):
    def __init__(self, parent, settings, images=0, annotated=0):
        super().__init__(parent, "Export annotations",
                         "Your shape files stay exactly as they are.  Exports go into "
                         "their own folder inside the batch and can be rebuilt any time.",
                         width=600)
        frame, inner = card("Format")
        self.group = QButtonGroup(self)
        self.radios = {}
        wanted = settings.get("export_task", TASK_SEGMENT)
        for task, title, where, text in EXPORT_CHOICES:
            radio = QRadioButton("%s   ·   %s" % (title, where))
            radio.setChecked(task == wanted)
            self.group.addButton(radio)
            self.radios[task] = radio
            inner.addWidget(radio)
            note = hint(text)
            note.setContentsMargins(26, 0, 0, 4)
            inner.addWidget(note)
        if not any(r.isChecked() for r in self.radios.values()):
            self.radios[TASK_SEGMENT].setChecked(True)
        self.body.addWidget(frame)

        frame, inner = card("Options")
        self.segments = QSpinBox()
        self.segments.setRange(8, 360)
        self.segments.setValue(int(settings.get("curve_segments", CURVE_SEGMENTS)))
        self.segments.setSuffix(" points")
        inner.addWidget(row("Circles and ellipses become", self.segments, None))
        self.background = QCheckBox("Include background images (saved with no shapes)")
        self.background.setChecked(bool(settings.get("export_background", True)))
        inner.addWidget(self.background)
        inner.addWidget(hint("%d image(s) in the folder, %d with a shape file.  YOLO class "
                             "numbers are the Class Manager IDs." % (images, annotated)))
        self.body.addWidget(frame)

        self.add_button("Cancel", slot=self.reject)
        self.add_button("Export", primary=True, slot=self.accept)

    def values(self) -> dict:
        task = next(t for t, radio in self.radios.items() if radio.isChecked())
        return {"export_task": task, "curve_segments": self.segments.value(),
                "export_background": self.background.isChecked()}


class ShapesSettingsDialog(Dialog):
    def __init__(self, parent, settings):
        super().__init__(parent, "Settings", "LabelImg Shapes preferences.", width=560)
        self.settings = settings

        frame, inner = card("Theme")
        self.theme_box = ThemeCombo(settings.get("theme", "dark"))
        inner.addWidget(row("Colours", self.theme_box, None))
        inner.addWidget(hint("Applies to every tool, each in its own colour.  Ctrl+T switches to the "
                             "theme's light or dark partner."))
        self.body.addWidget(frame)

        frame, inner = card("Drawing")
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(int(settings.get("fill_opacity", 22)))
        self.opacity_value = QLabel("%d%%" % self.opacity.value())
        self.opacity.valueChanged.connect(lambda v: self.opacity_value.setText("%d%%" % v))
        inner.addWidget(row("Fill", self.opacity, self.opacity_value, stretch_last=False))
        self.line_width = QSpinBox()
        self.line_width.setRange(1, 6)
        self.line_width.setValue(int(settings.get("line_width", 2)))
        self.line_width.setSuffix(" px")
        inner.addWidget(row("Outline", self.line_width, None))
        self.show_labels = self._check("Show class names on the shapes", "show_labels")
        self.show_crosshair = self._check("Show a crosshair while drawing", "show_crosshair")
        for widget in (self.show_labels, self.show_crosshair):
            inner.addWidget(widget)
        self.body.addWidget(frame)

        frame, inner = card("Classes")
        self.skip_dialog = self._check("Give a new shape the active class without asking",
                                       "skip_label_dialog")
        self.sticky = self._check("Keep the last class used for the next shape", "sticky_class")
        inner.addWidget(self.skip_dialog)
        inner.addWidget(self.sticky)
        self.body.addWidget(frame)

        frame, inner = card("AI (Segment Anything)")
        self.model_label = QLabel("")
        self.model_label.setWordWrap(True)
        inner.addWidget(self.model_label)
        choose = QPushButton("Choose the model…")
        choose.clicked.connect(self._choose_model)
        inner.addWidget(row(choose, None))
        self.ai_keep = QCheckBox("Keep the clicks after a shape is added")
        self.ai_keep.setChecked(bool(settings.get("ai_keep_prompt", False)))
        inner.addWidget(self.ai_keep)
        self.smoothing = QSlider(Qt.Orientation.Horizontal)
        self.smoothing.setRange(2, 60)
        self.smoothing.setValue(int(round(float(settings.get("ai_smoothing", 1.2)) * 10)))
        self.smoothing_value = QLabel("")
        self.smoothing.valueChanged.connect(
            lambda v: self.smoothing_value.setText("%.1f px" % (v / 10.0)))
        self.smoothing_value.setText("%.1f px" % (self.smoothing.value() / 10.0))
        inner.addWidget(row("Outline smoothing", self.smoothing, self.smoothing_value))
        inner.addWidget(hint("Press S for the AI tool and click the object; the outline "
                             "is proposed as a polygon and Enter keeps it.  More "
                             "smoothing means fewer points to edit."))
        self.body.addWidget(frame)
        self._refresh_model_label()

        from annotex.ui.dialogs.keys import KeyBindingsEditor
        from . import shortcuts as shape_keys
        frame, inner = card("Keyboard shortcuts")
        self.keys = KeyBindingsEditor(shape_keys.ACTIONS, settings.get("shortcuts", {}) or {},
                                      reserved=shape_keys.RESERVED)
        self.keys.setMinimumHeight(320)
        inner.addWidget(self.keys)
        self.body.addWidget(frame)

        self.add_button("Cancel", slot=self.reject)
        self.add_button("Save", primary=True, slot=self.accept)

    def _check(self, text, key) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(bool(self.settings.get(key, True)))
        return box

    def _refresh_model_label(self) -> None:
        import os
        encoder = str(self.settings.get("sam_encoder", "") or "")
        decoder = str(self.settings.get("sam_decoder", "") or "")
        if encoder and decoder:
            self.model_label.setText("Model:  %s  +  %s" % (os.path.basename(encoder),
                                                            os.path.basename(decoder)))
            self.model_label.setToolTip("%s\n%s" % (encoder, decoder))
        else:
            self.model_label.setText("No model chosen yet - the AI tool is off.")

    def _choose_model(self) -> None:
        window = self.parent()
        if window is not None and hasattr(window, "open_ai_model"):
            window.open_ai_model()
        else:                                         # pragma: no cover
            QMessageBox.information(self, "AI model",
                                    "Open this from the tool's Settings button.")
        self._refresh_model_label()

    def result_values(self) -> dict:
        return {"theme": self.theme_box.currentData(),
                "fill_opacity": self.opacity.value(),
                "line_width": self.line_width.value(),
                "show_labels": self.show_labels.isChecked(),
                "show_crosshair": self.show_crosshair.isChecked(),
                "skip_label_dialog": self.skip_dialog.isChecked(),
                "sticky_class": self.sticky.isChecked(),
                "ai_keep_prompt": self.ai_keep.isChecked(),
                "ai_smoothing": self.smoothing.value() / 10.0,
                "shortcuts": self.keys.overrides()}
