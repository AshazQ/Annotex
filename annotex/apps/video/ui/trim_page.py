"""Video Trimmer."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem)

from annotex.core.jobs import Job
from annotex.core.media.ffmpeg import format_time, parse_time
from annotex.ui.dialogs.common import hint
from annotex.ui.media_widgets import OutputChooser
from annotex.ui.widgets import section_label

from .. import core
from .base import VideoPage


class TrimPage(VideoPage):
    TOOL_ID = "trim"
    TOOL_NAME = "Video Trimmer"
    TAGLINE = "Cut one or more pieces out of a video"
    DEFAULTS = {"mode": "fast", "join": False}

    def build(self) -> None:
        self.segments = {}
        self.in_point = None
        self._filling = False

        left, left_layout = self.card()
        left_layout.addWidget(self.make_file_list())
        self.splitter.addWidget(left)

        centre, centre_layout = self.scroll_card()
        centre_layout.addWidget(self.make_player(), 3)
        marks = QHBoxLayout()
        self.start_button = QPushButton("Set start   I")
        self.start_button.clicked.connect(self.set_start)
        self.end_button = QPushButton("Set end   O")
        self.end_button.setObjectName("Primary")
        self.end_button.clicked.connect(self.set_end)
        self.whole_button = QPushButton("Whole video")
        self.whole_button.clicked.connect(self.add_whole)
        for button in (self.start_button, self.end_button, self.whole_button):
            marks.addWidget(button)
        self.mark_label = QLabel("Press I at the start of a piece and O at its end.")
        self.mark_label.setObjectName("Hint")
        marks.addWidget(self.mark_label, 1)
        centre_layout.addLayout(marks)
        self.player_key("I", self.set_start)
        self.player_key("O", self.set_end)

        header = QHBoxLayout()
        header.addWidget(section_label("Pieces to keep"))
        header.addStretch(1)
        self.total_label = QLabel("")
        self.total_label.setObjectName("Subtitle")
        header.addWidget(self.total_label)
        centre_layout.addLayout(header)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Start", "End", "Length"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in (1, 2, 3):
            head.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.setMaximumHeight(170)
        self.table.itemChanged.connect(self._edited)
        self.table.cellDoubleClicked.connect(self._jump)
        centre_layout.addWidget(self.table, 1)
        table_buttons = QHBoxLayout()
        remove = QPushButton("Remove piece")
        remove.clicked.connect(self.remove_selected)
        clear = QPushButton("Clear pieces")
        clear.clicked.connect(self.clear_segments)
        table_buttons.addWidget(remove)
        table_buttons.addWidget(clear)
        table_buttons.addStretch(1)
        table_buttons.addWidget(QLabel("Double-click a row to jump to it; edit a time to adjust it."))
        centre_layout.addLayout(table_buttons)
        self.splitter.addWidget(centre)

        options, layout = self.scroll_card()
        layout.addWidget(section_label("How to cut"))
        self.mode_group = QButtonGroup(self)
        self.fast = QRadioButton("Fast - no quality loss")
        self.exact = QRadioButton("Exact - frame-accurate")
        self.mode_group.addButton(self.fast)
        self.mode_group.addButton(self.exact)
        layout.addWidget(self.fast)
        layout.addWidget(hint("Copies the video without re-encoding, so it is instant and "
                              "keeps full quality - but a cut can only start on a keyframe, "
                              "so it may begin up to a second or two early."))
        layout.addWidget(self.exact)
        layout.addWidget(hint("Re-encodes each piece so it starts and ends on exactly the "
                              "frame you marked. Slower, with a very small quality cost."))
        self.join = QCheckBox("Join the pieces into one file")
        layout.addWidget(self.join)
        layout.addWidget(section_label("Output"))
        self.output = OutputChooser("Beside each video, in trimmed/")
        layout.addWidget(self.output)
        layout.addWidget(hint("Pieces are named clip_trim_01.mp4, clip_trim_02.mp4 … and "
                              "keep the original format."))
        layout.addStretch(1)
        self.run_current = QPushButton("Trim this video")
        self.run_current.setObjectName("Primary")
        self.run_current.clicked.connect(lambda: self.trim([self.player.path]))
        self.run_all = QPushButton("Trim every video with pieces")
        self.run_all.clicked.connect(lambda: self.trim(self.files.paths()))
        layout.addWidget(self.run_current)
        layout.addWidget(self.run_all)
        self.splitter.addWidget(options)
        self.splitter.setSizes([280, 780, 360])

        (self.exact if self.settings.get("mode") == "exact" else self.fast).setChecked(True)
        self.join.setChecked(bool(self.settings.get("join")))
        self._refresh()

    # ── marking ───────────────────────────────────────────
    def current_segments(self):
        return self.segments.setdefault(self.player.path, []) if self.player.path else []

    def set_start(self) -> None:
        if not self.player.info:
            return
        self.in_point = self.player.position
        self.player.timeline.in_point = self.in_point
        self.player.timeline.update()
        self.mark_label.setText("Start at %s - now move to the end and press O"
                                % format_time(self.in_point))

    def set_end(self) -> None:
        if not self.player.info:
            return
        if self.in_point is None:
            self.status("Press I at the start of the piece first", "warning")
            return
        end = self.player.position
        if end <= self.in_point:
            self.status("The end must be after the start (%s)" % format_time(self.in_point), "warning")
            return
        self.current_segments().append(core.Segment(self.in_point, end))
        self.in_point = None
        self.player.timeline.in_point = None
        self.mark_label.setText("Piece added. Press I to start another.")
        self._refresh()

    def add_whole(self) -> None:
        if self.player.info:
            self.current_segments().append(core.Segment(0.0, self.player.duration))
            self._refresh()

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        segments = self.current_segments()
        for index in rows:
            if index < len(segments):
                segments.pop(index)
        self._refresh()

    def clear_segments(self) -> None:
        if self.player.path:
            self.segments[self.player.path] = []
        self._refresh()

    def _jump(self, row, _column) -> None:
        segments = self.current_segments()
        if row < len(segments):
            self.player.seek(segments[row].start)

    def _edited(self, item) -> None:
        if self._filling or item.column() not in (1, 2):
            return
        segments = self.current_segments()
        if item.row() >= len(segments):
            return
        segment = segments[item.row()]
        try:
            value = parse_time(item.text())
            start = value if item.column() == 1 else segment.start
            end = value if item.column() == 2 else segment.end
            if end <= start:
                raise ValueError("the end must be after the start")
            if self.player.duration and start >= self.player.duration:
                raise ValueError("that is past the end of the video")
            segment.start, segment.end = start, min(end, self.player.duration or end)
        except ValueError as exc:
            self.status("Not changed: %s" % exc, "warning")
        self._refresh()

    def on_loaded(self, info) -> None:
        self.in_point = None
        self._refresh()

    def on_files_changed(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        segments = self.current_segments() if self.player and self.player.path else []
        self._filling = True
        self.table.setRowCount(len(segments))
        for index, segment in enumerate(segments):
            values = (str(index + 1), format_time(segment.start), format_time(segment.end),
                      format_time(segment.duration))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (0, 3):
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(index, column, item)
        self._filling = False
        if self.player:
            self.player.timeline.segments = [(s.start, s.end) for s in segments]
            self.player.timeline.update()
        total = sum(s.duration for s in segments)
        self.total_label.setText("%d piece(s) · %s" % (len(segments), format_time(total))
                                 if segments else "")
        has_video = bool(self.player and self.player.info)
        for button in (self.start_button, self.end_button, self.whole_button):
            button.setEnabled(has_video)
        self.run_current.setEnabled(bool(segments))
        ready = [p for p in self.files.paths() if self.segments.get(p)]
        self.run_all.setEnabled(bool(ready))
        self.run_all.setText("Trim all %d videos with pieces" % len(ready) if len(ready) > 1
                             else "Trim every video with pieces")

    # ── run ───────────────────────────────────────────────
    def trim(self, paths) -> None:
        mode = "exact" if self.exact.isChecked() else "fast"
        join = self.join.isChecked()
        # Read now, on this thread: the work runs on another, where a widget
        # must not be touched - and a later change must not move a queued job.
        output_dir = self.output.folder()
        self.settings.update({"mode": mode, "join": join})
        queued = 0
        for path in paths:
            segments = [core.Segment(s.start, s.end) for s in self.segments.get(path, [])]
            if not path or not segments:
                continue

            def work(ctx, path=path, segments=segments):
                outputs = core.trim_video(ctx, path, segments, mode, output_dir, join)
                return "%d file(s) in %s" % (len(outputs), os.path.basename(os.path.dirname(outputs[0])))

            self.submit(Job("Trim · %s" % os.path.basename(path), work))
            queued += 1
        if queued:
            self.status("Queued %d video(s)" % queued, "good")
        else:
            self.status("Mark at least one piece first (I then O)", "warning")
