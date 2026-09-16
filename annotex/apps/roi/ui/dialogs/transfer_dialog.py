"""Export to other formats, and import or merge existing annotations."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton)

from ...core import exporters
from ...core.importers import STRATEGIES
from .common import Dialog, card, hint, row


class ExportDialog(Dialog):
    """Pick the formats and, optionally, narrow the batch first."""

    def __init__(self, parent, rows, folder):
        super().__init__(parent, "Export to other formats",
                         "Each format is written into its own subfolder of the "
                         "batch, so nothing overwrites the batch outputs.",
                         width=620, height=560)
        self.rows = list(rows or [])
        self.folder = str(folder)
        self.chosen_formats = []
        self.chosen_rows = list(self.rows)

        frame, inner = card("Formats")
        self.format_boxes = {}
        for key, (label, _fn) in exporters.EXPORTERS.items():
            box = QCheckBox(label)
            box.setChecked(key in ("coco", "yolo"))
            self.format_boxes[key] = box
            inner.addWidget(box)
        self.body.addWidget(frame)

        frame2, inner2 = card("What to include")
        self.scope = QComboBox()
        self.scope.addItem("The whole batch", "all")
        self.scope.addItem("Only the sites I pick", "site")
        self.scope.addItem("Only the cameras I pick", "cam")
        self.scope.currentIndexChanged.connect(self._scope_changed)
        inner2.addWidget(row(QLabel("Scope"), None, self.scope))

        self.picker = QListWidget()
        self.picker.setSelectionMode(
            QAbstractItemView.SelectionMode.MultiSelection)
        self.picker.setMaximumHeight(190)
        self.picker.setVisible(False)
        self.picker.itemSelectionChanged.connect(self._update_summary)
        inner2.addWidget(self.picker)

        self.summary = hint("")
        inner2.addWidget(self.summary)
        self.body.addWidget(frame2)
        self.body.addStretch(1)

        self.add_button("Cancel", slot=self.reject)
        self.add_button("Export", primary=True, slot=self._accept)
        self._scope_changed()

    def _scope_changed(self) -> None:
        mode = self.scope.currentData()
        self.picker.clear()
        self.picker.setVisible(mode != "all")
        if mode == "site":
            values = exporters.distinct(self.rows, "site_id")
        elif mode == "cam":
            values = exporters.distinct(self.rows, "roi_key")
        else:
            values = []
        for value in values:
            self.picker.addItem(QListWidgetItem(value))
        self._update_summary()

    def _selected_rows(self):
        mode = self.scope.currentData()
        picked = {item.text() for item in self.picker.selectedItems()}
        if mode == "all" or not picked:
            return list(self.rows)
        if mode == "site":
            return exporters.filter_rows(self.rows, sites=picked)
        return exporters.filter_rows(self.rows, roi_keys=picked)

    def _update_summary(self) -> None:
        rows = self._selected_rows()
        annotated = sum(1 for r in rows if r.get("row_type") == "roi")
        self.summary.setText(
            "%d row(s) selected  ·  %d with ROIs" % (len(rows), annotated))

    def _accept(self) -> None:
        self.chosen_formats = [key for key, box in self.format_boxes.items()
                               if box.isChecked()]
        self.chosen_rows = self._selected_rows()
        if not self.chosen_formats:
            self.summary.setText("Tick at least one format to export.")
            return
        self.accept()


class ImportDialog(Dialog):
    """Read one or more annotation files and choose how to combine them."""

    def __init__(self, parent, folder):
        super().__init__(parent, "Import or merge annotations",
                         "Read annotations written by this application or by "
                         "the previous script - .xlsx, .csv or .json.",
                         width=620, height=520)
        self.folder = str(folder)
        self.paths = []
        self.strategy = "union"
        self.replace_all = False

        frame, inner = card("Files")
        self.files = QListWidget()
        self.files.setMaximumHeight(160)
        inner.addWidget(self.files)
        buttons = QHBoxLayout()
        add = QPushButton("Add files…")
        add.clicked.connect(self._add_files)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove_selected)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        inner.addLayout(buttons)
        self.body.addWidget(frame)

        frame2, inner2 = card("When two files describe the same image")
        self.strategy_box = QComboBox()
        for key, label in STRATEGIES.items():
            self.strategy_box.addItem(label, key)
        inner2.addWidget(self.strategy_box)
        inner2.addWidget(hint("Images only one file mentions are always kept. "
                              "Conflicts are listed after the import so you "
                              "can check them."))
        self.body.addWidget(frame2)

        frame3, inner3 = card("How to apply it")
        self.mode_merge = QCheckBox(
            "Replace everything currently loaded (otherwise merge into it)")
        inner3.addWidget(self.mode_merge)
        inner3.addWidget(hint("Nothing is written until you export. Review the "
                              "result first, then save."))
        self.body.addWidget(frame3)
        self.body.addStretch(1)

        self.add_button("Cancel", slot=self.reject)
        self.import_button = self.add_button("Import", primary=True,
                                             slot=self._accept)
        self.import_button.setEnabled(False)

    def _add_files(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "Choose annotation files", self.folder,
            "Annotations (*.xlsx *.csv *.json);;All files (*)")
        for path in paths:
            if path not in self.paths:
                self.paths.append(path)
                self.files.addItem(QListWidgetItem(os.path.basename(path)))
        self.import_button.setEnabled(bool(self.paths))

    def _remove_selected(self) -> None:
        for item in self.files.selectedItems():
            index = self.files.row(item)
            self.files.takeItem(index)
            if 0 <= index < len(self.paths):
                self.paths.pop(index)
        self.import_button.setEnabled(bool(self.paths))

    def _accept(self) -> None:
        if not self.paths:
            return
        self.strategy = self.strategy_box.currentData()
        self.replace_all = self.mode_merge.isChecked()
        self.accept()
