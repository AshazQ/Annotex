"""What the four video pages share: the video list, probing, the player and
its keys."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

from annotex.core.media.ffmpeg import MediaError, find_ffmpeg, probe
from annotex.ui.media_page import MediaToolPage
from annotex.ui.media_widgets import FileList, VideoPlayer

from .. import core

VIDEO_FILTER = "Videos (%s);;All files (*)" % " ".join("*" + e for e in core.VIDEO_EXTS)


class VideoPage(MediaToolPage):
    MARK = "polygon"

    def __init__(self, app, host=None, settings=None, jobs=None):
        self.infos = {}
        self.player = None
        super().__init__(app, host, settings, jobs)
        if not find_ffmpeg():
            self.status("ffmpeg was not found - run `python bootstrap.py` to install the "
                        "bundled copy", "danger")

    # ── inputs ────────────────────────────────────────────
    def make_file_list(self, title="Videos", reorderable=False) -> FileList:
        files = FileList(title, core.VIDEO_EXTS, core.scan_videos, VIDEO_FILTER, reorderable)
        files.currentChanged.connect(self.load_current)
        files.changed.connect(self._on_files_changed)
        self.files = files
        return files

    def browse_files(self) -> None:
        self.files.browse_files()

    def browse_folder(self) -> None:
        self.files.browse_folder()

    def add_paths(self, paths) -> None:
        added = self.files.add_paths(paths)
        self.status("Added %d video(s)" % added if added else "No new videos found there",
                    "good" if added else "warning")

    def _on_files_changed(self) -> None:
        for path in self.files.paths():
            if path not in self.infos:
                self.info_for(path)
        self.on_files_changed()

    def on_files_changed(self) -> None:
        pass

    def info_for(self, path):
        """MediaInfo, cached; None (with a status line) if it cannot be read."""
        if path in self.infos:
            return self.infos[path]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = probe(path)
            self.files.set_info(path, "%dx%d · %s" % (info.width, info.height,
                                                      core.format_time(info.duration, 0))
                                if info.has_video else "no video stream")
        except MediaError as exc:
            info = None
            self.files.set_info(path, "unreadable")
            self.status(str(exc), "danger")
        finally:
            QApplication.restoreOverrideCursor()
        self.infos[path] = info
        return info

    def load_current(self, path) -> None:
        if self.player is None:
            return
        if not path:
            self.player.clear()
            self.on_loaded(None)
            return
        info = self.info_for(path)
        if info is None or not info.has_video:
            self.player.clear()
            self.player.view.clear("This file cannot be played")
            self.on_loaded(None)
            return
        self.player.load(path, info)
        self.subtitle.setText("%s  ·  %s" % (os.path.basename(path), info.describe()))
        self.on_loaded(info)
        self.player.setFocus()

    def on_loaded(self, info) -> None:
        pass

    # ── player ────────────────────────────────────────────
    def make_player(self) -> VideoPlayer:
        self.player = VideoPlayer()
        self.player.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        for key, slot in (("Space", self.player.toggle_play),
                          ("Left", lambda: self.player.step_frames(-1)),
                          ("Right", lambda: self.player.step_frames(1)),
                          ("Shift+Left", lambda: self.player.step_seconds(-1)),
                          ("Shift+Right", lambda: self.player.step_seconds(1)),
                          ("Home", lambda: self.player.seek(0)),
                          ("End", lambda: self.player.seek(self.player.duration))):
            self.player_key(key, slot)
        return self.player

    def player_key(self, key, slot) -> QShortcut:
        shortcut = QShortcut(QKeySequence(key), self.player)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(slot)
        return shortcut

    def on_theme(self, theme) -> None:
        if self.player is not None:
            self.player.set_theme(theme)

    def shutdown(self) -> None:
        if self.player is not None:
            self.player.shutdown()
