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

PREDICT_MAX_SIDE = 1024          # mask resolution asked of the model

# An embedding is about 4 MB, so sixteen of them is 64 MB in exchange for
# never encoding the same image twice in one sitting.
MAX_CACHED_EMBEDDINGS = 16

# How far around the current image to encode before anybody asks.  Forwards
# further than backwards, because that is how a folder gets worked through.
PREFETCH_AHEAD = 2
PREFETCH_BEHIND = 1

# Queue priorities.  The image on screen always goes before speculative work
# for an image nobody is looking at yet.
PRIORITY_NOW = 10
PRIORITY_SOON = 0


def neighbour_offsets(ahead: int = PREFETCH_AHEAD, behind: int = PREFETCH_BEHIND):
    """Which images around this one to get ready, nearest and forwards first.

    Forwards before backwards at every distance, because Next is the key
    people actually wear out."""
    out = []
    for step in range(1, max(int(ahead), int(behind)) + 1):
        if step <= ahead:
            out.append(step)
        if step <= behind:
            out.append(-step)
    return out


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
    """Every answer says which model it came from.

    A job holds its own reference to the runtime, so one already running
    when the model is swapped will still finish and still report - with an
    embedding the new model knows nothing about.  The generation is what
    lets that answer be recognised and dropped, rather than handed to
    somebody as though their new model had produced it."""

    done = Signal(int, str, object)       # generation, token, embedding
    failed = Signal(int, str, str)        # generation, token, message
    skipped = Signal(int, str)            # generation, token - dropped unrun
    loaded = Signal(int)                  # generation - the model is open


def _read_image(path):
    """An image file as a QImage, oriented as the labelling tools show it.

    Read on a worker thread, so it has to go through QImageReader rather
    than anything that touches a widget."""
    try:
        from PySide6.QtGui import QImageReader
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)              # honour the EXIF rotation
        image = reader.read()
        return image if not image.isNull() else None
    except Exception:
        return None


class _WarmJob(QRunnable):
    """Open the model before anybody clicks.

    Building the sessions is a fraction of a second once the file is in the
    operating system's cache, but the first open of the run also reads the
    whole model off the disk - a hundred megabytes for ViT-B and six hundred
    for ViT-H - and none of that has anything to do with any particular
    image.  Better spent while somebody is still looking at their first
    picture than in front of their first click."""

    def __init__(self, runtime, signals, generation=0):
        super().__init__()
        self.runtime = runtime
        self.signals = signals
        self.generation = int(generation)
        self.setAutoDelete(True)

    def run(self):
        try:
            if not self.runtime.loaded:
                self.runtime.load()
            self.signals.loaded.emit(self.generation)
        except Exception:
            # A model that cannot be opened is reported when somebody
            # actually asks for it, not out of the blue while they work.
            pass


class _EncodeJob(QRunnable):
    """Everything slow about a new image, off the interface thread.

    Opening the model (seconds, the first time), reading and resizing the
    picture, and running the encoder all happen here, so the window never
    freezes while somebody is waiting to click.

    Three things make this cheaper than it looks.  A job whose image nobody
    is waiting for any more is dropped before it costs anything.  An answer
    already on disk is read instead of recomputed.  And a fresh answer is
    written to disk, so the next visit to this folder is free."""

    def __init__(self, runtime, image, token, signals, path="", cache=None,
                 model_key="", wanted=None, generation=0):
        super().__init__()
        self.runtime = runtime
        self.image = image
        self.token = token
        self.signals = signals
        self.path = str(path or "")
        self.cache = cache
        self.model_key = str(model_key or "")
        self.wanted = wanted or (lambda _token: True)
        self.generation = int(generation)
        self.setAutoDelete(True)

    def _key(self):
        """Names the model and what the picture actually holds.

        Worked out here rather than by the caller because reading the file
        to digest it belongs on this thread, not the interface's."""
        if self.cache is None or not self.model_key or not self.path:
            return ""
        try:
            from annotex.core.ai.cache import EmbeddingCache, content_identity
            return EmbeddingCache.key(self.model_key, content_identity(self.path))
        except Exception:
            return ""

    def _cached(self, key):
        """The embedding this image already has on disk, or None."""
        if self.cache is None or not key:
            return None
        try:
            from annotex.core.ai.sam import Embedding
            features, meta = self.cache.get(key)
            if features is None or not meta:
                return None
            orig = tuple(int(v) for v in meta["orig_size"])
            size = tuple(int(v) for v in meta["input_size"])
            return Embedding(features, orig, size, float(meta["scale"]), self.token)
        except Exception:
            return None

    def _store(self, key, embedding):
        if self.cache is None or not key:
            return
        try:
            self.cache.put(key, embedding.features,
                           {"orig_size": list(embedding.orig_size),
                            "input_size": list(embedding.input_size),
                            "scale": float(embedding.scale)})
        except Exception:
            pass

    def run(self):
        try:
            from annotex.core.ai.sam import SamError
        except Exception as exc:                        # pragma: no cover
            self.signals.failed.emit(self.generation, self.token, str(exc))
            return
        if not self.wanted(self.token):
            self.image = None
            self.signals.skipped.emit(self.generation, self.token)
            return
        try:
            # The decoder is needed for the first click whether or not the
            # encoder's answer is already on disk, so the model opens either
            # way - and once open it stays open for every later image.
            if not self.runtime.loaded:
                self.runtime.load()
                self.signals.loaded.emit(self.generation)
            key = self._key()
            embedding = self._cached(key)
            if embedding is None:
                if self.image is None and self.path:
                    self.image = _read_image(self.path)
                if self.image is None:
                    raise ValueError("the image could not be read")
                width, height = self.image.width(), self.image.height()
                if not width or not height:
                    raise ValueError("the image is empty")
                target_w, target_h = self.runtime.target_size(width, height)
                rgb = scaled_rgb(self.image, target_w, target_h)
                if rgb is None:
                    raise ValueError("the image could not be converted for the model")
                embedding = self.runtime.encode(rgb, (height, width), self.token)
                self._store(key, embedding)
        except SamError as exc:
            self.signals.failed.emit(self.generation, self.token, str(exc))
            return
        except Exception as exc:                        # never let a thread die loudly
            self.signals.failed.emit(self.generation, self.token,
                                     "the model failed on this image: %s" % exc)
            return
        finally:
            self.image = None
        self.signals.done.emit(self.generation, self.token, embedding)


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
        self._queued = []                # tokens waiting, current one first
        self._warming = False
        # Bumped whenever the model changes.  Work already in flight belongs
        # to the generation it started in and is dropped when it lands late.
        self._generation = 0
        self._last = None                # (token, points, box, logits) of the last answer
        self.last_refined = False        # whether the last answer built on the one before
        self._lock = threading.Lock()
        self._cache = None
        self._cache_off = False
        self._signals = _JobSignals(self)
        self._signals.done.connect(self._on_encoded)
        self._signals.failed.connect(self._on_failed)
        self._signals.skipped.connect(self._on_skipped)
        self._signals.loaded.connect(self._on_loaded)
        self._pool = QThreadPool(self)
        # One at a time on purpose: the encoder already spreads itself across
        # the cores, so a second one running beside it makes both slower.
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
                           "downloads one in a click, or points the tool at your "
                           "own encoder and decoder .onnx files.")
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
        # Somebody who has just chosen a model means to use it, and this is
        # the one moment when ten seconds of opening it costs nobody anything.
        self.warm()

    def reset(self) -> None:
        """Drop the loaded model and everything computed with it."""
        try:
            self._pool.clear()               # queued work belonged to the old model
        except Exception:
            pass
        with self._lock:
            runtime, self._runtime = self._runtime, None
            self._embeddings.clear()
            self._order = []
            self._pending = ""
            self._queued = []
            self._last = None
            self._warming = False
            # Anything still running was started by the model being dropped;
            # its answer must not be mistaken for the next model's.
            self._generation += 1
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

    def loaded(self) -> bool:
        """Whether the model is open, so a click costs only the fast half."""
        with self._lock:
            runtime = self._runtime
        return bool(runtime is not None and runtime.loaded)

    # ── the answers kept on disk ──────────────────────────
    def disk_cache(self):
        """The embedding cache, or None when it is switched off or unusable.

        Encoding an image costs seconds and its answer costs two megabytes,
        so the second visit to a folder should not pay again."""
        if self._cache_off:
            return None
        if self._cache is not None:
            return self._cache
        if not self.settings.get("ai_embed_cache", True):
            self._cache_off = True
            return None
        try:
            from annotex.core.ai.cache import EmbeddingCache
            cache = EmbeddingCache("sam")
            if not cache.available():
                self._cache_off = True
                return None
            self._cache = cache
        except Exception:
            self._cache_off = True
            return None
        return self._cache

    def _model_key(self) -> str:
        """Names the model, so a different one never answers for this one."""
        try:
            from annotex.core.ai.cache import model_id
            encoder, decoder = self.chosen_paths()
            return model_id(encoder, decoder)
        except Exception:
            return ""

    def _from_disk(self, token, path):
        """An embedding read straight off disk, or None.

        Only worth doing on the interface thread once the model is already
        open: digesting the file and reading two megabytes takes a few
        milliseconds, where going through the queue could wait behind a
        whole encode."""
        cache = self.disk_cache()
        model_key = self._model_key()
        if cache is None or not model_key or not path:
            return None
        try:
            from annotex.core.ai.cache import EmbeddingCache, content_identity
            from annotex.core.ai.sam import Embedding
            features, meta = cache.get(
                EmbeddingCache.key(model_key, content_identity(path)))
            if features is None or not meta:
                return None
            return Embedding(features, tuple(int(v) for v in meta["orig_size"]),
                             tuple(int(v) for v in meta["input_size"]),
                             float(meta["scale"]), token)
        except Exception:
            return None

    def cache_description(self) -> str:
        cache = self.disk_cache()
        return cache.describe() if cache is not None else "switched off"

    def clear_disk_cache(self) -> int:
        cache = self.disk_cache()
        return cache.clear() if cache is not None else 0

    # ── per image ─────────────────────────────────────────
    @staticmethod
    def token_for(path) -> str:
        """Identifies an image *and* its content, so an edited file is not
        answered from a stale embedding.

        Where, how big, and when to the nanosecond - three numbers off the
        directory entry, because this is asked on the interface thread every
        time an image is shown.  What goes on disk is keyed more carefully
        than this; see `content_identity`."""
        try:
            from annotex.core.ai.cache import file_identity
            return file_identity(path)
        except Exception:                               # pragma: no cover
            try:
                stat = os.stat(str(path))
                return "%s|%d|%d" % (os.path.abspath(str(path)), stat.st_size,
                                     stat.st_mtime_ns)
            except Exception:
                return os.path.abspath(str(path)) if path else ""

    def has_image(self, token) -> bool:
        return bool(token) and token in self._embeddings

    def is_busy(self) -> bool:
        return bool(self._pending)

    def forget_image(self) -> None:
        self._token = ""

    def prepare(self, token, image: QImage, path="") -> bool:
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
            # Re-remembered, not merely found: without this the picture on
            # screen keeps the age it had when it was encoded, and the
            # prefetching done on its behalf can eventually evict it.
            self._remember(token, self._embeddings[token])
            self.stateChanged.emit("AI ready - click the object", "good")
            self.ready.emit(token)
            return True
        # The model is already open and this image was encoded on an earlier
        # visit: read the answer and be done, without a queue or a thread hop.
        if self.loaded():
            embedding = self._from_disk(token, path)
            if embedding is not None:
                self._remember(token, embedding)
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
        # Speculative work for images nobody is looking at gives up its place
        # to the one on screen.  Anything already running finishes.
        try:
            self._pool.clear()
        except Exception:
            pass
        self._pending = token
        self._queued = [token]
        self.stateChanged.emit(
            "Loading %s and preparing this image…" % (self.model_name() or "the model")
            if not runtime.loaded else "Preparing this image for the AI…", "info")
        self._pool.start(_EncodeJob(runtime, image, token, self._signals, path=path,
                                    cache=self.disk_cache(),
                                    model_key=self._model_key(),
                                    wanted=self._wanted,
                                    generation=self._generation), PRIORITY_NOW)
        return False

    def prefetch(self, items) -> None:
        """Encode the images around this one before anybody asks for them.

        `items` is [(token, path), …] most worth doing first.  This is what
        makes the AI tool feel instant: as long as a person spends longer on
        an image than the encoder does, they never wait for it again."""
        ok, _message = self.usable()
        if not ok:
            return
        try:
            runtime = self._ensure_runtime()
        except Exception:
            return
        cache = self.disk_cache()
        model_key = self._model_key()
        limit = PREFETCH_AHEAD + PREFETCH_BEHIND
        started = 0
        for token, path in items:
            if started >= limit:
                break
            if not token or not path:
                continue
            if token in self._embeddings or token == self._pending \
                    or token in self._queued:
                continue
            self._queued.append(token)
            started += 1
            self._pool.start(_EncodeJob(runtime, None, token, self._signals, path=path,
                                        cache=cache, model_key=model_key,
                                        wanted=self._wanted,
                                        generation=self._generation), PRIORITY_SOON)

    def warm(self) -> None:
        """Open the model now, so the first click does not wait for it.

        Worth calling the moment somebody shows they mean to use the AI tool
        - choosing a model is the obvious one - because reading the model off
        the disk and building its sessions has nothing to do with any
        particular image, and so need not be in front of any click."""
        ok, _message = self.usable()
        if not ok or self._warming or self.loaded():
            return
        try:
            runtime = self._ensure_runtime()
        except Exception:
            return
        self._warming = True
        self._pool.start(_WarmJob(runtime, self._signals, self._generation),
                         PRIORITY_SOON)

    def _wanted(self, token) -> bool:
        """Whether a job's answer is still worth the seconds it costs.

        Called from the worker: the current image always is, and so is
        anything still queued; everything else has been navigated past."""
        return bool(token) and (token == self._token or token in self._queued)

    def _remember(self, token, embedding) -> None:
        self._embeddings[token] = embedding
        self._order = [t for t in self._order if t != token] + [token]
        while len(self._order) > MAX_CACHED_EMBEDDINGS:
            self._embeddings.pop(self._order.pop(0), None)

    def _forget_queued(self, token) -> None:
        try:
            self._queued.remove(token)
        except ValueError:
            pass

    def _stale(self, generation) -> bool:
        """An answer from a model that is no longer the model."""
        return int(generation) != self._generation

    def _on_encoded(self, generation, token, embedding) -> None:
        if self._stale(generation):
            return
        if self._pending == token:
            self._pending = ""
        self._forget_queued(token)
        self._remember(token, embedding)
        if token != self._token:
            return                                   # the user has moved on
        self.stateChanged.emit("AI ready - click the object", "good")
        self.ready.emit(token)

    def _on_failed(self, generation, token, message) -> None:
        if self._stale(generation):
            return
        if self._pending == token:
            self._pending = ""
        self._forget_queued(token)
        if token != self._token:
            return                # a picture nobody is waiting for stays quiet
        self.failed.emit(message)

    def _on_skipped(self, generation, token) -> None:
        if self._stale(generation):
            return
        if self._pending == token:
            self._pending = ""
        self._forget_queued(token)

    def _on_loaded(self, generation) -> None:
        if self._stale(generation):
            return
        self._warming = False

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
        points = [tuple(point) for point in points]
        refine = None
        last = self._last
        if last is not None and last[0] == self._token and last[2] == box \
                and len(points) > len(last[1]) and points[:len(last[1])] == last[1]:
            # One more click on the same prompt starts from the answer it is
            # refining, as SAM's own interactive demo does - otherwise a
            # second click can throw away what the first one found.
            refine = last[3]
        try:
            mask, size, _score = runtime.predict(embedding, points=points, box=box,
                                                 max_side=PREDICT_MAX_SIDE, refine=refine)
        except SamError as exc:
            self._last = None
            return None, str(exc)
        except Exception as exc:
            self._last = None
            return None, "the model could not answer that prompt: %s" % exc
        logits = getattr(runtime, "last_low_res", None)
        self._last = (self._token, points, box, logits) if logits is not None else None
        self.last_refined = refine is not None
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
        # Emptied first, so anything already running gives up at its next
        # check instead of holding the window open for a picture nobody
        # will ever see.
        self._token = ""
        self._queued = []
        try:
            self._pool.clear()
            self._pool.waitForDone(2000)
        except Exception:
            pass
        self.reset()
