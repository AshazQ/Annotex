"""Choosing the SAM model the AI tool uses.

Both labelling tools open this dialog.  It only ever changes two settings -
the encoder file and the decoder file - and it refuses to leave the tool in
a state where a click would fail: the model is actually opened before the
dialog accepts it.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton)

from ..dialogs.common import Dialog, card, hint, row

WHERE_TO_GET = (
    "A model is two .onnx files - an <b>encoder</b> and a <b>decoder</b> - "
    "exported from Segment Anything, MobileSAM, EdgeSAM or a similar model. "
    "Put both in the model folder below and they appear here automatically; "
    "names containing <i>encoder</i> and <i>decoder</i> are paired up for you. "
    "MobileSAM (about 40 MB) is the quickest on a laptop; ViT-B is more "
    "accurate and slower.  Nothing is uploaded: the model runs on this "
    "machine.")


class AiModelDialog(Dialog):
    """Pick the encoder/decoder pair, or say plainly what is missing."""

    def __init__(self, parent, assistant, theme=None):
        super().__init__(parent, "AI model (SAM)",
                         "Click an object and the tool proposes the shape.",
                         width=640)
        self.assistant = assistant
        self.encoder, self.decoder = assistant.chosen_paths()
        self.changed = False

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)

        frame, inner = card("Models found on this machine")
        self.list = QListWidget()
        self.list.setMinimumHeight(130)
        self.list.itemSelectionChanged.connect(self._on_pick)
        inner.addWidget(self.list)
        try:
            from annotex.core.ai.sam import models_dir
            folder = str(models_dir())
        except Exception:
            folder = ""
        self.folder = folder
        inner.addWidget(hint("Model folder:  %s" % (folder or "unavailable")))
        open_button = QPushButton("Open the model folder")
        open_button.clicked.connect(self._open_folder)
        refresh = QPushButton("Look again")
        refresh.clicked.connect(self.refresh)
        inner.addWidget(row(open_button, refresh, None))
        self.body.addWidget(frame)

        chosen, chosen_inner = card("Chosen files")
        self.encoder_label = QLabel("")
        self.encoder_label.setWordWrap(True)
        self.decoder_label = QLabel("")
        self.decoder_label.setWordWrap(True)
        encoder_button = QPushButton("Choose the encoder…")
        encoder_button.clicked.connect(lambda: self._browse("encoder"))
        decoder_button = QPushButton("Choose the decoder…")
        decoder_button.clicked.connect(lambda: self._browse("decoder"))
        chosen_inner.addWidget(row(encoder_button, self.encoder_label, stretch_last=True))
        chosen_inner.addWidget(row(decoder_button, self.decoder_label, stretch_last=True))
        self.body.addWidget(chosen)

        note = QLabel(WHERE_TO_GET)
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.RichText)
        note.setObjectName("Hint")
        self.body.addWidget(note)

        self.add_button("Test this model", slot=self._test)
        self.add_button("Clear", slot=self._clear)
        self.add_button("Cancel", slot=self.reject)
        self.add_button("Use this model", primary=True, slot=self._accept)
        self.refresh()

    # ── contents ──────────────────────────────────────────
    def refresh(self) -> None:
        self.list.clear()
        for pair in self.assistant.models():
            item = QListWidgetItem(pair.describe())
            item.setData(Qt.ItemDataRole.UserRole, (pair.encoder, pair.decoder, pair.name))
            item.setToolTip("%s\n%s" % (pair.encoder, pair.decoder))
            self.list.addItem(item)
        if not self.list.count():
            empty = QListWidgetItem("Nothing found - use the buttons below to "
                                    "point at the two .onnx files")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        for label, path, what in ((self.encoder_label, self.encoder, "encoder"),
                                  (self.decoder_label, self.decoder, "decoder")):
            if not path:
                label.setText("no %s chosen" % what)
            elif not os.path.isfile(path):
                label.setText("missing:  %s" % path)
            else:
                label.setText(os.path.basename(path))
            label.setToolTip(path)
        missing = self.assistant.packages_missing()
        if missing:
            self.status.setText(self.assistant.install_hint())
        elif self.encoder and self.decoder:
            self.status.setText("Ready.  Turn the AI tool on in the toolbar, then "
                                "click the object you want.")
        else:
            self.status.setText("Choose an encoder and a decoder to switch the AI "
                                "tool on.")

    # ── actions ───────────────────────────────────────────
    def _on_pick(self) -> None:
        items = self.list.selectedItems()
        if not items:
            return
        data = items[0].data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        self.encoder, self.decoder, self._name = data[0], data[1], data[2]
        self._refresh_labels()

    def _browse(self, role) -> None:
        start = os.path.dirname(self.encoder or self.decoder) or self.folder or \
            os.path.expanduser("~")
        path, _filter = QFileDialog.getOpenFileName(
            self, "Choose the %s (.onnx)" % role, start, "ONNX models (*.onnx);;All files (*)")
        if not path:
            return
        if role == "encoder":
            self.encoder = path
        else:
            self.decoder = path
        self._refresh_labels()

    def _open_folder(self) -> None:
        if not self.folder:
            return
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            os.makedirs(self.folder, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder))
        except Exception as exc:
            QMessageBox.warning(self, "Could not open the folder", str(exc))

    def _clear(self) -> None:
        self.encoder = self.decoder = ""
        self._refresh_labels()

    def _check(self):
        """(ok, message) - actually open the model, do not just trust the name."""
        if not self.encoder or not self.decoder:
            return False, "Choose both an encoder and a decoder file."
        missing = self.assistant.packages_missing()
        if missing:
            return False, self.assistant.install_hint()
        try:
            from annotex.core.ai.sam import SamError, SamRuntime
        except Exception as exc:
            return False, str(exc)
        runtime = SamRuntime(self.encoder, self.decoder)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            runtime.load()
        except SamError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, "the model could not be opened: %s" % exc
        finally:
            QApplication.restoreOverrideCursor()
            try:
                runtime.unload()
            except Exception:
                pass
        return True, "The model opened cleanly."

    def _test(self) -> None:
        ok, message = self._check()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information if ok else QMessageBox.Icon.Warning)
        box.setWindowTitle("AI model" if ok else "That model cannot be used")
        box.setText(message)
        box.exec()

    def _accept(self) -> None:
        if not self.encoder and not self.decoder:
            self.assistant.set_model("", "")
            self.changed = True
            self.accept()
            return
        ok, message = self._check()
        if not ok:
            QMessageBox.warning(self, "That model cannot be used", message)
            return
        self.assistant.set_model(self.encoder, self.decoder,
                                 getattr(self, "_name", ""))
        self.changed = True
        self.accept()
