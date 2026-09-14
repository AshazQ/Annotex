"""Sorting with an ONNX model.  No Qt.

Two kinds of model are understood:

* classifiers - one output of shape [1, classes]; logits or probabilities;
* YOLO-style detectors - [1, 4+classes, boxes] (v8/v11), [1, 5+classes, boxes]
  (v5, with objectness) or [1, boxes, 6] (end-to-end: x1 y1 x2 y2 score class).

Class names come from a labels file (one per line) or from the model's own
metadata (Ultralytics exports store them as `names`).  onnxruntime is an
optional install; without it this module says how to add it instead of
failing at import.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field

from .sorter import EMPTY, UNSURE

INSTALL_HINT = ("AI sorting needs onnxruntime. Install it with:\n"
                "    python bootstrap.py --ai\n"
                "or: python -m pip install onnxruntime")


class AIUnavailable(RuntimeError):
    pass


def available():
    try:
        import numpy          # noqa: F401
        import onnxruntime    # noqa: F401
        return True
    except Exception:
        return False


def read_labels(path):
    with open(path, encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]


@dataclass
class Prediction:
    kind: str
    scores: dict = field(default_factory=dict)       # label -> confidence
    boxes: int = 0

    def top(self):
        if not self.scores:
            return None, 0.0
        label = max(self.scores, key=self.scores.get)
        return label, self.scores[label]


class OnnxModel:
    def __init__(self, model_path, labels=None, kind="auto", imagenet_norm=False):
        try:
            import numpy as np
            import onnxruntime as ort
        except Exception as exc:
            raise AIUnavailable(INSTALL_HINT) from exc
        self.np = np
        if not os.path.isfile(model_path):
            raise ValueError("Model not found: %s" % model_path)
        options = ort.SessionOptions()
        options.log_severity_level = 3
        try:
            self.session = ort.InferenceSession(str(model_path), options,
                                                providers=["CPUExecutionProvider"])
        except Exception as exc:
            raise ValueError("The model could not be loaded: %s" % exc)
        self.input = self.session.get_inputs()[0]
        self.output = self.session.get_outputs()[0]
        self.imagenet_norm = imagenet_norm

        shape = list(self.input.shape)
        if len(shape) != 4:
            raise ValueError("Expected an image input with 4 dimensions, got %s" % shape)
        if isinstance(shape[1], int) and shape[1] in (1, 3):
            self.layout, channels, height, width = "nchw", shape[1], shape[2], shape[3]
        elif isinstance(shape[3], int) and shape[3] in (1, 3):
            self.layout, height, width, channels = "nhwc", shape[1], shape[2], shape[3]
        else:
            self.layout, channels, height, width = "nchw", 3, shape[2], shape[3]
        output_rank = len(self.output.shape)
        if kind == "auto":
            kind = "classifier" if output_rank == 2 else "detector"
        self.kind = kind
        default = 224 if kind == "classifier" else 640
        self.width = width if isinstance(width, int) and width > 0 else default
        self.height = height if isinstance(height, int) and height > 0 else default
        self.channels = channels
        self.dtype = {"tensor(float16)": np.float16, "tensor(uint8)": np.uint8,
                      "tensor(double)": np.float64}.get(self.input.type, np.float32)

        self.labels = list(labels) if labels else self._metadata_labels()

    def _metadata_labels(self):
        try:
            names = self.session.get_modelmeta().custom_metadata_map.get("names")
            if names:
                parsed = ast.literal_eval(names)
                if isinstance(parsed, dict):
                    return [str(parsed[k]) for k in sorted(parsed, key=int)]
                if isinstance(parsed, (list, tuple)):
                    return [str(v) for v in parsed]
        except Exception:
            pass
        return []

    def label(self, index):
        return self.labels[index] if 0 <= index < len(self.labels) else "class_%d" % index

    # ── inference ─────────────────────────────────────────
    def _tensor(self, path):
        from PIL import Image, ImageOps
        np = self.np
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("L" if self.channels == 1 else "RGB")
        if self.kind == "detector":
            scale = min(self.width / image.width, self.height / image.height)
            size = (max(1, int(round(image.width * scale))), max(1, int(round(image.height * scale))))
            canvas = Image.new(image.mode, (self.width, self.height),
                               114 if image.mode == "L" else (114, 114, 114))
            canvas.paste(image.resize(size, Image.Resampling.BILINEAR),
                         ((self.width - size[0]) // 2, (self.height - size[1]) // 2))
            image = canvas
        else:
            image = image.resize((self.width, self.height), Image.Resampling.BILINEAR)
        array = np.asarray(image, dtype=np.float32)
        if array.ndim == 2:
            array = array[:, :, None]
        if self.dtype != np.uint8:
            array = array / 255.0
            if self.imagenet_norm and array.shape[2] == 3:
                array = (array - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
        if self.layout == "nchw":
            array = array.transpose(2, 0, 1)
        return array[None].astype(self.dtype)

    def predict(self, path) -> Prediction:
        np = self.np
        output = self.session.run([self.output.name], {self.input.name: self._tensor(path)})[0]
        output = np.asarray(output, dtype=np.float32)
        if self.kind == "classifier":
            values = output.reshape(-1)
            if values.min() < 0 or values.max() > 1.0001 or abs(float(values.sum()) - 1) > 0.01:
                shifted = np.exp(values - values.max())
                values = shifted / shifted.sum()
            return Prediction("classifier", {self.label(i): float(v) for i, v in enumerate(values)})
        return self._detections(output)

    def _detections(self, output):
        np = self.np
        array = output[0] if output.ndim == 3 else output
        if array.ndim != 2:
            raise ValueError("Unexpected detector output shape %s" % (output.shape,))
        nc = len(self.labels)
        rows, cols = array.shape
        widths = {4 + nc, 5 + nc} if nc else set()
        end_to_end = False
        if widths and cols in widths:
            pass                                             # (boxes, columns) already
        elif widths and rows in widths:
            array = array.T
        elif 6 in (rows, cols) and nc not in (1, 2):
            end_to_end = True                                # x1 y1 x2 y2 score class
            if cols != 6:
                array = array.T
        elif rows < cols:
            array = array.T                                  # (columns, boxes) -> (boxes, columns)
        scores = {}
        if end_to_end:
            for row in array:
                confidence, index = float(row[4]), int(row[5])
                label = self.label(index)
                scores[label] = max(scores.get(label, 0.0), confidence)
            return Prediction("detector", scores, int((array[:, 4] > 0).sum()))
        columns = array.shape[1]
        if columns <= 4:
            raise ValueError("The detector output has no class scores (shape %s)" % (output.shape,))
        if nc and columns == 5 + nc:
            class_scores = array[:, 5:] * array[:, 4:5]
        else:
            class_scores = array[:, 4:]
        if len(class_scores) == 0:
            return Prediction("detector", {}, 0)
        best = class_scores.max(axis=0)
        for index, value in enumerate(best):
            scores[self.label(index)] = float(value)
        return Prediction("detector", scores, int((class_scores.max(axis=1) > 0.25).sum()))

def categorise(prediction, threshold=0.5, multiple="top", mapping=None):
    """Folder names for one prediction.

    Classifier: the top class when it clears the threshold, else _unsure.
    Detector: the classes found above the threshold (the best one, or all of
    them with multiple="all"), else _empty.  `mapping` renames a class's
    folder; a class mapped to "" is ignored."""
    mapping = dict(mapping or {})

    def folder(label):
        return mapping.get(label, label)

    if prediction.kind == "classifier":
        label, confidence = prediction.top()
        if label is None or confidence < threshold or folder(label) == "":
            return [UNSURE], "top %s %.2f" % (label, confidence)
        return [folder(label)], "%s %.2f" % (label, confidence)
    found = sorted(((c, l) for l, c in prediction.scores.items()
                    if c >= threshold and folder(l) != ""), reverse=True)
    if not found:
        return [EMPTY], "nothing above %.2f" % threshold
    detail = ", ".join("%s %.2f" % (l, c) for c, l in found)
    if multiple == "all":
        return [folder(l) for _c, l in found], detail
    return [folder(found[0][1])], detail
