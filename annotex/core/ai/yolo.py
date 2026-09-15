"""Auto-labelling with your own YOLO detector.  No Qt.

Your trained detector (an .onnx export - Ultralytics' `yolo export
format=onnx`) proposes boxes; a person reviews them.  Three output layouts
are understood, and told apart by their shape:

    YOLOv8 / v11     [1, 4 + classes, boxes]      cx cy w h, class scores
    YOLOv5           [1, boxes, 5 + classes]      cx cy w h, objectness, scores
    end-to-end       [1, boxes, 6]                x1 y1 x2 y2 score class
                     (exports with NMS built in, YOLOv10)

Boxes may be in the model's input pixels or 0-1; either way they come back in
the original image's pixels, with the letterbox undone, overlapping repeats of
one object removed (per class) and anything under the confidence dropped.

Class names come from a names file when one is given (one per line, or a
data.yaml), otherwise from the model's own metadata, which Ultralytics
writes.  Segmentation, oriented-box, classification and pose models are
refused with a sentence rather than misread - this is for detection.

`prelabel` runs a detector over a folder for the Pre-label job: it never
touches an image that already has an annotation, and writes nothing for an
image where nothing was found.
"""

from __future__ import annotations

import ast
import os
import re
import threading
from dataclasses import dataclass

from annotex.core.jobs import JobCancelled

from .sam import install_hint, missing_packages

REFUSED_TASKS = {"segment": "a segmentation model", "obb": "an oriented-box model",
                 "classify": "a classification model", "pose": "a pose model"}
LETTERBOX_GREY = 114
DEFAULT_SIZE = 640


class YoloError(RuntimeError):
    """Something stops the model.  The message is written for a person."""


@dataclass
class Detection:
    cls: int
    name: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float


# ══════════════════════════════════════════════════════════════
# NAMES
# ══════════════════════════════════════════════════════════════
def names_from_yaml(text):
    inline = re.search(r"^names\s*:\s*\[(.*?)\]", text, re.M | re.S)
    if inline:
        return [part.strip().strip("'\"") for part in inline.group(1).split(",") if part.strip()]
    block = re.search(r"^names\s*:\s*\n((?:[ \t]+.*\n?)+)", text, re.M)
    names = []
    if block:
        for line in block.group(1).splitlines():
            item = re.match(r"^\s*(?:-\s*|\d+\s*:\s*)(.+?)\s*$", line)
            if item:
                names.append(item.group(1).strip("'\""))
    return names


def read_names_file(path):
    """Class names from a .txt (one per line) or a data.yaml.  Raises YoloError."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            text = handle.read()
    except OSError as exc:
        raise YoloError("The class names file could not be read: %s" % exc)
    if os.path.splitext(str(path))[1].lower() in (".yaml", ".yml"):
        names = names_from_yaml(text)
    else:
        names = [line.strip() for line in text.splitlines() if line.strip()]
    if not names:
        raise YoloError("There are no class names in %s." % os.path.basename(str(path)))
    return names


def _metadata_names(meta):
    raw = meta.get("names")
    if not raw:
        return []
    try:
        parsed = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []
    if isinstance(parsed, dict):
        try:
            return [str(parsed[key]) for key in sorted(parsed, key=int)]
        except (TypeError, ValueError):
            return [str(value) for value in parsed.values()]
    if isinstance(parsed, (list, tuple)):
        return [str(value) for value in parsed]
    return []


# ══════════════════════════════════════════════════════════════
# THE DETECTOR
# ══════════════════════════════════════════════════════════════
def _static(value) -> int:
    return int(value) if isinstance(value, int) and value > 0 else 0


class YoloDetector:
    """One YOLO .onnx model.  `detect` loads it on first use and is safe to
    call from a worker thread."""

    def __init__(self, path, names=None):
        self.path = str(path or "")
        self._names_override = [str(n) for n in names] if names else None
        self.session = None
        self.names = []
        self.task = ""
        self.size = (DEFAULT_SIZE, DEFAULT_SIZE)       # (width, height) the model takes
        self.layout = "nchw"
        self.channels = 3
        self.dtype = None
        self.input_name = ""
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self.session is not None

    def name(self, index) -> str:
        return self.names[index] if 0 <= index < len(self.names) else "class_%d" % index

    def load(self) -> None:
        with self._lock:
            if self.session is not None:
                return
            if missing_packages():
                raise YoloError(install_hint())
            if not self.path:
                raise YoloError("No YOLO model has been chosen yet.")
            if not os.path.isfile(self.path):
                raise YoloError("The YOLO model file is missing:\n%s" % self.path)
            import numpy as np
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.log_severity_level = 3
            try:
                session = ort.InferenceSession(self.path, options, providers=["CPUExecutionProvider"])
            except Exception as exc:
                raise YoloError("The model could not be opened - is it a YOLO .onnx export?\n\n%s" % exc)
            try:
                meta = dict(session.get_modelmeta().custom_metadata_map or {})
            except Exception:
                meta = {}
            task = str(meta.get("task", "")).strip().lower()
            if task in REFUSED_TASKS:
                raise YoloError("This is %s.  Auto-labelling takes detection models, which give "
                                "boxes - export a detection model (not -seg, -obb, -cls or -pose)."
                                % REFUSED_TASKS[task])
            inputs, outputs = session.get_inputs(), session.get_outputs()
            if len(inputs) != 1 or len(inputs[0].shape) != 4:
                raise YoloError("The model does not take a single image, so it is not a YOLO detector.")
            if len(outputs) != 1:
                raise YoloError("The model has %d outputs; a YOLO detector has one%s."
                                % (len(outputs), " (two is a segmentation model)"
                                   if len(outputs) == 2 else ""))
            shape = list(inputs[0].shape)
            if _static(shape[1]) in (1, 3):
                layout, height, width, channels = "nchw", _static(shape[2]), _static(shape[3]), _static(shape[1])
            elif _static(shape[3]) in (1, 3):
                layout, height, width, channels = "nhwc", _static(shape[1]), _static(shape[2]), _static(shape[3])
            else:
                layout, height, width, channels = "nchw", _static(shape[2]), _static(shape[3]), 3
            if not (height and width) and meta.get("imgsz"):
                try:
                    parsed = ast.literal_eval(meta["imgsz"])
                    if isinstance(parsed, int):
                        height = width = parsed
                    elif isinstance(parsed, (list, tuple)) and parsed:
                        height, width = int(parsed[0]), int(parsed[-1])
                except (ValueError, SyntaxError, TypeError):
                    pass
            self.size = (width or DEFAULT_SIZE, height or DEFAULT_SIZE)
            self.layout, self.channels = layout, channels or 3
            self.dtype = {"tensor(float16)": np.float16, "tensor(uint8)": np.uint8,
                          "tensor(double)": np.float64}.get(inputs[0].type, np.float32)
            self.names = self._names_override or _metadata_names(meta)
            self.task = task
            self.input_name = inputs[0].name
            self.session = session

    def unload(self) -> None:
        with self._lock:
            self.session = None

    # ── inference ─────────────────────────────────────────
    def _letterbox(self, rgb):
        import numpy as np
        from PIL import Image
        height, width = rgb.shape[:2]
        in_w, in_h = self.size
        scale = min(in_w / float(width), in_h / float(height))
        new_w, new_h = max(1, int(round(width * scale))), max(1, int(round(height * scale)))
        image = Image.fromarray(np.ascontiguousarray(rgb.astype(np.uint8)), "RGB")
        if self.channels == 1:
            image = image.convert("L")
        resized = image.resize((new_w, new_h), Image.Resampling.BILINEAR)
        fill = LETTERBOX_GREY if resized.mode == "L" else (LETTERBOX_GREY,) * 3
        canvas = Image.new(resized.mode, (in_w, in_h), fill)
        pad_x, pad_y = (in_w - new_w) // 2, (in_h - new_h) // 2
        canvas.paste(resized, (pad_x, pad_y))
        data = np.asarray(canvas, dtype=np.float32)
        if data.ndim == 2:
            data = data[:, :, None]
        if self.dtype != np.uint8:
            data = data / 255.0
        if self.layout == "nchw":
            data = data.transpose(2, 0, 1)
        return np.ascontiguousarray(data[None]).astype(self.dtype), scale, pad_x, pad_y

    def _decode(self, output):
        """(boxes x0 y0 x1 y1 in input pixels, scores, class ids)."""
        import numpy as np
        if output.ndim == 3:
            output = output[0]
        if output.ndim != 2:
            raise YoloError("The model's output has the shape %s, which is not a YOLO detector's."
                            % (tuple(output.shape),))
        nc = len(self.names)
        rows, cols = output.shape
        if nc and cols in (4 + nc, 5 + nc):
            pass
        elif nc and rows in (4 + nc, 5 + nc):
            output = output.T
        elif cols == 6 and rows != 6:
            pass
        elif rows == 6 and cols != 6:
            output = output.T
        elif rows < cols:
            output = output.T
        count, columns = output.shape
        if columns < 5:
            raise YoloError("The model's output has no class scores - is it a detector?")
        # Six columns is either an end-to-end export (x1 y1 x2 y2 score class)
        # or YOLOv8 with exactly two classes; an end-to-end class column holds
        # whole numbers, a class score does not.
        end_to_end = False
        if columns == 6 and nc not in (1, 2):
            ids = output[:, 5]
            if not len(ids):
                end_to_end = True
            else:
                whole = bool(np.all(np.abs(ids - np.round(ids)) < 1e-3)) and float(ids.min()) >= 0
                if whole and (not nc or float(ids.max()) < nc):
                    end_to_end = True
                elif nc:
                    raise YoloError("The model's output does not fit the %d class names given - "
                                    "check the names file." % nc)
        if end_to_end:
            boxes = output[:, :4].astype(np.float32)
            scores = output[:, 4].astype(np.float32)
            classes = np.round(output[:, 5]).astype(int)
        else:
            if nc and columns == 5 + nc:
                class_scores = output[:, 5:] * output[:, 4:5]
            elif not nc or columns == 4 + nc:
                class_scores = output[:, 4:]
            else:
                raise YoloError("The model gives %d class scores, but %d class names were given - "
                                "check the names file." % (columns - 4, nc))
            if not count:
                return (np.zeros((0, 4), np.float32), np.zeros(0, np.float32), np.zeros(0, int))
            classes = class_scores.argmax(axis=1)
            scores = class_scores[np.arange(count), classes].astype(np.float32)
            cx, cy, w, h = output[:, 0], output[:, 1], output[:, 2], output[:, 3]
            boxes = np.stack([cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0], axis=1)
        if len(boxes) and float(np.abs(boxes).max()) <= 1.5:
            in_w, in_h = self.size
            boxes = boxes * np.array([in_w, in_h, in_w, in_h], dtype=np.float32)
        return boxes.astype(np.float32), scores, classes.astype(int)

    def detect(self, rgb, confidence=0.25, iou=0.45, max_detections=300):
        """[Detection] in the image's own pixels, best first."""
        self.load()
        import numpy as np
        array = np.asarray(rgb)
        if array.ndim != 3 or array.shape[2] < 3 or not array.shape[0] or not array.shape[1]:
            raise YoloError("The image could not be read for the model.")
        height, width = array.shape[:2]
        tensor, scale, pad_x, pad_y = self._letterbox(array[:, :, :3])
        try:
            output = self.session.run(None, {self.input_name: tensor})[0]
        except Exception as exc:
            raise YoloError("The model could not run on this image: %s" % exc)
        boxes, scores, classes = self._decode(np.asarray(output, dtype=np.float32))
        keep = scores >= float(confidence)
        boxes, scores, classes = boxes[keep], scores[keep], classes[keep]
        if len(scores):
            order = nms(boxes, scores, classes, iou)[:max(1, int(max_detections))]
            boxes, scores, classes = boxes[order], scores[order], classes[order]
        found = []
        for (x0, y0, x1, y1), score, cls in zip(boxes, scores, classes):
            x0 = min(max((float(x0) - pad_x) / scale, 0.0), float(width))
            x1 = min(max((float(x1) - pad_x) / scale, 0.0), float(width))
            y0 = min(max((float(y0) - pad_y) / scale, 0.0), float(height))
            y1 = min(max((float(y1) - pad_y) / scale, 0.0), float(height))
            if x1 - x0 < 1.0 or y1 - y0 < 1.0:
                continue
            found.append(Detection(int(cls), self.name(int(cls)), float(score), x0, y0, x1, y1))
        return found


def nms(boxes, scores, classes, threshold=0.45):
    """Indices to keep, best first: a box is dropped when it overlaps a better
    box of the same class by more than `threshold` (IoU)."""
    import numpy as np
    if not len(scores):
        return np.zeros(0, dtype=int)
    shifted = boxes + (classes[:, None].astype(np.float32) * 1e6)   # classes never overlap
    x0, y0, x1, y1 = shifted[:, 0], shifted[:, 1], shifted[:, 2], shifted[:, 3]
    areas = np.maximum(0.0, x1 - x0) * np.maximum(0.0, y1 - y0)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        best = order[0]
        keep.append(best)
        rest = order[1:]
        if not rest.size:
            break
        w = np.maximum(0.0, np.minimum(x1[best], x1[rest]) - np.maximum(x0[best], x0[rest]))
        h = np.maximum(0.0, np.minimum(y1[best], y1[rest]) - np.maximum(y0[best], y0[rest]))
        inter = w * h
        union = areas[best] + areas[rest] - inter
        overlap = np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)
        order = rest[overlap <= threshold]
    return np.array(keep, dtype=int)


def read_image_rgb(path):
    """An image file as an (h, w, 3) uint8 array, turned the way its EXIF says
    - as the labelling tools show it.  Raises YoloError."""
    try:
        import numpy as np
        from PIL import Image, ImageOps
        with Image.open(path) as opened:
            return np.asarray(ImageOps.exif_transpose(opened).convert("RGB"), dtype=np.uint8)
    except Exception as exc:
        raise YoloError("%s could not be read: %s" % (os.path.basename(str(path)), exc))


# ══════════════════════════════════════════════════════════════
# CLASSES AND FOLDERS
# ══════════════════════════════════════════════════════════════
def model_key(path) -> str:
    """What remembered class choices are filed under: the model's file name and size."""
    try:
        return "%s|%d" % (os.path.basename(str(path)), os.path.getsize(str(path)))
    except OSError:
        return os.path.basename(str(path))


def match_classes(model_names, project_names, remembered=None):
    """{model class: project class, "" to ignore, or None when undecided}.
    A remembered choice wins, then a project class of the same name (case
    does not matter)."""
    remembered = dict(remembered or {})
    by_name = {str(name).casefold(): str(name) for name in project_names}
    decided = {}
    for name in model_names:
        name = str(name)
        if name in remembered:
            decided[name] = remembered[name]
        elif name.casefold() in by_name:
            decided[name] = by_name[name.casefold()]
        else:
            decided[name] = None
    return decided


def prelabel(images, detector, confidence, mapping, is_annotated, read_rgb, write, ctx=None):
    """Run the detector over `images` (relative names) for the Pre-label job.

    `is_annotated(rel)` - skip images that already have an annotation;
    `read_rgb(rel)` - the image as an (h, w, 3) array;
    `write(rel, [(class name, Detection)], width, height)` -> (ok, error).
    Classes mapped to "" (or not mapped) are left out.  Returns a summary."""
    done = annotated = empty = failed = 0
    total = len(images)
    for index, rel in enumerate(images):
        if ctx is not None:
            if ctx.cancelled:
                raise JobCancelled()
            ctx.progress(index / float(total or 1), "%d of %d  ·  %s"
                         % (index + 1, total, os.path.basename(str(rel))))
        try:
            if is_annotated(rel):
                annotated += 1
                continue
            rgb = read_rgb(rel)
            kept = [(mapping.get(d.name), d) for d in detector.detect(rgb, confidence)]
            kept = [(target, d) for target, d in kept if target]
            if not kept:
                empty += 1
                continue
            ok, error = write(rel, kept, int(rgb.shape[1]), int(rgb.shape[0]))
            if ok:
                done += 1
            else:
                failed += 1
                if ctx is not None:
                    ctx.warn("%s: %s" % (rel, error))
        except JobCancelled:
            raise
        except Exception as exc:                            # one bad image never stops the rest
            failed += 1
            if ctx is not None:
                ctx.warn("%s: %s" % (rel, exc))
    if ctx is not None:
        ctx.progress(1.0)
    parts = []
    if annotated:
        parts.append("%d already annotated" % annotated)
    if empty:
        parts.append("%d with nothing found" % empty)
    if failed:
        parts.append("%d failed" % failed)
    return "Pre-labelled %d image(s)%s" % (done, (" - " + ", ".join(parts)) if parts else "")
