"""Every folder you have worked in, and what a start should look like.

Home's Continue strip shows the last three.  This shows the rest, with what
each one cost and how far it got, and it is where the choice of what Annotex
does when it opens lives - because that choice is about these sessions and
nowhere else would explain itself.

A session from another machine is listed and labelled, never resumed: the
folder it names is an absolute path on a computer that is not this one, and
a synced settings folder is an ordinary thing to have.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHeaderView,
                               QLabel, QTableWidget, QTableWidgetItem)

from ..config import STARTUP_CHOICES, STARTUP_HOME, SUITE_NAME
from ..core.sessions import machine_label
from ..ui.dialogs import messages
from ..ui.dialogs.common import Dialog, hint, row
from ..ui.jobs import open_location

COLUMNS = ("Tool", "Folder", "Last worked in", "How far", "Time")


def _when(stamp) -> str:
    """"2026-09-16T13:04:11" as something worth reading."""
    text = str(stamp or "")
    if not text:
        return "—"
    return text.replace("T", "  ").rsplit(".", 1)[0][:16]


class SessionsDialog(Dialog):
    """The session list, and the Startup setting that acts on it."""

    resumeRequested = Signal(str, str)           # tool_id, folder

    def __init__(self, parent, store, tools, settings):
        super().__init__(parent, "Sessions",
                         "Every folder you have worked in, newest first.  Resume "
                         "opens one again where you left it.",
                         width=720, height=520)
        self.store = store
        self.settings = settings
        self.specs = {spec.id: spec for spec in tools}
        self.records = []

        self.startup = QComboBox()
        for value, label, why in STARTUP_CHOICES:
            self.startup.addItem(label, value)
            self.startup.setItemData(self.startup.count() - 1, why, Qt.ItemDataRole.ToolTipRole)
        current = str(self.settings.get("startup", STARTUP_HOME) or STARTUP_HOME)
        found = self.startup.findData(current)
        self.startup.setCurrentIndex(found if found >= 0 else 0)
        self.startup.currentIndexChanged.connect(self._startup_changed)
        self.body.addWidget(row(QLabel("When %s starts" % SUITE_NAME), self.startup, None))
        self.startup_why = hint("")
        self.body.addWidget(self.startup_why)

        self.recover = QCheckBox("Offer to pick up a run that did not finish")
        self.recover.setToolTip("After a crash or a power cut, ask once about the "
                                "folder you were in")
        self.recover.setChecked(bool(self.settings.get("offer_recovery", True)))
        self.recover.toggled.connect(
            lambda on: self.settings.set("offer_recovery", bool(on)))
        self.body.addWidget(self.recover)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, len(COLUMNS)):
            head.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._sync)
        self.table.doubleClicked.connect(lambda _index: self.resume())
        self.body.addWidget(self.table, 1)

        self.note = hint("")
        self.body.addWidget(self.note)

        self.resume_button = self.add_button("Resume", primary=True, slot=self.resume)
        self.open_button = self.add_button("Open folder", slot=self.open_folder)
        self.forget_button = self.add_button(
            "Forget", slot=self.forget,
            tooltip="Remove this session from the list.  The folder itself and "
                    "everything in it are left alone.")
        self.add_close_button()
        self.reload()
        self._startup_changed()

    # ── the list ──────────────────────────────────────────
    def reload(self) -> None:
        try:
            self.records = self.store.recent(limit=0, here_only=False,
                                             existing_only=False)
        except Exception:
            self.records = []
        self.table.setRowCount(len(self.records))
        for index, record in enumerate(self.records):
            spec = self.specs.get(record.tool_id)
            tool = spec.name if spec is not None else record.tool_id
            notes = []
            elsewhere = machine_label(record.machine)
            if elsewhere:
                notes.append(elsewhere)
            if not record.exists:
                notes.append("folder not there")
            if record.crashed:
                notes.append("did not finish")
            folder = record.folder + (("   ·   " + ", ".join(notes)) if notes else "")
            far = record.progress_text() or "—"
            if record.last_image:
                far = "%s   ·   %s" % (far, record.last_image) if record.progress_text() \
                    else record.last_image
            for column, text in enumerate((tool, folder, _when(record.touched_at), far,
                                           record.worked_text())):
                item = QTableWidgetItem(str(text))
                if column == 1:
                    item.setToolTip(record.folder)
                self.table.setItem(index, column, item)
        if self.records:
            self.table.selectRow(0)
        self.note.setText("Nothing has been worked in yet - open a folder in any "
                          "tool and it appears here." if not self.records else
                          "%d session(s) remembered." % len(self.records))
        self._sync()

    def selected(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if len(rows) != 1:
            return None
        row_index = rows.pop()
        return self.records[row_index] if 0 <= row_index < len(self.records) else None

    def _sync(self) -> None:
        record = self.selected()
        usable = record is not None and record.exists and not machine_label(record.machine)
        self.resume_button.setEnabled(bool(usable))
        self.open_button.setEnabled(bool(record is not None and record.exists))
        self.forget_button.setEnabled(record is not None)
        if record is None:
            self.resume_button.setToolTip("")
        elif machine_label(record.machine):
            self.resume_button.setToolTip("This session belongs to another machine, "
                                          "so its folders may be somewhere else here")
        elif not record.exists:
            self.resume_button.setToolTip("That folder is not there any more")
        else:
            self.resume_button.setToolTip("Open it again where you left off")

    def _startup_changed(self, _index=0) -> None:
        value = self.startup.currentData() or STARTUP_HOME
        self.settings.set("startup", value)
        why = next((w for v, _l, w in STARTUP_CHOICES if v == value), "")
        self.startup_why.setText(why)

    # ── what its buttons do ───────────────────────────────
    def resume(self) -> None:
        record = self.selected()
        if record is None or not record.exists or machine_label(record.machine):
            return
        self.resumeRequested.emit(record.tool_id, record.folder)
        self.accept()

    def open_folder(self) -> None:
        record = self.selected()
        if record is not None and record.exists:
            try:
                open_location(record.folder)
            except Exception:
                pass

    def forget(self) -> None:
        record = self.selected()
        if record is None:
            return
        if not messages.ask(self, "Forget this session",
                            "Remove %s from the list?\n\nThe folder and everything in "
                            "it are left exactly as they are." % record.name,
                            confirm="Forget", cancel="Keep"):
            return
        try:
            self.store.forget(record.tool_id, record.folder)
        except Exception:
            pass
        # The tool's own recent-folder list is a separate thing, and Home
        # reads both, so a session forgotten here would come back from there.
        spec = self.specs.get(record.tool_id)
        if spec is not None and spec.forget is not None:
            try:
                spec.forget(record.folder)
            except Exception:
                pass
        self.reload()
