"""Importing existing annotations, and merging several annotators' work.

Import accepts anything this application or its predecessor ever wrote - an
xlsx, a legacy csv, the full json or the bare roi_map json - and returns
canonical rows.  Merge is deliberately explicit about conflicts rather than
silently picking a winner.
"""

from __future__ import annotations

import csv
import json
import os

from . import geometry as geo
from .store import (HAS_XLSX, AnnotationStore, load_workbook_rows,
                    rows_to_dicts)

STRATEGIES = {
    "union": "Keep every ROI from every file (duplicates merged per image)",
    "newest": "On a conflict keep the file listed last",
    "most": "On a conflict keep whichever file has more ROIs",
    "skip": "On a conflict keep the first file and report the rest",
}


class ImportResult:
    def __init__(self):
        self.rows = []
        self.notes = []
        self.errors = []
        self.conflicts = []

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.errors:
            return "Import failed - " + "; ".join(self.errors[:2])
        text = "Imported %d row(s)" % len(self.rows)
        if self.conflicts:
            text += "  |  %d conflict(s)" % len(self.conflicts)
        if self.notes:
            text += "  |  " + "; ".join(self.notes[:2])
        return text


# ══════════════════════════════════════════════════════════════
# READING ONE FILE
# ══════════════════════════════════════════════════════════════
def read_annotation_file(path) -> ImportResult:
    """Detect the format from the extension and content, and canonicalise."""
    result = ImportResult()
    path = str(path)
    if not os.path.isfile(path):
        result.errors.append("no such file: %s" % os.path.basename(path))
        return result

    # A rolling backup is "<name>.xlsx.bak", so the real type is the
    # extension underneath the .bak suffix.
    stem = path[:-4] if path.lower().endswith(".bak") else path
    ext = os.path.splitext(stem)[1].lower()
    try:
        if ext in (".xlsx", ".xlsm"):
            raw = _read_xlsx(path)
        elif ext == ".csv":
            raw = _read_csv(path)
        elif ext == ".json":
            raw = _read_json(path, result)
        else:
            result.errors.append("unsupported file type '%s'" % (ext or "?"))
            return result
    except Exception as exc:
        result.errors.append(str(exc))
        return result

    rows = [AnnotationStore.canonicalize(r) for r in raw]
    result.rows = [r for r in rows if r["image_name"]]
    dropped = len(rows) - len(result.rows)
    if dropped:
        result.notes.append("skipped %d row(s) with no image name" % dropped)
    if not result.rows:
        result.notes.append("file contained no usable rows")
    return result


def _read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return [{k: ("" if v is None else v) for k, v in row.items()
                 if k is not None} for row in csv.DictReader(fh)]


def _read_xlsx(path):
    if not HAS_XLSX:
        raise RuntimeError("openpyxl is required to read .xlsx files")
    return rows_to_dicts(load_workbook_rows(path))


def _read_json(path, result):
    """Accept the full record, the bare map, or a plain list of rows."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]

    if not isinstance(data, dict):
        raise ValueError("unrecognised JSON structure")

    # full record written by this application
    if "rois" in data or "no_roi" in data:
        rows = []
        sources = data.get("sources", {}) if isinstance(data.get("sources"), dict) else {}
        shapes = data.get("shapes", {}) if isinstance(data.get("shapes"), dict) else {}
        for key, polys in (data.get("rois") or {}).items():
            name = _first_source(sources, key, key)
            rows.append(_row_from_norm(name, key, polys, shapes.get(key)))
        for key in (data.get("no_roi") or []):
            name = _first_source(sources, key, key)
            rows.append({"image_name": name, "roi_key": key,
                         "row_type": "no_roi", "comment": ""})
        result.notes.append("read the full JSON record")
        return rows

    # bare roi_map.json: {key: [[[x, y], ...], ...]}
    rows = []
    for key, polys in data.items():
        if isinstance(polys, list):
            rows.append(_row_from_norm(key, key, polys, None))
    if rows:
        result.notes.append("read a roi_map file - image names default to the roi_key")
    return rows


def _first_source(sources, key, default):
    names = sources.get(key)
    if isinstance(names, list) and names:
        return str(names[0])
    return default


def _row_from_norm(image_name, roi_key, polys, kinds):
    site_id, cam = geo.extract_site_cam(image_name)
    clean = geo._normalize_poly_structure(polys)
    return {
        "image_name": image_name,
        "roi_key": roi_key,
        "site_id": site_id,
        "cam_number": cam,
        "pixel_coords": "",
        "normalized_coords": geo.fmt_polys(clean),
        "total_polygons": len(clean),
        "image_width": 0,
        "image_height": 0,
        "row_type": "roi",
        "comment": "",
        "shape_types": geo.fmt_shape_types(kinds or []),
    }


# ══════════════════════════════════════════════════════════════
# MERGING SEVERAL FILES
# ══════════════════════════════════════════════════════════════
def merge_rows(row_sets, labels=None, strategy: str = "union") -> ImportResult:
    """Combine several annotators' rows into one canonical set.

    `row_sets` is a list of row lists, `labels` their display names.  Images
    that only one file mentions are always kept; images several files disagree
    about are resolved by `strategy` and recorded in `result.conflicts`.
    """
    result = ImportResult()
    labels = list(labels or [])
    while len(labels) < len(row_sets):
        labels.append("file %d" % (len(labels) + 1))
    if strategy not in STRATEGIES:
        strategy = "union"

    by_image = {}
    order = []
    for index, rows in enumerate(row_sets):
        for row in rows:
            name = row["image_name"]
            if name not in by_image:
                by_image[name] = []
                order.append(name)
            by_image[name].append((index, row))

    for name in order:
        entries = by_image[name]
        if len(entries) == 1:
            result.rows.append(entries[0][1])
            continue

        polysets = []
        for index, row in entries:
            polys = geo.parse_multi_polys(row.get("pixel_coords", "")) or \
                geo.parse_multi_polys(row.get("normalized_coords", ""))
            polysets.append((index, row, polys))

        identical = all(p[2] == polysets[0][2] for p in polysets)
        if identical:
            result.rows.append(polysets[0][1])
            continue

        result.conflicts.append({
            "image_name": name,
            "sources": [labels[i] for i, _r, _p in polysets],
            "counts": [len(p) for _i, _r, p in polysets],
        })
        result.rows.append(_resolve(name, polysets, strategy))

    result.notes.append("merged %d file(s) with the '%s' strategy"
                        % (len(row_sets), strategy))
    return result


def _resolve(name, polysets, strategy):
    if strategy == "newest":
        return polysets[-1][1]
    if strategy == "most":
        return max(polysets, key=lambda p: len(p[2]))[1]
    if strategy == "skip":
        return polysets[0][1]

    # union: concatenate every distinct polygon, in file order
    base = dict(polysets[0][1])
    merged, kinds = [], []
    for _i, row, polys in polysets:
        row_kinds = geo.parse_shape_types(row.get("shape_types", ""), len(polys))
        for j, poly in enumerate(polys):
            if poly not in merged:
                merged.append(poly)
                kinds.append(row_kinds[j] if j < len(row_kinds) else "polygon")

    width = max((int(r.get("image_width") or 0) for _i, r, _p in polysets), default=0)
    height = max((int(r.get("image_height") or 0) for _i, r, _p in polysets), default=0)
    pixel_source = any(geo.parse_multi_polys(r.get("pixel_coords", ""))
                       for _i, r, _p in polysets)

    base["total_polygons"] = len(merged)
    base["shape_types"] = geo.fmt_shape_types(kinds)
    base["image_width"] = width
    base["image_height"] = height
    if pixel_source:
        base["pixel_coords"] = geo.fmt_polys(merged)
        base["normalized_coords"] = geo.fmt_polys(
            geo.polys_to_norm(merged, width, height)) if width and height else ""
    else:
        base["pixel_coords"] = ""
        base["normalized_coords"] = geo.fmt_polys(merged)

    comments = [r.get("comment", "") for _i, r, _p in polysets if r.get("comment")]
    base["comment"] = " | ".join(dict.fromkeys(comments))
    return base


def import_and_merge(paths, strategy: str = "union") -> ImportResult:
    """Read several files and merge them in one call."""
    combined = ImportResult()
    row_sets, labels = [], []
    for path in paths:
        one = read_annotation_file(path)
        combined.notes.extend(one.notes)
        combined.errors.extend(one.errors)
        if one.rows:
            row_sets.append(one.rows)
            labels.append(os.path.basename(str(path)))
    if not row_sets:
        if not combined.errors:
            combined.errors.append("nothing to import")
        return combined
    if len(row_sets) == 1:
        combined.rows = row_sets[0]
        return combined

    merged = merge_rows(row_sets, labels, strategy)
    combined.rows = merged.rows
    combined.conflicts = merged.conflicts
    combined.notes.extend(merged.notes)
    return combined
