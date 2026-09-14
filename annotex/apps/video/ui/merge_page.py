"""Video Merger."""

from __future__ import annotations

import os
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QPushButton, QSlider

from annotex.core.jobs import Job
from annotex.core.media.ffmpeg import format_time, human_size
from annotex.ui.dialogs.common import hint, row
from annotex.ui.media_widgets import FitLabel, OutputChooser
from annotex.ui.widgets import section_label

from .. import core
from .base import VideoPage

SIZES = (("first", "Match the first clip"), ("largest", "Match the largest clip"),
         ("2160", "2160p (4K)"), ("1080", "1080p"), ("720", "720p"), ("480", "480p"))
RATES = ((0, "Match the first clip"), (60, "60 fps"), (30, "30 fps"), (25, "25 fps"),
         (24, "24 fps"), (15, "15 fps"))


class MergePage(VideoPage):
    TOOL_ID = "merge"
    TOOL_NAME = "Video Merger"
    TAGLINE = "Join clips into one video, in the order you choose"
    DEFAULTS = {"mode": "auto", "size": "first", "fps": 0, "preset": "mp4_h264", "quality": 75}

    def build(self) -> None:
        left, left_layout = self.card()
        left_layout.addWidget(self.make_file_list("Clips, in order", reorderable=True))
        left_layout.addWidget(hint("Drag files in, then use ↑ ↓ to set the order."))
        self.splitter.addWidget(left)

        centre, centre_layout = self.card()
        centre_layout.addWidget(self.make_player(), 1)
        self.splitter.addWidget(centre)

        options, layout = self.scroll_card()
        layout.addWidget(section_label("These clips"))
        self.verdict = FitLabel("Add at least two clips.")
        self.verdict.setWordWrap(True)
        layout.addWidget(self.verdict)
        self.total = QLabel("")
        self.total.setObjectName("Subtitle")
        layout.addWidget(self.total)

        layout.addWidget(section_label("How to join"))
        self.mode = QComboBox()
        self.mode.addItem("Automatic - lossless when the clips match", "auto")
        self.mode.addItem("Always convert to a common format", "normalize")
        layout.addWidget(self.mode)
        self.size = QComboBox()
        for key, label in SIZES:
            self.size.addItem(label, key)
        layout.addWidget(row(QLabel("Resolution"), self.size, stretch_last=True))
        self.fps = QComboBox()
        for value, label in RATES:
            self.fps.addItem(label, value)
        layout.addWidget(row(QLabel("Frame rate"), self.fps, stretch_last=True))
        self.preset = QComboBox()
        for key, preset in core.PRESETS.items():
            self.preset.addItem(preset.label, key)
        layout.addWidget(row(QLabel("Format"), self.preset, stretch_last=True))
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(0, 100)
        layout.addWidget(row(QLabel("Smaller"), self.quality, QLabel("Better")))
        layout.addWidget(hint("Clips of a different shape are fitted with black bars rather "
                              "than stretched. A clip without sound gets silence."))

        layout.addWidget(section_label("Output"))
        self.name = QLineEdit("")
        self.name.setPlaceholderText("merged")
        layout.addWidget(row(QLabel("File name"), self.name, stretch_last=True))
        self.output = OutputChooser("Beside the first clip, in merged/")
        layout.addWidget(self.output)
        layout.addStretch(1)
        self.run = QPushButton("Merge")
        self.run.setObjectName("Primary")
        self.run.clicked.connect(self.merge)
        layout.addWidget(self.run)
        self.splitter.addWidget(options)
        self.splitter.setSizes([320, 680, 400])

        s = self.settings
        self.mode.setCurrentIndex(max(0, self.mode.findData(s.get("mode"))))
        self.size.setCurrentIndex(max(0, self.size.findData(s.get("size"))))
        self.fps.setCurrentIndex(max(0, self.fps.findData(int(s.get("fps", 0)))))
        self.preset.setCurrentIndex(max(0, self.preset.findData(s.get("preset"))))
        self.quality.setValue(int(s.get("quality", 75)))
        self.mode.currentIndexChanged.connect(lambda *_a: self._sync())
        self._sync()

    def on_files_changed(self) -> None:
        paths = self.files.paths()
        if paths and not self.name.text().strip():
            self.name.setText(os.path.splitext(os.path.basename(paths[0]))[0] + "_merged")
        self._sync()

    def _infos(self):
        infos = [self.infos.get(p) or self.info_for(p) for p in self.files.paths()]
        return [i for i in infos if i is not None and i.has_video]

    def _sync(self) -> None:
        infos = self._infos()
        count = len(self.files.paths())
        if count < 2:
            self.verdict.setText("Add at least two clips.")
            self.verdict.setObjectName("Hint")
        elif len(infos) < count:
            self.verdict.setText("Some files cannot be read - remove them to continue.")
            self.verdict.setObjectName("HintDanger")
        else:
            compatible, reasons = core.compatibility(infos)
            if compatible and self.mode.currentData() == "auto":
                self.verdict.setText("These clips match - they will be joined without "
                                     "re-encoding, instantly and at full quality.")
                self.verdict.setObjectName("HintGood")
            elif compatible:
                self.verdict.setText("These clips match, but you chose to convert them.")
                self.verdict.setObjectName("Hint")
            else:
                self.verdict.setText("These clips differ (%s), so they will be converted to "
                                     "one format first." % ", ".join(reasons))
                self.verdict.setObjectName("HintWarn")
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)
        if infos:
            self.total.setText("%d clip(s) · %s · %s" % (
                len(infos), format_time(sum(i.duration for i in infos), 0),
                human_size(sum(i.size_bytes for i in infos))))
        else:
            self.total.setText("")
        needs_convert = bool(infos) and (self.mode.currentData() == "normalize"
                                         or not core.compatibility(infos)[0])
        for widget in (self.size, self.fps, self.preset, self.quality):
            widget.setEnabled(needs_convert)
        self.run.setEnabled(count >= 2 and len(infos) == count)
        self.run.setText("Merge %d clips" % count if count >= 2 else "Merge")

    def _target(self, infos) -> core.MergeTarget:
        first = infos[0]
        key = self.size.currentData()
        width = height = 0
        if key == "largest":
            biggest = max(infos, key=lambda i: i.width * i.height)
            width, height = biggest.width, biggest.height
        elif key != "first":
            height = int(key)
            width = int(round(first.width * height / float(first.height or 1) / 2)) * 2
        return core.MergeTarget(width=width, height=height, fps=float(self.fps.currentData()),
                                preset=self.preset.currentData(), quality=self.quality.value())

    def merge(self) -> None:
        paths = self.files.paths()
        infos = self._infos()
        if len(paths) < 2 or len(infos) != len(paths):
            self.status("Add at least two readable clips", "warning")
            return
        name = re.sub(r'[\\/:*?"<>|]+', "_", self.name.text().strip()) or "merged"
        folder = self.output.folder() or os.path.join(os.path.dirname(paths[0]), core.MERGE_DIR)
        output = os.path.join(folder, name + ".mp4")
        mode = self.mode.currentData()
        target = self._target(infos)
        self.settings.update({"mode": mode, "size": self.size.currentData(),
                              "fps": int(self.fps.currentData()), "preset": target.preset,
                              "quality": target.quality})

        def work(ctx):
            result = core.merge_videos(ctx, paths, output, mode, target)
            return "%s · %s" % (os.path.basename(result), human_size(os.path.getsize(result)))

        self.submit(Job("Merge · %d clips → %s" % (len(paths), name), work))
