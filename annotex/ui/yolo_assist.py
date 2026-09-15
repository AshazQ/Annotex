"""Auto-labelling with your own YOLO model - what both labelling tools share.

LabelImg Master turns the detections into boxes and LabelImg Shapes into
rectangles, but finding them is the same: the model runs on a worker thread
(the window never freezes), the model's classes are matched to the project's
by name - asking once, per model, about the rest - and the folder job is built
here too.  As with SAM, nothing is imported until auto-labelling is used.
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from .ai_assist import qimage_to_rgb

NEW_CLASS = "__new__"


class _Signals(QObject):
    done = Signal(str, object)        # token, [Detection]
    failed = Signal(str, str)         # token, message


class _DetectJob(QRunnable):
    def __init__(self, detector, image, confidence, token, signals):
        super().__init__()
        self.detector = detector
        self.image = image
        self.confidence = confidence
        self.token = token
        self.signals = signals
        self.setAutoDelete(True)

    def run(self):
        from annotex.core.ai.yolo import YoloError
        try:
            rgb = qimage_to_rgb(self.image)
            if rgb is None:
                raise YoloError("This image could not be handed to the model.")
            found = self.detector.detect(rgb, self.confidence)
        except YoloError as exc:
            self._emit(self.signals.failed, str(exc))
            return
        except Exception as exc:                        # a worker never dies loudly
            self._emit(self.signals.failed, "The model failed on this image: %s" % exc)
            return
        finally:
            self.image = None
        self._emit(self.signals.done, found)

    def _emit(self, signal, payload):
        try:
            signal.emit(self.token, payload)
        except RuntimeError:
            pass                                        # the window has gone


class YoloAssistant(QObject):
    """Owns the chosen detector for one tool.

    Signals:
        detected(list)   detections for the image last asked about
        failed(str)      something went wrong, already phrased
    """

    detected = Signal(object)
    failed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._detector = None
        self._detector_for = ("", "")
        self._lock = threading.Lock()
        self._token = ""
        self.busy = False
        self._signals = _Signals(self)
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    # ── the model ─────────────────────────────────────────
    def model_path(self) -> str:
        return str(self.settings.get("yolo_model", "") or "")

    def names_path(self) -> str:
        return str(self.settings.get("yolo_names", "") or "")

    def confidence(self) -> float:
        try:
            value = float(self.settings.get("yolo_confidence", 50))
        except (TypeError, ValueError):
            value = 50.0
        return min(0.99, max(0.01, value / 100.0))

    def usable(self):
        """(ok, message) - everything a detection needs."""
        from annotex.core.ai.sam import install_hint, missing_packages
        if missing_packages():
            return False, install_hint().replace("The AI tool", "Auto-labelling")
        path = self.model_path()
        if not path:
            return False, ("No YOLO model has been chosen yet.  Tools → YOLO model… points "
                           "Annotex at your detector (.onnx).")
        if not os.path.isfile(path):
            return False, "The YOLO model file is missing:\n%s" % path
        return True, ""

    def set_model(self, path, names_path="") -> None:
        self.settings.set("yolo_model", str(path or ""))
        self.settings.set("yolo_names", str(names_path or ""))
        with self._lock:
            self._detector = None
            self._detector_for = ("", "")

    def detector(self):
        """The detector for the chosen files (not loaded yet - that happens on
        its first detection, off the interface thread).  Raises YoloError."""
        from annotex.core.ai.yolo import YoloDetector, read_names_file
        wanted = (self.model_path(), self.names_path())
        with self._lock:
            if self._detector is not None and self._detector_for == wanted:
                return self._detector
        names = read_names_file(wanted[1]) if wanted[1] else None
        detector = YoloDetector(wanted[0], names)
        with self._lock:
            self._detector, self._detector_for = detector, wanted
        return detector

    # ── one image ─────────────────────────────────────────
    def detect(self, token, image: QImage) -> bool:
        ok, why = self.usable()
        if not ok:
            self.failed.emit(why)
            return False
        if image is None or image.isNull():
            self.failed.emit("This image could not be read.")
            return False
        from annotex.core.ai.yolo import YoloError
        try:
            detector = self.detector()
        except YoloError as exc:
            self.failed.emit(str(exc))
            return False
        self._token = str(token)
        self.busy = True
        self._pool.start(_DetectJob(detector, image, self.confidence(), self._token, self._signals))
        return True

    def forget_image(self) -> None:
        self._token = ""
        self.busy = False

    def _on_done(self, token, found) -> None:
        if token != self._token:
            return                                      # the image changed meanwhile
        self.busy = False
        self.detected.emit(found)

    def _on_failed(self, token, message) -> None:
        if token != self._token:
            return
        self.busy = False
        self.failed.emit(message)

    # ── classes ───────────────────────────────────────────
    def remembered(self) -> dict:
        from annotex.core.ai.yolo import model_key
        store = self.settings.get("yolo_class_map", {}) or {}
        return dict(store.get(model_key(self.model_path()), {}) or {})

    def forget_classes(self) -> None:
        from annotex.core.ai.yolo import model_key
        store = dict(self.settings.get("yolo_class_map", {}) or {})
        store.pop(model_key(self.model_path()), None)
        self.settings.set("yolo_class_map", store)

    def resolve_classes(self, model_names, project_names, parent=None):
        """{model class: project class or "" (ignored)}, asking once about the
        classes that match nothing.  None when the person cancels."""
        from annotex.core.ai.yolo import match_classes, model_key
        decided = match_classes(model_names, project_names, self.remembered())
        undecided = [name for name, choice in decided.items() if choice is None]
        if undecided:
            from .dialogs.yolo_dialog import ClassMapDialog
            dialog = ClassMapDialog(parent, undecided, list(project_names))
            if not dialog.exec():
                return None
            chosen = dialog.mapping()
            decided.update(chosen)
            store = dict(self.settings.get("yolo_class_map", {}) or {})
            entry = dict(store.get(model_key(self.model_path()), {}) or {})
            entry.update(chosen)
            store[model_key(self.model_path())] = entry
            self.settings.set("yolo_class_map", store)
        return decided

    # ── a whole folder ────────────────────────────────────
    def prelabel_job(self, title, images, mapping, is_annotated, read_rgb, write):
        """A Job for the shared job queue.  Raises YoloError."""
        from annotex.core.ai.yolo import prelabel
        from annotex.core.jobs import Job
        detector = self.detector()
        confidence = self.confidence()
        return Job(title, lambda ctx: prelabel(list(images), detector, confidence, dict(mapping),
                                               is_annotated, read_rgb, write, ctx))

    def shutdown(self) -> None:
        try:
            self._pool.clear()
            self._pool.waitForDone(2000)
        except Exception:
            pass
