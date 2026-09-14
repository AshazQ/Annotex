"""Image Sorter: by hand with number keys, by rule, or with an ONNX model."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QFileDialog, QGridLayout, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QPushButton, QSlider,
                               QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from annotex.core.jobs import Job
from annotex.ui.dialogs.common import hint, row
from annotex.ui.jobs import open_location
from annotex.ui.media_page import MediaToolPage
from annotex.ui.media_widgets import FitLabel, FrameView
from annotex.ui.widgets import section_label

from .. import ai, sorter
from ..common import scan_images

KEYS = [str(i) for i in range(1, 10)]


class SorterPage(MediaToolPage):
    TOOL_ID = "sorter"
    TOOL_NAME = "Image Sorter"
    TAGLINE = "Copy images into folders - by hand, by rule, or with a model"
    MARK = "box"
    DEFAULTS = {"recursive": True, "folders": ["keep", "reject", "", "", "", "", "", "", ""],
                "rule": "name_tokens", "tokens": 2, "regex": r"cam(\d+)", "granularity": "day",
                "threshold": 50, "multiple": "top", "imagenet": False, "last_source": ""}

    def build(self) -> None:
        self.source = ""
        self.images = []
        self.position = 0
        self.session = None
        self.model = None
        self.placed = {}                 # image -> set of folders (this session)

        top, top_layout = self.card()
        source_row = QHBoxLayout()
        source_row.addWidget(section_label("Images from"))
        self.source_edit = QLineEdit("")
        self.source_edit.setReadOnly(True)
        self.source_edit.setPlaceholderText("Choose a folder of images")
        source_row.addWidget(self.source_edit, 1)
        choose = QPushButton("Choose folder…")
        choose.clicked.connect(self.browse_folder)
        source_row.addWidget(choose)
        self.recursive = QCheckBox("Sub-folders")
        self.recursive.setChecked(bool(self.settings.get("recursive", True)))
        self.recursive.toggled.connect(lambda _c: self.set_source(self.source))
        source_row.addWidget(self.recursive)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Subtitle")
        source_row.addWidget(self.count_label)
        top_layout.addLayout(source_row)
        output_row = QHBoxLayout()
        output_row.addWidget(section_label("Copies go to"))
        self.output_edit = QLineEdit("")
        self.output_edit.setPlaceholderText("<source>_sorted")
        self.output_edit.editingFinished.connect(self._output_changed)
        output_row.addWidget(self.output_edit, 1)
        change = QPushButton("Change…")
        change.clicked.connect(self._choose_output)
        output_row.addWidget(change)
        open_button = QPushButton("Open")
        open_button.clicked.connect(lambda: self.output_root() and os.path.isdir(self.output_root())
                                    and open_location(self.output_root()))
        output_row.addWidget(open_button)
        undo_run = QPushButton("Undo a run…")
        undo_run.setToolTip("Remove every copy one earlier sort made")
        undo_run.clicked.connect(self.undo_a_run)
        output_row.addWidget(undo_run)
        top_layout.addLayout(output_row)
        top_layout.addWidget(hint("Sorting always copies - the originals stay exactly where they "
                                  "are. Every copy is logged in sort_log.csv, so any run can be undone."))

        self.tabs = QTabWidget()
        self.tabs.addTab(self._manual_tab(), "By hand")
        self.tabs.addTab(self._rules_tab(), "By rule")
        self.tabs.addTab(self._ai_tab(), "With a model (ONNX)")
        top_layout.addWidget(self.tabs, 1)
        self.splitter.addWidget(top)

        last = self.settings.get("last_source", "")
        if last and os.path.isdir(last):
            self.set_source(last)
        self._sync()

    # ══════════════════════════════════════════════════════
    # SOURCE & OUTPUT
    # ══════════════════════════════════════════════════════
    def browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Folder of images",
                                                  self.source or os.path.expanduser("~"))
        if folder:
            self.set_source(folder)

    def browse_files(self) -> None:
        self.browse_folder()

    def add_paths(self, paths) -> None:
        for path in paths:
            if os.path.isdir(path):
                self.set_source(path)
                return
            if os.path.isfile(path):
                self.set_source(os.path.dirname(path))
                return

    def set_source(self, folder) -> None:
        if not folder:
            return
        folder = os.path.abspath(folder)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            images = scan_images(folder, self.recursive.isChecked())
        finally:
            QApplication.restoreOverrideCursor()
        if self.source != folder:
            self.output_edit.setText(sorter.default_output(folder))
            self.session = None
            self.placed = {}
        self.source = folder
        self.images = images
        self.position = 0
        self.source_edit.setText(folder)
        self.count_label.setText("%d image(s)" % len(images))
        self.settings.update({"last_source": folder, "recursive": self.recursive.isChecked()})
        self.status("%d image(s) in %s" % (len(images), folder), "good" if images else "warning")
        self._show()
        self._sync()

    def output_root(self) -> str:
        return self.output_edit.text().strip() or (sorter.default_output(self.source) if self.source else "")

    def _output_changed(self) -> None:
        self.session = None

    def _choose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Where should the sorted copies go?",
                                                  self.output_root() or os.path.expanduser("~"))
        if folder:
            self.output_edit.setText(folder)
            self.session = None

    def _check_output(self) -> bool:
        output = self.output_root()
        if not self.images:
            self.status("Choose a folder with images first", "warning")
            return False
        if os.path.abspath(output) == os.path.abspath(self.source):
            self.status("The output must be a different folder from the images", "warning")
            return False
        return True

    def undo_a_run(self) -> None:
        output = self.output_root()
        runs = [r for r in sorter.runs(output) if r[2] > 0] if output else []
        if not runs:
            self.status("Nothing to undo in %s" % (output or "the output folder"), "info")
            return
        labels = ["%s  ·  %s  ·  %d copies" % (time.replace("T", " "), mode, live)
                  for _run, mode, live, time in runs]
        choice, accepted = QInputDialog.getItem(self, "Undo a run",
                                                "Remove every copy this run made:", labels, 0, False)
        if not accepted:
            return
        run_id = runs[labels.index(choice)][0]
        removed = sorter.undo_run(output, run_id)
        self.placed = {}
        self._show()
        self.status("Removed %d copies" % removed, "good")

    # ══════════════════════════════════════════════════════
    # BY HAND
    # ══════════════════════════════════════════════════════
    def _manual_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        viewer = QVBoxLayout()
        self.view = FrameView()
        self.view.message = "Choose a folder to start"
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        viewer.addWidget(self.view, 1)
        nav = QHBoxLayout()
        self.prev_button = QPushButton("←  Previous")
        self.prev_button.clicked.connect(lambda: self.step(-1))
        self.next_button = QPushButton("Skip  →")
        self.next_button.clicked.connect(lambda: self.step(1))
        self.undo_button = QPushButton("Undo  Ctrl+Z")
        self.undo_button.clicked.connect(self.undo_last)
        for button in (self.prev_button, self.next_button, self.undo_button):
            nav.addWidget(button)
        self.position_label = QLabel("")
        self.position_label.setObjectName("Subtitle")
        nav.addWidget(self.position_label, 1)
        viewer.addLayout(nav)
        self.placed_label = QLabel("")
        self.placed_label.setObjectName("Hint")
        viewer.addWidget(self.placed_label)
        layout.addLayout(viewer, 3)

        side = QVBoxLayout()
        side.addWidget(section_label("Keys and their folders"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        self.folder_edits = []
        saved = list(self.settings.get("folders") or [])
        for index, key in enumerate(KEYS):
            badge = QLabel(key)
            badge.setObjectName("Kbd")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit = QLineEdit(saved[index] if index < len(saved) else "")
            edit.setPlaceholderText("unused")
            edit.editingFinished.connect(self._remember_folders)
            grid.addWidget(badge, index, 0)
            grid.addWidget(edit, index, 1)
            self.folder_edits.append(edit)
        side.addLayout(grid)
        side.addWidget(hint("Press a number to copy the image into that folder and move on. "
                            "← → move without sorting. Ctrl+Z undoes the last copy."))
        side.addStretch(1)
        layout.addLayout(side, 1)

        for index, key in enumerate(KEYS):
            self._manual_key(key, lambda i=index: self.assign(i))
        self._manual_key("Left", lambda: self.step(-1))
        self._manual_key("Right", lambda: self.step(1))
        self._manual_key("Ctrl+Z", self.undo_last)
        self.manual_page = page
        return page

    def _manual_key(self, key, slot) -> None:
        shortcut = QShortcut(QKeySequence(key), self.view)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(slot)

    def _remember_folders(self) -> None:
        self.settings.set("folders", [e.text().strip() for e in self.folder_edits])

    def current_image(self):
        return self.images[self.position] if 0 <= self.position < len(self.images) else ""

    def _show(self) -> None:
        path = self.current_image()
        if not path:
            self.view.clear("Choose a folder to start" if not self.images else "All done")
            self.position_label.setText("")
            self.placed_label.setText("")
            return
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > 1800:
            reader.setScaledSize(size.scaled(1800, 1800, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            self.view.clear("Cannot read %s" % os.path.basename(path))
        else:
            self.view.set_image(image)
        self.position_label.setText("%d / %d  ·  %s" % (self.position + 1, len(self.images),
                                                         os.path.relpath(path, self.source)))
        placed = sorted(self.placed.get(path, ()))
        self.placed_label.setText("Copied to: %s" % ", ".join(placed) if placed else "")
        self.view.setFocus()

    def step(self, delta) -> None:
        if not self.images:
            return
        self.position = max(0, min(len(self.images) - 1, self.position + delta))
        self._show()

    def _session(self):
        output = self.output_root()
        if self.session is None or self.session.output_root != os.path.abspath(output):
            self.session = sorter.SortSession(output, "manual")
        return self.session

    def assign(self, index) -> None:
        path = self.current_image()
        if not path or not self._check_output():
            return
        folder = self.folder_edits[index].text().strip()
        if not folder:
            self.status("Key %s has no folder yet - type a name next to it" % KEYS[index], "warning")
            return
        try:
            destination = self._session().copy(path, folder, "key %s" % KEYS[index])
        except OSError as exc:
            self.status("Could not copy: %s" % exc, "danger")
            return
        self.placed.setdefault(path, set()).add(sorter.safe_folder_name(folder))
        self.status("%s → %s" % (os.path.basename(path), os.path.relpath(destination, self.output_root())),
                    "good")
        if self.position < len(self.images) - 1:
            self.position += 1
        self._show()

    def undo_last(self) -> None:
        if self.session is None:
            self.status("Nothing to undo", "info")
            return
        undone = self.session.undo_last()
        if undone is None:
            self.status("Nothing to undo", "info")
            return
        source, destination, category = undone
        self.placed.get(source, set()).discard(category)
        if source in self.images:
            self.position = self.images.index(source)
        self._show()
        self.status("Undid the copy into %s" % category, "good")

    # ══════════════════════════════════════════════════════
    # BY RULE
    # ══════════════════════════════════════════════════════
    def _rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        self.rule = QComboBox()
        for key, label in sorter.RULES.items():
            self.rule.addItem(label, key)
        self.rule.setCurrentIndex(max(0, self.rule.findData(self.settings.get("rule"))))
        layout.addWidget(row(QLabel("Sort by"), self.rule, stretch_last=True))

        self.rule_stack = QStackedWidget()
        self.tokens = QSpinBox()
        self.tokens.setRange(1, 10)
        self.tokens.setValue(int(self.settings.get("tokens", 2)))
        self.rule_stack.addWidget(row(QLabel("Use the first"), self.tokens,
                                      QLabel("parts of the name (SITE_cam3_… → SITE_cam3)"), None))
        self.regex = QLineEdit(self.settings.get("regex", ""))
        self.rule_stack.addWidget(row(QLabel("Pattern"), self.regex,
                                      QLabel("the first group names the folder"), stretch_last=False))
        self.granularity = QComboBox()
        for key, label in (("year", "Year"), ("month", "Month"), ("day", "Day"), ("hour", "Hour")):
            self.granularity.addItem(label, key)
        self.granularity.setCurrentIndex(max(0, self.granularity.findData(self.settings.get("granularity"))))
        self.rule_stack.addWidget(row(QLabel("One folder per"), self.granularity, None))
        self.rule_stack.addWidget(QLabel("One folder per exact size, e.g. 1920x1080."))
        self.rule_stack.addWidget(QLabel("landscape / portrait / square, after EXIF rotation."))
        self.save_dir = QLineEdit("")
        self.save_dir.setPlaceholderText("beside the images")
        self.rule_stack.addWidget(row(QLabel("Annotations are in"), self.save_dir, stretch_last=True))
        self.rule_stack.addWidget(QLabel("Uses roi_annotations.xlsx in each image folder."))
        layout.addWidget(self.rule_stack)
        self.rule.currentIndexChanged.connect(lambda i: self.rule_stack.setCurrentIndex(i))
        self.rule_stack.setCurrentIndex(self.rule.currentIndex())

        buttons = QHBoxLayout()
        preview = QPushButton("Preview")
        preview.clicked.connect(self.preview_rule)
        buttons.addWidget(preview)
        buttons.addStretch(1)
        self.rule_run = QPushButton("Sort")
        self.rule_run.setObjectName("Primary")
        self.rule_run.clicked.connect(self.run_rule)
        buttons.addWidget(self.rule_run)
        layout.addLayout(buttons)
        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setHorizontalHeaderLabels(["Folder", "Images", "For example"])
        self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        head = self.preview_table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.preview_table, 1)
        return page

    def categoriser(self):
        rule = self.rule.currentData()
        self.settings.update({"rule": rule, "tokens": self.tokens.value(), "regex": self.regex.text(),
                              "granularity": self.granularity.currentData()})
        return sorter.RuleCategoriser(rule, self.tokens.value(), self.regex.text(),
                                      self.granularity.currentData(), self.save_dir.text().strip())

    def preview_rule(self) -> None:
        if not self.images:
            self.status("Choose a folder with images first", "warning")
            return
        try:
            categoriser = self.categoriser()
        except ValueError as exc:
            self.status(str(exc), "warning")
            return
        limit = 3000
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            groups, errors = sorter.preview(self.images, categoriser, limit)
        finally:
            QApplication.restoreOverrideCursor()
        self.preview_table.setRowCount(len(groups))
        for index, (folder, images) in enumerate(groups.items()):
            self.preview_table.setItem(index, 0, QTableWidgetItem(folder))
            self.preview_table.setItem(index, 1, QTableWidgetItem(str(len(images))))
            self.preview_table.setItem(index, 2, QTableWidgetItem(
                ", ".join(os.path.basename(i) for i in images[:3])))
        note = " (first %d images)" % limit if len(self.images) > limit else ""
        self.status("%d folder(s)%s%s" % (len(groups), note,
                                          ", %d unreadable" % len(errors) if errors else ""),
                    "warning" if errors else "good")

    def run_rule(self) -> None:
        if not self._check_output():
            return
        try:
            categoriser = self.categoriser()
        except ValueError as exc:
            self.status(str(exc), "warning")
            return
        images, output = list(self.images), self.output_root()
        self.submit(Job("Sort by rule · %d image(s)" % len(images),
                        lambda ctx: sorter.run_sort(ctx, images, categoriser, output, "rules")[0]))

    # ══════════════════════════════════════════════════════
    # WITH A MODEL
    # ══════════════════════════════════════════════════════
    def _ai_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        self.ai_missing = hint(ai.INSTALL_HINT)
        layout.addWidget(self.ai_missing)

        self.model_edit = QLineEdit("")
        self.model_edit.setPlaceholderText("model.onnx")
        browse_model = QPushButton("Browse…")
        browse_model.clicked.connect(lambda: self._pick(self.model_edit, "ONNX models (*.onnx)"))
        layout.addWidget(row(QLabel("Model"), self.model_edit, browse_model))
        self.labels_edit = QLineEdit("")
        self.labels_edit.setPlaceholderText("optional - one class name per line; else read from the model")
        browse_labels = QPushButton("Browse…")
        browse_labels.clicked.connect(lambda: self._pick(self.labels_edit, "Text files (*.txt);;All files (*)"))
        layout.addWidget(row(QLabel("Class names"), self.labels_edit, browse_labels))
        self.imagenet = QCheckBox("ImageNet normalisation (for most torchvision classifiers)")
        self.imagenet.setChecked(bool(self.settings.get("imagenet")))
        load_row = QHBoxLayout()
        load_row.addWidget(self.imagenet)
        load_row.addStretch(1)
        self.load_button = QPushButton("Load model")
        self.load_button.clicked.connect(self.load_model)
        load_row.addWidget(self.load_button)
        layout.addLayout(load_row)
        self.model_label = QLabel("No model loaded.")
        self.model_label.setObjectName("Hint")
        self.model_label.setWordWrap(True)
        layout.addWidget(self.model_label)

        self.threshold = QSlider(Qt.Orientation.Horizontal)
        self.threshold.setRange(5, 95)
        self.threshold.setValue(int(self.settings.get("threshold", 50)))
        self.threshold_value = QLabel("")
        self.threshold.valueChanged.connect(lambda v: self.threshold_value.setText("%.2f" % (v / 100.0)))
        self.threshold_value.setText("%.2f" % (self.threshold.value() / 100.0))
        layout.addWidget(row(QLabel("Confidence at least"), self.threshold, self.threshold_value))
        self.multiple = QComboBox()
        self.multiple.addItem("the most confident class", "top")
        self.multiple.addItem("every class found (one copy each)", "all")
        self.multiple.setCurrentIndex(max(0, self.multiple.findData(self.settings.get("multiple"))))
        layout.addWidget(row(QLabel("When a detector finds several classes, copy to"), self.multiple,
                             stretch_last=True))
        layout.addWidget(hint("Below the threshold, a classifier's image goes to _unsure and a "
                              "detector's to _empty. Clear a folder name to ignore that class."))

        self.mapping = QTableWidget(0, 2)
        self.mapping.setHorizontalHeaderLabels(["Class", "Folder"])
        self.mapping.verticalHeader().setVisible(False)
        self.mapping.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.mapping.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.mapping, 1)

        buttons = QHBoxLayout()
        self.test_button = QPushButton("Test on the image shown in ‘By hand’")
        self.test_button.clicked.connect(self.test_model)
        buttons.addWidget(self.test_button)
        buttons.addStretch(1)
        self.ai_run = QPushButton("Sort")
        self.ai_run.setObjectName("Primary")
        self.ai_run.clicked.connect(self.run_ai)
        buttons.addWidget(self.ai_run)
        layout.addLayout(buttons)
        self.test_label = FitLabel("")
        self.test_label.setObjectName("Mono")
        self.test_label.setWordWrap(True)
        layout.addWidget(self.test_label)
        return page

    def _pick(self, edit, file_filter) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Choose a file",
                                                    os.path.dirname(edit.text()) or os.path.expanduser("~"),
                                                    file_filter)
        if path:
            edit.setText(path)

    def load_model(self) -> None:
        path = self.model_edit.text().strip()
        labels = None
        try:
            if self.labels_edit.text().strip():
                labels = ai.read_labels(self.labels_edit.text().strip())
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.model = ai.OnnxModel(path, labels, imagenet_norm=self.imagenet.isChecked())
            finally:
                QApplication.restoreOverrideCursor()
        except (ai.AIUnavailable, ValueError, OSError) as exc:
            self.model = None
            self.model_label.setText(str(exc))
            self.status("The model could not be loaded", "danger")
            self._sync()
            return
        model = self.model
        self.settings.set("imagenet", self.imagenet.isChecked())
        self.model_label.setText("%s · input %dx%d · %d class(es)%s" % (
            model.kind, model.width, model.height, len(model.labels),
            "" if model.labels else " - no names found; add a class names file"))
        self.mapping.setRowCount(len(model.labels))
        for index, label in enumerate(model.labels):
            item = QTableWidgetItem(label)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.mapping.setItem(index, 0, item)
            self.mapping.setItem(index, 1, QTableWidgetItem(label))
        self.status("Model loaded", "good")
        self._sync()

    def mapping_dict(self):
        out = {}
        for index in range(self.mapping.rowCount()):
            label = self.mapping.item(index, 0).text()
            folder = self.mapping.item(index, 1).text().strip() if self.mapping.item(index, 1) else ""
            out[label] = folder
        return out

    def test_model(self) -> None:
        path = self.current_image()
        if self.model is None or not path:
            self.status("Load a model and choose images first", "warning")
            return
        try:
            prediction = self.model.predict(path)
        except Exception as exc:                                     # noqa: BLE001
            self.test_label.setText("Failed: %s" % exc)
            return
        folders, detail = ai.categorise(prediction, self.threshold.value() / 100.0,
                                        self.multiple.currentData(), self.mapping_dict())
        best = sorted(prediction.scores.items(), key=lambda kv: kv[1], reverse=True)[:5]
        self.test_label.setText("%s → %s\n%s" % (os.path.basename(path), ", ".join(folders),
                                                 "   ".join("%s %.2f" % kv for kv in best)))

    def run_ai(self) -> None:
        if self.model is None:
            self.status("Load a model first", "warning")
            return
        if not self._check_output():
            return
        model, images, output = self.model, list(self.images), self.output_root()
        threshold, multiple = self.threshold.value() / 100.0, self.multiple.currentData()
        mapping = self.mapping_dict()
        self.settings.update({"threshold": self.threshold.value(), "multiple": multiple})
        self.submit(Job("Sort with %s · %d image(s)" % (os.path.basename(self.model_edit.text()), len(images)),
                        lambda ctx: sorter.run_sort(ctx, images, lambda p: ai.categorise(
                            model.predict(p), threshold, multiple, mapping), output, "ai")[0]))

    # ══════════════════════════════════════════════════════
    def _sync(self) -> None:
        available = ai.available()
        self.ai_missing.setVisible(not available)
        for widget in (self.model_edit, self.labels_edit, self.load_button, self.imagenet):
            widget.setEnabled(available)
        loaded = self.model is not None
        for widget in (self.test_button, self.ai_run, self.threshold, self.multiple, self.mapping):
            widget.setEnabled(loaded)
        has_images = bool(self.images)
        self.rule_run.setEnabled(has_images)
        self.rule_run.setText("Sort %d image(s)" % len(self.images) if has_images else "Sort")
        self.ai_run.setText("Sort %d image(s)" % len(self.images) if has_images else "Sort")
        for button in (self.prev_button, self.next_button):
            button.setEnabled(has_images)

    def tool_activated(self) -> None:
        self.view.setFocus()
