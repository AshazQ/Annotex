"""Interop exports: COCO, YOLO, Pascal VOC and binary masks.

Every exporter takes canonical rows and writes into a subfolder of the batch,
so an export can never overwrite the batch's own outputs.  All of them go
through atomic_write and report rather than raise.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from xml.sax.saxutils import escape

from ..config import APP_VERSION
from . import geometry as geo
from .io_safe import WriteReport, atomic_write, ensure_dir, write_text_atomic

try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except Exception:                                    # pragma: no cover
    Image = ImageDraw = None
    HAS_PIL = False

CATEGORY_ID = 1
CATEGORY_NAME = "roi"


# ══════════════════════════════════════════════════════════════
def _roi_rows(rows):
    """Only rows that actually carry geometry."""
    out = []
    for row in rows:
        if row.get("row_type") != "roi":
            continue
        polys = geo.parse_multi_polys(row.get("pixel_coords", ""))
        if not polys:
            norm = geo.parse_multi_polys(row.get("normalized_coords", ""))
            w = int(row.get("image_width") or 0)
            h = int(row.get("image_height") or 0)
            if norm and w and h:
                polys = geo.norm_to_polys(norm, w, h)
        if polys:
            out.append((row, polys))
    return out


def _size_of(row, polys):
    """Image size from the row, falling back to the shapes' own extent."""
    w = int(row.get("image_width") or 0)
    h = int(row.get("image_height") or 0)
    if w and h:
        return w, h
    max_x = max((p[0] for poly in polys for p in poly), default=0)
    max_y = max((p[1] for poly in polys for p in poly), default=0)
    return int(max_x) + 1, int(max_y) + 1


def _bbox(poly):
    x0, y0, x1, y1 = geo.polygon_bounds(poly)
    return [float(x0), float(y0), float(x1 - x0), float(y1 - y0)]


# ══════════════════════════════════════════════════════════════
# COCO
# ══════════════════════════════════════════════════════════════
def export_coco(rows, folder, subdir="export_coco",
                filename="annotations.json") -> WriteReport:
    """One COCO instance-segmentation file for the whole batch."""
    report = WriteReport()
    out_dir = os.path.join(str(folder), subdir)
    if not ensure_dir(out_dir):
        report.errors.append("could not create %s" % subdir)
        return report

    images, annotations = [], []
    ann_id = 1
    for image_id, (row, polys) in enumerate(_roi_rows(rows), start=1):
        width, height = _size_of(row, polys)
        images.append({
            "id": image_id,
            "file_name": row.get("image_name", ""),
            "width": width,
            "height": height,
            "roi_key": row.get("roi_key", ""),
        })
        kinds = geo.parse_shape_types(row.get("shape_types", ""), len(polys))
        for i, poly in enumerate(polys):
            flat = [float(v) for pt in poly for v in pt]
            annotations.append({
                "id": ann_id,
                "image_id": image_id,
                "category_id": CATEGORY_ID,
                "segmentation": [flat],
                "bbox": _bbox(poly),
                "area": float(geo.polygon_area(poly)),
                "iscrowd": 0,
                "shape_type": kinds[i] if i < len(kinds) else "polygon",
            })
            ann_id += 1

    payload = {
        "info": {"description": "ROI Studio export",
                 "version": APP_VERSION,
                 "date_created": datetime.now().isoformat(timespec="seconds")},
        "licenses": [],
        "images": images,
        "annotations": annotations,
        "categories": [{"id": CATEGORY_ID, "name": CATEGORY_NAME,
                        "supercategory": "region"}],
    }
    path = os.path.join(out_dir, filename)
    ok, err = write_text_atomic(path, json.dumps(payload, indent=1),
                                verify_json=True, keep_backup=False)
    if ok:
        report.written.append(path)
        if not annotations:
            report.warnings.append("no ROI rows to export")
    else:
        report.errors.append("coco: %s" % err)
    return report


# ══════════════════════════════════════════════════════════════
# YOLO  (segmentation format)
# ══════════════════════════════════════════════════════════════
def export_yolo(rows, folder, subdir="export_yolo") -> WriteReport:
    """One .txt of normalised polygons per image, plus a dataset stub."""
    report = WriteReport()
    out_dir = os.path.join(str(folder), subdir)
    labels_dir = os.path.join(out_dir, "labels")
    if not ensure_dir(labels_dir):
        report.errors.append("could not create %s" % subdir)
        return report

    written = 0
    for row, polys in _roi_rows(rows):
        width, height = _size_of(row, polys)
        norm = geo.polys_to_norm(polys, width, height, ndigits=6)
        lines = []
        for poly in norm:
            if len(poly) < 3:
                continue
            coords = " ".join("%.6f %.6f" % (geo.clamp(x, 0.0, 1.0),
                                             geo.clamp(y, 0.0, 1.0))
                              for x, y in poly)
            lines.append("0 " + coords)
        if not lines:
            continue
        stem = os.path.splitext(row.get("image_name", ""))[0] or "image"
        path = os.path.join(labels_dir, stem + ".txt")
        ok, err = write_text_atomic(path, "\n".join(lines) + "\n",
                                    keep_backup=False)
        if ok:
            written += 1
        else:
            report.errors.append("%s: %s" % (os.path.basename(path), err))

    stub = os.path.join(out_dir, "data.yaml")
    ok, err = write_text_atomic(
        stub,
        "# ROI Studio export\n"
        "path: .\ntrain: images\nval: images\n\nnames:\n  0: %s\n" % CATEGORY_NAME,
        keep_backup=False)
    if ok:
        report.written.append(stub)
    report.written.append(labels_dir)
    if not written:
        report.warnings.append("no ROI rows to export")
    return report


# ══════════════════════════════════════════════════════════════
# PASCAL VOC
# ══════════════════════════════════════════════════════════════
def export_voc(rows, folder, subdir="export_voc") -> WriteReport:
    """One XML per image.

    VOC describes axis-aligned boxes, so each polygon is written as its
    bounding box and the exact points are kept in a custom <polygon> child
    for anything that can use them."""
    report = WriteReport()
    out_dir = os.path.join(str(folder), subdir)
    if not ensure_dir(out_dir):
        report.errors.append("could not create %s" % subdir)
        return report

    written = 0
    for row, polys in _roi_rows(rows):
        width, height = _size_of(row, polys)
        name = row.get("image_name", "")
        parts = ["<annotation>",
                 "  <folder>%s</folder>" % escape(os.path.basename(str(folder))),
                 "  <filename>%s</filename>" % escape(name),
                 "  <source><database>ROI Studio</database></source>",
                 "  <size><width>%d</width><height>%d</height>"
                 "<depth>3</depth></size>" % (width, height),
                 "  <segmented>1</segmented>"]
        kinds = geo.parse_shape_types(row.get("shape_types", ""), len(polys))
        for i, poly in enumerate(polys):
            x0, y0, x1, y1 = geo.polygon_bounds(poly)
            pts = " ".join("%d,%d" % (int(p[0]), int(p[1])) for p in poly)
            parts.extend([
                "  <object>",
                "    <name>%s</name>" % CATEGORY_NAME,
                "    <shape_type>%s</shape_type>"
                % escape(kinds[i] if i < len(kinds) else "polygon"),
                "    <pose>Unspecified</pose><truncated>0</truncated>"
                "<difficult>0</difficult>",
                "    <bndbox><xmin>%d</xmin><ymin>%d</ymin>"
                "<xmax>%d</xmax><ymax>%d</ymax></bndbox>"
                % (int(x0), int(y0), int(x1), int(y1)),
                "    <polygon>%s</polygon>" % pts,
                "  </object>"])
        parts.append("</annotation>")

        stem = os.path.splitext(name)[0] or "image"
        path = os.path.join(out_dir, stem + ".xml")
        ok, err = write_text_atomic(path, "\n".join(parts) + "\n",
                                    keep_backup=False)
        if ok:
            written += 1
        else:
            report.errors.append("%s: %s" % (os.path.basename(path), err))

    report.written.append(out_dir)
    if not written:
        report.warnings.append("no ROI rows to export")
    return report


# ══════════════════════════════════════════════════════════════
# BINARY MASKS
# ══════════════════════════════════════════════════════════════
def export_masks(rows, folder, subdir="export_masks",
                 fill=255, background=0) -> WriteReport:
    """One 8-bit PNG per annotated image, ROIs filled white."""
    report = WriteReport()
    if not HAS_PIL:
        report.errors.append("Pillow is required for mask export")
        return report
    out_dir = os.path.join(str(folder), subdir)
    if not ensure_dir(out_dir):
        report.errors.append("could not create %s" % subdir)
        return report

    written = 0
    for row, polys in _roi_rows(rows):
        width, height = _size_of(row, polys)
        stem = os.path.splitext(row.get("image_name", ""))[0] or "image"
        path = os.path.join(out_dir, stem + "_mask.png")

        def write(tmp, polys=polys, width=width, height=height):
            mask = Image.new("L", (max(1, width), max(1, height)), background)
            drw = ImageDraw.Draw(mask)
            for poly in polys:
                if len(poly) >= 3:
                    drw.polygon([(int(p[0]), int(p[1])) for p in poly], fill=fill)
            mask.save(tmp, format="PNG")

        def verify(tmp):
            with Image.open(tmp) as im:
                im.verify()

        ok, err = atomic_write(path, write, verify, keep_backup=False)
        if ok:
            written += 1
        else:
            report.errors.append("%s: %s" % (os.path.basename(path), err))

    report.written.append(out_dir)
    if not written:
        report.warnings.append("no ROI rows to export")
    return report


# ══════════════════════════════════════════════════════════════
# FILTERING
# ══════════════════════════════════════════════════════════════
def filter_rows(rows, sites=None, cams=None, roi_keys=None, names=None,
                row_types=None):
    """Narrow the row set for a partial export.

    Every argument is optional; a None or empty collection means "no filter
    on this field", so the default is the whole batch."""
    def keep(row):
        if row_types and row.get("row_type") not in row_types:
            return False
        if sites and row.get("site_id") not in sites:
            return False
        if cams and row.get("cam_number") not in cams:
            return False
        if roi_keys and row.get("roi_key") not in roi_keys:
            return False
        if names and row.get("image_name") not in names:
            return False
        return True

    return [r for r in rows if keep(r)]


def distinct(rows, field):
    seen = []
    for row in rows:
        value = str(row.get(field, "") or "")
        if value and value not in seen:
            seen.append(value)
    return sorted(seen, key=geo.natural_key)


# ══════════════════════════════════════════════════════════════
EXPORTERS = {
    "coco": ("COCO instance segmentation (annotations.json)", export_coco),
    "yolo": ("YOLO segmentation labels (one .txt per image)", export_yolo),
    "voc": ("Pascal VOC XML (one file per image)", export_voc),
    "masks": ("Binary mask PNGs (one per image)", export_masks),
}


def run_exports(kinds, rows, folder) -> WriteReport:
    """Run several exporters and merge their reports."""
    combined = WriteReport()
    for kind in kinds:
        entry = EXPORTERS.get(kind)
        if not entry:
            combined.warnings.append("unknown export '%s'" % kind)
            continue
        try:
            combined.merge(entry[1](rows, folder))
        except Exception as exc:                     # pragma: no cover
            combined.errors.append("%s: %s" % (kind, exc))
    return combined
