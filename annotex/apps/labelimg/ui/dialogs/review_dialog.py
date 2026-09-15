"""Review mode and the summary dashboard."""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QListWidget,
                               QListWidgetItem, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from annotex.ui.dialogs.common import Dialog, card, hint
from annotex.ui.palette import qcolor, readable_on

from .....ui import design
from ..panels import swatch_icon

FILTERS = (("all", "Every image"), ("labelled", "Labelled"),
           ("background", "Background"), ("todo", "Not started"),
           ("unverified", "Annotated, not verified"))


class BoxPreview(QWidget):
    """An image scaled to fit, with its boxes drawn in their class colours."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self._pixmap = None
        self._boxes = []
        self._message = "-"
        self._theme = {}
        self._colour_for = lambda _label: "#f0a33d"
        self.verified = False

    def set_theme(self, theme, colour_for) -> None:
        self._theme = dict(theme)
        self._colour_for = colour_for
        self.update()

    def show_image(self, pixmap, boxes, message="", verified=False) -> None:
        self._pixmap = pixmap if pixmap is not None and not pixmap.isNull() else None
        self._boxes = list(boxes or [])
        self._message = message or "Not available"
        self.verified = verified
        self.update()

    def paintEvent(self, event):
        theme = self._theme or {}
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), qcolor(theme.get("canvasVoid", "#101319")))
        if self._pixmap is None:
            painter.setPen(qcolor(theme.get("muted", "#6f7784")))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            painter.end()
            return
        area = QRectF(8, 8, self.width() - 16, self.height() - 16)
        scale = min(area.width() / self._pixmap.width(), area.height() / self._pixmap.height())
        width, height = self._pixmap.width() * scale, self._pixmap.height() * scale
        target = QRectF(area.center().x() - width / 2, area.center().y() - height / 2,
                        width, height)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        if self.verified:
            painter.setPen(QPen(qcolor(theme.get("good", "#5cbf6b")), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(target.adjusted(-2, -2, 2, 2))

        font = design.font("label", self.font())
        painter.setFont(font)
        metrics = QFontMetrics(font)
        for box in self._boxes:
            colour = qcolor(self._colour_for(box.label))
            rect = QRectF(target.left() + box.x0 * scale, target.top() + box.y0 * scale,
                          box.width * scale, box.height * scale)
            painter.setPen(QPen(QColor(0, 0, 0, 120), 4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            fill = QColor(colour)
            fill.setAlpha(40)
            painter.setPen(QPen(colour, 2))
            painter.setBrush(QBrush(fill))
            painter.drawRect(rect)
            text = box.label + ("  · difficult" if box.difficult else "")
            chip = QRectF(rect.left(), max(target.top(), rect.top() - metrics.height() - 4),
                          metrics.horizontalAdvance(text) + 10, metrics.height() + 4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(colour))
            painter.drawRoundedRect(chip, 3, 3)
            painter.setPen(qcolor(readable_on(colour.name())))
            painter.drawText(chip.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()


class ReviewDialog(Dialog):
    """Page through the batch at full size, and fix anything wrong."""

    jumpRequested = Signal(str)
    verifyRequested = Signal(str)

    def __init__(self, parent, names, statuses, loader, colour_for, theme=None):
        """`loader(name)` returns (pixmap, boxes, verified, note)."""
        super().__init__(parent, "Review mode",
                         "Every image as it will be exported. ← / → to move, "
                         "Space to toggle verified, Enter to edit.",
                         width=1080, height=720)
        self.names = list(names or [])
        self.statuses = dict(statuses or {})
        self.loader = loader
        self._visible = list(self.names)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body.addWidget(splitter, 1)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 8, 0)
        side_layout.setSpacing(8)
        self.filter_box = QComboBox()
        for key, label in FILTERS:
            self.filter_box.addItem(label, key)
        self.filter_box.currentIndexChanged.connect(self._populate)
        side_layout.addWidget(self.filter_box)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.currentRowChanged.connect(self._show_row)
        side_layout.addWidget(self.list, 1)
        self.counter = QLabel("-")
        self.counter.setObjectName("Subtitle")
        side_layout.addWidget(self.counter)
        splitter.addWidget(side)

        self.preview = BoxPreview()
        self.preview.set_theme(theme or {}, colour_for)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 800])

        self.note = hint("")
        self.body.addWidget(self.note)

        self.add_button("Previous", slot=lambda: self._step(-1))
        self.add_button("Next", slot=lambda: self._step(1))
        self.verify_button = self.add_button("Toggle verified", slot=self._verify)
        self.add_button("Edit this image", primary=True, slot=self._jump)
        self.add_close_button()
        self._populate()

    def set_status(self, name, status) -> None:
        self.statuses[name] = status
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                item.setText(self._row_text(name))

    def _row_text(self, name) -> str:
        marks = {"labelled": "●", "background": "○", "verified": "✓", "todo": "·"}
        return "%s  %s" % (marks.get(self.statuses.get(name, "todo"), "·"), name)

    def _matches(self, name, key) -> bool:
        status = self.statuses.get(name, "todo")
        if key == "all":
            return True
        if key == "labelled":
            return status in ("labelled", "verified")
        if key == "unverified":
            return status in ("labelled", "background")
        return status == key

    def _populate(self, *_args) -> None:
        key = self.filter_box.currentData()
        current = self.current_name()
        self._visible = [n for n in self.names if self._matches(n, key)]
        self.list.blockSignals(True)
        self.list.clear()
        for name in self._visible:
            item = QListWidgetItem(self._row_text(name))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(name)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if not self._visible:
            self.preview.show_image(None, [], "No image matches this filter.")
            self.counter.setText("0 images")
            self.note.setText("")
            return
        row = self._visible.index(current) if current in self._visible else 0
        self.list.setCurrentRow(row)
        self._show_row(row)

    def current_name(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _show_row(self, row) -> None:
        if not (0 <= row < len(self._visible)):
            return
        name = self._visible[row]
        pixmap, boxes, verified, note = self.loader(name)
        self.preview.show_image(pixmap, boxes, note or "Image could not be read", verified)
        self.counter.setText("%d of %d" % (row + 1, len(self._visible)))
        classes = sorted({b.label for b in boxes})
        status = self.statuses.get(name, "todo")
        if status == "todo":
            text = "%s has no annotation yet." % name
        elif not boxes:
            text = "%s is background - annotated with no boxes." % name
        else:
            text = "%s  ·  %d box(es)  ·  %s" % (name, len(boxes), ", ".join(classes))
        if verified:
            text += "  ·  verified"
        if note and pixmap is not None:
            text += "  ·  " + note
        self.note.setText(text)

    def _step(self, delta) -> None:
        target = self.list.currentRow() + int(delta)
        if 0 <= target < self.list.count():
            self.list.setCurrentRow(target)

    def _verify(self) -> None:
        name = self.current_name()
        if name:
            self.verifyRequested.emit(name)
            self._show_row(self.list.currentRow())

    def _jump(self) -> None:
        name = self.current_name()
        if name:
            self.jumpRequested.emit(name)
            self.accept()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._step(1)
            return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._step(-1)
            return
        if key == Qt.Key.Key_Space:
            self._verify()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._jump()
            return
        super().keyPressEvent(event)


class DashboardDialog(Dialog):
    """Where the batch stands, with the HTML report one click away."""

    reportRequested = Signal()

    def __init__(self, parent, stats, theme=None):
        super().__init__(parent, "Summary dashboard",
                         "Where this batch stands right now.", width=900, height=640)
        totals = stats["totals"]
        tiles = QGridLayout()
        tiles.setHorizontalSpacing(12)
        tiles.setVerticalSpacing(4)
        entries = [("Images", totals["images"]), ("Labelled", totals["labelled"]),
                   ("Background", totals["background"]), ("Remaining", totals["remaining"]),
                   ("Boxes", totals["boxes"]), ("Verified", totals["verified"])]
        for column, (label, value) in enumerate(entries):
            value_label = QLabel(str(value))
            value_label.setObjectName("StatValue")
            caption = QLabel(label)
            caption.setObjectName("StatLabel")
            tiles.addWidget(value_label, 0, column)
            tiles.addWidget(caption, 1, column)
        self.body.addLayout(tiles)

        frame, inner = card("Class balance")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", "class", "id", "boxes", "images", "share"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 6):
            head.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for entry in stats["classes"]:
            index = self.table.rowCount()
            self.table.insertRow(index)
            swatch = QTableWidgetItem("")
            swatch.setIcon(swatch_icon(entry["colour"] or "#888888"))
            self.table.setItem(index, 0, swatch)
            name = entry["name"]
            if not entry["in_project"]:
                name += "   (not in the project)"
            elif not entry["active"]:
                name += "   (deprecated)"
            self.table.setItem(index, 1, QTableWidgetItem(name))
            for column, value in ((2, "-" if entry["id"] is None else entry["id"]),
                                  (3, entry["boxes"]), (4, entry["images"]),
                                  (5, "%.1f%%" % entry["share"])):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(index, column, item)
        inner.addWidget(self.table)
        self.body.addWidget(frame, 1)

        unused = [c["name"] for c in stats["classes"] if c["in_project"] and c["active"]
                  and not c["boxes"]]
        if unused:
            self.body.addWidget(hint("%d active class(es) have no boxes yet: %s"
                                     % (len(unused), ", ".join(unused[:12]))))
        if totals.get("unreadable"):
            self.body.addWidget(hint("%d annotation file(s) could not be read - they "
                                     "are listed in the HTML report." % totals["unreadable"]))

        self.add_button("Write the HTML report",
                        slot=lambda: (self.reportRequested.emit(), self.accept()))
        self.add_close_button()
