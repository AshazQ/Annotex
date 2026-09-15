"""Offline self-test for LabelImg Master: classes, boxes, the three formats,
backups, import, export and the report.

Runs without a display.  When the original labelImg-master folder sits beside
the suite (or LABELIMG_LEGACY points at it), every format is also written by
the ORIGINAL modules and compared byte for byte.

    python run.py --selftest
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import time

from .config import (APP_NAME, APP_VERSION, BACKUP_DIR, DELETED_DIR,
                     FORMAT_CREATEML, FORMAT_VOC, FORMAT_YOLO)
from .core import exporters, importers, report
from .core.annotations import (AnnotationFolder, apply_boxes, copy_to_copies,
                               move_to_deleted, pil_probe, scan_images)
from .core.class_store import (ClassStore, ClassStoreError, find_class_usage,
                               rename_class_in_annotations, validate_class_name)
from .core.formats.label_file import convert_points_to_bnd_box
from .core.model import Box, boxes_match, find_duplicates, iou

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def legacy_root():
    """The original labelImg-master folder, if it is around."""
    for candidate in (os.environ.get("LABELIMG_LEGACY", ""),
                      os.path.join(os.path.dirname(SUITE_ROOT), "labelImg-master")):
        if candidate and os.path.isfile(os.path.join(candidate, "libs",
                                                     "pascal_voc_io.py")):
            return candidate
    return ""


def _load_legacy(root):
    """Import the original writers without their Qt-dependent siblings."""
    if root not in sys.path:
        sys.path.insert(0, root)
    return (importlib.import_module("libs.pascal_voc_io"),
            importlib.import_module("libs.yolo_io"),
            importlib.import_module("libs.create_ml_io"))


def _make_image(path, size=(640, 480), mode="RGB"):
    from PIL import Image
    colour = 128 if mode == "L" else (70, 110, 150)
    Image.new(mode, size, colour).save(path)


def run_selftest(verbose: bool = True) -> int:
    FAILS = []
    NOTES = []

    def check(label, got, want):
        if got != want:
            FAILS.append("%s\n     got : %r\n     want: %r" % (label, got, want))

    def ok(label, value):
        if not value:
            FAILS.append("%s (was falsy)" % label)

    # ── class names & store ───────────────────────────────────────
    check("name trimmed", validate_class_name("  face_uncover "), "face_uncover")
    for bad in ("", "a/b", "_lead", "con", "x" * 65):
        try:
            validate_class_name(bad)
            FAILS.append("name %r should be rejected" % bad)
        except ClassStoreError:
            pass

    tmp = tempfile.mkdtemp(prefix="labelimg_selftest_")
    try:
        store = ClassStore(os.path.join(tmp, "store.json"))
        project = store.active_project()
        for name in ("person", "helmet", "face_uncover", "weapon"):
            project.add_class(name)
        before = project.id_map()
        project.remove_class(project.by_name("face_uncover").id)
        ok("ids never renumber", all(before[n] == i for n, i in project.id_map().items()))
        lines = project.ordered_names_for_yolo()
        check("classes.txt keeps holes", (lines[0], lines[3], lines[2][:10]),
              ("person", "weapon", "_reserved_"))
        pinned = project.add_class("fire", class_id=42)
        check("manual id", pinned.id, 42)
        check("next id past manual", project.add_class("smoke").id, 43)
        store.save()
        check("store reloads", ClassStore.load_or_create(store.path).id_map(),
              project.id_map())

        # ── boxes ─────────────────────────────────────────────────
        b = Box("person", 50, 40, 10, 20)
        check("box normalised", b.bounds, (10.0, 20.0, 50.0, 40.0))
        check("points order", b.points, [(10.0, 20.0), (50.0, 20.0),
                                         (50.0, 40.0), (10.0, 40.0)])
        check("translate clamps", Box("p", 0, 0, 100, 50).translated(600, 0, 640, 480).bounds,
              (540.0, 0.0, 640.0, 50.0))
        clean, _msgs = Box("p", -20, -20, 30, 30).validated(640, 480)
        check("validate clamps", clean.bounds, (0.0, 0.0, 30.0, 30.0))
        check("validate rejects sliver", Box("p", 5, 5, 6, 90).validated(640, 480)[0], None)
        check("validate rejects no class", Box("", 5, 5, 60, 90).validated(640, 480)[0], None)
        check("duplicates", find_duplicates([Box("a", 0, 0, 10, 10), Box("a", 1, 1, 11, 10),
                                             Box("b", 0, 0, 10, 10)]), [1])
        ok("iou", abs(iou(Box("a", 0, 0, 10, 10), Box("a", 5, 0, 15, 10)) - 1 / 3) < 1e-9)
        check("bnd clamp to 1", convert_points_to_bnd_box([(0, 0), (9.7, 0), (9.7, 5.2), (0, 5.2)]),
              (1, 1, 9, 5))

        # ── images and probes ─────────────────────────────────────
        batch = os.path.join(tmp, "batch")
        os.makedirs(os.path.join(batch, "sub"))
        os.makedirs(os.path.join(batch, DELETED_DIR))
        os.makedirs(os.path.join(batch, ".hidden"))
        _make_image(os.path.join(batch, "cam2.jpg"))
        _make_image(os.path.join(batch, "cam10.jpg"))
        _make_image(os.path.join(batch, "sub", "grey.png"), (320, 240), "L")
        _make_image(os.path.join(batch, "small.jpg"), (200, 100))
        _make_image(os.path.join(batch, DELETED_DIR, "gone.jpg"))
        _make_image(os.path.join(batch, ".hidden", "x.jpg"))
        rels = scan_images(batch)
        check("scan skips output + hidden, natural order", rels,
              ["cam2.jpg", "cam10.jpg", "small.jpg", os.path.join("sub", "grey.png")])
        check("probe rgb", pil_probe(os.path.join(batch, "cam2.jpg")), (480, 640, 3))
        check("probe grey depth", pil_probe(os.path.join(batch, "sub", "grey.png")), (240, 320, 1))

        boxes = [Box("person", 12, 30, 200.5, 310), Box("helmet", 0, 0, 64, 64, True),
                 Box("weapon", 500, 400, 640, 480)]
        class_list = project.ordered_names_for_yolo()
        id_map = project.id_map()
        shape = pil_probe(os.path.join(batch, "cam2.jpg"))

        folder = AnnotationFolder(batch)
        for fmt in (FORMAT_VOC, FORMAT_YOLO, FORMAT_CREATEML):
            ann = AnnotationFolder(batch, save_dir=os.path.join(tmp, "out_" + fmt))
            rep = ann.write("cam2.jpg", boxes, fmt, shape, verified=True,
                            class_list=class_list, class_id_map=id_map)
            ok("%s write (%s)" % (fmt, "; ".join(rep.errors)), rep.ok)
            back = ann.read("cam2.jpg", shape)
            check("%s found" % fmt, back.fmt, fmt)
            check("%s verified round trip" % fmt, back.verified, True)
            check("%s count" % fmt, len(back.boxes), 3)
            check("%s labels" % fmt, [x.label for x in back.boxes],
                  ["person", "helmet", "weapon"])
            if fmt == FORMAT_VOC:
                check("voc difficult kept", back.boxes[1].difficult, True)
                check("voc bounds", back.boxes[0].bounds, (12.0, 30.0, 200.0, 310.0))
            if fmt == FORMAT_YOLO:
                ok("yolo classes.txt", os.path.isfile(os.path.join(tmp, "out_" + fmt, "classes.txt")))
                with open(os.path.join(tmp, "out_" + fmt, "cam2.txt")) as handle:
                    first = handle.readline().split()[0]
                check("yolo uses stable id", int(first), id_map["person"])
            if fmt == FORMAT_CREATEML:
                check("createml difficult not invented", back.boxes[1].difficult, False)
            no_temp = [f for f in os.listdir(os.path.join(tmp, "out_" + fmt)) if ".tmp" in f]
            check("%s no temp files" % fmt, no_temp, [])

        # ── byte-for-byte against the original LabelImg writers ───
        root = legacy_root()
        if root:
            voc_mod, yolo_mod, cml_mod = _load_legacy(root)
            image_path = os.path.join(batch, "cam2.jpg")
            legacy_dir = os.path.join(tmp, "legacy")
            os.makedirs(legacy_dir)
            shapes = [x.to_writer_shape() for x in boxes]

            writer = voc_mod.PascalVocWriter("batch", "cam2.jpg", list(shape),
                                             local_img_path=image_path)
            writer.verified = True
            for s in shapes:
                bb = convert_points_to_bnd_box(s["points"])
                writer.add_bnd_box(bb[0], bb[1], bb[2], bb[3], s["label"], int(s["difficult"]))
            writer.save(target_file=os.path.join(legacy_dir, "cam2.xml"))

            writer = yolo_mod.YOLOWriter("batch", "cam2.jpg", list(shape),
                                         local_img_path=image_path)
            for s in shapes:
                bb = convert_points_to_bnd_box(s["points"])
                writer.add_bnd_box(bb[0], bb[1], bb[2], bb[3], s["label"], int(s["difficult"]))
            writer.save(class_list=class_list, target_file=os.path.join(legacy_dir, "cam2.txt"),
                        class_id_map=id_map)

            writer = cml_mod.CreateMLWriter("batch", "cam2.jpg", list(shape), shapes,
                                            os.path.join(legacy_dir, "cam2.json"),
                                            local_img_path=image_path)
            writer.verified = True
            writer.write()

            for fmt, name in ((FORMAT_VOC, "cam2.xml"), (FORMAT_YOLO, "cam2.txt"),
                              (FORMAT_YOLO, "classes.txt"), (FORMAT_CREATEML, "cam2.json")):
                with open(os.path.join(legacy_dir, name), "rb") as handle:
                    legacy_bytes = handle.read()
                with open(os.path.join(tmp, "out_" + fmt, name), "rb") as handle:
                    new_bytes = handle.read()
                check("byte-identical %s %s" % (fmt, name), new_bytes, legacy_bytes)
            NOTES.append("formats compared byte for byte with %s" % root)
        else:
            NOTES.append("original labelImg-master not found - byte comparison skipped")

        # ── backups, retirement, change detection ─────────────────
        rep = folder.write("cam2.jpg", boxes[:1], FORMAT_VOC, shape)
        ok("first write", rep.ok)
        rep = folder.write("cam2.jpg", boxes, FORMAT_VOC, shape)
        ok("backup kept", os.path.isfile(os.path.join(batch, BACKUP_DIR, "cam2.xml")))
        restored = folder.read_backup("cam2.jpg", shape)
        check("backup holds the previous version", len(restored.boxes), 1)
        rep = folder.write("cam2.jpg", boxes, FORMAT_YOLO, shape, class_list=class_list,
                           class_id_map=id_map)
        ok("format switch retires the xml", not os.path.isfile(os.path.join(batch, "cam2.xml")))
        check("find follows the new format", folder.find("cam2.jpg")[0], FORMAT_YOLO)
        ok("switch reported", any("moved" in w for w in rep.warnings))

        folder.read("cam2.jpg", shape)
        ok("no false change", not folder.changed_externally("cam2.jpg"))
        target = os.path.join(batch, "cam2.txt")
        stamp = os.path.getmtime(target) + 5
        os.utime(target, (stamp, stamp))
        ok("external change detected", folder.changed_externally("cam2.jpg"))
        folder.accept_external("cam2.jpg")
        ok("accepted change forgotten", not folder.changed_externally("cam2.jpg"))

        folder.write("cam2.jpg", boxes, FORMAT_YOLO, shape, verified=True,
                     class_list=class_list, class_id_map=id_map)
        check("yolo verified ledger", AnnotationFolder(batch).read("cam2.jpg", shape).verified, True)

        # a foreign JSON sharing an image's name is not an annotation
        with open(os.path.join(batch, "cam10.json"), "w") as handle:
            json.dump({"camera": "cam10"}, handle)
        check("foreign json ignored", folder.find("cam10.jpg"), ("", ""))

        # ── summaries & index ─────────────────────────────────────
        folder.write("cam10.jpg", [], FORMAT_VOC, shape)
        index = folder.build_index(rels)
        check("summary labels", index["cam2.jpg"].labels, ["person", "helmet", "weapon"])
        check("background status", index["cam10.jpg"].status, "background")
        check("todo is None", index["small.jpg"], None)

        # ── batch apply clamps to each image ──────────────────────
        done, skipped, notes = apply_boxes(folder, ["small.jpg"], boxes, FORMAT_VOC,
                                           pil_probe, class_list, id_map)
        check("apply done", (done, skipped), (["small.jpg"], []))
        small = folder.read("small.jpg", pil_probe(os.path.join(batch, "small.jpg")))
        ok("applied boxes fit the smaller image",
           all(x.x1 <= 200 and x.y1 <= 100 for x in small.boxes))
        check("box outside the small image dropped", len(small.boxes), 2)

        # ── import & merge ────────────────────────────────────────
        other = os.path.join(tmp, "other")
        other_io = AnnotationFolder(batch, save_dir=other)
        other_io.write("cam2.jpg", [Box("person", 12, 30, 200, 310), Box("fire", 300, 300, 360, 360)],
                       FORMAT_VOC, shape)
        other_io.write("sub/grey.png".replace("/", os.sep), [Box("smoke", 5, 5, 50, 50)],
                       FORMAT_VOC, pil_probe(os.path.join(batch, "sub", "grey.png")))
        incoming, _notes = importers.read_folder(other, batch, rels, pil_probe)
        check("import found", sorted(incoming), sorted(["cam2.jpg", os.path.join("sub", "grey.png")]))
        current = {"cam2.jpg": folder.read("cam2.jpg", shape).boxes}
        union = importers.merge(current, incoming, "union")
        check("union conflicts", len(union.conflicts), 1)
        check("union dedupes the shared person", [x.label for x in union.merged["cam2.jpg"]],
              ["person", "helmet", "weapon", "fire"])
        ok("new image taken", os.path.join("sub", "grey.png") in union.merged)
        check("keep strategy leaves conflicts", "cam2.jpg" in importers.merge(current, incoming, "keep").merged, False)
        check("incoming strategy", len(importers.merge(current, incoming, "incoming").merged["cam2.jpg"]), 2)
        check("most strategy keeps the larger", "cam2.jpg" in importers.merge(current, incoming, "most").merged, False)

        # ── COCO ──────────────────────────────────────────────────
        rep, counts = exporters.export_coco(folder, rels, project, pil_probe)
        ok("coco ok (%s)" % "; ".join(rep.errors), rep.ok)
        with open(os.path.join(batch, "export_coco", "annotations.json")) as handle:
            coco = json.load(handle)
        person = [c for c in coco["categories"] if c["name"] == "person"][0]
        check("coco id is class id + 1", person["id"], id_map["person"] + 1)
        check("coco images incl. background", counts["images"], 3)
        first = [a for a in coco["annotations"] if a["category_id"] == person["id"]][0]
        check("coco bbox", first["bbox"][2:], [188.0, 280.0])
        _rep, filtered = exporters.export_coco(folder, rels, project, pil_probe,
                                               class_filter={"helmet"},
                                               include_background=False)
        check("coco class filter", filtered["annotations"], 2)

        # ── report ────────────────────────────────────────────────
        stats = report.build_stats(folder.build_index(rels), rels, project, batch)
        totals = stats["totals"]
        check("report totals", (totals["images"], totals["labelled"], totals["background"],
                                totals["remaining"]), (4, 2, 1, 1))
        rr = report.write_report(stats, batch)
        ok("report written", rr.ok)
        with open(rr.written[0], encoding="utf-8") as handle:
            page = handle.read()
        ok("report is html", page.startswith("<!doctype html>") and "</html>" in page)
        ok("report escaped", "%(" not in page)
        ok("no annotation timings in the report",
           "images / hour" not in page and "active time" not in page)
        ok("summary json", report.write_summary_json(stats, batch).ok)

        # ── class rename rewrites VOC, leaves YOLO ────────────────
        folder.write("cam10.jpg", [Box("weapon", 1, 1, 30, 30)], FORMAT_VOC, shape)
        changed = rename_class_in_annotations([batch], "weapon", "weapon_v2")
        ok("rename touched the xml", any(p.endswith("cam10.xml") for p in changed))
        check("usage by id in yolo", [os.path.basename(p) for p in
                                      find_class_usage("x", [batch], class_id=id_map["person"])],
              ["cam2.txt"])

        # ── delete / copy image ───────────────────────────────────
        good, _msg, moved = move_to_deleted(folder, "cam10.jpg")
        ok("delete moved image and annotation", good and len(moved) == 2)
        ok("image gone from batch", "cam10.jpg" not in scan_images(batch))
        good, _dest = copy_to_copies(folder, "cam2.jpg")
        ok("copy image", good and os.path.isfile(os.path.join(batch, "copy_images", "cam2.jpg")))
        ok("copies are not scanned", "cam2.jpg" in scan_images(batch)
           and all("copy_images" not in r for r in scan_images(batch)))

        ok("boxes_match", boxes_match(boxes, [x.copy() for x in boxes]))

        # ── no activity log is written beside the images ──────────
        suffixes = set()
        for root, _dirs, files in os.walk(batch):
            suffixes.update(os.path.splitext(name)[1].lower() for name in files)
        check("no .csv or log file is written for the batch",
              sorted(e for e in suffixes if e in (".csv", ".log", ".jsonl")), [])

        # ── two images that would share one annotation file ───────
        shared = AnnotationFolder(batch, os.path.join(tmp, "labels"))
        check("no collision when every name is different",
              shared.stem_collisions(["a/one.jpg", "b/two.jpg"]), {})
        check("a repeated name across sub-folders is reported",
              sorted(shared.stem_collisions(["a/one.jpg", "b/one.png"])), ["one"])
        beside = AnnotationFolder(batch)
        check("saving beside the images can never collide",
              beside.stem_collisions(["a/one.jpg", "b/one.png"]), {})

        # ── the annotation clipboard ──────────────────────────────
        from annotex.core import clipboard
        clipboard.set_bridge(None, None)
        clipboard.clear()
        ok("an empty clipboard pastes nothing", clipboard.count() == 0)
        picked = Box("person", 10, 20, 110, 220)
        clipboard.copy(clipboard.KIND_BOXES,
                       [{"label": picked.label, "difficult": False,
                         "x0": picked.x0, "y0": picked.y0,
                         "x1": picked.x1, "y1": picked.y1,
                         "bounds": list(picked.bounds)}], (200, 400), "cam1.jpg")
        check("one box on the clipboard", clipboard.count(), 1)
        payload = clipboard.content()
        same, fx, fy = payload.scale_to((200, 400))
        check("the same size needs no scaling", (fx, fy), (1.0, 1.0))
        check("a copy keeps its coordinates", same[0]["bounds"], [10.0, 20.0, 110.0, 220.0])
        half, fx, fy = payload.scale_to((100, 200))
        check("a smaller image scales the copy", (fx, fy), (0.5, 0.5))
        check("the scaled box lands in the same place",
              half[0]["bounds"], [5.0, 10.0, 55.0, 110.0])
        check("what LabelImg Shapes copies still becomes a box",
              Box("", *clipboard.Payload.from_json(payload.to_json()).items[0]["bounds"]).describe(),
              "100 x 200")
        check("rubbish on the system clipboard is ignored",
              clipboard.Payload.from_json("<html>not ours</html>"), None)
        clipboard.clear()

        # ── the AI helper degrades politely ───────────────────────
        from annotex.core.ai import sam
        ok("the AI reports what it needs", isinstance(sam.missing_packages(), list))
        ok("no model is invented out of nothing",
           all(pair.complete for pair in sam.discover_models()))
        try:
            sam.SamRuntime("", "").load()
            ok("a runtime with no files refuses to load", False)
        except sam.SamError:
            ok("a runtime with no files refuses to load", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    width = 66
    if verbose:
        print("=" * width)
    if FAILS:
        print("SELF TEST FAILED - %d problem(s)  (%s)\n" % (len(FAILS), APP_NAME))
        for entry in FAILS:
            print("  x " + entry)
        print("=" * width)
        return 1
    if verbose:
        print("SELF TEST PASSED  (%s %s)" % (APP_NAME, APP_VERSION))
        for note in NOTES:
            print("  " + note)
        print("=" * width)
    return 0


if __name__ == "__main__":
    sys.exit(run_selftest())
