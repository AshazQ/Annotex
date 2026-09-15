"""The AI assistant both labelling tools share.

LabelImg Shapes wants a polygon and LabelImg Master wants a rectangle, but
everything before that is identical: find a model, load it once, run the
slow encoder once per image on a background thread, then answer every click
from the fast decoder in a few milliseconds.

The rules this follows:

* Nothing here is imported unless the AI tool is switched on, so a machine
  without numpy or onnxruntime starts and runs exactly as it always did.
* No exception escapes.  Every failure becomes `failed(message)` with a
  sentence a person can act on.
* Work for an image the user has already left is dropped rather than drawn:
  every job carries a token, and a result whose token has moved on is
  ignored.
"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage

MAX_CACHED_EMBEDDINGS = 3
PREDICT_MAX_SIDE = 1024          # mask resolution asked of the model


# ══════════════════════════════════════════════════════════════
# IMAGE HAND-OFF
# ══════════════════════════════════════════════════════════════
def qimage_to_rgb(image: QImage):
    """A QImage as an (h, w, 3) uint8 numpy array, or None.

    Two things matter here.  Qt rows are padded to a four-byte boundary, so
    the stride has to be respected - reshaping by width alone shears the
    picture on any width that is not a multiple of four.  And the pixels are
    copied out of Qt's buffer immediately: the array must own its memory, or
    it is reading whatever Qt did with that memory next."""
    try:
        import numpy as np
    except Exception:
        return None
    if image is None or image.isNull():
        return None
    try:
        converted = image.convertToFormat(QImage.Format.Format_RGB888)
        width, height = converted.width(), converted.height()
        stride = converted.bytesPerLine()
        raw = converted.constBits()
        # Bindings have handed this back as a memoryview, a sip voidptr and a
        # bytes object over the years; take whichever one works.
        buffer = None
        for attempt in (lambda: memoryview(raw).cast("B"),
                        lambda: memoryview(raw),
                        lambda: bytes(raw)):
            try:
                buffer = attempt()
                break
            except Exception:
                continue
        if buffer is None:
            return None
        # Copy out of Qt's memory before doing anything else.  A numpy array
        # built straight on constBits() does not keep the QImage alive, and
        # reading it afterwards is at best garbage and at worst a crash.
        owned = bytearray(buffer[:stride * height])
        flat = np.frombuffer(owned, dtype=np.uint8, count=stride * height)
        return np.ascontiguousarray(flat.reshape(height, stride)[:, :width * 3]
                                    .reshape(height, width, 3))
    except Exception:
        return None


def scaled_rgb(image: QImage, width, height):
    """Resize with Qt (which does it well) and hand back a numpy array."""
    if image is None or image.isNull():
        return None
    try:
        small = image.scaled(int(width), int(height),
                             Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    except Exception:
        return None
    return qimage_to_rgb(small)


# ══════════════════════════════════════════════════════════════
# BACKGROUND WORK
# ══════════════════════════════════════════════════════════════
class _JobSignals(QObject):
    done = Signal(str, object)           # token, embedding
    failed = Signal(str, str)            # token, message


class _EncodeJob(QRunnable):
    """Everything slow about a new image, off the interface thread.

    Opening the model (seconds, the first time), resizing the picture to what
    the model wants, and running the encoder all happen here, so the window
    never freezes while somebody is waiting to click."""

    def __init__(self, runtime, image, token, signals):
        super().__init__()
        self.runtime = runtime
        self.image = image
        self.token = token
        self.signals = signals
        self.setAutoDelete(True)

    def run(self):
        try:
            from annotex.core.ai.sam import SamError
        except Exception as exc:                        # pragma: no cover
            self.signals.failed.emit(self.token, str(exc))
            return
        try:
            if not self.runtime.loaded:
                self.runtime.load()
            width, height = self.image.width(), self.image.height()
            if not width or not height:
                raise ValueError("the image is empty")
            target_w, target_h = self.runtime.target_size(width, height)
            rgb = scaled_rgb(self.image, target_w, target_h)
            if rgb is None:
                raise ValueError("the image could not be converted for the model")
            embedding = self.runtime.encode(rgb, (height, width), self.token)
        except SamError as exc:
            self.signals.failed.emit(self.token, str(exc))
            return
        except Exception as exc:                        # never let a thread die loudly
            self.signals.failed.emit(self.token, "the model failed on this image: %s" % exc)
            return
        finally:
            self.image = None
        self.signals.done.emit(self.token, embedding)


# ══════════════════════════════════════════════════════════════
# THE ASSISTANT
# ══════════════════════════════════════════════════════════════
class SamAssistant(QObject):
    """Owns the model, the embedding cache and the current image.

    Signals:
        stateChanged(str, str)   a short status line and its level
        ready(str)               the image with this token can be clicked
        failed(str)              something went wrong, already phrased
    """

    stateChanged = Signal(str, str)
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._runtime = None
        self._model_name = ""
        self._embeddings = {}            # token -> Embedding
        self._order = []
        self._token = ""
        self._pending = ""
        self._lock = threading.Lock()
        self._signals = _JobSignals(self)
        self._signals.done.connect(self._on_encoded)
        self._signals.failed.connect(self._on_failed)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    # ── availability ──────────────────────────────────────
    @staticmethod
    def packages_missing():
        try:
            from annotex.core.ai.sam import missing_packages
            return missing_packages()
        except Exception as exc:                        # pragma: no cover
            return ["the AI helpers could not be loaded (%s)" % exc]

    @staticmethod
    def install_hint():
        try:
            from annotex.core.ai.sam import install_hint
            return install_hint()
        except Exception:                               # pragma: no cover
            return "The AI tool needs numpy and onnxruntime."

    def models(self):
        try:
            from annotex.core.ai.sam import discover_models
            return discover_models()
        except Exception:
            return []

    def chosen_paths(self):
        return (str(self.settings.get("sam_encoder", "") or ""),
                str(self.settings.get("sam_decoder", "") or ""))

    def model_name(self) -> str:
        if self._model_name:
            return self._model_name
        encoder, _decoder = self.chosen_paths()
        return os.path.basename(encoder).split(".")[0] if encoder else ""

    def configured(self) -> bool:
        encoder, decoder = self.chosen_paths()
        return bool(encoder and decoder and os.path.isfile(encoder)
                    and os.path.isfile(decoder))

    def usable(self):
        """(ok, message) - everything needed for a click to work."""
        missing = self.packages_missing()
        if missing:
            return False, self.install_hint()
        if not self.configured():
            return False, ("No SAM model has been chosen yet.  Settings → AI "
                           "points the tool at an encoder and a decoder .onnx file.")
        return True, ""

    # ── model ─────────────────────────────────────────────
    def set_model(self, encoder, decoder, name="") -> None:
        encoder, decoder = str(encoder or ""), str(decoder or "")
        current = self.chosen_paths()
        self.settings.set("sam_encoder", encoder)
        self.settings.set("sam_decoder", decoder)
        if (encoder, decoder) != current:
            self.reset()
        self._model_name = name or os.path.basename(encoder).split(".")[0]

    def reset(self) -> None:
        """Drop the loaded model and everything computed with it."""
        with self._lock:
            runtime, self._runtime = self._runtime, None
            self._embeddings.clear()
            self._order = []
            self._pending = ""
        if runtime is not None:
            try:
                runtime.unload()
            except Exception:
                pass

    def _ensure_runtime(self):
        with self._lock:
            if self._runtime is not None:
                return self._runtime
        from annotex.core.ai.sam import SamRuntime
        encoder, decoder = self.chosen_paths()
        runtime = SamRuntime(encoder, decoder, self.model_name() or "SAM")
        with self._lock:
            self._runtime = runtime
        return runtime

    # ── per image ─────────────────────────────────────────
    @staticmethod
    def token_for(path) -> str:
        """Identifies an image *and* its content, so an edited file is not
        answered from a stale embedding."""
        try:
            stat = os.stat(str(path))
            return "%s|%d|%d" % (os.path.abspath(str(path)), stat.st_size,
                                 int(stat.st_mtime))
        except Exception:
            return os.path.abspath(str(path)) if path else ""

    def has_image(self, token) -> bool:
        return bool(token) and token in self._embeddings

    def is_busy(self) -> bool:
        return bool(self._pending)

    def forget_image(self) -> None:
        self._token = ""

    def prepare(self, token, image: QImage) -> bool:
        """Start (or reuse) the embedding for one image.  Returns True when
        the image is ready to click straight away."""
        ok, message = self.usable()
        if not ok:
            self.failed.emit(message)
            return False
        if not token:
            self.failed.emit("this image has no path to work from")
            return False
        self._token = token
        if token in self._embeddings:
            self.stateChanged.emit("AI ready - click the object", "good")
            self.ready.emit(token)
            return True
        if self._pending == token:
            return False
        if image is None or image.isNull():
            self.failed.emit("this image could not be read")
            return False
        try:
            runtime = self._ensure_runtime()
        except Exception as exc:
            self.failed.emit(str(exc))
            return False
        self._pending = token
        self.stateChanged.emit(
            "Loading %s and preparing this image…" % (self.model_name() or "the model")
            if not runtime.loaded else "Preparing this image for the AI…", "info")
        self._pool.start(_EncodeJob(runtime, image, token, self._signals))
        return False

    def _remember(self, token, embedding) -> None:
        self._embeddings[token] = embedding
        self._order = [t for t in self._order if t != token] + [token]
        while len(self._order) > MAX_CACHED_EMBEDDINGS:
            self._embeddings.pop(self._order.pop(0), None)

    def _on_encoded(self, token, embedding) -> None:
        if self._pending == token:
            self._pending = ""
        self._remember(token, embedding)
        if token != self._token:
            return                                   # the user has moved on
        self.stateChanged.emit("AI ready - click the object", "good")
        self.ready.emit(token)

    def _on_failed(self, token, message) -> None:
        if self._pending == token:
            self._pending = ""
        if token != self._token:
            return
        self.failed.emit(message)

    # ── prediction ────────────────────────────────────────
    def predict(self, points=(), box=None):
        """(mask, (height, width)) for the current image, or (None, reason)."""
        embedding = self._embeddings.get(self._token)
        if embedding is None:
            return None, ("The AI is still preparing this image…" if self._pending
                          else "Turn the AI tool on for this image first")
        with self._lock:
            runtime = self._runtime
        if runtime is None:
            return None, "The model is not loaded"
        try:
            from annotex.core.ai.sam import SamError
        except Exception as exc:                        # pragma: no cover
            return None, str(exc)
        try:
            mask, size, _score = runtime.predict(embedding, points=points, box=box,
                                                 max_side=PREDICT_MAX_SIDE)
        except SamError as exc:
            return None, str(exc)
        except Exception as exc:
            return None, "the model could not answer that prompt: %s" % exc
        return (mask, size, embedding.orig_size), ""

    # ── shapes out of a mask ──────────────────────────────
    def box_from(self, result):
        """(x0, y0, x1, y1) in image pixels, or None."""
        if not result:
            return None
        mask, size, orig = result
        try:
            from annotex.core.ai.masks import mask_to_box
            found = mask_to_box(mask)
        except Exception:
            return None
        if not found:
            return None
        fx = float(orig[1]) / float(size[1] or 1)
        fy = float(orig[0]) / float(size[0] or 1)
        x0, y0, x1, y1 = found
        return (x0 * fx, y0 * fy, x1 * fx, y1 * fy)

    def polygon_from(self, result, tolerance=1.2):
        """[(x, y), …] in image pixels, or []."""
        if not result:
            return []
        mask, size, orig = result
        try:
            from annotex.core.ai.masks import mask_to_polygon, scale_points
            points = mask_to_polygon(mask, tolerance=tolerance)
        except Exception:
            return []
        if not points:
            return []
        return scale_points(points, float(orig[1]) / float(size[1] or 1),
                            float(orig[0]) / float(size[0] or 1))

    def shutdown(self) -> None:
        try:
            self._pool.clear()
            self._pool.waitForDone(2000)
        except Exception:
            pass
        self.reset()
