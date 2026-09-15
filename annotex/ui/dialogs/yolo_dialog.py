"""Choosing your YOLO model, and matching its classes to the project's."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog,
                               QHeaderView, QLabel, QPushButton, QSlider,
                               QTableWidget, QTableWidgetItem)

from . import messages
from .common import Dialog, card, hint, row

NEW_CLASS = "__new__"


class YoloModelDialog(Dialog):
    """Pick the detector and, optionally, a class names file.  The model is
    opened before the dialog accepts it, so a click on Auto-label never meets
    a file that cannot be used."""

    def __init__(self, parent, assistant):
        super().__init__(parent, "YOLO model",
                         "Your own trained detector proposes the boxes; you review them.",
                         width=600)
        self.assistant = assistant
        self.model = assistant.model_path()
        self.names = assistant.names_path()
        self.changed = False

        frame, inner = card("Model")
        self.model_label = QLabel("")
        self.model_label.setWordWrap(True)
        choose = QPushButton("Choose the model (.onnx)…")
        choose.clicked.connect(self._choose_model)
        inner.addWidget(row(choose, self.model_label, stretch_last=True))
        self.names_label = QLabel("")
        self.names_label.setWordWrap(True)
        names = QPushButton("Class names file…")
        names.clicked.connect(self._choose_names)
        clear = QPushButton("Use the model's own")
        clear.clicked.connect(self._clear_names)
        inner.addWidget(row(names, clear, self.names_label, stretch_last=True))
        inner.addWidget(hint("Export from Ultralytics with  yolo export model=best.pt format=onnx .  "
                             "Detection models give boxes.  The class names are read from the "
                             "model when the export stored them; otherwise choose a names file "
                             "(one name per line, or your data.yaml)."))
        self.body.addWidget(frame)

        frame, inner = card("Proposals")
        self.confidence = QSlider(Qt.Orientation.Horizontal)
        self.confidence.setRange(5, 95)
        self.confidence.setValue(int(round(assistant.confidence() * 100)))
        self.confidence_value = QLabel("")
        self.confidence.valueChanged.connect(self._sync)
        inner.addWidget(row(QLabel("Confidence at least"), self.confidence, self.confidence_value))
        inner.addWidget(hint("Lower finds more objects, and more mistakes to drop; higher proposes "
                             "only what the model is sure of."))
        self.remembered_label = QLabel("")
        forget = QPushButton("Forget class choices")
        forget.setToolTip("Ask again how this model's classes match the project's")
        forget.clicked.connect(self._forget)
        inner.addWidget(row(self.remembered_label, None, forget))
        self.body.addWidget(frame)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)

        self.add_button("Test this model", slot=self._test)
        self.add_button("Cancel", slot=self.reject)
        self.add_button("Use this model", primary=True, slot=self._accept)
        self._sync()

    def _sync(self, *_args) -> None:
        self.confidence_value.setText("%.2f" % (self.confidence.value() / 100.0))
        self.model_label.setText(os.path.basename(self.model) if self.model else "no model chosen")
        self.model_label.setToolTip(self.model)
        self.names_label.setText(os.path.basename(self.names) if self.names else "the model's own names")
        self.names_label.setToolTip(self.names)
        count = len(self.assistant.remembered()) if self.model == self.assistant.model_path() else 0
        self.remembered_label.setText("%d class choice(s) remembered for this model" % count
                                      if count else "No class choices remembered yet")

    def _choose_model(self) -> None:
        start = os.path.dirname(self.model) if self.model else os.path.expanduser("~")
        path, _f = QFileDialog.getOpenFileName(self, "Choose your YOLO model", start,
                                               "ONNX models (*.onnx);;All files (*)")
        if path:
            self.model = path
            self._sync()

    def _choose_names(self) -> None:
        start = os.path.dirname(self.names or self.model) or os.path.expanduser("~")
        path, _f = QFileDialog.getOpenFileName(self, "Choose the class names", start,
                                               "Class names (*.txt *.names *.yaml *.yml);;All files (*)")
        if path:
            self.names = path
            self._sync()

    def _clear_names(self) -> None:
        self.names = ""
        self._sync()

    def _forget(self) -> None:
        self.assistant.forget_classes()
        self._sync()

    def check(self):
        """(ok, message) - open the model for real."""
        from annotex.core.ai.sam import install_hint, missing_packages
        if missing_packages():
            return False, install_hint().replace("The AI tool", "Auto-labelling")
        if not self.model:
            return False, "Choose the model file first."
        from annotex.core.ai.yolo import YoloDetector, YoloError, read_names_file
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            names = read_names_file(self.names) if self.names else None
            detector = YoloDetector(self.model, names)
            detector.load()
        except YoloError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, "The model could not be opened: %s" % exc
        finally:
            QApplication.restoreOverrideCursor()
        shown = ", ".join(detector.names[:6]) + (" …" if len(detector.names) > 6 else "")
        if not detector.names:
            return True, ("The model opened (input %d x %d), but it carries no class names - they "
                          "will show as class_0, class_1, … unless you choose a names file."
                          % detector.size)
        return True, "The model opened: %d class(es) - %s - input %d x %d." % (
            (len(detector.names), shown) + tuple(detector.size))

    def _test(self) -> None:
        ok, message = self.check()
        self.status.setText(message)
        self.status.setObjectName("HintGood" if ok else "HintDanger")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _accept(self) -> None:
        if not self.model:
            self.assistant.set_model("", "")
            self.changed = True
            self.accept()
            return
        ok, message = self.check()
        if not ok:
            messages.warn(self, "That model cannot be used", message)
            return
        self.assistant.set_model(self.model, self.names)
        self.assistant.settings.set("yolo_confidence", self.confidence.value())
        self.changed = True
        self.accept()


class ClassMapDialog(Dialog):
    """The model's classes with no project class of the same name: map each
    to a project class, add it as a new class, or ignore it."""

    def __init__(self, parent, model_names, project_names):
        super().__init__(parent, "Match the model's classes",
                         "These classes of your model have no class of the same name in this "
                         "project.  Choose once - it is remembered for this model.", width=560)
        self.model_names = list(model_names)
        self.table = QTableWidget(len(self.model_names), 2)
        self.table.setHorizontalHeaderLabels(["Model class", "Becomes"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.boxes = []
        for position, name in enumerate(self.model_names):
            self.table.setItem(position, 0, QTableWidgetItem(name))
            box = QComboBox()
            box.addItem("Add \"%s\" as a new class" % name, NEW_CLASS)
            for project_name in project_names:
                box.addItem(str(project_name), str(project_name))
            box.addItem("Ignore it", "")
            self.table.setCellWidget(position, 1, box)
            self.boxes.append(box)
        self.table.setMinimumHeight(min(360, 60 + 34 * len(self.model_names)))
        self.body.addWidget(self.table, 1)
        self.body.addWidget(hint("An ignored class is never proposed.  Tools → YOLO model… → "
                                 "Forget class choices asks again."))
        self.add_button("Cancel", slot=self.reject)
        self.add_button("Use these", primary=True, slot=self.accept)

    def mapping(self) -> dict:
        out = {}
        for name, box in zip(self.model_names, self.boxes):
            choice = box.currentData()
            out[name] = name if choice == NEW_CLASS else str(choice or "")
        return out
