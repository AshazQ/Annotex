"""Dataset Tools - one tool on Home, six independent operations inside.

    ┌ Folder ──────────┐┌ Rename image + label pairs ────────┐┌ History ─────────┐
    │ …\\batch_07       ││ name  [AB_proj_150926   ]  from [1] ││ Split · 14:02    │
    │ [Choose folder…] ││ [Preview]                  [Run]    ││ Rename · 13:55   │
    │ ○ Empty .txt     ││ 240 pair(s) will be numbered …      ││                  │
    │ ○ Unpaired       ││ What    From        To              ││ [Undo selected]  │
    │ ● Rename pairs   ││ Rename  a.jpg       AB_…_001.jpg    ││                  │
    │ ○ Split …        ││ …                                   ││                  │
    └──────────────────┘└─────────────────────────────────────┘└──────────────────┘

Nothing runs without a preview of exactly what will change, the run is a
background job (so the window never freezes on a big folder), and every run
lands in History, where Undo puts it back - after a restart too.
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDoubleSpinBox, QFileDialog,
                               QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from annotex.core.jobs import DONE, Job
from annotex.ui import icons
from annotex.ui.dialogs.common import hint, row
from annotex.ui.media_page import MediaToolPage
from annotex.ui.widgets import section_label
from annotex.ui.workspace import ElidedLabel

from ....ui import design
from .. import ops

ICONS = {"empty_labels": "trash", "unpaired": "pair", "rename_pairs": "rename",
         "split": "split", "rename_parts": "folder", "zip_folders": "folder_zip",
         "check_labels": "verified", "split_sets": "layers", "class_tools": "tag"}
NOTE_LINES = 40
PREVIEW_ROWS = 2000


class _Signals(QObject):
    planned = Signal(int, object, str)          # generation, plan (or None), error


def _emit(signal, *args) -> None:
    try:
        signal.emit(*args)
    except RuntimeError:
        pass                                    # the page was closed meanwhile


class DatasetPage(MediaToolPage):
    TOOL_ID = "dataset"
    TOOL_NAME = "Dataset Tools"
    TAGLINE = "Clean up, rename, split and zip image + label folders - previewed first, undoable after"
    MARK = "dataset"
    DEFAULTS = {"folder": "", "operation": "empty_labels", "include_subfolders": True,
                "pair_name": "", "pair_start": 1, "split_sizes": "", "split_prefix": "part",
                "parts_name": "", "parts_prefix": "part", "zip_output": "zipped",
                "check_classes": 0, "check_fix_coordinates": True, "check_remove_unusable": True,
                "check_remove_duplicates": True, "check_min_size": 0.0, "check_subfolders": True,
                "sets_train": 70, "sets_val": 20, "sets_test": 10, "sets_seed": 42,
                "sets_balanced": True, "sets_background": True, "sets_move": False,
                "class_mapping": "", "class_subfolders": True}

    def build(self) -> None:
        self.plan = None
        self.previewing = False
        self._generation = 0
        self._jobs_of_mine = set()
        self._signals = _Signals(self)
        self._signals.planned.connect(self._on_planned)
        self.fields = {}

        # ── folder and tools ──────────────────────────────
        left, left_layout = self.card()
        left_layout.addWidget(section_label("Folder"))
        self.folder_label = ElidedLabel("No folder chosen")
        self.folder_label.setObjectName("Subtitle")
        left_layout.addWidget(self.folder_label)
        choose = QPushButton("Choose folder…")
        choose.clicked.connect(self.browse_folder)
        left_layout.addWidget(choose)
        left_layout.addWidget(section_label("Tools"))
        self.op_list = QListWidget()
        self.op_list.setIconSize(QSize(design.ICON["s"], design.ICON["s"]))
        for key, title, _text in ops.OPERATIONS:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.op_list.addItem(item)
        left_layout.addWidget(self.op_list, 1)
        left_layout.addWidget(hint("Each tool works on its own - use any of them, in any order."))
        self.splitter.addWidget(left)

        # ── options and preview ───────────────────────────
        centre, centre_layout = self.card()
        self.op_title = QLabel("")
        self.op_title.setObjectName("TileTitle")
        self.op_text = QLabel("")
        self.op_text.setObjectName("Hint")
        self.op_text.setWordWrap(True)
        centre_layout.addWidget(self.op_title)
        centre_layout.addWidget(self.op_text)
        self.options = QStackedWidget()
        self.option_index = {}
        for key, _title, _text in ops.OPERATIONS:
            self.option_index[key] = self.options.addWidget(self._options_for(key))
        centre_layout.addWidget(self.options)
        self.preview_button = QPushButton("Preview")
        self.preview_button.setToolTip("Look at the folder and show exactly what would change")
        self.preview_button.clicked.connect(self.preview)
        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("Primary")
        self.run_button.clicked.connect(self.run_plan)
        centre_layout.addWidget(row(self.preview_button, None, self.run_button))
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.problems = QLabel("")
        self.problems.setObjectName("HintDanger")
        self.problems.setWordWrap(True)
        self.notes = QLabel("")
        self.notes.setObjectName("Hint")
        self.notes.setWordWrap(True)
        self.notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        for label in (self.summary, self.problems, self.notes):
            centre_layout.addWidget(label)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["What", "From", "To"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(150)
        centre_layout.addWidget(self.table, 1)
        self.splitter.addWidget(centre)

        # ── history ───────────────────────────────────────
        right, right_layout = self.card()
        right_layout.addWidget(section_label("History"))
        self.only_this = QCheckBox("Only this folder")
        self.only_this.setChecked(True)
        self.only_this.toggled.connect(lambda _v: self.refresh_history())
        right_layout.addWidget(self.only_this)
        self.history = QListWidget()
        self.history.setWordWrap(True)
        self.history.currentItemChanged.connect(lambda *_a: self._sync_undo())
        right_layout.addWidget(self.history, 1)
        self.undo_button = QPushButton("Undo selected run")
        self.undo_button.clicked.connect(self.undo_selected)
        right_layout.addWidget(self.undo_button)
        right_layout.addWidget(hint("Every run is recorded.  Undo puts the files back as they "
                                    "were - even after closing Annotex.  Removed files wait "
                                    "in a hidden .annotex_removed folder until then."))
        self.splitter.addWidget(right)
        self.splitter.setSizes([250, 720, 300])

        self.jobs.jobFinished.connect(self._on_job_finished)
        self.op_list.currentRowChanged.connect(lambda _r: self._on_operation())
        self._restore()

    # ── options ───────────────────────────────────────────
    def _line(self, key, field, setting, placeholder="") -> QLineEdit:
        edit = QLineEdit(str(self.settings.get(setting, "") or ""))
        edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(lambda _t: self._invalidate())
        self.fields.setdefault(key, {})[field] = edit
        return edit

    def _options_for(self, key) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)
        if key == "empty_labels":
            box = QCheckBox("Include sub-folders")
            box.setChecked(bool(self.settings.get("include_subfolders", True)))
            box.toggled.connect(lambda _v: self._invalidate())
            self.fields.setdefault(key, {})["include_subfolders"] = box
            layout.addWidget(box)
        elif key == "unpaired":
            layout.addWidget(hint("Nothing to set.  Only the files directly in the folder are "
                                  "looked at, not sub-folders."))
        elif key == "rename_pairs":
            name = self._line(key, "base_name", "pair_name",
                              "e.g. YourInitials_Project_ddmmyy_fc_data")
            start = QSpinBox()
            start.setMinimumWidth(110)
            start.setRange(0, 10 ** 7)
            start.setValue(int(self.settings.get("pair_start", 1) or 1))
            start.valueChanged.connect(lambda _v: self._invalidate())
            self.fields[key]["start"] = start
            layout.addWidget(row(QLabel("New name"), name, stretch_last=True))
            layout.addWidget(row(QLabel("First number"), start, None))
            layout.addWidget(hint("Files become name_001.jpg + name_001.txt, name_002.jpg + "
                                  "name_002.txt, … in natural order."))
        elif key == "split":
            sizes = self._line(key, "sizes", "split_sizes", "e.g. 500, 500, rest")
            prefix = self._line(key, "prefix", "split_prefix", "part")
            layout.addWidget(row(QLabel("Pairs per part"), sizes, stretch_last=True))
            layout.addWidget(row(QLabel("Folder name"), prefix, stretch_last=True))
            layout.addWidget(hint("Numbers separated by commas; \"rest\" as the last one takes "
                                  "whatever is left.  Folders are named part_1, part_2, …"))
        elif key == "rename_parts":
            name = self._line(key, "base_name", "parts_name", "e.g. batch")
            prefix = self._line(key, "prefix", "parts_prefix", "part")
            layout.addWidget(row(QLabel("New name"), name, stretch_last=True))
            layout.addWidget(row(QLabel("Folders now called"), prefix, QLabel("_1, _2, …"),
                                 stretch_last=False))
        elif key == "zip_folders":
            output = self._line(key, "output", "zip_output", "zipped")
            layout.addWidget(row(QLabel("Put the zips in"), output, stretch_last=True))
            layout.addWidget(hint("Each sub-folder becomes one .zip holding what is inside it."))
        elif key == "check_labels":
            classes = self._spin(key, "classes", "check_classes", 0, 100000)
            classes.setSpecialValueText("from classes.txt")
            min_size = QDoubleSpinBox()
            min_size.setRange(0.0, 0.2)
            min_size.setDecimals(3)
            min_size.setSingleStep(0.001)
            min_size.setSpecialValueText("off")
            min_size.setValue(float(self.settings.get("check_min_size", 0.0) or 0.0))
            min_size.setMinimumWidth(110)
            min_size.valueChanged.connect(lambda _v: self._invalidate())
            self.fields[key]["min_size"] = min_size
            layout.addWidget(row(QLabel("Number of classes"), classes, None))
            layout.addWidget(row(QLabel("Smallest box side (share of the image)"), min_size, None))
            for field, setting, text in (
                    ("fix_coordinates", "check_fix_coordinates", "Clip coordinates that fall outside the image"),
                    ("remove_unusable", "check_remove_unusable",
                     "Remove lines that cannot be used (bad class, wrong values, no size)"),
                    ("remove_duplicates", "check_remove_duplicates", "Remove repeated boxes"),
                    ("include_subfolders", "check_subfolders", "Include sub-folders")):
                layout.addWidget(self._check(key, field, setting, text))
        elif key == "split_sets":
            train = self._spin(key, "train", "sets_train", 0, 100, " %")
            val = self._spin(key, "val", "sets_val", 0, 100, " %")
            test = self._spin(key, "test", "sets_test", 0, 100, " %")
            seed = self._spin(key, "seed", "sets_seed", 0, 2 ** 31 - 1)
            layout.addWidget(row(QLabel("Train"), train, QLabel("Val"), val, QLabel("Test"), test,
                                 None))
            layout.addWidget(row(QLabel("Seed"), seed, None))
            for field, setting, text in (
                    ("balanced", "sets_balanced", "Keep every class in each set where possible"),
                    ("include_background", "sets_background",
                     "Include images without a label, as background"),
                    ("move", "sets_move", "Move the files instead of copying them")):
                layout.addWidget(self._check(key, field, setting, text))
            layout.addWidget(hint("Makes images/train, labels/train, images/val, … and data.yaml "
                                  "in this folder.  The same seed always gives the same split."))
        elif key == "class_tools":
            mapping = self._line(key, "mapping", "class_mapping", "e.g. 3>1, 4>1, 7>delete")
            layout.addWidget(row(QLabel("Changes"), mapping, stretch_last=True))
            layout.addWidget(self._check(key, "include_subfolders", "class_subfolders",
                                         "Include sub-folders"))
            layout.addWidget(hint("Leave it empty to just count the boxes of every class.  "
                                  "Changes use the original numbers, so 0>1, 1>0 swaps two classes."))
        return holder

    def _spin(self, key, field, setting, low, high, suffix="") -> QSpinBox:
        box = QSpinBox()
        box.setRange(low, high)
        box.setMinimumWidth(96)
        if suffix:
            box.setSuffix(suffix)
        try:
            box.setValue(int(self.settings.get(setting, low) or low))
        except (TypeError, ValueError):
            box.setValue(low)
        box.valueChanged.connect(lambda _v: self._invalidate())
        self.fields.setdefault(key, {})[field] = box
        return box

    def _check(self, key, field, setting, text) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(bool(self.settings.get(setting, True)))
        box.toggled.connect(lambda _v: self._invalidate())
        self.fields.setdefault(key, {})[field] = box
        return box

    def current_operation(self) -> str:
        item = self.op_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else ops.OPERATIONS[0][0]

    def select_operation(self, key) -> None:
        for position in range(self.op_list.count()):
            if self.op_list.item(position).data(Qt.ItemDataRole.UserRole) == key:
                self.op_list.setCurrentRow(position)
                return

    def _option_values(self, key) -> dict:
        fields = self.fields.get(key, {})
        if key == "empty_labels":
            return {"include_subfolders": fields["include_subfolders"].isChecked()}
        if key == "rename_pairs":
            return {"base_name": fields["base_name"].text().strip(), "start": fields["start"].value()}
        if key == "split":
            return {"sizes": fields["sizes"].text(), "prefix": fields["prefix"].text().strip() or "part"}
        if key == "rename_parts":
            return {"base_name": fields["base_name"].text().strip(),
                    "prefix": fields["prefix"].text().strip() or "part"}
        if key == "zip_folders":
            return {"output": fields["output"].text().strip() or ops.ZIP_FOLDER}
        if key == "check_labels":
            return {"classes": fields["classes"].value(),
                    "fix_coordinates": fields["fix_coordinates"].isChecked(),
                    "remove_unusable": fields["remove_unusable"].isChecked(),
                    "remove_duplicates": fields["remove_duplicates"].isChecked(),
                    "min_size": fields["min_size"].value(),
                    "include_subfolders": fields["include_subfolders"].isChecked()}
        if key == "split_sets":
            return {"train": fields["train"].value(), "val": fields["val"].value(),
                    "test": fields["test"].value(), "seed": fields["seed"].value(),
                    "balanced": fields["balanced"].isChecked(),
                    "include_background": fields["include_background"].isChecked(),
                    "move": fields["move"].isChecked()}
        if key == "class_tools":
            return {"mapping": fields["mapping"].text(),
                    "include_subfolders": fields["include_subfolders"].isChecked()}
        return {}

    def _remember_options(self) -> None:
        f = self.fields
        try:
            self.settings.update({
                "include_subfolders": f["empty_labels"]["include_subfolders"].isChecked(),
                "pair_name": f["rename_pairs"]["base_name"].text(),
                "pair_start": f["rename_pairs"]["start"].value(),
                "split_sizes": f["split"]["sizes"].text(),
                "split_prefix": f["split"]["prefix"].text(),
                "parts_name": f["rename_parts"]["base_name"].text(),
                "parts_prefix": f["rename_parts"]["prefix"].text(),
                "zip_output": f["zip_folders"]["output"].text(),
                "check_classes": f["check_labels"]["classes"].value(),
                "check_fix_coordinates": f["check_labels"]["fix_coordinates"].isChecked(),
                "check_remove_unusable": f["check_labels"]["remove_unusable"].isChecked(),
                "check_remove_duplicates": f["check_labels"]["remove_duplicates"].isChecked(),
                "check_min_size": f["check_labels"]["min_size"].value(),
                "check_subfolders": f["check_labels"]["include_subfolders"].isChecked(),
                "sets_train": f["split_sets"]["train"].value(),
                "sets_val": f["split_sets"]["val"].value(),
                "sets_test": f["split_sets"]["test"].value(),
                "sets_seed": f["split_sets"]["seed"].value(),
                "sets_balanced": f["split_sets"]["balanced"].isChecked(),
                "sets_background": f["split_sets"]["include_background"].isChecked(),
                "sets_move": f["split_sets"]["move"].isChecked(),
                "class_mapping": f["class_tools"]["mapping"].text(),
                "class_subfolders": f["class_tools"]["include_subfolders"].isChecked(),
                "operation": self.current_operation()})
        except Exception:
            pass

    def _restore(self) -> None:
        self.select_operation(self.settings.get("operation", "empty_labels"))
        if self.op_list.currentRow() < 0:
            self.op_list.setCurrentRow(0)
        folder = str(self.settings.get("folder", "") or "")
        if folder and os.path.isdir(folder):
            self.set_folder(folder)
        else:
            self._on_operation()
            self.refresh_history()

    # ── folder ────────────────────────────────────────────
    def folder(self) -> str:
        return str(self.settings.get("folder", "") or "")

    def set_folder(self, folder) -> None:
        folder = os.path.abspath(str(folder))
        self.settings.set("folder", folder)
        self.folder_label.setText(folder)
        self.refresh_history()
        self.preview()

    def browse_folder(self) -> None:
        start = self.folder() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "Choose the dataset folder", start)
        if chosen:
            self.set_folder(chosen)

    def browse_files(self) -> None:
        self.browse_folder()

    def add_paths(self, paths) -> None:
        for path in paths or []:
            path = str(path)
            if os.path.isdir(path):
                self.set_folder(path)
                return
            if os.path.isfile(path):
                self.set_folder(os.path.dirname(path))
                return
        self.status("Drop or choose a folder", "warning")

    # ── preview ───────────────────────────────────────────
    def _on_operation(self) -> None:
        key = self.current_operation()
        title = ops.TITLES.get(key, "")
        text = next((t for k, _title, t in ops.OPERATIONS if k == key), "")
        self.op_title.setText(title)
        self.op_text.setText(text)
        self.options.setCurrentIndex(self.option_index.get(key, 0))
        # A stacked widget is as tall as its tallest page; size it to the one
        # shown, so the preview table gets the room instead.
        from PySide6.QtWidgets import QSizePolicy
        for position in range(self.options.count()):
            page = self.options.widget(position)
            if position == self.options.currentIndex():
                page.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            else:
                page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.options.setMaximumHeight(self.options.currentWidget().sizeHint().height())
        self.settings.set("operation", key)
        if self.folder():
            self.preview()
        else:
            self._invalidate("Choose a folder to start.")

    def _invalidate(self, message="Press Preview to see what will change.") -> None:
        self._generation += 1
        self.previewing = False
        self.plan = None
        self.table.setRowCount(0)
        self.summary.setText(message)
        self.problems.setText("")
        self.notes.setText("")
        self._sync_run()

    def preview(self) -> None:
        folder, key = self.folder(), self.current_operation()
        if not folder:
            self._invalidate("Choose a folder to start.")
            return
        self._remember_options()
        values = self._option_values(key)
        self._invalidate("Looking at the folder…")
        generation = self._generation
        self.previewing = True
        self._sync_run()
        signals = self._signals

        def work():
            try:
                plan = ops.PLANNERS[key](folder, **values)
                _emit(signals.planned, generation, plan, "")
            except ops.DatasetError as exc:
                _emit(signals.planned, generation, None, str(exc))
            except Exception as exc:                        # never let a thread die loudly
                _emit(signals.planned, generation, None,
                      "The folder could not be examined: %s" % exc)

        threading.Thread(target=work, name="annotex-dataset-preview", daemon=True).start()

    def _on_planned(self, generation, plan, error) -> None:
        if generation != self._generation:
            return                                  # the folder or options changed since
        self.previewing = False
        self.plan = plan
        if plan is None:
            self.summary.setText("")
            self.problems.setText(error)
            self._sync_run()
            return
        count = len(plan.actions)
        self.summary.setText("%d change(s) will be made." % count if count and not plan.problems
                             else ("Nothing will change." if not plan.problems else ""))
        self.problems.setText("\n".join(plan.problems))
        self.notes.setText("\n".join(plan.notes[:NOTE_LINES]) +
                           ("\n… %d more note(s)" % (len(plan.notes) - NOTE_LINES)
                            if len(plan.notes) > NOTE_LINES else ""))
        rows = plan.rows(PREVIEW_ROWS)
        self.table.setRowCount(len(rows))
        for position, cells in enumerate(rows):
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(position, column, item)
        if count > PREVIEW_ROWS:
            self.summary.setText("%d change(s) will be made - the first %d are listed."
                                 % (count, PREVIEW_ROWS))
        self._sync_run()

    def _busy(self) -> bool:
        return any(job.active for job in self.jobs.jobs if job.id in self._jobs_of_mine)

    def _sync_run(self) -> None:
        # An empty line still takes a row; hide it so the table gets the room.
        for label in (self.summary, self.problems, self.notes):
            label.setVisible(bool(label.text()))
        plan = self.plan
        busy = self._busy()
        self.run_button.setEnabled(bool(plan is not None and plan.runnable and not busy
                                        and not self.previewing))
        if plan is not None and plan.runnable:
            self.run_button.setText("Run  ·  %d change(s)" % len(plan.actions))
        else:
            self.run_button.setText("Run")
        self.preview_button.setEnabled(not busy)
        self._sync_undo()

    # ── run ───────────────────────────────────────────────
    def run_plan(self) -> None:
        plan = self.plan
        if plan is None or not plan.runnable:
            self.status("Preview first - there is nothing ready to run", "warning")
            return
        if self._busy():
            self.status("Wait for the running job to finish", "warning")
            return
        if not self.ask(plan.title,
                        "%s: %d change(s) in\n%s\n\nEverything is recorded - Undo in History "
                        "puts it back." % (plan.title, len(plan.actions), plan.root)):
            return
        job = Job("%s  ·  %s" % (plan.title, os.path.basename(plan.root) or plan.root),
                  lambda ctx, plan=plan: ops.apply(plan, ctx))
        self._jobs_of_mine.add(job.id)
        self.plan = None
        self.submit(job)
        self._sync_run()

    def _on_job_finished(self, job) -> None:
        if job.id not in self._jobs_of_mine:
            return
        self._jobs_of_mine.discard(job.id)
        level = "good" if job.state == DONE and not job.warnings else \
            ("warning" if job.state == DONE else "danger")
        self.status(job.message, level)
        self.refresh_history()
        if self.folder():
            self.preview()
        else:
            self._sync_run()

    # ── history ───────────────────────────────────────────
    def refresh_history(self) -> None:
        current = self.history.currentItem()
        keep = current.data(Qt.ItemDataRole.UserRole)["run"] if current is not None else ""
        self.history.clear()
        folder = self.folder() if self.only_this.isChecked() else None
        try:
            found = ops.runs(root=folder) if (folder or not self.only_this.isChecked()) else []
        except Exception:
            found = []
        for record in found:
            when = record["time"].replace("T", "  ")
            state = "  ·  undone" if record["undone"] else ""
            text = "%s%s\n%s\n%s" % (record["title"], state, when, record["summary"])
            if not self.only_this.isChecked():
                text += "\n%s" % record["root"]
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, record)
            item.setToolTip(record["root"])
            if record["undone"]:
                item.setForeground(self.palette().color(self.palette().ColorRole.PlaceholderText))
            self.history.addItem(item)
            if record["run"] == keep:
                self.history.setCurrentItem(item)
        if self.history.count() == 0:
            empty = QListWidgetItem("Nothing has been run here yet.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.history.addItem(empty)
        self._sync_undo()

    def _selected_run(self):
        item = self.history.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _sync_undo(self) -> None:
        run = self._selected_run()
        self.undo_button.setEnabled(bool(run) and not run.get("undone") and not self._busy())

    def undo_selected(self) -> None:
        run = self._selected_run()
        if not run:
            self.status("Pick a run in History first", "warning")
            return
        if run.get("undone"):
            self.status("That run was already undone", "info")
            return
        if self._busy():
            self.status("Wait for the running job to finish", "warning")
            return
        if not self.ask("Undo", "Put back what \"%s\" changed?\n\n%s\n%s"
                        % (run["title"], run["time"].replace("T", " "), run["root"])):
            return

        def work(ctx, run_id=run["run"]):
            restored, skipped, messages = ops.undo(run_id, ctx=ctx)
            for message in messages[:200]:
                ctx.warn(message)
            return "Put back %d change(s)%s" % (restored, ", %d left as they are" % skipped
                                                if skipped else "")

        job = Job("Undo  ·  %s" % run["title"], work)
        self._jobs_of_mine.add(job.id)
        self.submit(job)
        self._sync_run()

    # ── theme ─────────────────────────────────────────────
    def on_theme(self, theme) -> None:
        for position in range(self.op_list.count()):
            item = self.op_list.item(position)
            key = item.data(Qt.ItemDataRole.UserRole)
            item.setIcon(icons.icon(ICONS.get(key, "folder"), theme["text"], 18))

    def tool_close(self) -> bool:
        self._remember_options()
        return super().tool_close()
