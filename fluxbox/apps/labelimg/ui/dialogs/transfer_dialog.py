"""COCO export, and importing another annotator's annotations."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QTableWidget, QTableWidgetItem)

from fluxbox.ui.dialogs.common import Dialog, card, hint, row

from ...config import COCO_DIR
from ...core.importers import STRATEGIES
from ..panels import swatch_icon


class CocoExportDialog(Dialog):
    """Pick the classes, then write one COCO file for the batch."""

    def __init__(self, parent, entries, usage=None):
        super().__init__(parent, "Export to COCO",
                         "One object-detection annotations.json for the batch, "
                         "written into %s inside the image folder." % COCO_DIR,
                         width=560, height=560)
        usage = dict(usage or {})
        self.chosen_classes = None
        self.include_background = True

        frame, inner = card("Classes")
        picks = QHBoxLayout()
        for label, state in (("All", True), ("None", False)):
            button = QPushButton(label)
            button.clicked.connect(lambda _c=False, s=state: self._set_all(s))
            picks.addWidget(button)
        picks.addStretch(1)
        inner.addLayout(picks)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for entry in entries:
            count = usage.get(entry.name, 0)
            text = "%s   ·   id %d   ·   %d box(es)%s" % (
                entry.name, entry.id, count, "" if entry.active else "   ·   deprecated")
            item = QListWidgetItem(swatch_icon(entry.color), text)
            item.setData(Qt.ItemDataRole.UserRole, entry.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        inner.addWidget(self.list, 1)
        self.body.addWidget(frame, 1)

        self.background_box = QCheckBox("Include background images (annotated, no boxes)")
        self.background_box.setChecked(True)
        self.body.addWidget(self.background_box)
        self.body.addWidget(hint("Category ids are the class ID plus one, so 0 stays "
                                 "free for background; the original ID is kept as "
                                 "labelimg_id."))
        self.add_button("Cancel", slot=self.reject)
        self.add_button("Export", primary=True, slot=self._accept)

    def _set_all(self, state) -> None:
        for index in range(self.list.count()):
            self.list.item(index).setCheckState(
                Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)

    def _accept(self) -> None:
        names = [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                 for i in range(self.list.count())
                 if self.list.item(i).checkState() == Qt.CheckState.Checked]
        if self.list.count() and not names:
            return
        self.chosen_classes = None if len(names) == self.list.count() else set(names)
        self.include_background = self.background_box.isChecked()
        self.accept()


class ImportDialog(Dialog):
    """Where the other annotations are, and how to combine them."""

    def __init__(self, parent, start_dir):
        super().__init__(parent, "Import or merge annotations",
                         "Point at a folder of VOC, YOLO or CreateML files for these "
                         "images - another annotator's work, or an older export. "
                         "Files are matched to images by name.",
                         width=600, height=380)
        self.folder = ""
        self.strategy = "union"

        frame, inner = card("Folder")
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Folder with the annotation files")
        self.path_edit.textChanged.connect(self._sync)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse(start_dir))
        inner.addWidget(row(self.path_edit, browse, stretch_last=False))
        self.body.addWidget(frame)

        frame2, inner2 = card("When both sides describe the same image differently")
        self.strategy_box = QComboBox()
        for key, label in STRATEGIES.items():
            self.strategy_box.addItem(label, key)
        inner2.addWidget(self.strategy_box)
        inner2.addWidget(hint("Images only the imported folder annotates are always "
                              "taken. You see the conflicts before anything is written."))
        self.body.addWidget(frame2)
        self.body.addStretch(1)

        self.add_button("Cancel", slot=self.reject)
        self.read_button = self.add_button("Read the folder", primary=True, slot=self._accept)
        self._sync()

    def _browse(self, start_dir) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Folder of annotations",
                                                  start_dir or os.path.expanduser("~"))
        if folder:
            self.path_edit.setText(folder)

    def _sync(self, *_args) -> None:
        self.read_button.setEnabled(os.path.isdir(self.path_edit.text().strip()))

    def _accept(self) -> None:
        self.folder = self.path_edit.text().strip()
        if not os.path.isdir(self.folder):
            return
        self.strategy = self.strategy_box.currentData()
        self.accept()


class ImportReviewDialog(Dialog):
    """What the import will change, before anything is written."""

    def __init__(self, parent, result, fmt_label):
        super().__init__(parent, "Review the import", result.summary(),
                         width=640, height=520)
        if result.conflicts:
            frame, inner = card("Conflicts")
            table = QTableWidget(0, 3)
            table.setHorizontalHeaderLabels(["image", "boxes here", "boxes imported"])
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            for conflict in result.conflicts:
                index = table.rowCount()
                table.insertRow(index)
                table.setItem(index, 0, QTableWidgetItem(conflict["image"]))
                table.setItem(index, 1, QTableWidgetItem(str(conflict["current"])))
                table.setItem(index, 2, QTableWidgetItem(str(conflict["incoming"])))
            inner.addWidget(table)
            self.body.addWidget(frame, 1)
        else:
            self.body.addWidget(hint("No conflicts - every imported image either had no "
                                     "annotation here or already matched."))
            self.body.addStretch(1)
        for note in result.notes[:4]:
            self.body.addWidget(hint(note))
        self.body.addWidget(QLabel("Updated images are written as %s; the previous "
                                   "version of each is kept in the backup folder."
                                   % fmt_label))
        self.add_button("Cancel", slot=self.reject)
        button = self.add_button("Write %d annotation(s)" % len(result.merged),
                                 primary=True, slot=self.accept)
        button.setEnabled(bool(result.merged))
