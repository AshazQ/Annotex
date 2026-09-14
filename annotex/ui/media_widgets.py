"""Widgets the media tools share: the input list, the output chooser, and a
frame-accurate video player built on ffmpeg."""

from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..core.media.ffmpeg import format_time
from . import icons
from .palette import qcolor
from .widgets import section_label


class FitLabel(QLabel):
    """A word-wrapped label that reserves height for all of its lines, so a
    stretching neighbour (an image, a table) can never squeeze it."""

    def __init__(self, text="", min_lines=1, parent=None):
        super().__init__("", parent)
        self._min_lines = min_lines
        self.setWordWrap(True)
        self.setText(text)

    def setText(self, text):
        super().setText(text)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def changeEvent(self, event):
        super().changeEvent(event)
        self._fit()

    def _fit(self):
        metrics = self.fontMetrics()
        width = max(self.contentsRect().width(), 160)
        flags = int(Qt.TextFlag.TextWordWrap) | int(Qt.AlignmentFlag.AlignLeft)
        text_height = metrics.boundingRect(0, 0, width, 100000, flags, self.text() or " ").height()
        height = max(text_height, metrics.lineSpacing() * self._min_lines) + 4
        if height != self.minimumHeight():
            self.setMinimumHeight(height)


# ══════════════════════════════════════════════════════════════
class FileList(QWidget):
    """Files to work on: add, drop, remove, reorder."""

    changed = Signal()
    currentChanged = Signal(str)

    def __init__(self, title, extensions, scan_folder, file_filter, reorderable=False,
                 parent=None):
        super().__init__(parent)
        self.extensions = tuple(extensions)
        self.scan_folder = scan_folder
        self.file_filter = file_filter
        self.setAcceptDrops(True)
        self._info = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(section_label(title))
        header.addStretch(1)
        self.count = QLabel("")
        self.count.setObjectName("Subtitle")
        header.addWidget(self.count)
        layout.addLayout(header)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setMinimumHeight(120)
        self.list.setAcceptDrops(True)
        self.list.viewport().setAcceptDrops(True)
        self.list.dragEnterEvent = self.dragEnterEvent
        self.list.dragMoveEvent = self.dragEnterEvent
        self.list.dropEvent = self.dropEvent
        self.list.currentItemChanged.connect(
            lambda item, _prev: self.currentChanged.emit(self._path(item) if item else ""))
        layout.addWidget(self.list, 1)

        self.hint = QLabel("Drop files or folders here, or use Add.")
        self.hint.setObjectName("Hint")
        layout.addWidget(self.hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.add_files_button = QPushButton("Add files…")
        self.add_files_button.clicked.connect(self.browse_files)
        self.add_folder_button = QPushButton("Add folder…")
        self.add_folder_button.clicked.connect(self.browse_folder)
        buttons.addWidget(self.add_files_button)
        buttons.addWidget(self.add_folder_button)
        buttons.addStretch(1)
        self.up_button = self.down_button = None
        if reorderable:
            self.up_button = QPushButton("↑")
            self.up_button.setToolTip("Move up")
            self.up_button.clicked.connect(lambda: self.move(-1))
            self.down_button = QPushButton("↓")
            self.down_button.setToolTip("Move down")
            self.down_button.clicked.connect(lambda: self.move(1))
            buttons.addWidget(self.up_button)
            buttons.addWidget(self.down_button)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_selected)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear)
        buttons.addWidget(remove)
        buttons.addWidget(clear)
        layout.addLayout(buttons)
        self._sync()

    # ── content ───────────────────────────────────────────
    def add_paths(self, paths) -> int:
        existing = set(self.paths())
        added = 0
        for path in paths:
            path = os.path.abspath(str(path))
            if os.path.isdir(path):
                candidates = self.scan_folder(path)
            elif path.lower().endswith(self.extensions):
                candidates = [path]
            else:
                candidates = []
            for candidate in candidates:
                if candidate in existing:
                    continue
                existing.add(candidate)
                item = QListWidgetItem(os.path.basename(candidate))
                item.setData(Qt.ItemDataRole.UserRole, candidate)
                item.setToolTip(candidate)
                self.list.addItem(item)
                added += 1
        if added and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        self._sync()
        self.changed.emit()
        return added

    def paths(self):
        return [self._path(self.list.item(i)) for i in range(self.list.count())]

    def current_path(self):
        item = self.list.currentItem()
        return self._path(item) if item else ""

    def select(self, path) -> None:
        for index in range(self.list.count()):
            if self._path(self.list.item(index)) == path:
                self.list.setCurrentRow(index)
                return

    def set_info(self, path, text) -> None:
        self._info[path] = text
        for index in range(self.list.count()):
            item = self.list.item(index)
            if self._path(item) == path:
                item.setText("%s   ·   %s" % (os.path.basename(path), text) if text
                             else os.path.basename(path))

    @staticmethod
    def _path(item):
        return item.data(Qt.ItemDataRole.UserRole)

    def remove_selected(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._sync()
        self.changed.emit()

    def clear(self) -> None:
        self.list.clear()
        self._sync()
        self.changed.emit()

    def move(self, step) -> None:
        row = self.list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)
        self.changed.emit()

    def _sync(self) -> None:
        count = self.list.count()
        self.count.setText("%d file(s)" % count if count else "")
        self.hint.setVisible(count == 0)

    # ── browsing & dropping ───────────────────────────────
    def browse_files(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(self, "Add files", os.path.expanduser("~"),
                                                      self.file_filter)
        if paths:
            self.add_paths(paths)

    def browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add a folder", os.path.expanduser("~"))
        if folder:
            self.add_paths([folder])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()


# ══════════════════════════════════════════════════════════════
class OutputChooser(QWidget):
    """Beside each source (in a named subfolder), or one chosen folder."""

    changed = Signal()

    def __init__(self, beside_text, parent=None):
        super().__init__(parent)
        self._folder = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(QLabel("Save to"))
        self.combo = QComboBox()
        self.combo.addItem(beside_text, "beside")
        self.combo.addItem("A folder I choose…", "folder")
        self.combo.activated.connect(self._activated)
        row.addWidget(self.combo, 1)
        layout.addLayout(row)
        self.path = QLabel("")
        self.path.setObjectName("Subtitle")
        self.path.setWordWrap(True)
        layout.addWidget(self.path)
        self._sync()

    def _activated(self, index) -> None:
        if self.combo.itemData(index) == "folder":
            folder = QFileDialog.getExistingDirectory(self, "Output folder",
                                                      self._folder or os.path.expanduser("~"))
            if folder:
                self._folder = folder
            elif not self._folder:
                self.combo.setCurrentIndex(0)
        self._sync()
        self.changed.emit()

    def set_folder(self, folder) -> None:
        self._folder = folder or ""
        self.combo.setCurrentIndex(1 if self._folder else 0)
        self._sync()

    def folder(self) -> str:
        """"" means beside each source."""
        return self._folder if self.combo.currentData() == "folder" else ""

    def _sync(self) -> None:
        self.path.setText(self._folder if self.combo.currentData() == "folder" else "")
        self.path.setVisible(self.combo.currentData() == "folder")


# ══════════════════════════════════════════════════════════════
class FrameView(QWidget):
    """A picture scaled to fit, on the dark canvas colour."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image = None
        self.message = "No video loaded"
        self.void = QColor("#101319")

    def set_theme(self, theme) -> None:
        self.void = qcolor(theme.get("canvasVoid", "#101319"))
        self.update()

    def set_image(self, image) -> None:
        self.image = image
        self.update()

    def clear(self, message="No video loaded") -> None:
        self.image = None
        self.message = message
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), self.void)
        if self.image is None or self.image.isNull():
            painter.setPen(QColor("#6f7784"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            painter.end()
            return
        scale = min(self.width() / self.image.width(), self.height() / self.image.height())
        width, height = self.image.width() * scale, self.image.height() * scale
        target = QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
        painter.drawImage(target, self.image)
        painter.end()


class Timeline(QWidget):
    """Playhead, clickable/draggable, with optional segments and an in-mark."""

    seekRequested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.duration = 0.0
        self.position = 0.0
        self.segments = []
        self.marks = []
        self.in_point = None
        self.theme = {}

    def set_theme(self, theme) -> None:
        self.theme = dict(theme)
        self.update()

    def _x(self, seconds) -> float:
        usable = max(1.0, self.width() - 16)
        return 8 + usable * (seconds / self.duration if self.duration else 0)

    def _seconds(self, x) -> float:
        usable = max(1.0, self.width() - 16)
        return max(0.0, min(self.duration, (x - 8) / usable * self.duration))

    def mousePressEvent(self, event):
        if self.duration:
            self.seekRequested.emit(self._seconds(event.position().x()))

    def mouseMoveEvent(self, event):
        if self.duration and event.buttons() & Qt.MouseButton.LeftButton:
            self.seekRequested.emit(self._seconds(event.position().x()))

    def paintEvent(self, event):
        theme = self.theme or {}
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QRectF(8, self.height() / 2 - 4, self.width() - 16, 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(qcolor(theme.get("surfaceAlt", "#252a33"))))
        painter.drawRoundedRect(track, 4, 4)
        accent = qcolor(theme.get("accent", "#df5e3b"))
        if self.duration:
            for start, end in self.segments:
                fill = QColor(accent)
                fill.setAlpha(150)
                painter.setBrush(QBrush(fill))
                painter.drawRoundedRect(QRectF(self._x(start), track.top() - 3,
                                               max(2.0, self._x(end) - self._x(start)),
                                               track.height() + 6), 3, 3)
            painter.setPen(QPen(qcolor(theme.get("info", "#5b9cea")), 2))
            for mark in self.marks:
                painter.drawLine(QPointF(self._x(mark), track.top() - 2),
                                 QPointF(self._x(mark), track.bottom() + 2))
            if self.in_point is not None:
                painter.setPen(QPen(qcolor(theme.get("good", "#5cbf6b")), 3))
                x = self._x(self.in_point)
                painter.drawLine(QPointF(x, 4), QPointF(x, self.height() - 4))
            x = self._x(self.position)
            painter.setPen(QPen(qcolor(theme.get("title", "#e9ecf1")), 2))
            painter.drawLine(QPointF(x, 3), QPointF(x, self.height() - 3))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(accent))
            painter.drawEllipse(QPointF(x, self.height() / 2), 6, 6)
        painter.end()


class _Decoder(QObject):
    """Decodes the most recently requested frame on a background thread."""

    frameReady = Signal(float, QImage)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._pending = None
        self._wake = threading.Event()
        self._stopping = False
        threading.Thread(target=self._loop, daemon=True, name="annotex-decoder").start()

    def request(self, video, seconds, size) -> None:
        with self._lock:
            self._pending = (video, seconds, size)
        self._wake.set()

    def _loop(self) -> None:
        from annotex.apps.video.core import decode_frame
        while not self._stopping:
            self._wake.wait(0.5)
            with self._lock:
                job, self._pending = self._pending, None
                self._wake.clear()
            if job is None or self._stopping:
                continue
            video, seconds, (width, height) = job
            try:
                raw = decode_frame(video, seconds, (width, height))
                image = QImage(raw, width, height, width * 3, QImage.Format.Format_RGB888).copy()
                self.frameReady.emit(seconds, image)
            except Exception as exc:                          # noqa: BLE001
                self.failed.emit(str(exc))

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()


class _Playback(QObject):
    """Streams scaled frames from ffmpeg in real time."""

    frameReady = Signal(float, QImage)
    ended = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = None
        self._generation = 0

    def start(self, video, seconds, size, fps) -> None:
        self.stop()
        from annotex.apps.video.core import playback_process
        self._generation += 1
        generation = self._generation
        process = playback_process(video, seconds, size, fps)
        self._process = process

        def read():
            width, height = size
            needed = width * height * 3
            started = time.monotonic()
            index = 0
            while generation == self._generation:
                chunk = b""
                while len(chunk) < needed:
                    data = process.stdout.read(needed - len(chunk))
                    if not data:
                        break
                    chunk += data
                if len(chunk) < needed or generation != self._generation:
                    break
                due = started + index / float(fps)
                delay = due - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                image = QImage(chunk, width, height, width * 3, QImage.Format.Format_RGB888).copy()
                self.frameReady.emit(seconds + index / float(fps), image)
                index += 1
            if generation == self._generation:
                self.ended.emit()

        threading.Thread(target=read, daemon=True, name="annotex-playback").start()

    def stop(self) -> None:
        self._generation += 1
        process, self._process = self._process, None
        if process is not None:
            try:
                process.kill()
            except Exception:
                pass

    @property
    def playing(self) -> bool:
        return self._process is not None


class VideoPlayer(QWidget):
    """Frame view, timeline and transport controls for one video."""

    positionChanged = Signal(float)

    PLAY_FPS_CAP = 15.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = ""
        self.info = None
        self.position = 0.0
        self.size_hint = (640, 360)
        self._theme = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.view = FrameView()
        layout.addWidget(self.view, 1)
        self.timeline = Timeline()
        self.timeline.seekRequested.connect(self.seek)
        layout.addWidget(self.timeline)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.buttons = {}
        for key, text, tip, slot in (
                ("back_second", "−1s", "Back one second  [Shift+←]", lambda: self.step_seconds(-1)),
                ("back_frame", "−1f", "Back one frame  [←]", lambda: self.step_frames(-1)),
                ("play", "Play", "Play / pause  [Space]", self.toggle_play),
                ("next_frame", "+1f", "Forward one frame  [→]", lambda: self.step_frames(1)),
                ("next_second", "+1s", "Forward one second  [Shift+→]", lambda: self.step_seconds(1))):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.buttons[key] = button
            controls.addWidget(button)
        controls.addStretch(1)
        self.time_label = QLabel("--:--:--.--- / --:--:--.---")
        self.time_label.setObjectName("Mono")
        controls.addWidget(self.time_label)
        layout.addLayout(controls)

        self.decoder = _Decoder(self)
        self.decoder.frameReady.connect(self._decoded)
        self.decoder.failed.connect(lambda message: self.view.clear(message))
        self.playback = _Playback(self)
        self.playback.frameReady.connect(self._played)
        self.playback.ended.connect(self._ended)
        self._sync_controls()

    def set_theme(self, theme) -> None:
        self._theme = dict(theme)
        self.view.set_theme(theme)
        self.timeline.set_theme(theme)

    @property
    def fps(self) -> float:
        return (self.info.fps if self.info and self.info.fps else 25.0)

    @property
    def duration(self) -> float:
        return self.info.duration if self.info else 0.0

    def load(self, path, info) -> None:
        from annotex.apps.video.core import preview_size
        self.playback.stop()
        self.path = path
        self.info = info
        self.size_hint = preview_size(info, 960, 540)
        self.timeline.duration = info.duration
        self.timeline.segments = []
        self.timeline.marks = []
        self.timeline.in_point = None
        self.position = -1.0
        self.view.clear("Loading…")
        self.seek(0.0)
        self._sync_controls()

    def clear(self) -> None:
        self.playback.stop()
        self.path, self.info = "", None
        self.timeline.duration = 0.0
        self.timeline.update()
        self.view.clear()
        self.time_label.setText("--:--:--.--- / --:--:--.---")
        self._sync_controls()

    def seek(self, seconds) -> None:
        if not self.info:
            return
        was_playing = self.playback.playing
        self.playback.stop()
        last = max(0.0, self.duration - 1.0 / self.fps)
        seconds = max(0.0, min(float(seconds), last))
        self.position = seconds
        self.decoder.request(self.path, seconds, self.size_hint)
        self._show_position()
        if was_playing:
            self.buttons["play"].setText("Play")

    def step_frames(self, count) -> None:
        self.seek(self.position + count / self.fps)

    def step_seconds(self, count) -> None:
        self.seek(self.position + count)

    def toggle_play(self) -> None:
        if not self.info:
            return
        if self.playback.playing:
            self.playback.stop()
            self.buttons["play"].setText("Play")
            self.seek(self.position)
            return
        start = self.position if self.position < self.duration - 0.2 else 0.0
        self.playback.start(self.path, start, self.size_hint, min(self.fps, self.PLAY_FPS_CAP))
        self.buttons["play"].setText("Pause")

    @Slot(float, QImage)
    def _decoded(self, seconds, image) -> None:
        if abs(seconds - self.position) < 1e-6 and not self.playback.playing:
            self.view.set_image(image)

    @Slot(float, QImage)
    def _played(self, seconds, image) -> None:
        if not self.playback.playing:
            return
        self.position = seconds
        self.view.set_image(image)
        self._show_position()

    def _ended(self) -> None:
        self.playback.stop()
        self.buttons["play"].setText("Play")

    def _show_position(self) -> None:
        self.timeline.position = self.position
        self.timeline.update()
        self.time_label.setText("%s / %s" % (format_time(self.position), format_time(self.duration)))
        self.positionChanged.emit(self.position)

    def _sync_controls(self) -> None:
        for button in self.buttons.values():
            button.setEnabled(self.info is not None)

    def shutdown(self) -> None:
        self.playback.stop()
        self.decoder.stop()
