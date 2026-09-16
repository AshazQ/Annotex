"""The Image Sorter's fourth way: by example.

Three steps, in the order a person takes them:

    1. point it at a folder of examples, one sub-folder per category;
    2. Compare - the slow part, run as a job, and cached, so doing it again
       with different examples costs only what changed;
    3. look at the split, drag the two sliders until the pictures shown land
       where they should, then Sort.

Step 3 is the one that matters.  How alike two pictures score depends on
the pictures, so the sliders start where the examples themselves suggest,
the table lists the weakest matches first - they are exactly the ones a
threshold decides - and clicking any row shows the picture.  Nothing is
copied until Sort, and Sort copies, logs and can be undone like every other
way of sorting here.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from annotex.core.ai import embed
from annotex.core.jobs import Job
from annotex.ui import design
from annotex.ui.dialogs.common import hint, row
from annotex.ui.media_widgets import FrameView

from .. import reference, sorter
from ..sorter import UNMATCHED, UNSURE

MAX_ROWS = 1000                  # the table is for looking, not for every image
PREVIEW_SIDE = 900               # px a preview is decoded at, at most


def _score(value) -> str:
    return "%.3f" % value


class ReferenceTab(QWidget):
    """Sort by example.  Lives inside SorterPage and borrows its folder,
    output, jobs and status line."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.comparison = None
        self._compared_for = None        # what the comparison was made from
        self._job_id = None
        self._result = {}
        settings = page.settings

        layout = QVBoxLayout(self)
        design.margins(layout, "s", "0", "0", "0")
        self.missing = hint(embed.install_hint())
        layout.addWidget(self.missing)

        # ── 1. the examples ───────────────────────────────
        self.ref_edit = QLineEdit(str(settings.get("ref_folder", "") or ""))
        self.ref_edit.setPlaceholderText("a folder with one sub-folder of examples per category")
        self.ref_edit.editingFinished.connect(self._references_changed)
        browse = QPushButton("Choose…")
        browse.clicked.connect(self.browse_references)
        layout.addWidget(row(QLabel("Examples"), self.ref_edit, browse))
        self.ref_summary = hint("")
        layout.addWidget(self.ref_summary)

        self.embedder = QComboBox()
        self.embedder.addItem("How they look - nothing to download", reference.EMBED_CLASSIC)
        self.embedder.addItem("What is in them - an ONNX image model", reference.EMBED_ONNX)
        self.embedder.setToolTip(
            "How they look compares layout and colour: right for the same scene, the same "
            "camera, near-duplicates.  What is in them needs an image model such as a CLIP "
            "or DINOv2 image encoder exported to ONNX, and is right for \"more pictures of "
            "this kind of thing\".")
        found = self.embedder.findData(settings.get("ref_embedder", reference.EMBED_CLASSIC))
        self.embedder.setCurrentIndex(max(0, found))
        self.embedder.currentIndexChanged.connect(self._embedder_changed)
        self.combine = QComboBox()
        self.combine.addItem("its closest example", reference.COMBINE_NEAREST)
        self.combine.addItem("its examples on average", reference.COMBINE_AVERAGE)
        found = self.combine.findData(settings.get("ref_combine", reference.COMBINE_NEAREST))
        self.combine.setCurrentIndex(max(0, found))
        self.combine.currentIndexChanged.connect(lambda _i: self._invalidate())
        # The Compare button sits at the end of the row it acts on: one row
        # fewer, which is a row more of pictures on a laptop screen.
        self.compare_button = QPushButton("Compare")
        self.compare_button.setObjectName("Primary")
        self.compare_button.clicked.connect(self.compare)
        layout.addWidget(row(QLabel("Compare by"), self.embedder, QLabel("against"),
                             self.combine, None, self.compare_button))

        self.model_edit = QLineEdit(str(settings.get("ref_model", "") or ""))
        self.model_edit.setPlaceholderText("image_encoder.onnx")
        self.model_edit.editingFinished.connect(self._invalidate)
        self.model_browse = QPushButton("Browse…")
        self.model_browse.clicked.connect(self.browse_model)
        self.model_row = row(QLabel("Model"), self.model_edit, self.model_browse)
        layout.addWidget(self.model_row)

        self.compare_note = hint("")
        layout.addWidget(self.compare_note)

        # ── 2. the settings, over the comparison ──────────
        self.threshold = QSlider(Qt.Orientation.Horizontal)
        self.threshold.setRange(0, 99)
        self.threshold.setValue(int(round(reference.DEFAULT_THRESHOLD * 100)))
        self.threshold_value = QLabel("")
        self.threshold.valueChanged.connect(self._settings_moved)
        self.margin = QSlider(Qt.Orientation.Horizontal)
        self.margin.setRange(0, 30)
        self.margin.setValue(int(round(reference.DEFAULT_MARGIN * 100)))
        self.margin_value = QLabel("")
        self.margin.valueChanged.connect(self._settings_moved)
        sliders = QHBoxLayout()
        sliders.setSpacing(design.SPACE["s"])
        for label, slider, value, tip in (
                ("Alike at least", self.threshold, self.threshold_value,
                 "Below this an image goes to _unmatched"),
                ("ahead of the next by", self.margin, self.margin_value,
                 "Closer than this to a second category, an image goes to _unsure")):
            caption = QLabel(label)
            caption.setToolTip(tip)
            slider.setToolTip(tip)
            sliders.addWidget(caption)
            sliders.addWidget(slider, 1)
            sliders.addWidget(value)
        layout.addLayout(sliders)

        self.split_label = QLabel("")
        self.split_label.setObjectName("Mono")
        self.split_label.setWordWrap(True)
        self.every = QCheckBox("Every close category")
        self.every.setToolTip("Copy an image to every category it is alike enough to, "
                              "not only the best one")
        self.every.setChecked(bool(settings.get("ref_all", False)))
        self.every.toggled.connect(self._settings_moved)
        self.sort_button = QPushButton("Sort")
        self.sort_button.setObjectName("Primary")
        self.sort_button.clicked.connect(self.run_sort)
        outcome = QHBoxLayout()
        outcome.setSpacing(design.SPACE["s"])
        outcome.addWidget(self.split_label, 1)
        outcome.addWidget(self.every)
        outcome.addWidget(self.sort_button)
        layout.addLayout(outcome)
        self.calibration = hint("")
        layout.addWidget(self.calibration)

        # ── 3. what it decided, picture by picture ────────
        looking = QHBoxLayout()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Image", "Most like", "Alike", "Next best",
                                              "Goes to"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            head.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._show_selected)
        looking.addWidget(self.table, 3)
        self.preview = FrameView()
        self.preview.setMinimumSize(200, 150)
        self.preview.clear("Click a row to see the picture")
        try:
            self.preview.set_theme(page.theme)
        except Exception:
            pass
        looking.addWidget(self.preview, 2)
        layout.addLayout(looking, 1)
        self.table.setToolTip("Weakest matches first - they are the ones the threshold "
                              "decides.  Click one to see it.")

        self._rows = []
        page.jobs.jobFinished.connect(self._job_finished)
        self._references_changed(quiet=True)
        self._settings_moved()
        self.sync()

    # ══════════════════════════════════════════════════════
    # CHOOSING
    # ══════════════════════════════════════════════════════
    def browse_references(self) -> None:
        start = self.ref_edit.text().strip() or self.page.source or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Folder of examples", start)
        if folder:
            self.ref_edit.setText(folder)
            self._references_changed()

    def browse_model(self) -> None:
        start = os.path.dirname(self.model_edit.text()) or os.path.expanduser("~")
        path, _filter = QFileDialog.getOpenFileName(self, "Image model", start,
                                                    "ONNX models (*.onnx)")
        if path:
            self.model_edit.setText(path)
            self._invalidate()

    def categories(self):
        """The categories the chosen folder holds, or None with the reason shown."""
        try:
            found = reference.read_references(self.ref_edit.text().strip())
        except reference.ReferenceError as exc:
            self.ref_summary.setText(str(exc))
            return None
        self.ref_summary.setText(reference.describe_references(found))
        return found

    def _references_changed(self, quiet=False) -> None:
        folder = self.ref_edit.text().strip()
        self.page.settings.set("ref_folder", folder)
        if folder:
            self.categories()
        else:
            self.ref_summary.setText("Make a folder with one sub-folder per category and a "
                                     "few example pictures in each.")
        self._invalidate()

    def _embedder_changed(self, _index=0) -> None:
        self.page.settings.set("ref_embedder", self.embedder.currentData())
        self._invalidate()

    # ══════════════════════════════════════════════════════
    # COMPARING
    # ══════════════════════════════════════════════════════
    def _recipe(self):
        """Everything a comparison depends on, to tell when it is out of date."""
        return (self.ref_edit.text().strip(), self.embedder.currentData(),
                self.model_edit.text().strip(), self.combine.currentData(),
                self.page.source, len(self.page.images))

    def _invalidate(self) -> None:
        if self.comparison is not None and self._compared_for != self._recipe():
            self.comparison = None
            self._fill_table()
        self.sync()

    def compare(self) -> None:
        if not self.page.images:
            self.page.status("Choose a folder of images to sort first", "warning")
            return
        categories = self.categories()
        if categories is None:
            self.page.status("The examples cannot be used yet - see the note under them",
                             "warning")
            return
        kind = self.embedder.currentData()
        model = self.model_edit.text().strip()
        if kind == reference.EMBED_ONNX and not os.path.isfile(model):
            self.page.status("Choose the ONNX image model to compare with", "warning")
            return
        images = reference.images_to_sort(self.page.images, categories)
        if not images:
            self.page.status("Every image in that folder is one of the examples", "warning")
            return
        combine = self.combine.currentData()
        self.page.settings.update({"ref_model": model, "ref_combine": combine,
                                   "ref_embedder": kind})
        recipe = self._recipe()
        result = {}

        def work(ctx):
            embedder = reference.make_embedder(kind, model)

            def progress(done, total, message=""):
                ctx.progress(done / float(total or 1), "%s  ·  %d of %d"
                             % (message or "Comparing", done, total))
            comparison = reference.compare(embedder, categories, images, combine,
                                           progress=progress,
                                           cancelled=lambda: ctx.cancelled)
            if comparison is None:
                from annotex.core.jobs import JobCancelled
                raise JobCancelled()
            for path, why in comparison.errors[:20]:
                ctx.warn("%s: %s" % (os.path.basename(path), why))
            result["comparison"] = comparison
            result["recipe"] = recipe
            return "Compared %d image(s) with %s" % (len(comparison),
                                                     reference.describe_references(categories))

        job = self.page.submit(Job("Compare with examples · %d image(s)" % len(images), work))
        self._job_id = job.id
        self._result = result
        self.compare_note.setText("Comparing - it runs in the background, and the images "
                                  "it has seen before are remembered…")
        self.sync()

    def _job_finished(self, job) -> None:
        if job.id != self._job_id:
            return
        self._job_id = None
        comparison = self._result.get("comparison")
        if job.state != "done" or comparison is None:
            self.compare_note.setText(job.error or "The comparison did not finish.")
            self.sync()
            return
        self.comparison = comparison
        self._compared_for = self._result.get("recipe")
        threshold, margin = comparison.suggested
        # The examples' own suggestion goes onto the sliders; from here on the
        # person moves them, and nothing is recomputed but the decisions.
        self.threshold.blockSignals(True)
        self.margin.blockSignals(True)
        self.threshold.setValue(max(0, min(99, int(round(threshold * 100)))))
        self.margin.setValue(max(0, min(30, int(round(margin * 100)))))
        self.threshold.blockSignals(False)
        self.margin.blockSignals(False)
        self.calibration.setText("Started where your examples suggest: %s." % comparison.calibration
                                 if comparison.calibration else "")
        errors = len(comparison.errors)
        self.compare_note.setText("%d image(s) compared%s." % (
            len(comparison), ", %d could not be read" % errors if errors else ""))
        self._fill_table()
        self._settings_moved()
        self.sync()

    # ══════════════════════════════════════════════════════
    # DECIDING
    # ══════════════════════════════════════════════════════
    def settings_now(self):
        return (self.threshold.value() / 100.0, self.margin.value() / 100.0,
                "all" if self.every.isChecked() else "top")

    def _fill_table(self) -> None:
        comparison = self.comparison
        self.table.setRowCount(0)
        self._rows = []
        if comparison is None:
            self.preview.clear("Click a row to see the picture")
            return
        order = sorted(range(len(comparison)),
                       key=lambda i: comparison.ranked(i)[0][1] if comparison.categories else 0)
        self._rows = order[:MAX_ROWS]
        self.table.setRowCount(len(self._rows))
        source = self.page.source or ""
        for row_index, index in enumerate(self._rows):
            path = comparison.paths[index]
            ranked = comparison.ranked(index)
            name = os.path.relpath(path, source) if source else os.path.basename(path)
            cells = [name, ranked[0][0] if ranked else "",
                     _score(ranked[0][1]) if ranked else "",
                     "%s %s" % (ranked[1][0], _score(ranked[1][1])) if len(ranked) > 1 else "",
                     ""]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setToolTip(path)
                self.table.setItem(row_index, column, item)

    def _settings_moved(self, *_args) -> None:
        threshold, margin, multiple = self.settings_now()
        self.threshold_value.setText("%.2f" % threshold)
        self.margin_value.setText("%.2f" % margin)
        self.page.settings.set("ref_all", self.every.isChecked())
        comparison = self.comparison
        if comparison is None:
            self.split_label.setText("")
            return
        split = comparison.split(threshold, margin, multiple)
        self.split_label.setText("   ".join("%s %d" % kv for kv in split.items()) or
                                 "nothing to sort")
        for row_index, index in enumerate(self._rows):
            folders, _detail = comparison.decide(index, threshold, margin, multiple)
            item = self.table.item(row_index, 4)
            if item is not None:
                item.setText(", ".join(folders))
                special = folders[0] in (UNSURE, UNMATCHED)
                item.setToolTip("Left out - look at these" if special else "")

    def _show_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if len(rows) != 1 or self.comparison is None:
            return
        row_index = rows.pop()
        if not 0 <= row_index < len(self._rows):
            return
        path = self.comparison.paths[self._rows[row_index]]
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > PREVIEW_SIDE:
            reader.setScaledSize(size.scaled(PREVIEW_SIDE, PREVIEW_SIDE,
                                             Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            self.preview.clear("Cannot read %s" % os.path.basename(path))
        else:
            self.preview.set_image(image)

    # ══════════════════════════════════════════════════════
    # SORTING
    # ══════════════════════════════════════════════════════
    def run_sort(self) -> None:
        comparison = self.comparison
        if comparison is None or self._compared_for != self._recipe():
            self.page.status("Compare first - the images or the examples have changed",
                             "warning")
            self._invalidate()
            return
        if not self.page._check_output():
            return
        threshold, margin, multiple = self.settings_now()
        categorise = comparison.categoriser(threshold, margin, multiple)
        paths, output = list(comparison.paths), self.page.output_root()
        self.page.settings.update({"ref_threshold": self.threshold.value(),
                                   "ref_margin": self.margin.value()})
        self.page.submit(Job("Sort by example · %d image(s)" % len(paths),
                             lambda ctx: sorter.run_sort(ctx, paths, categorise, output,
                                                         reference.MODE)[0]))

    def sync(self) -> None:
        missing = bool(embed.missing_packages())
        self.missing.setVisible(missing)
        onnx = self.embedder.currentData() == reference.EMBED_ONNX
        self.model_row.setVisible(onnx)
        running = self._job_id is not None
        self.compare_button.setEnabled(not missing and not running and bool(self.page.images))
        ready = self.comparison is not None and self._compared_for == self._recipe()
        for widget in (self.threshold, self.margin, self.every, self.table):
            widget.setEnabled(ready)
        self.sort_button.setEnabled(ready and not running)
        self.sort_button.setText("Sort %d image(s)" % len(self.comparison)
                                 if ready else "Sort")
        if not ready and not running and not self.compare_note.text():
            self.compare_note.setText("Compare works out how alike every image is to your "
                                      "examples; then the sliders decide where each goes.")
