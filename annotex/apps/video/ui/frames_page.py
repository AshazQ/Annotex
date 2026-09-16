"""Video to Images."""

from __future__ import annotations

import math
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSlider, QSpinBox, QStackedWidget,
                               QWidget)

from annotex.core.jobs import Job
from annotex.core.media.ffmpeg import MediaError, format_time, parse_time
from annotex.ui.dialogs.common import hint, row
from annotex.ui.media_widgets import OutputChooser
from annotex.ui.widgets import section_label

from .. import core
from .base import VideoPage

MODES = (("interval", "Every N seconds"), ("fps", "N frames per second"),
         ("nth", "Every Nth frame"), ("scene", "Only when the scene changes"))


class FramesPage(VideoPage):
    TOOL_ID = "frames"
    TOOL_NAME = "Video to Images"
    TAGLINE = "Turn footage into image frames - automatically or one frame at a time"
    DEFAULTS = {"mode": "interval", "interval": 1.0, "fps": 1.0, "nth": 30, "scene": 30,
                "format": "jpg", "quality": 92, "max_frames": 0}

    def build(self) -> None:
        self.grabbed = 0
        left, left_layout = self.card()
        left_layout.addWidget(self.make_file_list())
        self.splitter.addWidget(left)

        centre, centre_layout = self.card()
        centre_layout.addWidget(self.make_player(), 1)
        grab_row = QHBoxLayout()
        self.grab_button = QPushButton("Grab this frame   G")
        self.grab_button.setObjectName("Primary")
        self.grab_button.clicked.connect(self.grab_current_frame)
        grab_row.addWidget(self.grab_button)
        self.grab_label = QLabel("Play or scrub to the moment you want, then press G.")
        self.grab_label.setObjectName("Hint")
        grab_row.addWidget(self.grab_label, 1)
        centre_layout.addLayout(grab_row)
        self.player_key("G", self.grab_current_frame)
        self.splitter.addWidget(centre)

        options, layout = self.scroll_card()
        layout.addWidget(section_label("Pick frames automatically"))
        self.mode = QComboBox()
        for key, label in MODES:
            self.mode.addItem(label, key)
        layout.addWidget(self.mode)
        self.mode_stack = QStackedWidget()
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.04, 3600)
        self.interval.setDecimals(2)
        self.interval.setSingleStep(0.5)
        self.interval.setSuffix(" s between frames")
        self.fps = QDoubleSpinBox()
        self.fps.setRange(0.01, 240)
        self.fps.setDecimals(2)
        self.fps.setSuffix(" frames per second")
        self.nth = QSpinBox()
        self.nth.setRange(1, 1000000)
        self.nth.setPrefix("every ")
        self.nth.setSuffix(" frames")
        scene = QWidget()
        scene_row = QHBoxLayout(scene)
        scene_row.setContentsMargins(0, 0, 0, 0)
        self.scene = QSlider(Qt.Orientation.Horizontal)
        self.scene.setRange(5, 60)
        self.scene_value = QLabel("")
        scene_row.addWidget(QLabel("More"))
        scene_row.addWidget(self.scene, 1)
        scene_row.addWidget(QLabel("Fewer"))
        scene_row.addWidget(self.scene_value)
        for widget in (self.interval, self.fps, self.nth, scene):
            self.mode_stack.addWidget(widget)
        layout.addWidget(self.mode_stack)
        self.estimate = hint("")
        layout.addWidget(self.estimate)

        layout.addWidget(section_label("Part of the video"))
        self.use_range = QCheckBox("Only between two times")
        self.use_range.setToolTip("Only take frames between a start and an end time")
        layout.addWidget(self.use_range)
        self.start = QLineEdit("00:00:00")
        self.end = QLineEdit("")
        self.end.setPlaceholderText("end of video")
        for label, edit in (("Start", self.start), ("End", self.end)):
            playhead = QPushButton("Playhead")
            playhead.setToolTip("Use the player's current position")
            playhead.clicked.connect(lambda _c=False, e=edit: e.setText(format_time(self.player.position)))
            layout.addWidget(row(QLabel(label), edit, playhead))

        layout.addWidget(section_label("Images"))
        self.image_format = QComboBox()
        self.image_format.addItem("JPEG (.jpg)", "jpg")
        self.image_format.addItem("PNG (.png, lossless, larger)", "png")
        layout.addWidget(row(QLabel("Format"), self.image_format, stretch_last=True))
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(50, 100)
        self.quality_value = QLabel("")
        layout.addWidget(row(QLabel("JPEG quality"), self.quality, self.quality_value))
        self.max_frames = QSpinBox()
        self.max_frames.setRange(0, 1000000)
        self.max_frames.setSpecialValueText("no limit")
        # One label and the number, not a sentence around it: three pieces in a
        # row were the widest thing in the panel, and with a wide font they
        # pushed the whole panel past what a laptop screen can give it.
        self.max_frames.setToolTip("The most frames to take from each video.  "
                                   "No limit takes every frame the settings above pick.")
        limit = QLabel("Frame limit")
        limit.setToolTip(self.max_frames.toolTip())
        layout.addWidget(row(limit, self.max_frames))

        layout.addWidget(section_label("Output"))
        self.output = OutputChooser("Beside each video, in <name>_frames")
        layout.addWidget(self.output)
        layout.addWidget(hint("Frames are named with their time in the video "
                              "(clip_01m05s250.jpg) and listed in frames.csv."))
        layout.addStretch(1)
        self.run_current = QPushButton("Extract from this video")
        self.run_current.setObjectName("Primary")
        self.run_current.clicked.connect(lambda: self.extract([self.files.current_path()]))
        self.run_all = QPushButton("Extract from every video")
        self.run_all.clicked.connect(lambda: self.extract(self.files.paths()))
        layout.addWidget(self.run_current)
        layout.addWidget(self.run_all)
        self.splitter.addWidget(options)
        self.splitter.setSizes([280, 760, 380])

        self._restore()
        for signal in (self.mode.currentIndexChanged, self.interval.valueChanged,
                       self.fps.valueChanged, self.nth.valueChanged, self.scene.valueChanged,
                       self.quality.valueChanged, self.image_format.currentIndexChanged,
                       self.max_frames.valueChanged, self.use_range.toggled,
                       self.start.textChanged, self.end.textChanged):
            signal.connect(lambda *_a: self._sync())
        self._sync()

    def _restore(self) -> None:
        s = self.settings
        self.mode.setCurrentIndex(max(0, self.mode.findData(s.get("mode"))))
        self.interval.setValue(float(s.get("interval", 1.0)))
        self.fps.setValue(float(s.get("fps", 1.0)))
        self.nth.setValue(int(s.get("nth", 30)))
        self.scene.setValue(int(s.get("scene", 30)))
        self.image_format.setCurrentIndex(max(0, self.image_format.findData(s.get("format"))))
        self.quality.setValue(int(s.get("quality", 92)))
        self.max_frames.setValue(int(s.get("max_frames", 0)))

    def _remember(self) -> None:
        self.settings.update({"mode": self.mode.currentData(), "interval": self.interval.value(),
                              "fps": self.fps.value(), "nth": self.nth.value(),
                              "scene": self.scene.value(), "format": self.image_format.currentData(),
                              "quality": self.quality.value(), "max_frames": self.max_frames.value()})

    def on_loaded(self, info) -> None:
        self.grabbed = 0
        self._sync()

    def on_files_changed(self) -> None:
        self._sync()

    # ── options ───────────────────────────────────────────
    def options(self) -> core.FrameOptions:
        start, end = 0.0, 0.0
        if self.use_range.isChecked():
            start = parse_time(self.start.text() or "0")
            end = parse_time(self.end.text()) if self.end.text().strip() else 0.0
            if end and end <= start:
                raise ValueError("the end time must be after the start time")
        return core.FrameOptions(mode=self.mode.currentData(), interval=self.interval.value(),
                                 fps=self.fps.value(), nth=self.nth.value(),
                                 scene=self.scene.value() / 100.0, start=start, end=end,
                                 image_format=self.image_format.currentData(),
                                 quality=self.quality.value(), max_frames=self.max_frames.value())

    def _sync(self) -> None:
        self.mode_stack.setCurrentIndex(self.mode.currentIndex())
        self.scene_value.setText("%.2f" % (self.scene.value() / 100.0))
        self.quality_value.setText(str(self.quality.value()))
        self.quality.setEnabled(self.image_format.currentData() == "jpg")
        self.start.setEnabled(self.use_range.isChecked())
        self.end.setEnabled(self.use_range.isChecked())
        has_current = bool(self.player and self.player.info)
        self.run_current.setEnabled(has_current)
        self.grab_button.setEnabled(has_current)
        count = len(self.files.paths())
        self.run_all.setEnabled(count > 0)
        self.run_all.setText("Extract from all %d videos" % count if count > 1
                             else "Extract from every video")
        self.estimate.setText(self._estimate())

    def _estimate(self) -> str:
        if not (self.player and self.player.info):
            return ""
        info = self.player.info
        try:
            options = self.options()
        except ValueError as exc:
            return "Check the times: %s" % exc
        window = (min(options.end, info.duration) if options.end else info.duration) - options.start
        if window <= 0:
            return "The start time is past the end of this video."
        if options.mode == "scene":
            return "The number of frames depends on how often the picture changes."
        if options.mode == "fps":
            count = window * options.fps
        elif options.mode == "nth":
            count = window * (info.fps or 25) / options.nth
        else:
            count = window / options.interval
        count = int(math.ceil(count))
        if options.max_frames:
            count = min(count, options.max_frames)
        return "About %d frame(s) from this video." % count

    def frames_dir(self, path) -> str:
        folder = self.output.folder()
        if folder:
            return os.path.join(folder, os.path.splitext(os.path.basename(path))[0] + core.FRAMES_SUFFIX)
        return core.frames_dir_for(path)

    # ── actions ───────────────────────────────────────────
    def grab_current_frame(self) -> None:
        if not (self.player and self.player.info):
            self.status("Load a video first", "warning")
            return
        try:
            saved = core.grab_frame(self.player.path, self.player.position,
                                    self.frames_dir(self.player.path),
                                    self.image_format.currentData(), self.quality.value())
        except MediaError as exc:
            self.status("Could not grab the frame: %s" % exc, "danger")
            return
        self.grabbed += 1
        self.player.timeline.marks.append(self.player.position)
        self.player.timeline.update()
        self.grab_label.setText("%d frame(s) grabbed from this video  ·  last: %s"
                                % (self.grabbed, os.path.basename(saved)))
        self.status("Saved %s" % saved, "good")

    def extract(self, paths) -> None:
        paths = [p for p in paths if p]
        if not paths:
            self.status("Add a video first", "warning")
            return
        try:
            options = self.options()
        except ValueError as exc:
            self.status("Check the times: %s" % exc, "warning")
            return
        self._remember()
        for path in paths:
            output = self.frames_dir(path)

            def work(ctx, path=path, output=output):
                folder, count = core.extract_frames(ctx, path, options, output)
                return "%d frame(s) → %s" % (count, os.path.basename(folder))

            self.submit(Job("Frames · %s" % os.path.basename(path), work))
        self.status("Queued %d video(s) - they run in the background" % len(paths), "good")
