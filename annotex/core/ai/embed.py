"""Turning an image into one vector, so images can be compared.

This is the half of reference-image sorting that has nothing to do with
sorting: hand it a picture, get back a unit-length vector, and two pictures
are alike exactly as far as their vectors point the same way.  Everything
above it - reference sets, thresholds, folders - is arithmetic on those
vectors.

Two embedders, one interface, because the honest answer to "which model?"
depends on what somebody is sorting:

    ClassicEmbedder   nothing to download, nothing to install beyond what
                      Annotex already needs.  Compares how a picture looks -
                      its layout, its colours, its overall shape - so it is
                      right for "the same scene again", "another frame from
                      this camera" and near-duplicates, and wrong for "any
                      photo of a dog".

    OnnxEmbedder      any image model exported to ONNX - a CLIP image
                      encoder, DINOv2, a plain classifier with its last
                      layer read off.  Compares what is *in* a picture, which
                      is what people usually mean.  Costs a download.

The export is inspected rather than assumed, exactly as `sam.py` does it:
input names, layout, dtype and size are read off the graph, and the output
is pooled into a vector whatever rank it arrives with.  numpy and
onnxruntime stay optional - without them this module says what is missing
instead of failing at import.

No Qt here.
"""

from __future__ import annotations

import os

from .cache import EmbeddingCache, content_identity, model_id

# How much each part of the classic descriptor is allowed to matter.
CLASSIC_WEIGHTS = (1.0, 1.0, 0.5)       # structure, colour, hash
GREY_SIDE = 32                          # structure and hash work at this size
COLOUR_SIDE = 64                        # the histogram is sampled at this size
COLOUR_BINS = 8                         # per channel, so 512 buckets
HASH_SIDE = 8                           # low-frequency corner kept for the hash


class EmbedUnavailable(RuntimeError):
    """The machine is missing something this embedder needs.

    The message is written to be shown to a person as it is."""


def missing_packages(onnx: bool = False):
    """The optional packages still needed, in install order."""
    wanted = [("numpy", "numpy")]
    if onnx:
        wanted.append(("onnxruntime", "onnxruntime"))
    missing = []
    for module, package in wanted:
        try:
            __import__(module)
        except Exception:
            missing.append(package)
    return missing


def install_hint(onnx: bool = False) -> str:
    missing = missing_packages(onnx)
    if not missing:
        return ""
    return ("Comparing images needs %s.  Install it with:\n\n"
            "    python bootstrap.py --ai\n\nor\n\n"
            "    python -m pip install %s" % (" and ".join(missing), " ".join(missing)))


def _numpy():
    try:
        import numpy
        return numpy
    except Exception:
        raise EmbedUnavailable(install_hint())


def _open_rgb(path):
    """A picture as a PIL image in RGB, oriented the way it is meant to be."""
    from PIL import Image, ImageOps
    with Image.open(str(path)) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB")


def unit(vector):
    """The same direction, length one.  A zero vector stays zero."""
    np = _numpy()
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(array))
    return array / norm if norm > 1e-8 else array


# ══════════════════════════════════════════════════════════════
# THE INTERFACE
# ══════════════════════════════════════════════════════════════
class Embedder:
    """One way of turning an image into a vector.

    Subclasses provide `id`, `name` and `vector(path)`.  `id` names the
    model for the cache, so it must change whenever the numbers would."""

    id = "none"
    name = "none"
    dim = 0
    semantic = False          # does it compare meaning, or only appearance?

    def vector(self, path):                             # pragma: no cover
        raise NotImplementedError

    def describe(self) -> str:
        return self.name


# ══════════════════════════════════════════════════════════════
# NOTHING TO DOWNLOAD
# ══════════════════════════════════════════════════════════════
class ClassicEmbedder(Embedder):
    """Layout, colour and a perceptual hash, stuck together.

    Three descriptions of a picture, each normalised on its own so that one
    cannot shout the others down, then weighted and normalised again:

        structure   a 32x32 grey thumbnail, standardised - so it describes
                    the arrangement of light and dark rather than the
                    exposure;
        colour      an 8x8x8 histogram in HSV - which colours, in what
                    proportion, and not where;
        hash        the low frequencies of the thumbnail's cosine transform
                    against their own median, which is the usual perceptual
                    hash and is what catches a re-saved or resized copy.

    Nothing here needs onnxruntime or a download, which is the point: the
    feature works the moment the application opens."""

    name = "Appearance (no download)"
    semantic = False

    def __init__(self, weights=CLASSIC_WEIGHTS):
        self.weights = tuple(float(w) for w in weights)
        self.dim = GREY_SIDE * GREY_SIDE + COLOUR_BINS ** 3 + HASH_SIDE * HASH_SIDE - 1

    @property
    def id(self) -> str:
        return "classic-%s" % EmbeddingCache.key(self.weights, GREY_SIDE,
                                                 COLOUR_BINS, HASH_SIDE)[:8]

    # ── the three parts ───────────────────────────────────
    @staticmethod
    def _dct_matrix(side):
        np = _numpy()
        rows = np.arange(side, dtype=np.float32).reshape(-1, 1)
        cols = np.arange(side, dtype=np.float32).reshape(1, -1)
        return np.cos(np.pi * (cols + 0.5) * rows / float(side)).astype("float32")

    def _structure(self, image):
        from PIL import Image
        np = _numpy()
        grey = image.convert("L").resize((GREY_SIDE, GREY_SIDE),
                                         Image.Resampling.BILINEAR)
        array = np.asarray(grey, dtype=np.float32)
        # Standardised, so brightening a photo does not make it a different
        # picture as far as this descriptor is concerned.
        spread = float(array.std())
        centred = array - float(array.mean())
        return (centred / spread if spread > 1e-6 else centred), array

    def _colour(self, image):
        from PIL import Image
        np = _numpy()
        small = image.resize((COLOUR_SIDE, COLOUR_SIDE), Image.Resampling.BILINEAR)
        hsv = np.asarray(small.convert("HSV"), dtype=np.uint8).reshape(-1, 3)
        step = 256 // COLOUR_BINS
        binned = np.minimum(hsv // step, COLOUR_BINS - 1).astype(np.int32)
        index = (binned[:, 0] * COLOUR_BINS + binned[:, 1]) * COLOUR_BINS + binned[:, 2]
        counts = np.bincount(index, minlength=COLOUR_BINS ** 3).astype(np.float32)
        # The square root keeps one dominant colour from burying the rest.
        return np.sqrt(counts / max(1.0, float(counts.sum())))

    def _hash(self, grey):
        np = _numpy()
        matrix = self._dct_matrix(GREY_SIDE)
        spectrum = matrix.dot(grey).dot(matrix.T)
        corner = spectrum[:HASH_SIDE, :HASH_SIDE].reshape(-1)[1:]   # drop the DC term
        return np.where(corner > float(np.median(corner)), 1.0, -1.0).astype("float32")

    def vector(self, path):
        np = _numpy()
        image = _open_rgb(path)
        structure, grey = self._structure(image)
        parts = (unit(structure.reshape(-1)), unit(self._colour(image)),
                 unit(self._hash(grey)))
        weighted = [part * weight for part, weight in zip(parts, self.weights)]
        return unit(np.concatenate(weighted))


# ══════════════════════════════════════════════════════════════
# ANY ONNX IMAGE MODEL
# ══════════════════════════════════════════════════════════════
class OnnxEmbedder(Embedder):
    """A vector from whatever image model somebody points this at.

    The graph is read rather than assumed - name, layout, dtype and input
    size all come off it - and the first output with any width to it is
    pooled down to one vector.  That covers a CLIP image encoder (which
    hands back a vector already), DINOv2 (a row of tokens) and an ordinary
    convolutional network (a feature map), without a line of code per
    model."""

    semantic = True

    def __init__(self, model_path, imagenet_norm: bool = True, size=0, recipe=None,
                 name=""):
        missing = missing_packages(onnx=True)
        if missing:
            raise EmbedUnavailable(install_hint(onnx=True))
        import numpy as np
        import onnxruntime as ort
        self.np = np
        self.path = str(model_path or "")
        if recipe is None:
            # A model from the catalogue is prepared exactly as it was trained;
            # anybody else's is read off its graph as before.
            try:
                from .catalog import embed_recipe_for
                recipe = embed_recipe_for(self.path)
            except Exception:                           # pragma: no cover
                recipe = None
        self.recipe = dict(recipe) if recipe else None
        if not os.path.isfile(self.path):
            raise EmbedUnavailable("That model file is not there:\n%s" % self.path)
        options = ort.SessionOptions()
        options.log_severity_level = 3
        try:
            options.intra_op_num_threads = max(1, min(8, os.cpu_count() or 2))
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        except Exception:
            pass
        try:
            self.session = ort.InferenceSession(self.path, options,
                                                providers=["CPUExecutionProvider"])
        except Exception as exc:
            raise EmbedUnavailable("That model could not be opened - is it an ONNX "
                                   "image model?\n\n%s" % exc)
        spec = self.session.get_inputs()[0]
        shape = list(spec.shape or [])
        if len(shape) != 4:
            raise EmbedUnavailable("That model does not take an image: its input has "
                                   "%d dimension(s), not 4." % len(shape))
        self.input_name = spec.name
        self.imagenet_norm = bool(imagenet_norm)
        if isinstance(shape[1], int) and shape[1] in (1, 3):
            self.layout, self.channels = "nchw", shape[1]
            height, width = shape[2], shape[3]
        elif isinstance(shape[3], int) and shape[3] in (1, 3):
            self.layout, self.channels = "nhwc", shape[3]
            height, width = shape[1], shape[2]
        else:
            self.layout, self.channels = "nchw", 3
            height, width = shape[2], shape[3]
        fixed = int(size) if size else 0
        self.width = fixed or (width if isinstance(width, int) and width > 0 else 224)
        self.height = fixed or (height if isinstance(height, int) and height > 0 else 224)
        self.dtype = {"tensor(float16)": np.float16, "tensor(uint8)": np.uint8,
                      "tensor(double)": np.float64}.get(spec.type, np.float32)
        self.name = name or os.path.basename(self.path)
        self.dim = 0                       # learnt from the first answer
        self._outputs = [o.name for o in self.session.get_outputs()]
        if self.recipe:
            self.width = self.height = int(self.recipe.get("crop") or self.width)

    @property
    def id(self) -> str:
        tag = ""
        if self.recipe:
            # A change of preparation changes every number, so it is part of
            # what the cache files the answers under.
            tag = "-" + EmbeddingCache.key(sorted(self.recipe.items()))[:8]
        return "onnx-%s%s" % (model_id(self.path), tag)

    def _prepared(self, image):
        """Resized the way the model expects: to its size directly, or - with
        a recipe - shortest side first, then the centre cut square, so the
        picture keeps its proportions instead of being squashed."""
        from PIL import Image
        if not self.recipe:
            return image.resize((self.width, self.height), Image.Resampling.BILINEAR)
        shortest = float(self.recipe.get("resize") or self.width)
        scale = shortest / float(min(image.width, image.height) or 1)
        size = (max(self.width, int(round(image.width * scale))),
                max(self.height, int(round(image.height * scale))))
        image = image.resize(size, Image.Resampling.BICUBIC)
        left = (size[0] - self.width) // 2
        top = (size[1] - self.height) // 2
        return image.crop((left, top, left + self.width, top + self.height))

    def _tensor(self, path):
        np = self.np
        image = _open_rgb(path)
        if self.channels == 1:
            image = image.convert("L")
        image = self._prepared(image)
        array = np.asarray(image, dtype=np.float32)
        if array.ndim == 2:
            array = array[:, :, None]
        if self.dtype != np.uint8:
            array = array / 255.0
            if self.recipe and array.shape[2] == 3:
                array = (array - np.array(self.recipe["mean"], dtype=np.float32)) \
                    / np.array(self.recipe["std"], dtype=np.float32)
            elif self.imagenet_norm and array.shape[2] == 3:
                array = (array - np.array([0.485, 0.456, 0.406], dtype=np.float32)) \
                    / np.array([0.229, 0.224, 0.225], dtype=np.float32)
        if self.layout == "nchw":
            array = array.transpose(2, 0, 1)
        return np.ascontiguousarray(array[None].astype(self.dtype))

    def _pool(self, outputs):
        """One vector out of whatever the model handed back."""
        np = self.np
        wanted = (self.recipe or {}).get("output")
        if wanted:
            named = dict(zip(self._outputs, outputs))
            if wanted == "cls" and "last_hidden_state" in named:
                # The class token: what a ViT sums a picture up in.
                tokens = np.asarray(named["last_hidden_state"], dtype=np.float32)
                if tokens.ndim == 3 and tokens.shape[1]:
                    return tokens[0, 0].reshape(-1)
            if wanted in named:
                return np.asarray(named[wanted], dtype=np.float32).reshape(-1)
        best = None
        for value in outputs:
            array = np.asarray(value, dtype=np.float32)
            if array.ndim >= 2 and array.size:
                best = array
                break
        if best is None:
            raise EmbedUnavailable("That model returned nothing a vector can be "
                                   "made from.")
        while best.ndim > 1 and best.shape[0] == 1:
            best = best[0]
        if best.ndim == 3:                 # a feature map: average over position
            best = best.reshape(best.shape[0], -1).mean(axis=1)
        elif best.ndim == 2:               # a row of tokens: average over them
            best = best.mean(axis=0)
        return best.reshape(-1)

    def vector(self, path):
        # Reading the picture stays outside: an unreadable image is that
        # image's problem, and embed_paths lists it and carries on, whereas
        # EmbedUnavailable says the model itself cannot be used and stops.
        tensor = self._tensor(path)
        try:
            outputs = self.session.run(None, {self.input_name: tensor})
        except Exception as exc:
            raise EmbedUnavailable("The model could not read that image: %s" % exc)
        vector = unit(self._pool(outputs))
        self.dim = int(vector.size)
        return vector


# ══════════════════════════════════════════════════════════════
# COMPARING, AND DOING IT IN BULK
# ══════════════════════════════════════════════════════════════
def cosine_many(vector, matrix):
    """How alike one unit vector is to each row of a unit matrix, -1 to 1."""
    np = _numpy()
    rows = np.asarray(matrix, dtype=np.float32)
    if rows.ndim == 1:
        rows = rows[None, :]
    if not rows.size:
        return np.zeros((0,), dtype=np.float32)
    return rows.dot(np.asarray(vector, dtype=np.float32).reshape(-1))


def embed_paths(embedder, paths, cache=None, progress=None, cancelled=None):
    """Vectors for many images, reading and writing the cache as it goes.

    Returns (vectors, errors): an (n, d) matrix for the images that worked
    and [(path, why)] for the ones that did not, so one unreadable file
    never costs somebody the whole run."""
    np = _numpy()
    progress = progress or (lambda done, total: None)
    cancelled = cancelled or (lambda: False)
    paths = [str(p) for p in paths]
    total = len(paths) or 1
    vectors, errors, kept = [], [], []
    for index, path in enumerate(paths):
        if cancelled():
            break
        progress(index, len(paths))
        key = ""
        if cache is not None:
            key = EmbeddingCache.key(embedder.id, content_identity(path))
            stored, _meta = cache.get(key)
            if stored is not None and stored.ndim == 1 and stored.size:
                vectors.append(stored)
                kept.append(path)
                continue
        try:
            vector = embedder.vector(path)
        except EmbedUnavailable:
            raise
        except Exception as exc:                                   # noqa: BLE001
            errors.append((path, str(exc)))
            continue
        if cache is not None and key:
            cache.put(key, vector)
        vectors.append(vector)
        kept.append(path)
    progress(len(paths), len(paths))
    if not vectors:
        return np.zeros((0, 0), dtype=np.float32), errors, kept
    width = max(int(v.size) for v in vectors)
    if any(int(v.size) != width for v in vectors):
        # A model answered inconsistently, or two of them wrote into one
        # cache namespace.  Keep what agrees on a width and say what went.
        agreed, agreed_paths = [], []
        for vector, path in zip(vectors, kept):
            if int(vector.size) == width:
                agreed.append(vector)
                agreed_paths.append(path)
            else:
                errors.append((path, "the model gave %d numbers, not %d"
                               % (int(vector.size), width)))
        vectors, kept = agreed, agreed_paths
    if not vectors:
        return np.zeros((0, 0), dtype=np.float32), errors, []
    return np.vstack([np.asarray(v, dtype=np.float32) for v in vectors]), errors, kept
