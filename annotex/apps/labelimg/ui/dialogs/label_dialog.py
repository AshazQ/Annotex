"""Choose - or create - the class for a box."""

from __future__ import annotations

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCompleter, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem)

from annotex.ui.dialogs.common import Dialog, hint

from ...core.class_store import ClassStoreError, validate_class_name
from ..panels import swatch_icon


class LabelDialog(Dialog):
    """Type to filter; Enter picks the highlighted class or adds a new one."""

    def __init__(self, parent, entries, current="", title="Choose a class",
                 allow_new=True):
        super().__init__(parent, title,
                         "Pick a class, or type a new name to add it to the "
                         "project." if allow_new else "Pick a class.",
                         width=420, height=460)
        self._entries = list(entries)
        self._names = [entry.name for entry in self._entries]
        self.allow_new = allow_new
        self._value = ""

        self.edit = QLineEdit(current or "")
        self.edit.setPlaceholderText("Class name")
        completer = QCompleter(QStringListModel(self._names), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.edit.setCompleter(completer)
        self.edit.textChanged.connect(self._filter)
        self.edit.returnPressed.connect(self._accept)
        self.body.addWidget(self.edit)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemClicked.connect(
            lambda item: self.edit.setText(item.data(Qt.ItemDataRole.UserRole)))
        self.list.itemDoubleClicked.connect(lambda _item: self._accept())
        self.body.addWidget(self.list, 1)

        self.error = QLabel("")
        self.error.setObjectName("HintDanger")
        self.error.setWordWrap(True)
        self.body.addWidget(self.error)
        if allow_new:
            self.body.addWidget(hint("A name that is not in the project yet "
                                     "is added with the next free ID."))

        self.add_button("Cancel", slot=self.reject)
        self.ok_button = self.add_button("Use this class", primary=True,
                                         slot=self._accept)
        self._filter(self.edit.text())
        self.edit.selectAll()
        self.edit.setFocus()

    def _filter(self, text) -> None:
        needle = text.strip().lower()
        self.list.clear()
        for entry in self._entries:
            if needle and needle not in entry.name.lower():
                continue
            item = QListWidgetItem(swatch_icon(entry.color), entry.name)
            item.setData(Qt.ItemDataRole.UserRole, entry.name)
            self.list.addItem(item)
        self._validate()

    def _match(self, text):
        lowered = text.strip().lower()
        for name in self._names:
            if name.lower() == lowered:
                return name
        return None

    def _validate(self) -> bool:
        text = self.edit.text()
        if not text.strip():
            self.error.setText("")
            self.ok_button.setEnabled(False)
            return False
        if self._match(text):
            self.error.setText("")
            self.ok_button.setText("Use this class")
            self.ok_button.setEnabled(True)
            return True
        if not self.allow_new:
            self.error.setText("That class is not in the project.")
            self.ok_button.setEnabled(False)
            return False
        try:
            validate_class_name(text)
        except ClassStoreError as exc:
            self.error.setText(str(exc))
            self.ok_button.setEnabled(False)
            return False
        self.error.setText("")
        self.ok_button.setText("Add class")
        self.ok_button.setEnabled(True)
        return True

    def _accept(self) -> None:
        if not self.edit.text().strip() and self.list.count() == 1:
            self.edit.setText(self.list.item(0).data(Qt.ItemDataRole.UserRole))
        if not self._validate():
            return
        self._value = self._match(self.edit.text()) or \
            validate_class_name(self.edit.text())
        self.accept()

    def value(self) -> str:
        return self._value

    @classmethod
    def ask(cls, parent, entries, current="", title="Choose a class",
            allow_new=True):
        dialog = cls(parent, entries, current, title, allow_new)
        if dialog.exec() == Dialog.DialogCode.Accepted:
            return dialog.value()
        return None
