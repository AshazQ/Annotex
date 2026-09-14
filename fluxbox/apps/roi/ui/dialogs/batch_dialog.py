"""Apply one decision to many images at once.

Fixed cameras produce batches where every frame wants the same regions, so
drawing them once and applying them to the rest is the difference between a
morning's work and a minute's.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QRadioButton)

from ...core import geometry as geo
from .common import Dialog, card, hint

APPLY_ROIS = "rois"
APPLY_NO_ROI = "no_roi"


class BatchApplyDialog(Dialog):
    """Choose the images, choose what to do to them."""

    def __init__(self, parent, names, current, statuses, shape_count,
                 default_action=APPLY_ROIS):
        title = ("Apply these ROIs to other images" if default_action == APPLY_ROIS
                 else "Mark several images as no_roi")
        super().__init__(parent, title, "", width=620, height=600)
        self.names = list(names or [])
        self.current = current
        self.statuses = dict(statuses or {})
        self.shape_count = int(shape_count)
        self.selected = []
        self.action = default_action
        self.overwrite = False

        frame, inner = card("What to do")
        self.group = QButtonGroup(self)
        self.radio_rois = QRadioButton(
            "Copy the %d ROI(s) from %s onto every chosen image"
            % (self.shape_count, current or "this image"))
        self.radio_no_roi = QRadioButton(
            "Mark every chosen image as no_roi")
        self.radio_rois.setEnabled(self.shape_count > 0)
        self.group.addButton(self.radio_rois)
        self.group.addButton(self.radio_no_roi)
        if default_action == APPLY_ROIS and self.shape_count > 0:
            self.radio_rois.setChecked(True)
        else:
            self.radio_no_roi.setChecked(True)
        inner.addWidget(self.radio_rois)
        inner.addWidget(self.radio_no_roi)
        if self.shape_count <= 0:
            inner.addWidget(hint("Draw at least one ROI to be able to copy it "
                                 "onto other images."))
        self.body.addWidget(frame)

        frame2, inner2 = card("Which images")
        picks = QHBoxLayout()
        picks.setSpacing(6)
        for label, slot in (("All", self._pick_all),
                            ("None", self._pick_none),
                            ("Same camera", self._pick_same_camera),
                            ("Untouched only", self._pick_untouched),
                            ("After this one", self._pick_after)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            picks.addWidget(button)
        picks.addStretch(1)
        inner2.addLayout(picks)

        self.list = QListWidget()
        self.list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        marks = {"roi": "●", "no_roi": "○", "todo": "·"}
        for name in self.names:
            item = QListWidgetItem("%s  %s" % (marks.get(
                self.statuses.get(name, "todo"), "·"), name))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            if name == current:
                item.setToolTip("the image you are on")
            self.list.addItem(item)
        self.list.itemChanged.connect(lambda _i: self._update_summary())
        inner2.addWidget(self.list, 1)
        self.body.addWidget(frame2, 1)

        self.overwrite_note = hint("")
        self.body.addWidget(self.overwrite_note)

        self.summary = QLabel("")
        self.summary.setObjectName("Subtitle")
        self.buttons.insertWidget(0, self.summary)
        self.buttons.insertStretch(1, 1)
        self.add_button("Cancel", slot=self.reject)
        self.apply_button = self.add_button("Apply", primary=True,
                                            slot=self._accept)
        self._pick_untouched()

    # ── selection helpers ─────────────────────────────────
    def _set_all(self, predicate) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            name = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(Qt.CheckState.Checked if predicate(name, index)
                               else Qt.CheckState.Unchecked)
        self._update_summary()

    def _pick_all(self):
        self._set_all(lambda name, _i: name != self.current)

    def _pick_none(self):
        self._set_all(lambda _n, _i: False)

    def _pick_same_camera(self):
        key = geo.make_roi_key(self.current or "")
        self._set_all(lambda name, _i: name != self.current
                      and geo.make_roi_key(name) == key)

    def _pick_untouched(self):
        self._set_all(lambda name, _i: name != self.current
                      and self.statuses.get(name, "todo") == "todo")

    def _pick_after(self):
        try:
            start = self.names.index(self.current)
        except ValueError:
            start = -1
        self._set_all(lambda _n, index: index > start)

    def _checked(self):
        out = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def _update_summary(self) -> None:
        chosen = self._checked()
        already = [n for n in chosen if self.statuses.get(n, "todo") != "todo"]
        self.summary.setText("%d image(s) chosen" % len(chosen))
        if already:
            self.overwrite_note.setText(
                "%d of them already have a decision saved and will be "
                "replaced." % len(already))
        else:
            self.overwrite_note.setText("")
        self.apply_button.setEnabled(bool(chosen))

    def _accept(self) -> None:
        self.selected = self._checked()
        self.action = APPLY_ROIS if self.radio_rois.isChecked() else APPLY_NO_ROI
        self.overwrite = any(self.statuses.get(n, "todo") != "todo"
                             for n in self.selected)
        if not self.selected:
            return
        self.accept()
