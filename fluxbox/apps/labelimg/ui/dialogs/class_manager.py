"""The Class Manager - create, edit, validate and ID each project's classes.

All persistence lives in core.class_store; this module is purely the front
end.  The rules are unchanged from LabelImg Master: IDs are permanent, a
class in use is deprecated or reassigned rather than silently orphaned, and
renames rewrite the saved VOC and CreateML files.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog,
                               QComboBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QRadioButton, QSpinBox,
                               QTableWidget, QTableWidgetItem)

from fluxbox.ui.dialogs.common import Dialog, card, hint

from ...core.class_store import (ClassStoreError, find_class_usage,
                                 validate_class_id, validate_class_name)

COL_ID, COL_COLOUR, COL_NAME, COL_STATUS, COL_DESC = range(5)


class ReassignDialog(Dialog):
    """Asked when deleting a class that saved annotations still use."""

    BLOCK, DEPRECATE, REASSIGN = range(3)

    def __init__(self, parent, class_name, usage_count, usage_examples, candidates):
        super().__init__(parent, "Class is in use",
                         "\"%s\" is still referenced by %s saved annotation "
                         "file%s. Deleting it outright would leave those boxes "
                         "pointing at a class that no longer exists."
                         % (class_name, usage_count or "existing",
                            "" if usage_count == 1 else "s"), width=500)
        frame, inner = card("Files referencing it (sample)")
        examples = QPlainTextEdit()
        examples.setReadOnly(True)
        examples.setMaximumHeight(96)
        examples.setPlainText("\n".join(os.path.basename(p) for p in usage_examples)
                              or "n/a")
        inner.addWidget(examples)
        self.body.addWidget(frame)

        self.radio_block = QRadioButton("Cancel - keep the class as it is")
        self.radio_deprecate = QRadioButton(
            "Deprecate - hide it from new labelling, keep it valid on old data")
        self.radio_reassign = QRadioButton(
            "Reassign - move its boxes to another class, then delete it")
        self.radio_deprecate.setChecked(True)
        self.target = QComboBox()
        for entry in candidates:
            self.target.addItem("%d - %s" % (entry.id, entry.name), entry.id)
        self.target.setEnabled(False)
        self.radio_reassign.setEnabled(bool(candidates))
        self.radio_reassign.toggled.connect(self.target.setEnabled)
        for widget in (self.radio_block, self.radio_deprecate, self.radio_reassign):
            self.body.addWidget(widget)
        row = QHBoxLayout()
        row.addSpacing(26)
        row.addWidget(QLabel("Reassign to"))
        row.addWidget(self.target, 1)
        self.body.addLayout(row)

        self.add_button("Cancel", slot=self.reject)
        self.add_button("Continue", primary=True, slot=self.accept)

    def choice(self):
        if self.radio_reassign.isChecked():
            return self.REASSIGN
        if self.radio_deprecate.isChecked():
            return self.DEPRECATE
        return self.BLOCK

    def target_class_id(self):
        return self.target.currentData()


class ClassManagerDialog(Dialog):
    """The class-management window."""

    def __init__(self, parent, store, search_dirs=None):
        super().__init__(parent, "Class Manager",
                         "Classes are per project. IDs are permanent - YOLO "
                         "files store them as the class index.",
                         width=940, height=640)
        self.store = store
        self.search_dirs = list(search_dirs or [])
        self.renames = []
        self.reassignments = []
        self.changed = False
        self._build()
        self._reload_projects()

    # ── construction ──────────────────────────────────────
    def _build(self) -> None:
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(QLabel("Project"))
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(180)
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        top.addWidget(self.project_combo)
        for text, tip, slot in (("New…", "Create an empty class set for another site",
                                 self._new_project),
                                ("Rename…", "Rename this project", self._rename_project),
                                ("Delete", "Delete this project", self._delete_project)):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            top.addWidget(button)
        top.addStretch(1)
        for text, tip, slot in (
                ("Import .txt…", "Import a predefined-classes text file. IDs follow "
                 "the file order, matching the indices YOLO already used.",
                 self._import_txt),
                ("Import set…", "Import a class set exported from another machine",
                 self._import_json),
                ("Export…", "Save this project as a class set or a YOLO classes.txt",
                 self._export)):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            top.addWidget(button)
        self.body.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "", "Name", "Status", "Description"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        head.setSectionResizeMode(COL_ID, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(COL_COLOUR, QHeaderView.ResizeMode.Fixed)
        head.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(COL_DESC, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(COL_COLOUR, 34)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        self.table.itemDoubleClicked.connect(lambda *_: self._rename_class())
        self.body.addWidget(self.table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.rename_button = QPushButton("Rename…")
        self.rename_button.clicked.connect(self._rename_class)
        self.colour_button = QPushButton("Colour…")
        self.colour_button.clicked.connect(self._change_colour)
        self.deprecate_button = QPushButton("Deprecate")
        self.deprecate_button.clicked.connect(self._toggle_deprecated)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete_class)
        for button in (self.rename_button, self.colour_button,
                       self.deprecate_button, self.delete_button):
            actions.addWidget(button)
        actions.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Subtitle")
        actions.addWidget(self.count_label)
        self.body.addLayout(actions)

        frame, inner = card("Add a class")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. face_uncover")
        self.name_edit.setMaxLength(80)
        self.name_edit.textChanged.connect(self._validate_live)
        self.name_edit.returnPressed.connect(self._add_class)
        self.auto_id = QCheckBox("Auto ID")
        self.auto_id.setChecked(True)
        self.auto_id.toggled.connect(self._on_auto_id)
        self.id_spin = QSpinBox()
        self.id_spin.setRange(0, 999999)
        self.id_spin.setEnabled(False)
        self.id_spin.valueChanged.connect(lambda *_: self._validate_live())
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("optional note")
        self.add_class_button = QPushButton("Add class")
        self.add_class_button.setObjectName("Primary")
        self.add_class_button.clicked.connect(self._add_class)
        grid.addWidget(QLabel("Name"), 0, 0)
        grid.addWidget(self.name_edit, 0, 1)
        grid.addWidget(self.auto_id, 0, 2)
        grid.addWidget(self.id_spin, 0, 3)
        grid.addWidget(QLabel("Note"), 1, 0)
        grid.addWidget(self.desc_edit, 1, 1, 1, 3)
        grid.addWidget(self.add_class_button, 0, 4, 2, 1)
        inner.addLayout(grid)
        self.error_label = QLabel("")
        self.error_label.setObjectName("HintDanger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        inner.addWidget(self.error_label)
        self.body.addWidget(frame)

        self.add_button("Cancel", slot=self.reject)
        self.add_button("Save and close", primary=True, slot=self._save_and_close)

    # ── projects ──────────────────────────────────────────
    def _reload_projects(self, select=None) -> None:
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for name in self.store.project_names():
            self.project_combo.addItem(name)
        index = self.project_combo.findText(select or self.store.active_project_name)
        self.project_combo.setCurrentIndex(max(0, index))
        self.project_combo.blockSignals(False)
        self._on_project_changed()

    def current_project(self):
        name = self.project_combo.currentText()
        return self.store.ensure_project(name) if name else self.store.active_project()

    def _on_project_changed(self, *_args) -> None:
        name = self.project_combo.currentText()
        if name:
            try:
                if name != self.store.active_project_name:
                    self.changed = True
                self.store.set_active_project(name)
            except ClassStoreError:
                pass
        self._refresh_table()
        self._validate_live()

    def _new_project(self) -> None:
        name, ok = QInputDialog.getText(self, "New project", "Project name:")
        if not ok:
            return
        try:
            project = self.store.create_project(name)
        except ClassStoreError as exc:
            self._warn(str(exc))
            return
        self.changed = True
        self._reload_projects(project.name)

    def _rename_project(self) -> None:
        old = self.project_combo.currentText()
        if not old:
            return
        name, ok = QInputDialog.getText(self, "Rename project", "Project name:", text=old)
        if not ok:
            return
        try:
            project = self.store.rename_project(old, name)
        except ClassStoreError as exc:
            self._warn(str(exc))
            return
        self.changed = True
        self._reload_projects(project.name)

    def _delete_project(self) -> None:
        name = self.project_combo.currentText()
        if not name:
            return
        answer = QMessageBox.question(
            self, "Delete project",
            "Delete the project \"%s\" and its %d class definitions?\n\n"
            "Saved annotations are not touched."
            % (name, len(self.store.ensure_project(name))))
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete_project(name)
        except ClassStoreError as exc:
            self._warn(str(exc))
            return
        self.changed = True
        self._reload_projects()

    # ── table ─────────────────────────────────────────────
    def _refresh_table(self) -> None:
        project = self.current_project()
        entries = project.sorted_classes()
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            id_item = QTableWidgetItem(str(entry.id))
            id_item.setData(Qt.ItemDataRole.UserRole, entry.id)
            self.table.setItem(row, COL_ID, id_item)
            swatch = QTableWidgetItem("")
            swatch.setBackground(QColor(entry.color))
            swatch.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, COL_COLOUR, swatch)
            name_item = QTableWidgetItem(entry.name)
            if not entry.active:
                font = name_item.font()
                font.setItalic(True)
                name_item.setFont(font)
            self.table.setItem(row, COL_NAME, name_item)
            self.table.setItem(row, COL_STATUS, QTableWidgetItem(
                "active" if entry.active else "deprecated"))
            self.table.setItem(row, COL_DESC, QTableWidgetItem(entry.description))
        self.count_label.setText("%d classes (%d active)"
                                 % (len(entries), sum(1 for e in entries if e.active)))
        self._sync_buttons()
        if self.auto_id.isChecked():
            self.id_spin.setValue(project.peek_next_id())

    def selected_class(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), COL_ID)
        return self.current_project().by_id(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _select_id(self, class_id) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COL_ID)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == class_id:
                self.table.selectRow(row)
                return

    def _sync_buttons(self) -> None:
        entry = self.selected_class()
        for button in (self.rename_button, self.colour_button,
                       self.deprecate_button, self.delete_button):
            button.setEnabled(entry is not None)
        if entry is not None:
            self.deprecate_button.setText("Reactivate" if not entry.active else "Deprecate")

    # ── add ───────────────────────────────────────────────
    def _on_auto_id(self, checked) -> None:
        self.id_spin.setEnabled(not checked)
        if checked:
            self.id_spin.setValue(self.current_project().peek_next_id())
        self._validate_live()

    def _set_error(self, message) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    def _validate_live(self, *_args) -> None:
        text = self.name_edit.text()
        if not text.strip():
            self._set_error("")
            self.add_class_button.setEnabled(False)
            return
        project = self.current_project()
        try:
            cleaned = validate_class_name(text)
        except ClassStoreError as exc:
            self._set_error(str(exc))
            self.add_class_button.setEnabled(False)
            return
        if project.by_name(cleaned) is not None:
            self._set_error("A class named \"%s\" already exists in this project." % cleaned)
            self.add_class_button.setEnabled(False)
            return
        if not self.auto_id.isChecked():
            class_id = validate_class_id(self.id_spin.value())
            clash = project.by_id(class_id)
            if clash is not None:
                self._set_error("ID %d is already used by \"%s\"." % (class_id, clash.name))
                self.add_class_button.setEnabled(False)
                return
        self._set_error("")
        self.add_class_button.setEnabled(True)

    def _add_class(self) -> None:
        if not self.add_class_button.isEnabled():
            return
        project = self.current_project()
        class_id = None if self.auto_id.isChecked() else self.id_spin.value()
        try:
            entry = project.add_class(self.name_edit.text(), class_id=class_id,
                                      description=self.desc_edit.text())
        except ClassStoreError as exc:
            self._set_error(str(exc))
            return
        self.changed = True
        self.name_edit.clear()
        self.desc_edit.clear()
        self._refresh_table()
        self._select_id(entry.id)

    # ── per-class actions ─────────────────────────────────
    def _rename_class(self) -> None:
        entry = self.selected_class()
        if entry is None:
            return
        name, ok = QInputDialog.getText(
            self, "Rename class",
            "New name for class %d (the ID stays %d, so exports stay valid):"
            % (entry.id, entry.id), text=entry.name)
        if not ok:
            return
        try:
            old, new = self.current_project().rename_class(entry.id, name)
        except ClassStoreError as exc:
            self._warn(str(exc))
            return
        if old != new:
            self.renames.append((old, new))
            self.changed = True
        self._refresh_table()
        self._select_id(entry.id)

    def _change_colour(self) -> None:
        entry = self.selected_class()
        if entry is None:
            return
        colour = QColorDialog.getColor(QColor(entry.color), self,
                                       "Box colour for \"%s\"" % entry.name)
        if not colour.isValid():
            return
        self.current_project().set_color(entry.id, colour.name())
        self.changed = True
        self._refresh_table()
        self._select_id(entry.id)

    def _toggle_deprecated(self) -> None:
        entry = self.selected_class()
        if entry is None:
            return
        self.current_project().set_active(entry.id, not entry.active)
        self.changed = True
        self._refresh_table()
        self._select_id(entry.id)

    def _delete_class(self) -> None:
        entry = self.selected_class()
        if entry is None:
            return
        project = self.current_project()
        usage = find_class_usage(entry.name, self.search_dirs, class_id=entry.id, limit=25)
        if usage:
            candidates = [c for c in project.active_classes() if c.id != entry.id]
            dialog = ReassignDialog(self, entry.name, len(usage), usage[:8], candidates)
            if dialog.exec() != Dialog.DialogCode.Accepted:
                return
            choice = dialog.choice()
            if choice == ReassignDialog.BLOCK:
                return
            if choice == ReassignDialog.DEPRECATE:
                project.set_active(entry.id, False)
                self.changed = True
                self._refresh_table()
                self._select_id(entry.id)
                return
            target = project.by_id(dialog.target_class_id())
            if target is None:
                return
            self.reassignments.append((entry.name, target.name))
            project.remove_class(entry.id)
            self.changed = True
            self._refresh_table()
            return
        answer = QMessageBox.question(
            self, "Delete class",
            "Delete \"%s\" (ID %d)?\n\nNo saved annotation in the scanned folders "
            "references it. ID %d will not be reused for a different class."
            % (entry.name, entry.id, entry.id))
        if answer != QMessageBox.StandardButton.Yes:
            return
        project.remove_class(entry.id)
        self.changed = True
        self._refresh_table()

    # ── import / export ───────────────────────────────────
    def _import_txt(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import predefined classes", os.path.expanduser("~"),
            "Text files (*.txt)")
        if not path:
            return
        try:
            project = self.store.import_txt(path)
        except ClassStoreError as exc:
            self._warn(str(exc))
            return
        self.changed = True
        self._reload_projects(project.name)
        QMessageBox.information(
            self, "Imported",
            "Imported %d classes into project \"%s\".\n\nIDs were assigned in "
            "file order (0, 1, 2 …), which matches the indices YOLO already "
            "wrote for this list, so existing exports remain valid."
            % (len(project), project.name))

    def _import_json(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import class set", os.path.expanduser("~"), "Class sets (*.json)")
        if not path:
            return
        try:
            project = self.store.import_project(path)
        except (ClassStoreError, ValueError, KeyError) as exc:
            self._warn(str(exc))
            return
        self.changed = True
        self._reload_projects(project.name)

    def _export(self) -> None:
        project = self.current_project()
        path, chosen = QFileDialog.getSaveFileName(
            self, "Export class set",
            os.path.join(os.path.expanduser("~"), "%s.json" % project.name),
            "Class set (*.json);;YOLO classes.txt (*.txt)")
        if not path:
            return
        try:
            if path.lower().endswith(".txt") or "txt" in (chosen or "").lower():
                if not path.lower().endswith(".txt"):
                    path += ".txt"
                self.store.export_txt(path, project.name)
            else:
                if not path.lower().endswith(".json"):
                    path += ".json"
                self.store.export_project(path, project.name)
        except Exception as exc:
            self._warn("Could not export: %s" % exc)
            return
        QMessageBox.information(self, "Exported", "Saved to:\n%s" % path)

    def _save_and_close(self) -> None:
        try:
            self.store.save()
        except Exception as exc:
            self._warn("Could not save the class store: %s" % exc)
            return
        self.accept()

    def _warn(self, message) -> None:
        QMessageBox.warning(self, "Class Manager", message)
