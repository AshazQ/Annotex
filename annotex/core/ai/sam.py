"""Segment Anything (SAM), the way the annotation tools use it.

One click on the object, and the tool proposes the box or the polygon - the
"AI" mode LabelMe made familiar.  The model runs locally through
onnxruntime; nothing is uploaded anywhere and nothing is downloaded unless
the person asks for it.

Two files make a model:

    encoder   runs once per image and is the slow half (a second or several)
    decoder   runs on every click and is the fast half (milliseconds)

Exports differ - the reference `segment-anything` export, MobileSAM,
samexporter's, EdgeSAM - so the session is inspected rather than assumed:
input names, layouts (NCHW or NHWC), dtypes and whether the export already
contains the normalisation are all read off the graph.  A model this module
cannot drive raises SamError with a sentence naming the problem instead of
failing somewhere deep in a matrix multiply.

No Qt here.  The caller hands in an RGB image already resized to the
model's long side (Qt does that better than we could), and gets back a
boolean mask.
"""

from __future__ import annotations

import os
import re

from ...config import first_writable, user_data_dir

# SAM's own preprocessing constants.
PIXEL_MEAN = (123.675, 116.28, 103.53)
PIXEL_STD = (58.395, 57.12, 57.375)
DEFAULT_LONG_SIDE = 1024
LOW_RES = 256

# Prompt labels, as the exported decoder understands them.
POINT_POSITIVE = 1
POINT_NEGATIVE = 0
BOX_TOP_LEFT = 2
BOX_BOTTOM_RIGHT = 3
PAD_POINT = -1

ENCODER_HINTS = ("encoder", "vision", "embed")
DECODER_HINTS = ("decoder", "prompt", "sam_onnx")


class SamError(RuntimeError):
    """Something about the model or the machine stops a prediction.

    The message is written to be shown to a person as it is."""


# ══════════════════════════════════════════════════════════════
# AVAILABILITY
# ══════════════════════════════════════════════════════════════
def missing_packages():
    """The optional packages this machine still needs, in install order."""
    missing = []
    for module, package in (("numpy", "numpy"), ("onnxruntime", "onnxruntime")):
        try:
            __import__(module)
        except Exception:
            missing.append(package)
    return missing


def is_available() -> bool:
    return not missing_packages()


def install_hint() -> str:
    missing = missing_packages()
    if not missing:
        return ""
    return ("The AI tool needs %s.  Install it with:\n\n"
            "    python bootstrap.py --ai\n\nor\n\n"
            "    python -m pip install %s" % (" and ".join(missing), " ".join(missing)))


def providers_in_use():
    try:
        import onnxruntime as ort
        return list(ort.get_available_providers())
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════
# WHERE MODELS LIVE
# ══════════════════════════════════════════════════════════════
def models_dir():
    """Where a downloaded or copied model is kept, per user."""
    return first_writable([user_data_dir() / "models"])


def bundled_models_dir():
    """A `models` folder beside the installation, for a shared or portable
    copy that everybody on the machine reads."""
    here = os.path.dirname(os.path.abspath(__file__))          # annotex/core/ai
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(root, "models")


def search_dirs(extra=()):
    """Every folder searched for model files, nearest first."""
    out = []
    for candidate in list(extra) + [models_dir(), bundled_models_dir()]:
        if not candidate:
            continue
        try:
            path = os.path.abspath(str(candidate))
        except Exception:
            continue
        if path not in out and os.path.isdir(path):
            out.append(path)
    return out


def _role(name):
    stem = os.path.basename(name).lower()
    if any(hint in stem for hint in DECODER_HINTS):
        return "decoder"
    if any(hint in stem for hint in ENCODER_HINTS):
        return "encoder"
    return ""


def _family(name):
    """"mobile_sam.encoder.onnx" and "mobile_sam.decoder.onnx" belong
    together; this is the part of the name they share."""
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    for hint in DECODER_HINTS + ENCODER_HINTS:
        stem = stem.replace(hint, " ")
    return re.sub(r"[^a-z0-9]+", " ", stem).strip() or "sam"


class ModelPair:
    """An encoder and a decoder that belong together."""

    def __init__(self, name, encoder, decoder):
        self.name = str(name or "SAM")
        self.encoder = str(encoder or "")
        self.decoder = str(decoder or "")

    @property
    def complete(self) -> bool:
        return bool(self.encoder and self.decoder
                    and os.path.isfile(self.encoder) and os.path.isfile(self.decoder))

    @property
    def key(self) -> str:
        return "%s|%s" % (self.encoder, self.decoder)

    def describe(self) -> str:
        if not self.complete:
            return "%s - files missing" % self.name
        size = 0
        for path in (self.encoder, self.decoder):
            try:
                size += os.path.getsize(path)
            except OSError:
                pass
        return "%s  ·  %.0f MB" % (self.name, size / (1024.0 * 1024.0))

    def __repr__(self):                                # pragma: no cover
        return "ModelPair(%r, %r, %r)" % (self.name, self.encoder, self.decoder)


def discover_models(extra_dirs=()):
    """Every encoder/decoder pair sitting in the model folders."""
    found = {}
    for folder in search_dirs(extra_dirs):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith(".onnx"):
                continue
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            role = _role(name)
            if not role:
                continue
            slot = found.setdefault((folder, _family(name)), {})
            slot.setdefault(role, path)
    pairs = []
    for (_folder, family), slot in sorted(found.items()):
        if "encoder" in slot and "decoder" in slot:
            pairs.append(ModelPair(family.replace(" ", " ").strip().title() or "SAM",
                                   slot["encoder"], slot["decoder"]))
    return pairs


# ══════════════════════════════════════════════════════════════
# THE RUNTIME
# ══════════════════════════════════════════════════════════════
class Embedding:
    """What the encoder produced for one image, kept so every later click
    costs only the fast half of the model."""

    __slots__ = ("features", "orig_size", "input_size", "scale", "token")

    def __init__(self, features, orig_size, input_size, scale, token=""):
        self.features = features
        self.orig_size = orig_size          # (height, width) of the real image
        self.input_size = input_size        # (height, width) fed to the encoder
        self.scale = scale                  # input / original
        self.token = token


def _static(dim):
    return int(dim) if isinstance(dim, int) and dim > 0 else 0


class SamRuntime:
    """One loaded SAM model.  Create it, `load()` it, then encode and predict.

    Every public method raises SamError - and only SamError - when something
    is wrong, so callers have exactly one thing to catch."""

    def __init__(self, encoder_path, decoder_path, name="SAM"):
        self.name = str(name or "SAM")
        self.encoder_path = str(encoder_path or "")
        self.decoder_path = str(decoder_path or "")
        self._encoder = None
        self._decoder = None
        self._plan = {}
        self._decoder_inputs = {}
        self.long_side = DEFAULT_LONG_SIDE

    # ── loading ───────────────────────────────────────────
    @property
    def loaded(self) -> bool:
        return self._encoder is not None and self._decoder is not None

    def load(self) -> None:
        if self.loaded:
            return
        missing = missing_packages()
        if missing:
            raise SamError(install_hint())
        for role, path in (("encoder", self.encoder_path), ("decoder", self.decoder_path)):
            if not path:
                raise SamError("no %s file has been chosen for %s" % (role, self.name))
            if not os.path.isfile(path):
                raise SamError("the %s file is missing:\n%s" % (role, path))
        try:
            import onnxruntime as ort
        except Exception as exc:                        # pragma: no cover
            raise SamError("onnxruntime could not be loaded: %s" % exc)

        options = ort.SessionOptions()
        options.log_severity_level = 3
        try:
            cpus = os.cpu_count() or 2
            options.intra_op_num_threads = max(1, min(4, cpus))
        except Exception:
            pass
        self._encoder = self._session(ort, options, self.encoder_path, "encoder")
        self._decoder = self._session(ort, options, self.decoder_path, "decoder")
        self._plan = self._encoder_plan()
        self._decoder_inputs = {i.name: i for i in self._decoder.get_inputs()}
        self._check_decoder()

    @staticmethod
    def _session(ort, options, path, role):
        available = []
        try:
            available = list(ort.get_available_providers())
        except Exception:
            pass
        wanted = [p for p in ("CUDAExecutionProvider", "CoreMLExecutionProvider",
                              "CPUExecutionProvider") if p in available]
        for providers in ([wanted] if wanted else []) + [["CPUExecutionProvider"], None]:
            try:
                if providers is None:
                    return ort.InferenceSession(path, options)
                return ort.InferenceSession(path, options, providers=providers)
            except Exception as exc:
                last = exc
        raise SamError("the %s could not be opened - is it a SAM ONNX export?\n%s\n\n%s"
                       % (role, os.path.basename(path), last))

    def unload(self) -> None:
        self._encoder = self._decoder = None
        self._plan, self._decoder_inputs = {}, {}

    # ── what this export expects ──────────────────────────
    def _encoder_plan(self) -> dict:
        inputs = self._encoder.get_inputs()
        if not inputs:
            raise SamError("the encoder has no inputs - it is not a SAM encoder")
        spec = inputs[0]
        shape = list(spec.shape or [])
        kind = (spec.type or "").lower()
        floating = "float" in kind
        layout, side = "nchw", 0
        if len(shape) == 4:
            if _static(shape[1]) == 3:
                layout, side = "nchw", max(_static(shape[2]), _static(shape[3]))
            elif _static(shape[3]) == 3:
                layout, side = "nhwc", max(_static(shape[1]), _static(shape[2]))
        elif len(shape) == 3 and _static(shape[2]) == 3:
            layout, side = "hwc", max(_static(shape[0]), _static(shape[1]))
        self.long_side = side or DEFAULT_LONG_SIDE
        return {"name": spec.name, "layout": layout, "float": floating,
                # A uint8 export carries SAM's normalisation inside the graph.
                "normalise": floating, "pad": layout in ("nchw", "nhwc", "hwc") and bool(side)}

    def _check_decoder(self) -> None:
        names = set(self._decoder_inputs)
        if not any("embed" in name or "feat" in name for name in names):
            raise SamError("the decoder does not take an image embedding - "
                           "encoder and decoder look swapped")
        if not any("point_coord" in name or name == "point_coords" for name in names):
            raise SamError("the decoder takes no point prompts - it is not a SAM decoder")

    def _input(self, *wanted):
        for name in self._decoder_inputs:
            for want in wanted:
                if want in name:
                    return name
        return ""

    # ── encoding ──────────────────────────────────────────
    def target_size(self, width, height):
        """The size the caller should resize the image to before encoding."""
        width, height = int(width), int(height)
        if width <= 0 or height <= 0:
            raise SamError("the image has no size")
        side = int(self.long_side or DEFAULT_LONG_SIDE)
        scale = float(side) / float(max(width, height))
        return (max(1, int(round(width * scale))), max(1, int(round(height * scale))))

    def encode(self, rgb, orig_size, token="") -> Embedding:
        """`rgb` is an (h, w, 3) uint8 array already resized to target_size()."""
        if not self.loaded:
            self.load()
        import numpy as np
        try:
            array = np.asarray(rgb)
            if array.ndim != 3 or array.shape[2] < 3:
                raise ValueError("expected an (h, w, 3) image")
            array = array[:, :, :3]
            height, width = int(array.shape[0]), int(array.shape[1])
            side = int(self.long_side or DEFAULT_LONG_SIDE)

            if self._plan.get("normalise", True):
                data = array.astype(np.float32)
                data = (data - np.array(PIXEL_MEAN, dtype=np.float32)) / \
                    np.array(PIXEL_STD, dtype=np.float32)
            else:
                data = array.astype(np.uint8)

            if self._plan.get("pad", True) and (height != side or width != side):
                pad = np.zeros((side, side, data.shape[2]), dtype=data.dtype)
                pad[:height, :width] = data[:side, :side]
                data = pad

            layout = self._plan.get("layout", "nchw")
            if layout == "nchw":
                tensor = np.ascontiguousarray(data.transpose(2, 0, 1)[None, ...])
            elif layout == "nhwc":
                tensor = np.ascontiguousarray(data[None, ...])
            else:
                tensor = np.ascontiguousarray(data)
            outputs = self._encoder.run(None, {self._plan["name"]: tensor})
        except SamError:
            raise
        except Exception as exc:
            raise SamError("the encoder could not read this image: %s" % exc)
        if not outputs:
            raise SamError("the encoder returned nothing")
        orig_h, orig_w = int(orig_size[0]), int(orig_size[1])
        scale = float(max(height, width)) / float(max(orig_h, orig_w) or 1)
        return Embedding(outputs[0], (orig_h, orig_w), (height, width), scale, token)

    # ── predicting ────────────────────────────────────────
    def predict(self, embedding: Embedding, points=(), box=None, max_side: int = 1024):
        """One prediction.

        `points` is [(x, y, positive_bool), …] and `box` is (x0, y0, x1, y1),
        both in ORIGINAL image pixels.  Returns (mask, (height, width), score)
        where `mask` is a boolean array in the returned size - which may be
        smaller than the image, so a huge photo does not cost a hundred
        megabytes per click.  Scale the result back with the size given."""
        if not self.loaded:
            self.load()
        if embedding is None:
            raise SamError("this image has not been prepared yet")
        if not points and box is None:
            raise SamError("click the object first")
        import numpy as np

        scale = float(embedding.scale or 1.0)
        coords, labels = [], []
        if box is not None:
            x0, y0, x1, y1 = [float(v) for v in box]
            coords += [[min(x0, x1) * scale, min(y0, y1) * scale],
                       [max(x0, x1) * scale, max(y0, y1) * scale]]
            labels += [BOX_TOP_LEFT, BOX_BOTTOM_RIGHT]
        for point in points:
            x, y = float(point[0]), float(point[1])
            positive = bool(point[2]) if len(point) > 2 else True
            coords.append([x * scale, y * scale])
            labels.append(POINT_POSITIVE if positive else POINT_NEGATIVE)
        if box is None:
            # The reference export expects a padding point when no box is given.
            coords.append([0.0, 0.0])
            labels.append(PAD_POINT)

        orig_h, orig_w = embedding.orig_size
        out_h, out_w = orig_h, orig_w
        cap = max(64, int(max_side))
        if max(orig_h, orig_w) > cap:
            shrink = float(cap) / float(max(orig_h, orig_w))
            out_h = max(1, int(round(orig_h * shrink)))
            out_w = max(1, int(round(orig_w * shrink)))

        feed = {}
        embed_name = self._input("image_embeddings", "embed", "feat")
        feed[embed_name] = embedding.features
        feed[self._input("point_coords")] = np.array([coords], dtype=np.float32)
        feed[self._input("point_labels")] = np.array([labels], dtype=np.float32)
        mask_input = self._input("mask_input")
        if mask_input:
            feed[mask_input] = np.zeros((1, 1, LOW_RES, LOW_RES), dtype=np.float32)
        has_mask = self._input("has_mask_input")
        if has_mask:
            feed[has_mask] = np.zeros(1, dtype=np.float32)
        size_input = self._input("orig_im_size", "orig_size")
        if size_input:
            feed[size_input] = np.array([out_h, out_w], dtype=np.float32)

        try:
            outputs = self._decoder.run(None, feed)
        except Exception as exc:
            raise SamError("the model could not use that prompt: %s" % exc)
        masks, scores = self._pick_outputs(outputs)
        if masks is None:
            raise SamError("the decoder returned no mask")

        try:
            data = np.asarray(masks)
            while data.ndim > 3:
                data = data[0]
            if data.ndim == 2:
                data = data[None, ...]
            best = 0
            if scores is not None:
                flat = np.asarray(scores).reshape(-1)
                if flat.size >= data.shape[0]:
                    best = int(np.argmax(flat[:data.shape[0]]))
            mask = data[best] > 0.0
            score = float(np.asarray(scores).reshape(-1)[best]) if scores is not None else 0.0
        except Exception as exc:
            raise SamError("the mask could not be read: %s" % exc)

        if not size_input:
            # No resize inside the graph: the mask covers the padded square,
            # so crop away the padding before handing it back.
            mask, out_h, out_w = self._crop_padding(mask, embedding)
        return mask, (int(mask.shape[0]), int(mask.shape[1])), score

    @staticmethod
    def _crop_padding(mask, embedding):
        height, width = int(mask.shape[0]), int(mask.shape[1])
        in_h, in_w = embedding.input_size
        side = float(max(in_h, in_w) or 1)
        keep_h = max(1, int(round(height * (in_h / side))))
        keep_w = max(1, int(round(width * (in_w / side))))
        return mask[:keep_h, :keep_w], keep_h, keep_w

    @staticmethod
    def _pick_outputs(outputs):
        masks, scores = None, None
        for value in outputs:
            shape = getattr(value, "shape", ())
            if masks is None and len(shape) >= 3:
                masks = value
            elif scores is None and 0 < len(shape) <= 2:
                scores = value
        if masks is None and outputs:
            masks = outputs[0]
        return masks, scores
