"""Running jobs in the background, and the panel that shows them.

One JobManager belongs to the shell, so a conversion started in one tool
keeps running while you use another or go Home.  Work runs on plain Python
threads; every state change comes back to the UI thread through a queued
signal, so widgets are only ever touched from the thread that owns them.
"""

from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QScrollArea,
                               QToolButton, QVBoxLayout, QWidget)

from . import design
from .dialogs import messages
from ..core.jobs import CANCELLED, DONE, FAILED, QUEUED, RUNNING, execute
from . import icons
from .widgets import section_label

STATE_TEXT = {QUEUED: ("Queued", "Subtitle"), RUNNING: ("Running", "HintWarn"),
              DONE: ("Done", "HintGood"), FAILED: ("Failed", "HintDanger"),
              CANCELLED: ("Cancelled", "Subtitle")}


class JobManager(QObject):
    jobAdded = Signal(object)
    jobChanged = Signal(object)
    jobFinished = Signal(object)
    jobsRemoved = Signal()

    _changed = Signal(object)
    _done = Signal(object)

    def __init__(self, parent=None, max_parallel: int = 1):
        super().__init__(parent)
        self.max_parallel = max(1, int(max_parallel))
        self.jobs = []
        self._queue = []
        self._running = 0
        self._changed.connect(self._on_changed, Qt.ConnectionType.QueuedConnection)
        self._done.connect(self._on_done, Qt.ConnectionType.QueuedConnection)

    # ── submitting ────────────────────────────────────────
    def submit(self, job):
        self.jobs.append(job)
        self._queue.append(job)
        self.jobAdded.emit(job)
        self._pump()
        return job

    def _pump(self) -> None:
        while self._running < self.max_parallel and self._queue:
            job = self._queue.pop(0)
            if job.cancel_event.is_set():
                self._mark_cancelled(job)
                continue
            self._running += 1
            threading.Thread(target=self._work, args=(job,), daemon=True,
                             name="annotex-job-%d" % job.id).start()

    def _work(self, job) -> None:
        try:
            execute(job, notify=self._changed.emit)
        finally:
            self._done.emit(job)

    @Slot(object)
    def _on_changed(self, job) -> None:
        self.jobChanged.emit(job)

    @Slot(object)
    def _on_done(self, job) -> None:
        self._running = max(0, self._running - 1)
        self.jobChanged.emit(job)
        self.jobFinished.emit(job)
        self._pump()

    def _mark_cancelled(self, job) -> None:
        job.state = CANCELLED
        job.message = "Cancelled before it started"
        job.finished_at = time.time()
        self.jobChanged.emit(job)
        self.jobFinished.emit(job)

    # ── controlling ───────────────────────────────────────
    def cancel(self, job) -> None:
        job.cancel()
        if job in self._queue:
            self._queue.remove(job)
            self._mark_cancelled(job)
        else:
            job.message = "Cancelling…"
            self.jobChanged.emit(job)

    def cancel_all(self, tool=None) -> int:
        targets = self.active(tool)
        for job in targets:
            self.cancel(job)
        return len(targets)

    def active(self, tool=None):
        return [j for j in self.jobs if j.active and (tool is None or j.tool == tool)]

    def remove(self, job) -> None:
        if job.active:
            return
        self.jobs = [j for j in self.jobs if j is not job]
        self.jobsRemoved.emit()

    def clear_finished(self, tool=None) -> None:
        self.jobs = [j for j in self.jobs if j.active or (tool is not None and j.tool != tool)]
        self.jobsRemoved.emit()

    def wait(self, timeout: float = 600.0) -> bool:
        """Block (processing events) until nothing is active.  For tests and
        for quitting."""
        deadline = time.monotonic() + timeout
        while self.active() and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.02)
        QApplication.processEvents()
        return not self.active()


def open_location(path) -> None:
    target = path if os.path.isdir(path) else os.path.dirname(path)
    QDesktopServices.openUrl(QUrl.fromLocalFile(target))


class JobRow(QFrame):
    def __init__(self, manager, job, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.job = job
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        design.margins(layout, "s", "s", "s", "m")
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.title = QLabel(job.title)
        self.title.setFont(design.font("emphasis", self.title.font()))
        top.addWidget(self.title, 1)
        self.state = QLabel("")
        top.addWidget(self.state)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("Quiet")
        self.cancel_button.clicked.connect(lambda: manager.cancel(self.job))
        top.addWidget(self.cancel_button)
        self.open_button = QPushButton("Open")
        self.open_button.setObjectName("Quiet")
        self.open_button.setToolTip("Show the result in the file manager")
        self.open_button.clicked.connect(self._open)
        top.addWidget(self.open_button)
        self.details_button = QPushButton("Details")
        self.details_button.setObjectName("Quiet")
        self.details_button.clicked.connect(self._details)
        top.addWidget(self.details_button)
        self.remove_button = QToolButton()
        self.remove_button.setText("✕")
        self.remove_button.setToolTip("Remove from the list")
        self.remove_button.clicked.connect(lambda: manager.remove(self.job))
        top.addWidget(self.remove_button)
        layout.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        layout.addWidget(self.bar)
        self.message = QLabel("")
        self.message.setObjectName("Hint")
        layout.addWidget(self.message)
        self.refresh()

    def refresh(self) -> None:
        job = self.job
        text, name = STATE_TEXT.get(job.state, (job.state, "Subtitle"))
        if job.state == RUNNING:
            text = "%d%%" % int(job.progress * 100)
        elif job.state == DONE and job.warnings:
            text, name = "Done with %d warning(s)" % len(job.warnings), "HintWarn"
        self.state.setText(text)
        self.state.setObjectName(name)
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        self.bar.setValue(int(job.progress * 1000))
        self.bar.setVisible(job.active)
        message = job.message
        if job.finished_at and job.started_at:
            message = "%s  ·  %.1fs" % (message, job.elapsed)
        metrics = QFontMetrics(self.message.font())
        self.message.setText(metrics.elidedText(message, Qt.TextElideMode.ElideRight,
                                                max(200, self.width() - 40)))
        self.message.setToolTip(message)
        self.cancel_button.setVisible(job.active)
        self.open_button.setVisible(bool(job.outputs) and not job.active)
        self.details_button.setVisible(job.state == FAILED or bool(job.warnings))
        self.remove_button.setVisible(not job.active)

    def _open(self) -> None:
        if self.job.outputs:
            open_location(self.job.outputs[-1])

    def _details(self) -> None:
        job = self.job
        lines = []
        if job.error:
            lines.append(job.error)
        lines.extend(job.warnings[:40])
        if len(job.warnings) > 40:
            lines.append("… and %d more" % (len(job.warnings) - 40))
        text = job.message
        if lines:
            text = "%s\n\n%s" % (text, "\n".join(lines)[:4000])
        show = messages.warn if job.state == FAILED else messages.inform
        show(self, job.title, text, detail=job.detail or "")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()


class JobQueuePanel(QWidget):
    """The jobs of one tool (or of every tool, with tool=None)."""

    def __init__(self, manager, tool=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.tool = tool
        self.rows = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(section_label("Jobs"))
        self.count = QLabel("")
        self.count.setObjectName("Subtitle")
        header.addWidget(self.count)
        header.addStretch(1)
        self.cancel_all = QPushButton("Cancel all")
        self.cancel_all.clicked.connect(lambda: manager.cancel_all(self.tool))
        header.addWidget(self.cancel_all)
        self.clear = QPushButton("Clear finished")
        self.clear.clicked.connect(lambda: manager.clear_finished(self.tool))
        header.addWidget(self.clear)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(40)
        holder = QWidget()
        self.list_layout = QVBoxLayout(holder)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(design.SPACE["s"])
        self.empty = QLabel("Nothing queued yet. Jobs keep running while you use other tools.")
        self.empty.setObjectName("Hint")
        self.list_layout.addWidget(self.empty)
        self.list_layout.addStretch(1)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)

        manager.jobAdded.connect(self._added)
        manager.jobChanged.connect(self._changed)
        manager.jobsRemoved.connect(self._rebuild)
        self._rebuild()

    def _wanted(self, job) -> bool:
        return self.tool is None or job.tool == self.tool

    def _added(self, job) -> None:
        if not self._wanted(job):
            return
        row = JobRow(self.manager, job)
        self.rows[job.id] = row
        self.list_layout.insertWidget(0, row)
        self._summary()

    def _changed(self, job) -> None:
        row = self.rows.get(job.id)
        if row is not None:
            row.refresh()
        self._summary()

    def _rebuild(self) -> None:
        for row in self.rows.values():
            row.setParent(None)
            row.deleteLater()
        self.rows = {}
        for job in self.manager.jobs:
            if self._wanted(job):
                row = JobRow(self.manager, job)
                self.rows[job.id] = row
                self.list_layout.insertWidget(0, row)
        self._summary()

    def _summary(self) -> None:
        jobs = [j for j in self.manager.jobs if self._wanted(j)]
        active = [j for j in jobs if j.active]
        self.empty.setVisible(not jobs)
        self.count.setText("%d running or queued" % len(active) if active else
                           ("%d finished" % len(jobs) if jobs else ""))
        self.cancel_all.setEnabled(bool(active))
        self.clear.setEnabled(len(jobs) > len(active))
