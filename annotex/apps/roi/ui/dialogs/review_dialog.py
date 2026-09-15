"""Review mode, the summary dashboard and the change history."""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget,
                               QListWidgetItem, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .....ui import design
from ...config import NO_ROI_DIR, PRINTED_DIR
from ...core import report as reporting
from .common import Dialog, card, hint


class _ImagePane(QWidget):
    """A single image, scaled to fit, with a caption."""

    def __init__(self, caption, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260, 220)
        self._pixmap = None
        self._caption = caption
        self._message = "-"
        self._theme = {}

    def set_theme(self, theme):
        self._theme = dict(theme)
        self.update()

    def show_path(self, path, message="") -> bool:
        self._message = message or "Not available"
        self._pixmap = None
        if path and os.path.isfile(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self._pixmap = pixmap
        self.update()
        return self._pixmap is not None

    def paintEvent(self, event):
        from ..palette import qcolor
        theme = self._theme or {}
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), qcolor(theme.get("canvasVoid", "#101319")))

        caption_height = 22
        area = QRectF(4, 4, self.width() - 8,
                      self.height() - 8 - caption_height)
        if self._pixmap is not None:
            scale = min(area.width() / self._pixmap.width(),
                        area.height() / self._pixmap.height())
            width = self._pixmap.width() * scale
            height = self._pixmap.height() * scale
            target = QRectF(area.center().x() - width / 2.0,
                            area.center().y() - height / 2.0, width, height)
            painter.drawPixmap(target, self._pixmap,
                               QRectF(self._pixmap.rect()))
        else:
            painter.setPen(qcolor(theme.get("muted", "#6f7784")))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, self._message)

        painter.setPen(qcolor(theme.get("sub", "#8b93a1")))
        painter.drawText(QRectF(4, self.height() - caption_height,
                                self.width() - 8, caption_height),
                         Qt.AlignmentFlag.AlignCenter, self._caption)
        painter.end()


class ReviewDialog(Dialog):
    """The original beside the burnt-in copy, image by image."""

    jumpRequested = Signal(str)

    def __init__(self, parent, folder, names, statuses, theme=None):
        super().__init__(parent, "Review mode",
                         "The image as it came in, beside the copy with its "
                         "ROIs burnt in.", width=1040, height=680)
        self.folder = str(folder)
        self.names = list(names or [])
        self.statuses = dict(statuses or {})
        self._theme = dict(theme or {})
        self._index = 0

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body.addWidget(splitter, 1)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 8, 0)
        side_layout.setSpacing(8)
        self.list = QListWidget()
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.list.currentRowChanged.connect(self._show_index)
        side_layout.addWidget(self.list, 1)
        self.counter = QLabel("-")
        self.counter.setObjectName("Subtitle")
        side_layout.addWidget(self.counter)
        splitter.addWidget(side)

        panes = QWidget()
        pane_layout = QHBoxLayout(panes)
        pane_layout.setContentsMargins(0, 0, 0, 0)
        pane_layout.setSpacing(8)
        self.left = _ImagePane("Original")
        self.right = _ImagePane("With ROIs (printed_roi)")
        for pane in (self.left, self.right):
            pane.set_theme(self._theme)
            pane_layout.addWidget(pane, 1)
        splitter.addWidget(panes)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 780])

        self.note = hint("")
        self.body.addWidget(self.note)

        self.add_button("Previous", slot=lambda: self._step(-1))
        self.add_button("Next", slot=lambda: self._step(1))
        self.add_button("Edit this image", slot=self._jump)
        self.add_close_button()

        self._populate()

    def _populate(self) -> None:
        self.list.clear()
        marks = {"roi": "●", "no_roi": "○", "todo": "·"}
        for name in self.names:
            status = self.statuses.get(name, "todo")
            item = QListWidgetItem("%s  %s" % (marks.get(status, "·"), name))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(name)
            self.list.addItem(item)
        if self.names:
            self.list.setCurrentRow(0)
        else:
            self.note.setText("This batch has no images.")

    def current_name(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _show_index(self, index) -> None:
        if not (0 <= index < len(self.names)):
            return
        self._index = index
        name = self.names[index]
        status = self.statuses.get(name, "todo")
        self.left.show_path(os.path.join(self.folder, name),
                            "Original not found")
        printed = os.path.join(self.folder, PRINTED_DIR, name)
        has_printed = self.right.show_path(
            printed, "No printed copy yet - save this image to create one")
        self.counter.setText("%d of %d" % (index + 1, len(self.names)))

        if status == "no_roi":
            self.note.setText("%s is filed under %s - no ROI was drawn."
                              % (name, NO_ROI_DIR))
        elif status == "roi" and not has_printed:
            self.note.setText("%s has saved ROIs but no printed copy. Re-save "
                              "it to regenerate the preview." % name)
        elif status == "todo":
            self.note.setText("%s has not been visited yet." % name)
        else:
            self.note.setText(name)

    def _step(self, delta) -> None:
        target = self._index + int(delta)
        if 0 <= target < len(self.names):
            self.list.setCurrentRow(target)

    def _jump(self) -> None:
        name = self.current_name()
        if name:
            self.jumpRequested.emit(name)
            self.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._step(1)
            return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._step(-1)
            return
        super().keyPressEvent(event)


class DashboardDialog(Dialog):
    """Coverage and throughput for the batch, with the HTML report one click
    away."""

    reportRequested = Signal()

    def __init__(self, parent, rows, folder, names, session=None, theme=None):
        super().__init__(parent, "Summary dashboard",
                         "Where this batch stands right now.",
                         width=880, height=620)
        self._theme = dict(theme or {})
        self.stats = reporting.build_stats(rows, names, folder)
        totals = self.stats["totals"]

        tiles = QGridLayout()
        tiles.setHorizontalSpacing(design.SPACE["s"])
        tiles.setVerticalSpacing(design.SPACE["s"])
        entries = [("Images", totals["images"]),
                   ("ROI drawn", totals["annotated"]),
                   ("No ROI", totals["no_roi"]),
                   ("Remaining", totals["remaining"]),
                   ("Total ROIs", totals["polygons"]),
                   ("Cameras covered", "%d / %d" % (totals["cameras_covered"],
                                                    totals["cameras"]))]
        if session:
            entries.append(("Session", session.get("elapsed", "-")))
            entries.append(("Images / hour",
                            "%.0f" % float(session.get("per_hour", 0.0))))
        for column, (label, value) in enumerate(entries):
            value_label = QLabel(str(value))
            value_label.setObjectName("StatValue")
            caption = QLabel(label)
            caption.setObjectName("StatLabel")
            tiles.addWidget(value_label, 0, column)
            tiles.addWidget(caption, 1, column)
        self.body.addLayout(tiles)

        frame, inner = card("Coverage by camera")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["roi_key", "site", "images", "annotated", "ROIs", "state"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter)
        for column in range(0, 5):
            head.setSectionResizeMode(column,
                                      QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for camera in self.stats["cameras"]:
            index = self.table.rowCount()
            self.table.insertRow(index)
            if camera["polygons"]:
                state = "covered"
            elif camera["no_roi"]:
                state = "marked no_roi"
            else:
                state = "not started"
            values = [camera["roi_key"], camera["site_id"],
                      str(camera["images"]), str(camera["annotated"]),
                      str(camera["polygons"]), state]
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(value))
        inner.addWidget(self.table)
        self.body.addWidget(frame, 1)

        missing = totals.get("cameras_missing", [])
        if missing:
            preview = ", ".join(missing[:10])
            more = " and %d more" % (len(missing) - 10) if len(missing) > 10 else ""
            self.body.addWidget(hint(
                "%d camera(s) have neither an ROI nor a no_roi decision: %s%s"
                % (len(missing), preview, more)))

        self.add_button("Write the HTML report",
                        slot=lambda: (self.reportRequested.emit(), self.accept()))
        self.add_close_button()


class HistoryDialog(Dialog):
    """The audit log for this batch."""

    def __init__(self, parent, entries):
        super().__init__(parent, "Change history",
                         "Every save, export and decision recorded for this "
                         "batch, newest last.", width=760, height=560)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["when", "action", "image",
                                              "detail"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter)
        for column in range(0, 3):
            head.setSectionResizeMode(column,
                                      QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        for entry in entries or []:
            index = self.table.rowCount()
            self.table.insertRow(index)
            for column, key in enumerate(("at", "action", "image", "detail")):
                self.table.setItem(index, column,
                                   QTableWidgetItem(str(entry.get(key, ""))))
        self.body.addWidget(self.table, 1)
        if not entries:
            self.body.addWidget(hint("Nothing recorded yet for this batch."))
        self.table.scrollToBottom()
        self.add_close_button()
