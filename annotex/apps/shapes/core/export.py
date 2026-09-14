"""YOLO and COCO exports.  No Qt.

The shape files stay the source of truth; exports are written into their own
folders inside the batch and can be rebuilt at any time.

YOLO needs one task per dataset, so the export asks which:

    segment   export_yolo_seg/   class x1 y1 x2 y2 ... (normalised polygon)
              every shape becomes a polygon; circles and ellipses are
              sampled, an oriented box is its four corners
    obb       export_yolo_obb/   class x1 y1 x2 y2 x3 y3 x4 y4
              an oriented box as it is; every other shape becomes its
              tightest rotated box

Both mirror the image folder under labels/ and write classes.txt and a
data.yaml.  YOLO class indices are the Class Manager's permanent IDs.

COCO writes export_coco_shapes/annotations.json with segmentation polygons.
Category ids are the class ID plus one (COCO keeps 0 for background), with
the original carried as `class_id`, and each annotation carries the exact
shape under `annotex_shape`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from annotex.core.io_safe import ensure_dir, write_text_atomic

from ..config import (APP_NAME, APP_VERSION, CURVE_SEGMENTS, EXPORT_COCO,
                      EXPORT_YOLO_OBB, EXPORT_YOLO_SEG, TASK_OBB, TASK_SEGMENT)
from . import geometry as geo
from .store import read_annotation


class ExportReport:
    def __init__(self, path=""):
        self.path = path
        self.images = 0
        self.shapes = 0
        self.files = 0
        self.skipped_labels = 0
        self.unknown = set()
        self.errors = []

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        text = "%d image(s), %d shape(s)" % (self.images, self.shapes)
        if self.skipped_labels:
            text += ", %d shape(s) skipped - class not in the project (%s)" % (
                self.skipped_labels, ", ".join(sorted(self.unknown)))
        if self.errors:
            text += ", %d problem(s)" % len(self.errors)
        return text


def _norm(value, size) -> str:
    return "%.6f" % geo.clamp(float(value) / float(size), 0.0, 1.0)


def yolo_line(shape, class_id, width, height, task=TASK_SEGMENT,
              segments=CURVE_SEGMENTS) -> str:
    if task == TASK_OBB:
        cx, cy, w, h, angle = shape.rotated_box()
        points = geo.rect_corners(cx, cy, w, h, angle)
    else:
        points = shape.outline(segments)
    coords = " ".join("%s %s" % (_norm(x, width), _norm(y, height)) for x, y in points)
    return "%d %s" % (class_id, coords)


def _iter_annotated(folder, rels, report):
    for rel in rels:
        result = read_annotation(folder, rel)
        if not result.found:
            continue
        if result.error:
            report.errors.append(result.error)
            continue
        if not (result.width and result.height):
            report.errors.append("%s has no image size - open and save it again" % rel)
            continue
        yield rel, result


def export_yolo(folder, rels, project, task=TASK_SEGMENT, segments=CURVE_SEGMENTS,
                include_background=True) -> ExportReport:
    task = TASK_OBB if task == TASK_OBB else TASK_SEGMENT
    out_dir = os.path.join(str(folder), EXPORT_YOLO_OBB if task == TASK_OBB else EXPORT_YOLO_SEG)
    report = ExportReport(out_dir)
    labels_dir = os.path.join(out_dir, "labels")
    if not ensure_dir(labels_dir):
        report.errors.append("could not create %s" % labels_dir)
        return report
    ids = project.id_map()

    for rel, result in _iter_annotated(folder, rels, report):
        lines = []
        for shape in result.shapes:
            if shape.label not in ids:
                report.skipped_labels += 1
                report.unknown.add(shape.label or "(no class)")
                continue
            lines.append(yolo_line(shape, ids[shape.label], result.width, result.height,
                                   task, segments))
        if not lines and (result.shapes or not include_background):
            continue
        target = os.path.join(labels_dir, os.path.splitext(rel)[0] + ".txt")
        if not ensure_dir(os.path.dirname(target)):
            report.errors.append("could not create the folder for %s" % rel)
            continue
        ok, error = write_text_atomic(target, "".join(line + "\n" for line in lines),
                                      keep_backup=False)
        if not ok:
            report.errors.append("%s: %s" % (rel, error))
            continue
        report.images += 1
        report.files += 1
        report.shapes += len(lines)

    names = project.ordered_names_for_yolo()
    write_text_atomic(os.path.join(out_dir, "classes.txt"),
                      "".join(name + "\n" for name in names), keep_backup=False)
    yaml = ["# %s %s - YOLO %s export, %s" % (APP_NAME, APP_VERSION,
                                               "OBB" if task == TASK_OBB else "segmentation",
                                               datetime.now().isoformat(timespec="seconds")),
            "# Labels mirror the image folder under labels/.  Place the images",
            "# beside them as images/ (same sub-folders) before training.",
            "path: %s" % json.dumps(out_dir),
            "train: images",
            "val: images",
            "task: %s" % ("obb" if task == TASK_OBB else "segment"),
            "names:"]
    yaml += ["  %d: %s" % (index, json.dumps(name)) for index, name in enumerate(names)]
    ok, error = write_text_atomic(os.path.join(out_dir, "data.yaml"), "\n".join(yaml) + "\n",
                                  keep_backup=False)
    if ok:
        report.files += 2
    else:
        report.errors.append("data.yaml: %s" % error)
    return report


def export_coco(folder, rels, project, segments=CURVE_SEGMENTS,
                include_background=True) -> ExportReport:
    out_dir = os.path.join(str(folder), EXPORT_COCO)
    report = ExportReport(out_dir)
    if not ensure_dir(out_dir):
        report.errors.append("could not create %s" % out_dir)
        return report
    ids = project.id_map()
    images, annotations = [], []

    for rel, result in _iter_annotated(folder, rels, report):
        known = [s for s in result.shapes if s.label in ids]
        for shape in result.shapes:
            if shape.label not in ids:
                report.skipped_labels += 1
                report.unknown.add(shape.label or "(no class)")
        if not known and (result.shapes or not include_background):
            continue
        image_id = len(images) + 1
        images.append({"id": image_id, "file_name": rel.replace(os.sep, "/"),
                       "width": result.width, "height": result.height,
                       "verified": result.verified})
        for shape in known:
            outline = shape.outline(segments)
            x0, y0, x1, y1 = shape.bounds
            annotations.append({
                "id": len(annotations) + 1,
                "image_id": image_id,
                "category_id": ids[shape.label] + 1,
                "segmentation": [[round(v, 2) for point in outline for v in point]],
                "bbox": [round(x0, 2), round(y0, 2), round(x1 - x0, 2), round(y1 - y0, 2)],
                "area": round(shape.area, 2),
                "iscrowd": 0,
                "annotex_shape": shape.to_dict(),
            })
        report.images += 1
        report.shapes += len(known)

    categories = [{"id": entry.id + 1, "name": entry.name, "supercategory": "object",
                   "class_id": entry.id}
                  for entry in project.sorted_classes()]
    payload = {
        "info": {"description": "%s export" % APP_NAME, "version": APP_VERSION,
                 "date_created": datetime.now().isoformat(timespec="seconds")},
        "images": images,
        "annotations": annotations,
        "categories": categories,
    }
    ok, error = write_text_atomic(os.path.join(out_dir, "annotations.json"),
                                  json.dumps(payload, indent=2, ensure_ascii=False),
                                  verify_json=True, keep_backup=True)
    if ok:
        report.files += 1
    else:
        report.errors.append("annotations.json: %s" % error)
    return report
