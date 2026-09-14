"""COCO export.  No Qt.

One COCO object-detection file for the whole batch (or the classes you
pick), written into export_coco inside the batch so it can never overwrite
the annotations themselves.

Category ids are the Class Manager's permanent class ID plus one.  COCO
tooling commonly reserves 0 for background, and adding one keeps every id
tied to a class for the life of the project - the original ID is carried
alongside as `labelimg_id`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from annotex.core.io_safe import WriteReport, ensure_dir, write_text_atomic

from ..config import APP_VERSION, COCO_DIR


def export_coco(folder_io, rels, project, probe, class_filter=None,
                include_background=True, subdir=COCO_DIR,
                filename="annotations.json"):
    """Returns (WriteReport, counts)."""
    report = WriteReport()
    counts = {"images": 0, "annotations": 0, "skipped_labels": 0}
    out_dir = os.path.join(folder_io.image_folder, subdir)
    if not ensure_dir(out_dir):
        report.errors.append("could not create %s" % subdir)
        return report, counts

    wanted = set(class_filter or ())
    classes = project.sorted_classes() if project is not None else []
    by_name = {entry.name: entry for entry in classes}

    images, annotations, unknown = [], [], set()
    for rel in rels:
        fmt, path = folder_io.find(rel)
        if not fmt:
            continue
        shape = probe(folder_io.image_path(rel))
        if not shape:
            report.warnings.append("%s could not be read" % rel)
            continue
        result = folder_io.read_path(path, fmt, rel, shape)
        boxes = [b for b in result.boxes if not wanted or b.label in wanted]
        if not boxes and (result.boxes or not include_background):
            continue

        image_id = len(images) + 1
        images.append({"id": image_id,
                       "file_name": str(rel).replace(os.sep, "/"),
                       "width": int(shape[1]), "height": int(shape[0]),
                       "verified": bool(result.verified)})
        for box in boxes:
            entry = by_name.get(box.label)
            if entry is None:
                unknown.add(box.label)
                counts["skipped_labels"] += 1
                continue
            annotations.append({
                "id": len(annotations) + 1,
                "image_id": image_id,
                "category_id": entry.id + 1,
                "bbox": [round(box.x0, 2), round(box.y0, 2),
                         round(box.width, 2), round(box.height, 2)],
                "area": round(box.area, 2),
                "iscrowd": 0,
                "difficult": int(box.difficult),
            })

    categories = [{"id": entry.id + 1, "name": entry.name,
                   "supercategory": "object", "labelimg_id": entry.id,
                   "deprecated": not entry.active}
                  for entry in classes if not wanted or entry.name in wanted]
    payload = {
        "info": {"description": "LabelImg Master export",
                 "version": APP_VERSION,
                 "date_created": datetime.now().isoformat(timespec="seconds"),
                 "category_ids": "LabelImg class ID + 1"},
        "licenses": [],
        "images": images,
        "annotations": annotations,
        "categories": categories,
    }
    path = os.path.join(out_dir, filename)
    ok, err = write_text_atomic(path, json.dumps(payload, indent=1),
                                verify_json=True, keep_backup=False)
    if ok:
        report.written.append(path)
    else:
        report.errors.append("coco: %s" % err)
    if unknown:
        report.warnings.append("%d box(es) skipped - class not in the project: %s"
                               % (counts["skipped_labels"],
                                  ", ".join(sorted(unknown)[:4])))
    counts["images"] = len(images)
    counts["annotations"] = len(annotations)
    return report, counts
