"""The audit log for a batch, as a table."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QTableWidget,
                               QTableWidgetItem)

from .common import Dialog, hint


class HistoryDialog(Dialog):
    """Every save, export and decision recorded for this batch."""

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
