"""Offline self-test: the whole persistence, export and geometry path.

Runs without a display and without Qt, so a machine can be verified before
anyone tries to annotate on it:  python run.py --selftest
"""

from __future__ import annotations

import csv as _csv
import json
import os
import shutil
import sys
import tempfile

from .config import (FULL_VIEW, JSON_NAME, MAP_NAME, SITE_VIEW, XLSX_NAME,
                     APP_NAME, APP_VERSION)
from .core import exporters, geometry as geo, importers, report
from .core.history import History
from .core.io_safe import FolderLock, atomic_write
from .core.model import Shape, polys_to_shapes
from .core.push import push_json, validate_url
from .core.session import DraftStore, SessionTimer
from .core.store import HAS_XLSX, AnnotationStore


def run_selftest(verbose: bool = True) -> int:
    FAILS = []
    def check(label, got, want):
        if got != want:
            FAILS.append("%s\n     got : %r\n     want: %r" % (label, got, want))
    def ok(label, value):
        if not value:
            FAILS.append("%s (was falsy)" % label)

    # ── naming ────────────────────────────────────────────────────
    check("roi_key cam3", geo.make_roi_key("UBBRAP0226_cam3_2026-08-14.jpg"), "UBBRAP0226_3")
    check("roi_key bare", geo.make_roi_key("UBBRAP0104_9_178.jpg"), "UBBRAP0104_9")
    check("roi_key padded", geo.make_roi_key("UBBRKA0020_cam03_x.png"), "UBBRKA0020_3")
    check("roi_key none", geo.make_roi_key("SOLO.jpg"), "SOLO")

    # ── cells ─────────────────────────────────────────────────────
    check("fmt", geo.fmt_polys([[(232,163),(494,280),(455,336)]]), "[[[232, 163], [494, 280], [455, 336]]]")
    check("cell is json", json.loads(geo.fmt_polys([[(1,2),(3,4),(5,6)]])), [[[1,2],[3,4],[5,6]]])
    check("parse v2", geo.parse_multi_polys("[[[1, 2], [3, 4], [5, 6]]]"), [[(1,2),(3,4),(5,6)]])
    check("parse v1", geo.parse_multi_polys("[(392, 296), (494, 280), (455, 336)]"), [[(392,296),(494,280),(455,336)]])
    check("parse bare", geo.parse_multi_polys("(1, 2), (3, 4), (5, 6)"), [[(1,2),(3,4),(5,6)]])
    for junk in ("", "  ", "nan", "None", "[]", "garbage", "[(1,", "#REF!"):
        check("junk %r" % junk, geo.parse_multi_polys(junk), [])
    orig = [[(232,163),(494,280),(455,336)], [(10,20),(30,40),(50,60)]]
    check("round trip", geo.parse_multi_polys(geo.fmt_polys(orig)), orig)

    # ── shape_types cell ──────────────────────────────────────────
    check("shape fmt", geo.fmt_shape_types(["rect","circle"]), '["rect", "circle"]')
    check("shape parse", geo.parse_shape_types('["rect", "circle"]', 2), ["rect","circle"])
    check("shape pad", geo.parse_shape_types("", 3), ["polygon"]*3)
    check("shape junk", geo.parse_shape_types("nonsense", 2), ["polygon"]*2)
    check("shape clamp", geo.parse_shape_types('["rect","bogus"]', 2), ["rect","polygon"])

    # ── geometry ──────────────────────────────────────────────────
    check("area", geo.polygon_area([(0,0),(10,0),(10,10),(0,10)]), 100.0)
    check("collapsed", geo.polygon_area([(0,0),(5,5),(10,10)]), 0.0)
    check("dedupe", geo.dedupe_consecutive([(1,1),(1,1),(2,2),(3,3),(1,1)]), [(1,1),(2,2),(3,3)])
    ok("self intersect", geo.poly_self_intersects([(0,0),(10,10),(10,0),(0,10)]))
    ok("square clean", not geo.poly_self_intersects([(0,0),(10,0),(10,10),(0,10)]))
    good,_ = geo.validate_polygon([(0,0),(10,0),(10,10),(0,10)], 100, 100)
    check("validate keeps", good, [(0,0),(10,0),(10,10),(0,10)])
    bad,_ = geo.validate_polygon([(0,0),(5,5),(10,10)], 100, 100)
    check("validate rejects line", bad, None)
    clamped,_ = geo.validate_polygon([(-50,-50),(500,0),(500,500)], 100, 100)
    ok("clamped in bounds", clamped and all(0<=x<100 and 0<=y<100 for x,y in clamped))
    check("normalise", geo.polys_to_norm([[(50,25)]], 100, 100), [[(0.5,0.25)]])
    check("normalise 2dp", geo.polys_to_norm([[(1,3)]], 7, 9), [[(0.14,0.33)]])
    check("natural sort", sorted(["img10.jpg","img2.jpg","img1.jpg"], key=geo.natural_key),
          ["img1.jpg","img2.jpg","img10.jpg"])

    # ── shapes ────────────────────────────────────────────────────
    r = Shape.rect(10, 20, 110, 220)
    check("rect points", r.points, [(10,20),(110,20),(110,220),(10,220)])
    check("rect kind", r.kind, "rect")
    ok("rect recognised", geo.is_axis_aligned_rect(r.points))
    c = Shape.circle(100, 100, 50)
    check("circle kind", c.kind, "circle")
    ok("circle point count", 32 <= len(c.points) <= 64)
    ok("circle round", abs(geo.polygon_area(c.points) - 3.14159*2500) < 200)
    moved = r.translated(5, 5, 500, 500)
    check("translate", moved.points[0], (15,25))
    check("translate keeps kind", moved.kind, "rect")
    back = polys_to_shapes([r.points], ["rect"])
    check("reload keeps rect", back[0].kind, "rect")
    legacy = polys_to_shapes([r.points], None)
    check("legacy box detected as rect", legacy[0].kind, "rect")
    poly = polys_to_shapes([[(0,0),(10,3),(4,9)]], None)
    check("legacy triangle stays polygon", poly[0].kind, "polygon")
    resized = c.resized_box(0, 0, 40, 40, 500, 500)
    ok("circle resize stays circle", resized.kind == "circle" and len(resized.points) > 8)
    check("simplify", len(geo.simplify_polygon([(0,0),(1,0),(2,0),(3,0),(3,3),(0,3)], 0.5)), 4)

    # ── history ───────────────────────────────────────────────────
    h = History()
    h.reset([])
    h.push("draw", [r])
    h.push("draw 2", [r, c])
    ok("can undo", h.can_undo)
    check("undo label", h.undo_label(), "draw 2")
    label, snap = h.undo()
    check("undo restores", len(snap), 1)
    ok("can redo", h.can_redo)
    _l, snap2 = h.redo()
    check("redo restores", len(snap2), 2)

    # ── store round trip ──────────────────────────────────────────
    tmp = tempfile.mkdtemp(prefix="roi_studio_test_")
    try:
        store = AnnotationStore(); store.bind(tmp)
        store.add(AnnotationStore.make_row(
            "UBBRAP0006_cam3_16-00.jpg", "roi",
            [[(27,39),(64,34),(74,99)]], [[(0.27,0.39),(0.64,0.34),(0.74,0.99)]],
            "", 100, 100, ["polygon"]))
        store.add(AnnotationStore.make_row(          # same camera, must MERGE
            "UBBRAP0006_cam3_18-00.jpg", "roi",
            [[(10,10),(20,10),(20,20),(10,20)]], [[(0.1,0.1),(0.2,0.1),(0.2,0.2),(0.1,0.2)]],
            "", 100, 100, ["rect"]))
        store.add(AnnotationStore.make_row(
            "UBBRAP0347_cam3_16-00.jpg", "no_roi", [], [], "nothing here", 100, 100))
        store.add(AnnotationStore.make_row(
            "UBBRAP0016_cam3_16-00.jpg", "roi",
            [[(34,36),(76,37),(99,99)]], [[(0.34,0.36),(0.76,0.37),(0.99,0.99)]],
            "", 100, 100, ["circle"]))

        rep = store.flush(FULL_VIEW)
        ok("flush ok (%s)" % "; ".join(rep.errors), rep.ok)
        for name in (JSON_NAME, MAP_NAME, XLSX_NAME):
            ok("wrote %s" % name, os.path.isfile(os.path.join(tmp, name)))
        check("no csv written", os.path.isfile(os.path.join(tmp, "roi_annotations.csv")), False)

        with open(os.path.join(tmp, MAP_NAME)) as fh:
            roi_map = json.load(fh)
        check("map keys", sorted(roi_map), ["UBBRAP0006_3","UBBRAP0016_3"])
        check("merged count", len(roi_map["UBBRAP0006_3"]), 2)
        check("requested shape", roi_map["UBBRAP0016_3"], [[[0.34,0.36],[0.76,0.37],[0.99,0.99]]])
        with open(os.path.join(tmp, JSON_NAME)) as fh:
            full = json.load(fh)
        check("no_roi", full["no_roi"], ["UBBRAP0347_3"])
        check("roi_count", full["roi_count"], 2)
        check("total polys", full["total_polygons"], 3)
        check("shapes recorded", full["shapes"]["UBBRAP0006_3"], ["polygon","rect"])

        store2 = AnnotationStore(); store2.bind(tmp); store2.load()
        check("reload rows", len(store2.rows), len(store.rows))
        _f2, map2, _w = store2.build_json()
        check("reload map identical", map2, roi_map)
        row = [r for r in store2.rows if r["image_name"].startswith("UBBRAP0006_cam3_18")][0]
        check("reload keeps shape_types", geo.parse_shape_types(row["shape_types"], 1), ["rect"])

        compact = AnnotationStore.project(store.rows[0], SITE_VIEW)
        check("site view coord", compact["roi_coordinate"], store.rows[0]["normalized_coords"])
        ok("site view has shape_types", "shape_types" in compact)
        check("no temp files", [f for f in os.listdir(tmp) if ".tmp" in f], [])

        # the rolling backup must be readable even though openpyxl
        # validates file names rather than content
        if HAS_XLSX:
            bak = os.path.join(tmp, XLSX_NAME) + ".bak"
            shutil.copyfile(os.path.join(tmp, XLSX_NAME), bak)
            from_bak = importers.read_annotation_file(bak)
            ok("bak readable (%s)" % "; ".join(from_bak.errors), from_bak.ok)
            check("bak row count", len(from_bak.rows), len(store.rows))

        # ── legacy csv upgrade ────────────────────────────────
        legacy_dir = os.path.join(tmp, "legacy"); os.makedirs(legacy_dir)
        with open(os.path.join(legacy_dir, "roi_annotations.csv"), "w",
                  encoding="utf-8-sig", newline="") as fh:
            w = _csv.writer(fh, quoting=_csv.QUOTE_ALL)
            w.writerow(["image_name","site_id","cam_number","pixel_coords",
                        "normalized_coords","total_polygons","row_type","comment"])
            w.writerow(["UBBRAP0091_cam3_16-34.jpg","UBBRAP0091","cam3",
                        "[(232, 163), (494, 280), (455, 336)]",
                        "[(0.3295, 0.4389), (0.5, 0.5), (0.1, 0.9)]","1","roi",""])
        ls = AnnotationStore(); ls.bind(legacy_dir); ls.load()
        check("legacy rows", len(ls.rows), 1)
        check("legacy roi_key", ls.rows[0]["roi_key"], "UBBRAP0091_3")
        check("legacy cell upgraded", ls.rows[0]["pixel_coords"], "[[[232, 163], [494, 280], [455, 336]]]")
        check("legacy shape_types filled", geo.parse_shape_types(ls.rows[0]["shape_types"], 1), ["polygon"])
        _lf, lmap, _lw = ls.build_json()
        check("legacy re-rounded", lmap, {"UBBRAP0091_3": [[[0.33,0.44],[0.5,0.5],[0.1,0.9]]]})

        # ── exporters ─────────────────────────────────────────
        er = exporters.run_exports(["coco","yolo","voc","masks"], store.rows, tmp)
        ok("exports ok (%s)" % "; ".join(er.errors), er.ok)
        with open(os.path.join(tmp, "export_coco", "annotations.json")) as fh:
            coco = json.load(fh)
        check("coco images", len(coco["images"]), 3)
        check("coco annotations", len(coco["annotations"]), 3)
        check("coco shape_type", coco["annotations"][1]["shape_type"], "rect")
        ok("yolo label written", os.path.isfile(os.path.join(tmp,"export_yolo","labels","UBBRAP0006_cam3_16-00.txt")))
        ok("voc xml written", os.path.isfile(os.path.join(tmp,"export_voc","UBBRAP0006_cam3_16-00.xml")))
        ok("mask written", os.path.isfile(os.path.join(tmp,"export_masks","UBBRAP0006_cam3_16-00_mask.png")))
        subset = exporters.filter_rows(store.rows, roi_keys={"UBBRAP0016_3"})
        check("filter subset", len(subset), 1)
        check("distinct sites", exporters.distinct(store.rows, "site_id"),
              ["UBBRAP0006","UBBRAP0016","UBBRAP0347"])

        # ── import + merge ────────────────────────────────────
        imported = importers.read_annotation_file(os.path.join(tmp, XLSX_NAME))
        ok("import ok (%s)" % "; ".join(imported.errors), imported.ok)
        check("imported rows", len(imported.rows), 4)
        from_map = importers.read_annotation_file(os.path.join(tmp, MAP_NAME))
        check("import map rows", len(from_map.rows), 2)
        a = [AnnotationStore.make_row("x_cam1_a.jpg","roi",[[(0,0),(9,0),(9,9)]],
                                      [[(0,0),(0.9,0),(0.9,0.9)]],"",10,10,["polygon"])]
        b = [AnnotationStore.make_row("x_cam1_a.jpg","roi",[[(1,1),(8,1),(8,8)]],
                                      [[(0.1,0.1),(0.8,0.1),(0.8,0.8)]],"",10,10,["rect"])]
        merged = importers.merge_rows([a,b], ["ann1","ann2"], "union")
        check("merge conflicts", len(merged.conflicts), 1)
        check("merge union polys", len(geo.parse_multi_polys(merged.rows[0]["pixel_coords"])), 2)
        newest = importers.merge_rows([a,b], ["ann1","ann2"], "newest")
        check("merge newest", geo.parse_multi_polys(newest.rows[0]["pixel_coords"]), [[(1,1),(8,1),(8,8)]])

        # ── report ────────────────────────────────────────────
        names = ["UBBRAP0006_cam3_16-00.jpg","UBBRAP0006_cam3_18-00.jpg",
                 "UBBRAP0347_cam3_16-00.jpg","UBBRAP0016_cam3_16-00.jpg",
                 "UBBRAP0999_cam1_00-00.jpg"]
        rr, stats = report.write_report(store.rows, tmp, names,
                                        {"elapsed":"12m","images":4,"per_hour":20.0,"shapes":3})
        ok("report ok (%s)" % "; ".join(rr.errors), rr.ok)
        page = open(os.path.join(tmp, "roi_report.html"), encoding="utf-8").read()
        ok("report has html", page.startswith("<!doctype html>") and "</html>" in page)
        ok("report no unescaped format", "%(" not in page and "%s" not in page)
        check("stats images", stats["totals"]["images"], 5)
        check("stats annotated", stats["totals"]["annotated"], 3)
        check("stats no_roi", stats["totals"]["no_roi"], 1)
        check("stats remaining", stats["totals"]["remaining"], 1)
        check("stats missing cameras", stats["totals"]["cameras_missing"], ["UBBRAP0999_1"])
        check("stats kinds", stats["totals"]["kinds"]["rect"], 1)
        cr, _s = report.write_coverage_json(store.rows, tmp, names)
        ok("coverage json ok", cr.ok)

        # ── drafts ────────────────────────────────────────────
        draft = DraftStore(); draft.bind(tmp)
        draft.save("UBBRAP0006_cam3_16-00.jpg", [r], "half done", force=True)
        pending = draft.pending()
        ok("draft recovered", pending and pending["image_name"] == "UBBRAP0006_cam3_16-00.jpg")
        check("draft shape kind", pending["shapes"][0]["kind"], "rect")
        draft.clear()
        check("draft cleared", draft.pending(), None)

        # ── lock ──────────────────────────────────────────────
        la, lb = FolderLock(), FolderLock()
        got, _m = la.acquire(tmp); ok("first lock", got)
        got_b, _m = lb.acquire(tmp); ok("same-pid lock is stale", got_b)
        lb.release()
        ok("lock file removed", not os.path.isfile(os.path.join(tmp, ".roi_studio.lock")))

        # ── atomic write refuses a bad payload ────────────────
        target = os.path.join(tmp, "guard.json")
        open(target, "w").write('{"good": true}')
        def bad_write(t): open(t, "w").write("{not json")
        def verify(t): json.load(open(t))
        okw, err = atomic_write(target, bad_write, verify)
        check("bad write refused", okw, False)
        check("original intact", json.load(open(target)), {"good": True})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ── push ──────────────────────────────────────────────────────
    check("url rejects empty", validate_url("")[0], False)
    check("url rejects scheme", validate_url("ftp://x/y")[0], False)
    check("url accepts https", validate_url("https://example.com/hook")[0], True)
    res = push_json("", {})
    ok("push refuses unconfigured", not res.ok and "no endpoint" in res.message)
    calls = []
    res2 = push_json("https://127.0.0.1:9/none", {"a":1}, retries=1, sleep=calls.append)
    ok("push retried then failed", not res2.ok and res2.attempts == 2)

    # ── session timer ─────────────────────────────────────────────
    t = SessionTimer(); t.touch(); t.count_image(3)
    check("timer counted", (t.images_done, t.shapes_drawn), (1, 3))
    ok("timer text", t.elapsed_text().endswith("s") or "m" in t.elapsed_text())

    width = 66
    if verbose:
        print("=" * width)
    if FAILS:
        print("SELF TEST FAILED - %d problem(s)\n" % len(FAILS))
        for entry in FAILS:
            print("  x " + entry)
        print("=" * width)
        return 1
    if verbose:
        print("SELF TEST PASSED  (%s %s)" % (APP_NAME, APP_VERSION))
        print("Pillow=%s  openpyxl=%s  python=%s"
              % (report.HAS_PIL if hasattr(report, "HAS_PIL") else True,
                 HAS_XLSX, ".".join(str(p) for p in sys.version_info[:3])))
        print("=" * width)
    return 0


if __name__ == "__main__":
    sys.exit(run_selftest())
