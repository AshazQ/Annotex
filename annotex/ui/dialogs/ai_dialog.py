"""Choosing the SAM model the AI tool uses.

Both labelling tools open this dialog.  It only ever changes two settings -
the encoder file and the decoder file - and it refuses to leave the tool in
a state where a click would fail: the model is actually opened before the
dialog accepts it.

The quickest way in is at the top, the way LabelMe does it: pick a model,
press Download, and once both files are whole and open cleanly the dialog
uses the model and closes.  Bringing your own export still works below.
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressBar, QPushButton)

from ..dialogs.common import Dialog, card, hint, row

WHERE_TO_GET = (
    "Downloads are the quantized Segment Anything models LabelMe uses, fetched "
    "from LabelMe's GitHub releases into the model folder. "
    "You can also bring your own export - Segment Anything, MobileSAM, "
    "samexporter or similar: put the <b>encoder</b> and <b>decoder</b> .onnx "
    "files in the model folder, or choose them below.  Nothing is uploaded: "
    "the model runs on this machine.")

MB = 1024.0 * 1024.0


class _DownloadSignals(QObject):
    progress = Signal(object, object)        # done bytes, total bytes
    finished = Signal(str, str, str)         # encoder, decoder, name
    failed = Signal(str, bool)               # message, cancelled


def _emit(signal, *args) -> None:
    """Emit from the worker; the dialog may already be gone."""
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


class AiModelDialog(Dialog):
    """Download a model, pick one found on disk, or say plainly what is missing."""

    def __init__(self, parent, assistant, theme=None):
        super().__init__(parent, "AI model (SAM)",
                         "Click an object and the tool proposes the shape.",
                         width=640)
        self.assistant = assistant
        self.encoder, self.decoder = assistant.chosen_paths()
        self._name = assistant.model_name() if self.encoder else ""
        self.changed = False
        self.downloading = False
        self._cancel = threading.Event()
        self._thread = None
        self._signals = _DownloadSignals(self)
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_downloaded)
        self._signals.failed.connect(self._on_download_failed)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)

        try:
            from annotex.core.ai.sam import models_dir
            folder = str(models_dir())
        except Exception:
            folder = ""
        self.folder = folder

        fetch, fetch_inner = card("Download a model")
        self.catalog_box = QComboBox()
        self.catalog_box.setMinimumWidth(400)
        self.catalog_box.currentIndexChanged.connect(self._refresh_download_button)
        self.download_button = QPushButton("Download")
        self.download_button.clicked.connect(self.start_download)
        fetch_inner.addWidget(row(self.catalog_box, self.download_button))
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_download)
        self.progress_row = row(self.progress, self.stop_button)
        self.progress_row.layout().setStretch(0, 1)
        self.progress_row.hide()
        fetch_inner.addWidget(self.progress_row)
        self.body.addWidget(fetch)

        frame, inner = card("Models found on this machine")
        self.list = QListWidget()
        self.list.setMinimumHeight(110)
        self.list.itemSelectionChanged.connect(self._on_pick)
        inner.addWidget(self.list)
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

        # Everything that must wait while a download is running.
        self._locked = [self.catalog_box, self.download_button, self.list,
                        open_button, refresh, encoder_button, decoder_button]
        self._locked += [self.add_button("Test this model", slot=self._test),
                         self.add_button("Clear", slot=self._clear)]
        self.add_button("Cancel", slot=self.reject)
        self._locked.append(self.add_button("Use this model", primary=True,
                                            slot=self._accept))
        self.refresh()

    # ── contents ──────────────────────────────────────────
    @staticmethod
    def _catalog():
        try:
            from annotex.core.ai import catalog
            return catalog
        except Exception:                               # pragma: no cover
            return None

    def refresh(self) -> None:
        self._fill_catalog()
        self.list.clear()
        for pair in self.assistant.models():
            item = QListWidgetItem(pair.describe())
            item.setData(Qt.ItemDataRole.UserRole, (pair.encoder, pair.decoder, pair.name))
            item.setToolTip("%s\n%s" % (pair.encoder, pair.decoder))
            self.list.addItem(item)
        if not self.list.count():
            empty = QListWidgetItem("Nothing here yet - download a model above, or "
                                    "point at your own two .onnx files below")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)
        self._refresh_labels()

    def _fill_catalog(self) -> None:
        catalog = self._catalog()
        current = self.catalog_box.currentData()
        self.catalog_box.blockSignals(True)
        self.catalog_box.clear()
        for model in (catalog.CATALOG if catalog else []):
            text = model.describe()
            if model.installed(self.folder or None):
                text += "  ·  downloaded"
            self.catalog_box.addItem(text, model.key)
        if current is not None:
            index = self.catalog_box.findData(current)
            if index >= 0:
                self.catalog_box.setCurrentIndex(index)
        self.catalog_box.blockSignals(False)
        self._refresh_download_button()

    def _chosen_model(self):
        catalog = self._catalog()
        key = self.catalog_box.currentData()
        return catalog.by_key(key) if catalog and key else None

    def _refresh_download_button(self, *_args) -> None:
        model = self._chosen_model()
        self.download_button.setEnabled(model is not None and not self.downloading)
        installed = model is not None and model.installed(self.folder or None)
        self.download_button.setText("Use it" if installed else "Download")

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
        if self.downloading:
            return
        missing = self.assistant.packages_missing()
        if missing:
            self.status.setText(self.assistant.install_hint())
        elif self.encoder and self.decoder:
            self.status.setText("Ready.  Turn the AI tool on in the toolbar, then "
                                "click the object you want.")
        else:
            self.status.setText("Download a model to switch the AI tool on - "
                                "SAM ViT-B is the quickest.")

    # ── downloading ───────────────────────────────────────
    def start_download(self) -> None:
        model = self._chosen_model()
        if model is None or self.downloading:
            return
        missing = self.assistant.packages_missing()
        if missing:
            QMessageBox.warning(self, "The AI tool is not installed",
                                self.assistant.install_hint())
            return
        if model.installed(self.folder or None):
            pair = model.pair(self.folder or None)
            self._on_downloaded(pair.encoder, pair.decoder, pair.name)
            return
        from annotex.core.ai.catalog import Cancelled, DownloadError, download_model

        self._cancel.clear()
        self._set_downloading(True)
        self.status.setText("Downloading %s (%.0f MB)…  You can keep this open or "
                            "stop and resume later." % (model.name, model.size / MB))
        self._on_progress(0, model.size)
        signals, cancel, folder = self._signals, self._cancel, self.folder or None
        last = [-1]

        def progress(done, total):
            permille = int(done * 1000 / total) if total else 0
            if permille != last[0]:
                last[0] = permille
                _emit(signals.progress, done, total)

        def work():
            try:
                pair = download_model(model, folder, progress, cancel.is_set)
            except Cancelled as exc:
                _emit(signals.failed, str(exc), True)
            except DownloadError as exc:
                _emit(signals.failed, str(exc), False)
            except Exception as exc:                    # never let a thread die loudly
                _emit(signals.failed, "the download failed: %s" % exc, False)
            else:
                _emit(signals.finished, pair.encoder, pair.decoder, pair.name)

        self._thread = threading.Thread(target=work, name="annotex-sam-download",
                                        daemon=True)
        self._thread.start()

    def stop_download(self) -> None:
        if self.downloading:
            self._cancel.set()
            self.stop_button.setEnabled(False)
            self.status.setText("Stopping…")

    def _set_downloading(self, on) -> None:
        self.downloading = bool(on)
        for widget in self._locked:
            widget.setEnabled(not on)
        self.stop_button.setEnabled(True)
        self.progress_row.setVisible(bool(on))
        if not on:
            self._refresh_download_button()

    def _on_progress(self, done, total) -> None:
        total = total or 1
        self.progress.setValue(int(done * 1000 / total))
        self.progress.setFormat("%.0f of %.0f MB" % (done / MB, total / MB))

    def _on_downloaded(self, encoder, decoder, name) -> None:
        self._set_downloading(False)
        self.encoder, self.decoder, self._name = encoder, decoder, name
        self.refresh()
        ok, message = self._check()
        if not ok:
            self.status.setText("%s downloaded, but it cannot be used." % name)
            QMessageBox.warning(self, "That model cannot be used", message)
            return
        self.assistant.set_model(encoder, decoder, name)
        self.changed = True
        self.accept()

    def _on_download_failed(self, message, cancelled) -> None:
        self._set_downloading(False)
        self._refresh_labels()
        if cancelled:
            self.status.setText("Download stopped.  Download again picks up where "
                                "it left off.")
            return
        self.status.setText("The download did not finish.")
        QMessageBox.warning(self, "The model could not be downloaded", message)

    def reject(self) -> None:
        if self.downloading:
            # The .part file stays, so opening the dialog again resumes it.
            self._cancel.set()
            if self._thread is not None:
                self._thread.join(1.0)
        super().reject()

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
        self._name = ""
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
        self.encoder = self.decoder = self._name = ""
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
        self.assistant.set_model(self.encoder, self.decoder, self._name)
        self.changed = True
        self.accept()
