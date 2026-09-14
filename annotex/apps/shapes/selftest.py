"""LabelImg Shapes self-test: geometry, the shape model, files and exports.
No Qt, no display.

    python -m annotex.apps.shapes.selftest
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile

from .config import (ANNOTATION_SUFFIX, APP_NAME, APP_VERSION, EXPORT_COCO,
                     EXPORT_YOLO_OBB, EXPORT_YOLO_SEG, KIND_CIRCLE, KIND_ELLIPSE,
                     KIND_FREEHAND, KIND_OBB, KIND_POLYGON, TASK_OBB, TASK_SEGMENT)
from .core import geometry as geo
from .core.export import export_coco, export_yolo, yolo_line
from .core.model import Shape, shapes_match
from .core.store import (annotation_path, read_annotation, rename_label,
                         scan_images, shape_count, write_annotation)


def run_selftest(verbose: bool = True) -> int:
    FAILS = []

    def check(label, got, want):
        if got != want:
            FAILS.append("%s\n     got : %r\n     want: %r" % (label, got, want))

    def near(label, got, want, tolerance=1e-3):
        if abs(float(got) - float(want)) > tolerance:
            FAILS.append("%s\n     got : %r\n     want: %r" % (label, got, want))

    # ── geometry ──────────────────────────────────────────
    corners = geo.rect_corners(50, 40, 20, 10, 90)
    near("rotating a box 90° swaps its extent", geo.polygon_bounds(corners)[2]
         - geo.polygon_bounds(corners)[0], 10)
    rect = geo.min_area_rect(geo.rect_corners(100, 80, 60, 20, 30))
    near("min-area rect recovers the width", rect[2], 60, 1e-2)
    near("min-area rect recovers the height", rect[3], 20, 1e-2)
    near("min-area rect recovers the angle", rect[4], 30, 1e-2)
    near("min-area rect recovers the centre", rect[0], 100, 1e-2)
    check("hull drops the inside point",
          len(geo.convex_hull([(0, 0), (10, 0), (10, 10), (0, 10), (5, 5)])), 4)
    near("polygon area", geo.polygon_area([(0, 0), (4, 0), (4, 3), (0, 3)]), 12)
    check("point in polygon", geo.point_in_polygon(2, 1, [(0, 0), (4, 0), (4, 3), (0, 3)]), True)
    check("simplify keeps a straight run short",
          len(geo.simplify([(i, 0.0) for i in range(20)] + [(19, 10)], 0.5)), 3)
    near("normalised angle", geo.normalize_angle(270), -90)
    ex, ey = geo.ellipse_extents(40, 20, 90)
    near("ellipse extents follow the rotation", ex, 10)
    near("ellipse extents follow the rotation (y)", ey, 20)

    # ── model ─────────────────────────────────────────────
    samples = [
        Shape.polygon("cookies", [(10, 10), (60, 12), (40, 50)]),
        Shape.polygon("coke", [(70, 70), (90, 72), (95, 95), (72, 90)], KIND_FREEHAND),
        Shape.obb("human", 120, 80, 40, 90, 25),
        Shape.circle("coke", 200, 60, 18),
        Shape.ellipse("human", 250, 150, 60, 30, -40),
    ]
    for shape in samples:
        back = Shape.from_dict(json.loads(json.dumps(shape.to_dict())))
        check("%s survives a round trip" % shape.kind, back.to_dict(), shape.to_dict())
    obb = samples[2]
    check("oriented box contains its centre", obb.contains(120, 80), True)
    check("oriented box excludes a rotated-away corner", obb.contains(120 + 30, 80 - 40), False)
    near("oriented box area", obb.area, 3600)
    near("circle area", samples[3].area, math.pi * 18 * 18)
    check("circle is kept round", Shape(kind=KIND_CIRCLE, cx=5, cy=5, w=10, h=20).h, 20.0)
    check("ellipse contains its centre", samples[4].contains(250, 150), True)
    check("ellipse excludes a point past its axis", samples[4].contains(250 + 35, 150), False)
    grown = obb.with_local_box(-20, -45, 40, 45)
    near("resizing to the right keeps the left edge", grown.w, 60)
    near("resizing moves the centre along the box", grown.to_local(*obb.from_local(10, 0))[0], 0, 1e-6)
    turned = obb.rotated(20)
    near("rotating an oriented box changes its angle", turned.angle, 45)
    check("rotating a circle leaves it round", samples[3].rotated(33).angle, 0.0)
    moved = samples[0].translated(-50, 0, 400, 300)
    near("a move stops at the image edge", moved.bounds[0], 0)
    clean, _messages = Shape.polygon("x", [(0, 0), (1, 0), (0, 1)]).validated(100, 100)
    check("a sliver polygon is refused", clean, None)
    clean, messages = Shape.polygon("x", [(-10, 5), (50, 5), (50, 60)]).validated(100, 100)
    check("points outside are pulled in", (clean is not None, bool(messages)), (True, True))
    check("identical lists match", shapes_match(samples, [s.copy() for s in samples]), True)
    near("tightest rotated box of an ellipse is its axes", samples[4].rotated_box()[2], 60)

    # ── files ─────────────────────────────────────────────
    folder = tempfile.mkdtemp(prefix="shapes_selftest_")
    try:
        os.makedirs(os.path.join(folder, "sub"))
        for rel in ("a.jpg", "b.png", os.path.join("sub", "c.jpg"), "a10.jpg", "a2.jpg"):
            with open(os.path.join(folder, rel), "wb") as handle:
                handle.write(b"\xff\xd8\xff")
        os.makedirs(os.path.join(folder, EXPORT_COCO))
        with open(os.path.join(folder, EXPORT_COCO, "skip.jpg"), "wb") as handle:
            handle.write(b"\xff")
        check("scan is natural and skips exports",
              scan_images(folder), ["a.jpg", "a2.jpg", "a10.jpg", "b.png", os.path.join("sub", "c.jpg")])

        ok, error = write_annotation(folder, "a.jpg", samples, 400, 300, verified=True)
        check("write succeeds", (ok, error), (True, ""))
        check("file sits beside the image",
              os.path.isfile(os.path.join(folder, "a" + ANNOTATION_SUFFIX)), True)
        result = read_annotation(folder, "a.jpg")
        check("read finds the shapes", shapes_match(result.shapes, samples), True)
        check("read keeps size and verified", (result.width, result.height, result.verified),
              (400, 300, True))
        write_annotation(folder, "b.png", [], 400, 300)
        check("an empty file is a background image", shape_count(folder, "b.png"), 0)
        check("no file yet", shape_count(folder, "a2.jpg"), None)
        write_annotation(folder, os.path.join("sub", "c.jpg"),
                         [Shape.circle("ghost", 50, 50, 10)], 100, 100)
        with open(annotation_path(folder, "a2.jpg"), "w") as handle:
            handle.write("{broken")
        check("a broken file is reported, not raised", bool(read_annotation(folder, "a2.jpg").error), True)
        write_annotation(folder, "a.jpg", samples[:2], 400, 300)
        check("a rewrite keeps a hidden backup",
              os.path.isfile(os.path.join(folder, ".labelimg_shapes_backup", "a" + ANNOTATION_SUFFIX)), True)
        write_annotation(folder, "a.jpg", samples, 400, 300)

        # ── exports ───────────────────────────────────────
        from .core.store import scan_images as scan   # noqa: F401 - same helper the UI uses
        from annotex.apps.labelimg.core.class_store import ClassStore
        store = ClassStore(os.path.join(folder, "classes.json"))
        project = store.active_project()
        for name in ("cookies", "coke", "human"):
            project.add_class(name)
        rels = scan_images(folder)

        seg = export_yolo(folder, rels, project, TASK_SEGMENT, segments=16)
        lines = open(os.path.join(folder, EXPORT_YOLO_SEG, "labels", "a.txt")).read().splitlines()
        check("segmentation: a line per shape", len(lines), 5)
        check("segmentation: class ids are the permanent ids", [l.split()[0] for l in lines],
              ["0", "1", "2", "1", "2"])
        check("segmentation: a circle is sampled", len(lines[3].split()), 1 + 16 * 2)
        check("segmentation: an oriented box is four corners", len(lines[2].split()), 9)
        values = [float(v) for l in lines for v in l.split()[1:]]
        check("segmentation: every value normalised", all(0.0 <= v <= 1.0 for v in values), True)
        check("segmentation: background image gets an empty file",
              open(os.path.join(folder, EXPORT_YOLO_SEG, "labels", "b.txt")).read(), "")
        check("segmentation: unknown class is skipped and reported",
              (seg.skipped_labels, sorted(seg.unknown)), (1, ["ghost"]))
        check("segmentation: the broken file is a problem, not a crash", len(seg.errors), 1)
        check("segmentation: classes.txt in id order",
              open(os.path.join(folder, EXPORT_YOLO_SEG, "classes.txt")).read(), "cookies\ncoke\nhuman\n")
        check("segmentation: data.yaml names the task",
              "task: segment" in open(os.path.join(folder, EXPORT_YOLO_SEG, "data.yaml")).read(), True)

        export_yolo(folder, rels, project, TASK_OBB)
        obb_lines = open(os.path.join(folder, EXPORT_YOLO_OBB, "labels", "a.txt")).read().splitlines()
        check("obb: every shape is four corners", {len(l.split()) for l in obb_lines}, {9})
        expected = yolo_line(obb, 2, 400, 300, TASK_SEGMENT)
        check("obb: an oriented box exports exactly", obb_lines[2], expected)

        coco = export_coco(folder, rels, project, segments=12)
        payload = json.load(open(os.path.join(folder, EXPORT_COCO, "annotations.json")))
        # a.jpg has shapes, b.png is background; sub/c.jpg only has an unknown class
        check("coco: images with shapes or background", len(payload["images"]), 2)
        check("coco: annotations", len(payload["annotations"]), 5)
        check("coco: category ids are id + 1", [c["id"] for c in payload["categories"]], [1, 2, 3])
        first_circle = [a for a in payload["annotations"] if a["annotex_shape"]["kind"] == "circle"][0]
        check("coco: exact shape kept", first_circle["annotex_shape"]["r"], 18.0)
        check("coco: sampled segmentation", len(first_circle["segmentation"][0]), 24)
        check("coco: report counts", (coco.images, coco.shapes), (2, 5))

        check("rename rewrites the files", rename_label(folder, rels, "human", "person"), 1)
        check("renamed on disk", sorted({s.label for s in read_annotation(folder, "a.jpg").shapes}),
              ["coke", "cookies", "person"])
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    if verbose:
        print("=" * 66)
    if FAILS:
        print("SELF TEST FAILED - %d problem(s)  (%s %s)\n" % (len(FAILS), APP_NAME, APP_VERSION))
        for entry in FAILS:
            print("  x " + entry)
        print("=" * 66)
        return 1
    if verbose:
        print("SELF TEST PASSED  (%s %s)" % (APP_NAME, APP_VERSION))
        print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(run_selftest())
