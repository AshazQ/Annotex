"""Apply one decision to many images at once.

Fixed cameras produce batches where every frame wants the same boxes - or
where a run of frames has nothing in it at all.  Deciding once and applying it
to the rest is the difference between a morning's work and a minute's.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QRadioButton)

from fluxbox.ui.dialogs.common import Dialog, card, hint

APPLY_BOXES = "boxes"
APPLY_BACKGROUND = "background"
MARKS = {"labelled": "●", "background": "○", "verified": "✓", "todo": "·"}


def camera_key(name) -> str:
    """'SITE01_cam3_2026-08-14.jpg' -> 'site01_cam3'; else the folder."""
    stem = os.path.splitext(os.path.basename(str(name)))[0]
    parts = stem.split("_")
    if len(parts) >= 2 and parts[0]:
        return (os.path.dirname(str(name)) + "|" + "_".join(parts[:2])).lower()
    return os.path.dirname(str(name)).lower()


class BatchApplyDialog(Dialog):
    """Choose the images, choose what to do to them."""

    def __init__(self, parent, names, current, statuses, box_count,
                 default_action=APPLY_BOXES):
        title = ("Apply these boxes to other images" if default_action == APPLY_BOXES
                 else "Mark several images as background")
        super().__init__(parent, title, "", width=640, height=620)
        self.names = list(names or [])
        self.current = current
        self.statuses = dict(statuses or {})
        self.box_count = int(box_count)
        self.selected = []
        self.action = default_action
        self.overwrite = False

        frame, inner = card("What to do")
        self.group = QButtonGroup(self)
        self.radio_boxes = QRadioButton("Copy the %d box(es) on %s onto every chosen image"
                                        % (self.box_count, current or "this image"))
        self.radio_background = QRadioButton(
            "Save every chosen image as background (an annotation with no boxes)")
        self.radio_boxes.setEnabled(self.box_count > 0)
        self.group.addButton(self.radio_boxes)
        self.group.addButton(self.radio_background)
        if default_action == APPLY_BOXES and self.box_count > 0:
            self.radio_boxes.setChecked(True)
        else:
            self.radio_background.setChecked(True)
        inner.addWidget(self.radio_boxes)
        inner.addWidget(self.radio_background)
        if self.box_count <= 0:
            inner.addWidget(hint("Draw at least one box to copy it onto other images."))
        else:
            inner.addWidget(hint("Each box is fitted to each image, so frames of a "
                                 "different size still get sensible boxes."))
        self.body.addWidget(frame)

        frame2, inner2 = card("Which images")
        picks = QHBoxLayout()
        picks.setSpacing(6)
        for label, slot in (("All", self._pick_all), ("None", self._pick_none),
                            ("Same camera", self._pick_same_camera),
                            ("Not started", self._pick_untouched),
                            ("After this one", self._pick_after)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            picks.addWidget(button)
        picks.addStretch(1)
        inner2.addLayout(picks)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for name in self.names:
            item = QListWidgetItem("%s  %s" % (MARKS.get(self.statuses.get(name, "todo"), "·"),
                                               name))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            if name == current:
                item.setToolTip("the image you are on")
            self.list.addItem(item)
        self.list.itemChanged.connect(lambda _item: self._update_summary())
        inner2.addWidget(self.list, 1)
        self.body.addWidget(frame2, 1)

        self.overwrite_note = hint("")
        self.body.addWidget(self.overwrite_note)
        self.summary = QLabel("")
        self.summary.setObjectName("Subtitle")
        self.buttons.insertWidget(0, self.summary)
        self.buttons.insertStretch(1, 1)
        self.add_button("Cancel", slot=self.reject)
        self.apply_button = self.add_button("Apply", primary=True, slot=self._accept)
        self._pick_untouched()

    def _set_all(self, predicate) -> None:
        self.list.blockSignals(True)
        for index in range(self.list.count()):
            item = self.list.item(index)
            name = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(Qt.CheckState.Checked if predicate(name, index)
                               else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self._update_summary()

    def _pick_all(self):
        self._set_all(lambda name, _i: name != self.current)

    def _pick_none(self):
        self._set_all(lambda _n, _i: False)

    def _pick_same_camera(self):
        key = camera_key(self.current or "")
        self._set_all(lambda name, _i: name != self.current and camera_key(name) == key)

    def _pick_untouched(self):
        self._set_all(lambda name, _i: name != self.current
                      and self.statuses.get(name, "todo") == "todo")

    def _pick_after(self):
        try:
            start = self.names.index(self.current)
        except ValueError:
            start = -1
        self._set_all(lambda _n, index: index > start)

    def checked(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def _update_summary(self) -> None:
        chosen = self.checked()
        already = [n for n in chosen if self.statuses.get(n, "todo") != "todo"]
        self.summary.setText("%d image(s) chosen" % len(chosen))
        self.overwrite_note.setText(
            "%d of them already have an annotation, which will be replaced "
            "(the previous version is kept in the backup folder)." % len(already)
            if already else "")
        self.apply_button.setEnabled(bool(chosen))

    def _accept(self) -> None:
        self.selected = self.checked()
        if not self.selected:
            return
        self.action = APPLY_BOXES if self.radio_boxes.isChecked() else APPLY_BACKGROUND
        self.overwrite = any(self.statuses.get(n, "todo") != "todo" for n in self.selected)
        self.accept()
