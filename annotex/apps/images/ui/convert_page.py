"""Image Converter."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSlider, QSpinBox, QStackedWidget, QWidget)

from annotex.core.jobs import Job
from annotex.core.media.ffmpeg import human_size
from annotex.ui.dialogs.common import ColourButton, hint, row
from annotex.ui.media_page import MediaToolPage
from annotex.ui.media_widgets import FitLabel, FileList, FrameView, OutputChooser
from annotex.ui.widgets import section_label

from .. import convert
from ..common import IMAGE_EXTS, scan_images, validate_pattern

IMAGE_FILTER = "Images (%s);;All files (*)" % " ".join("*" + e for e in IMAGE_EXTS)
RESIZE = (("none", "Keep the size"), ("max", "Longest side at most"),
          ("percent", "Scale by percent"), ("exact", "Fit a width and height"))


class ImageConvertPage(MediaToolPage):
    TOOL_ID = "iconvert"
    TOOL_NAME = "Image Converter"
    TAGLINE = "Change format, size, quality and names of many images at once"
    MARK = "box"
    DEFAULTS = {"target": "jpg", "resize": "none", "max_side": 1920, "percent": 50,
                "width": 1280, "height": 720, "keep_aspect": True, "never_upscale": True,
                "quality": 90, "png_level": 6, "webp_lossless": False, "strip": True,
                "background": "#ffffff", "pattern": "{name}", "start": 1}

    def build(self) -> None:
        self.roots = {}
        left, left_layout = self.card()
        self.files = FileList("Images", IMAGE_EXTS, self._scan, IMAGE_FILTER)
        self.files.currentChanged.connect(self._preview)
        self.files.changed.connect(self._sync)
        left_layout.addWidget(self.files)
        self.recursive = QCheckBox("Include sub-folders when adding a folder")
        self.recursive.setChecked(True)
        left_layout.addWidget(self.recursive)
        self.splitter.addWidget(left)

        centre, centre_layout = self.card()
        self.view = FrameView()
        self.view.message = "Select an image to preview it"
        centre_layout.addWidget(self.view, 1)
        self.before_after = FitLabel("")
        self.before_after.setObjectName("Hint")
        self.before_after.setWordWrap(True)
        centre_layout.addWidget(self.before_after)
        centre_layout.addWidget(section_label("First output names"))
        self.names = FitLabel("")
        self.names.setObjectName("Mono")
        self.names.setWordWrap(True)
        centre_layout.addWidget(self.names)
        self.splitter.addWidget(centre)

        options, layout = self.scroll_card()
        layout.addWidget(section_label("Format"))
        self.target = QComboBox()
        for key, (label, _fmt, _ext) in convert.TARGETS.items():
            self.target.addItem(label, key)
        layout.addWidget(self.target)
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(1, 100)
        self.quality_value = QLabel("")
        self.quality_row = row(QLabel("Quality"), self.quality, self.quality_value)
        layout.addWidget(self.quality_row)
        self.png_level = QSpinBox()
        self.png_level.setRange(0, 9)
        self.png_row = row(QLabel("PNG compression"), self.png_level, QLabel("(9 = smallest, slowest)"))
        layout.addWidget(self.png_row)
        self.webp_lossless = QCheckBox("Lossless WebP")
        layout.addWidget(self.webp_lossless)
        self.background = ColourButton("#ffffff")
        layout.addWidget(row(QLabel("Fill transparency with"), None, self.background))

        layout.addWidget(section_label("Size"))
        self.resize_mode = QComboBox()
        for key, label in RESIZE:
            self.resize_mode.addItem(label, key)
        layout.addWidget(self.resize_mode)
        self.resize_stack = QStackedWidget()
        self.resize_stack.addWidget(QWidget())
        self.max_side = QSpinBox()
        self.max_side.setRange(16, 20000)
        self.max_side.setSuffix(" px")
        self.resize_stack.addWidget(self.max_side)
        self.percent = QSpinBox()
        self.percent.setRange(1, 1000)
        self.percent.setSuffix(" %")
        self.resize_stack.addWidget(self.percent)
        exact = QWidget()
        exact_row = QHBoxLayout(exact)
        exact_row.setContentsMargins(0, 0, 0, 0)
        self.width_box = QSpinBox()
        self.height_box = QSpinBox()
        for box in (self.width_box, self.height_box):
            box.setRange(1, 20000)
            box.setSuffix(" px")
        exact_row.addWidget(self.width_box)
        exact_row.addWidget(QLabel("×"))
        exact_row.addWidget(self.height_box)
        self.resize_stack.addWidget(exact)
        layout.addWidget(self.resize_stack)
        self.keep_aspect = QCheckBox("Keep the proportions (fit inside the box)")
        self.never_upscale = QCheckBox("Never make an image larger")
        layout.addWidget(self.keep_aspect)
        layout.addWidget(self.never_upscale)

        layout.addWidget(section_label("Metadata"))
        self.strip = QCheckBox("Remove EXIF (camera, GPS, time) and apply its rotation")
        layout.addWidget(self.strip)

        layout.addWidget(section_label("Names"))
        self.pattern = QLineEdit("")
        layout.addWidget(row(QLabel("Pattern"), self.pattern, stretch_last=True))
        self.start = QSpinBox()
        self.start.setRange(0, 10000000)
        layout.addWidget(row(QLabel("Start {n} at"), self.start, None))
        layout.addWidget(hint("{name} original name  ·  {n} number, {n:05} zero-padded  ·  "
                              "{parent} folder name  ·  {ext} new extension"))
        self.pattern_error = QLabel("")
        self.pattern_error.setObjectName("HintDanger")
        self.pattern_error.setWordWrap(True)
        layout.addWidget(self.pattern_error)

        layout.addWidget(section_label("Output"))
        self.output = OutputChooser("Beside the originals, in converted/")
        layout.addWidget(self.output)
        layout.addWidget(hint("Originals are never changed, and existing files are never "
                              "overwritten."))
        layout.addStretch(1)
        self.run = QPushButton("Convert")
        self.run.setObjectName("Primary")
        self.run.clicked.connect(self.convert_all)
        layout.addWidget(self.run)
        self.splitter.addWidget(options)
        self.splitter.setSizes([320, 640, 420])

        self._restore()
        for signal in (self.target.currentIndexChanged, self.quality.valueChanged,
                       self.png_level.valueChanged, self.webp_lossless.toggled,
                       self.resize_mode.currentIndexChanged, self.max_side.valueChanged,
                       self.percent.valueChanged, self.width_box.valueChanged,
                       self.height_box.valueChanged, self.keep_aspect.toggled,
                       self.never_upscale.toggled, self.strip.toggled, self.pattern.textChanged,
                       self.start.valueChanged, self.output.changed):
            signal.connect(lambda *_a: self._sync())
        self._sync()

    def _restore(self) -> None:
        s = self.settings
        self.target.setCurrentIndex(max(0, self.target.findData(s.get("target"))))
        self.resize_mode.setCurrentIndex(max(0, self.resize_mode.findData(s.get("resize"))))
        self.max_side.setValue(int(s.get("max_side")))
        self.percent.setValue(int(s.get("percent")))
        self.width_box.setValue(int(s.get("width")))
        self.height_box.setValue(int(s.get("height")))
        self.keep_aspect.setChecked(bool(s.get("keep_aspect")))
        self.never_upscale.setChecked(bool(s.get("never_upscale")))
        self.quality.setValue(int(s.get("quality")))
        self.png_level.setValue(int(s.get("png_level")))
        self.webp_lossless.setChecked(bool(s.get("webp_lossless")))
        self.strip.setChecked(bool(s.get("strip")))
        self.background.set_colour(s.get("background"))
        self.pattern.setText(s.get("pattern") or "{name}")
        self.start.setValue(int(s.get("start", 1)))

    # ── inputs ────────────────────────────────────────────
    def _scan(self, folder):
        found = scan_images(folder, self.recursive.isChecked())
        for path in found:
            self.roots.setdefault(path, folder)
        return found

    def browse_files(self) -> None:
        self.files.browse_files()

    def browse_folder(self) -> None:
        self.files.browse_folder()

    def add_paths(self, paths) -> None:
        added = self.files.add_paths(paths)
        self.status("Added %d image(s)" % added if added else "No new images found there",
                    "good" if added else "warning")

    def items(self):
        return [(path, self.roots.get(path, os.path.dirname(path))) for path in self.files.paths()]

    # ── options ───────────────────────────────────────────
    def options(self) -> convert.ImageOptions:
        return convert.ImageOptions(
            target=self.target.currentData(), resize=self.resize_mode.currentData(),
            max_side=self.max_side.value(), percent=self.percent.value(),
            width=self.width_box.value(), height=self.height_box.value(),
            keep_aspect=self.keep_aspect.isChecked(), never_upscale=self.never_upscale.isChecked(),
            quality=self.quality.value(), png_level=self.png_level.value(),
            webp_lossless=self.webp_lossless.isChecked(), strip_metadata=self.strip.isChecked(),
            background=self.background.colour(), pattern=self.pattern.text(),
            start_number=self.start.value())

    def _sync(self) -> None:
        target = self.target.currentData()
        self.quality_value.setText(str(self.quality.value()))
        self.quality_row.setVisible(target in ("jpg", "webp", "keep"))
        self.png_row.setVisible(target in ("png", "keep"))
        self.webp_lossless.setVisible(target in ("webp", "keep"))
        self.resize_stack.setCurrentIndex(self.resize_mode.currentIndex())
        self.keep_aspect.setVisible(self.resize_mode.currentData() == "exact")
        self.never_upscale.setVisible(self.resize_mode.currentData() != "none")
        error = validate_pattern(self.pattern.text())
        self.pattern_error.setText(error or "")
        items = self.items()
        self.run.setEnabled(bool(items) and not error)
        self.run.setText("Convert %d image(s)" % len(items) if items else "Convert")
        if error or not items:
            self.names.setText("")
        else:
            roots = dict(items[:6])
            out = self.output.folder()
            planned = convert.plan(items[:6], self.options(), out)
            self.names.setText("\n".join("%s  →  %s" % (
                os.path.relpath(s, roots.get(s, os.path.dirname(s))),
                os.path.relpath(d, out or roots.get(s, os.path.dirname(s))))
                for s, d in planned))
        self._preview(self.files.current_path())

    def _preview(self, path) -> None:
        if not path:
            self.view.clear("Select an image to preview it")
            self.before_after.setText("")
            return
        reader = QImageReader(path)
        reader.setAutoTransform(self.strip.isChecked())
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > 1600:
            reader.setScaledSize(size.scaled(1600, 1600, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            self.view.clear("This image cannot be read")
            self.before_after.setText(reader.errorString())
            return
        self.view.set_image(image)
        try:
            from PIL import Image, ImageOps
            with Image.open(path) as opened:
                original = opened.size
                shown = ImageOps.exif_transpose(opened).size if self.strip.isChecked() else original
                kind = opened.format
            options = self.options()
            new = convert.new_size(shown, options)
            target = convert.TARGETS[convert.target_key(options, path)][1]
            self.before_after.setText("Now: %dx%d %s · %s\nAfter: %dx%d %s" % (
                original[0], original[1], kind, human_size(os.path.getsize(path)),
                new[0], new[1], target))
        except Exception as exc:                                      # noqa: BLE001
            self.before_after.setText(str(exc))

    # ── run ───────────────────────────────────────────────
    def convert_all(self) -> None:
        options = self.options()
        error = validate_pattern(options.pattern)
        if error:
            self.status(error, "warning")
            return
        items = self.items()
        if not items:
            self.status("Add images first", "warning")
            return
        self.settings.update({"target": options.target, "resize": options.resize,
                              "max_side": options.max_side, "percent": options.percent,
                              "width": options.width, "height": options.height,
                              "keep_aspect": options.keep_aspect, "never_upscale": options.never_upscale,
                              "quality": options.quality, "png_level": options.png_level,
                              "webp_lossless": options.webp_lossless, "strip": options.strip_metadata,
                              "background": options.background, "pattern": options.pattern,
                              "start": options.start_number})
        planned = convert.plan(items, options, self.output.folder())
        self.submit(Job("Convert %d image(s) → %s" % (len(planned), convert.TARGETS[options.target][0]),
                        lambda ctx: convert.run(ctx, planned, options)))
