"""Video Converter."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QLabel,
                               QPushButton, QRadioButton, QSlider)

from annotex.core.jobs import Job
from annotex.core.media.ffmpeg import has_encoder, human_size
from annotex.ui.dialogs.common import hint, row
from annotex.ui.media_widgets import OutputChooser
from annotex.ui.widgets import section_label

from .. import core
from .base import VideoPage

HEIGHTS = ((0, "Keep the original"), (2160, "2160p (4K)"), (1440, "1440p"), (1080, "1080p"),
           (720, "720p"), (480, "480p"), (360, "360p"))
FRAME_RATES = ((0, "Keep the original"), (60, "60 fps"), (50, "50 fps"), (30, "30 fps"),
               (25, "25 fps"), (24, "24 fps"), (15, "15 fps"), (10, "10 fps"), (5, "5 fps"))
SPEEDS = (("fast", "Fast - bigger files"), ("balanced", "Balanced"),
          ("small", "Slow - smallest files"))


class ConvertPage(VideoPage):
    TOOL_ID = "vconvert"
    TOOL_NAME = "Video Converter"
    TAGLINE = "Change format, resolution and frame rate, or shrink a video"
    DEFAULTS = {"preset": "mp4_h264", "height": 0, "fps": 0, "quality": 70, "size_mode": False,
                "target_mb": 50.0, "speed": "balanced", "never_upscale": True}

    def build(self) -> None:
        left, left_layout = self.card()
        left_layout.addWidget(self.make_file_list())
        self.splitter.addWidget(left)

        centre, centre_layout = self.card()
        centre_layout.addWidget(self.make_player(), 1)
        self.info_label = QLabel("")
        self.info_label.setObjectName("Hint")
        self.info_label.setWordWrap(True)
        centre_layout.addWidget(self.info_label)
        self.splitter.addWidget(centre)

        options, layout = self.scroll_card()
        layout.addWidget(section_label("Format"))
        self.preset = QComboBox()
        for key, preset in core.PRESETS.items():
            self.preset.addItem(preset.label, key)
            if preset.encoder and not has_encoder(preset.encoder):
                index = self.preset.count() - 1
                self.preset.setItemData(index, "%s is not available in this ffmpeg" % preset.encoder,
                                        Qt.ItemDataRole.ToolTipRole)
        layout.addWidget(self.preset)

        layout.addWidget(section_label("Picture"))
        self.height_box = QComboBox()
        for value, label in HEIGHTS:
            self.height_box.addItem(label, value)
        layout.addWidget(row(QLabel("Resolution"), self.height_box, stretch_last=True))
        self.never_upscale = QCheckBox("Never make a video larger than it is")
        layout.addWidget(self.never_upscale)
        self.fps_box = QComboBox()
        for value, label in FRAME_RATES:
            self.fps_box.addItem(label, value)
        layout.addWidget(row(QLabel("Frame rate"), self.fps_box, stretch_last=True))

        layout.addWidget(section_label("Size and quality"))
        self.size_group = QButtonGroup(self)
        self.by_quality = QRadioButton("Choose a quality")
        self.by_size = QRadioButton("Aim for a file size")
        self.size_group.addButton(self.by_quality)
        self.size_group.addButton(self.by_size)
        layout.addWidget(self.by_quality)
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(0, 100)
        self.quality_value = QLabel("")
        layout.addWidget(row(QLabel("Smaller"), self.quality, QLabel("Better"), self.quality_value))
        layout.addWidget(self.by_size)
        self.target = QDoubleSpinBox()
        self.target.setRange(0.5, 100000)
        self.target.setSuffix(" MB")
        self.target.setDecimals(1)
        layout.addWidget(row(QLabel("About"), self.target, QLabel("per video"), None))
        self.speed = QComboBox()
        for key, label in SPEEDS:
            self.speed.addItem(label, key)
        layout.addWidget(row(QLabel("Encoding"), self.speed, stretch_last=True))
        layout.addWidget(hint("Audio is kept; it is converted only when the new format "
                              "needs a different audio codec."))

        layout.addWidget(section_label("Output"))
        self.output = OutputChooser("Beside each video, in converted/")
        layout.addWidget(self.output)
        layout.addStretch(1)
        self.run_current = QPushButton("Convert this video")
        self.run_current.setObjectName("Primary")
        self.run_current.clicked.connect(lambda: self.convert([self.player.path]))
        self.run_all = QPushButton("Convert every video")
        self.run_all.clicked.connect(lambda: self.convert(self.files.paths()))
        layout.addWidget(self.run_current)
        layout.addWidget(self.run_all)
        self.splitter.addWidget(options)
        self.splitter.setSizes([280, 700, 400])

        s = self.settings
        self.preset.setCurrentIndex(max(0, self.preset.findData(s.get("preset"))))
        self.height_box.setCurrentIndex(max(0, self.height_box.findData(int(s.get("height", 0)))))
        self.fps_box.setCurrentIndex(max(0, self.fps_box.findData(int(s.get("fps", 0)))))
        self.quality.setValue(int(s.get("quality", 70)))
        self.target.setValue(float(s.get("target_mb", 50)))
        self.speed.setCurrentIndex(max(0, self.speed.findData(s.get("speed"))))
        self.never_upscale.setChecked(bool(s.get("never_upscale", True)))
        (self.by_size if s.get("size_mode") else self.by_quality).setChecked(True)
        for signal in (self.quality.valueChanged, self.by_size.toggled, self.preset.currentIndexChanged,
                       self.height_box.currentIndexChanged, self.fps_box.currentIndexChanged,
                       self.target.valueChanged, self.never_upscale.toggled):
            signal.connect(lambda *_a: self._sync())
        self._sync()

    def on_loaded(self, info) -> None:
        self._sync()

    def on_files_changed(self) -> None:
        self._sync()

    def options(self) -> core.ConvertOptions:
        return core.ConvertOptions(preset=self.preset.currentData(),
                                   height=int(self.height_box.currentData()),
                                   never_upscale=self.never_upscale.isChecked(),
                                   fps=float(self.fps_box.currentData()),
                                   quality=self.quality.value(),
                                   target_mb=self.target.value() if self.by_size.isChecked() else 0.0,
                                   speed=self.speed.currentData())

    def _sync(self) -> None:
        self.quality_value.setText("%d" % self.quality.value())
        self.quality.setEnabled(self.by_quality.isChecked())
        self.target.setEnabled(self.by_size.isChecked())
        preset = core.PRESETS[self.preset.currentData()]
        usable = not preset.encoder or has_encoder(preset.encoder)
        info = self.player.info if self.player else None
        if info:
            height = int(self.height_box.currentData())
            new_height = height if height and (height < info.height or not self.never_upscale.isChecked()) \
                else info.height
            new_width = int(round(info.width * new_height / float(info.height or 1) / 2)) * 2
            fps = self.fps_box.currentData() or info.fps
            self.info_label.setText("Now: %s\nAfter: %dx%d · %.3g fps · %s%s" % (
                info.describe(), new_width, new_height, fps, preset.label.split(" (")[0],
                "  ·  about %s" % human_size(self.target.value() * 1024 * 1024)
                if self.by_size.isChecked() else ""))
        else:
            self.info_label.setText("")
        if not usable:
            self.status("%s is not available in this ffmpeg - pick another format" % preset.encoder,
                        "warning")
        count = len(self.files.paths())
        self.run_current.setEnabled(bool(info) and usable)
        self.run_all.setEnabled(count > 0 and usable)
        self.run_all.setText("Convert all %d videos" % count if count > 1 else "Convert every video")

    def convert(self, paths) -> None:
        options = self.options()
        self.settings.update({"preset": options.preset, "height": options.height,
                              "fps": int(options.fps), "quality": options.quality,
                              "size_mode": bool(options.target_mb), "target_mb": self.target.value(),
                              "speed": options.speed, "never_upscale": options.never_upscale})
        paths = [p for p in paths if p]
        # Read now, on this thread: the work runs on another, where a widget
        # must not be touched - and a later change must not move a queued job.
        output_dir = self.output.folder()
        for path in paths:
            def work(ctx, path=path):
                output = core.convert_video(ctx, path, options, output_dir)
                return "%s · %s" % (os.path.basename(output), human_size(os.path.getsize(output)))

            self.submit(Job("Convert · %s" % os.path.basename(path), work))
        if paths:
            self.status("Queued %d video(s)" % len(paths), "good")
