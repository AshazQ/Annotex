"""Offline self-test for the image tools: conversion, sorting, AI sorting.

    python run.py --selftest
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime

from PIL import Image

from . import ai, convert, sorter
from .common import expand_inputs, render_pattern, validate_pattern


def _exif_photo(path):
    image = Image.new("RGB", (400, 200), (200, 30, 30))
    exif = Image.Exif()
    exif[274] = 6                     # rotate 90° clockwise to display
    exif[271] = "TestCam"
    image.save(path, exif=exif.tobytes(), quality=95)


def _onnx_models(folder):
    """A colour classifier and a colour 'detector', built from scratch."""
    import numpy as np
    from onnx import TensorProto, helper, numpy_helper

    weights = numpy_helper.from_array(np.array([[6, -2], [-2, 6], [0, 0]], dtype=np.float32), "W")
    image_in = helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 32, 32])

    def build(nodes, output, initialisers, name):
        graph = helper.make_graph(nodes, name, [image_in], [output], initialisers)
        model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
        model.ir_version = 8
        helper.set_model_props(model, {"names": "{0: 'red', 1: 'green'}"})
        path = os.path.join(folder, name + ".onnx")
        with open(path, "wb") as handle:
            handle.write(model.SerializeToString())
        return path

    classifier = build(
        [helper.make_node("ReduceMean", ["images"], ["mean"], axes=[2, 3], keepdims=0),
         helper.make_node("MatMul", ["mean", "W"], ["logits"]),
         helper.make_node("Softmax", ["logits"], ["probs"], axis=1)],
        helper.make_tensor_value_info("probs", TensorProto.FLOAT, [1, 2]), [weights], "classifier")
    boxes = numpy_helper.from_array(np.array([[16, 16, 32, 32]], dtype=np.float32), "boxes")
    shape = numpy_helper.from_array(np.array([1, 6, 1], dtype=np.int64), "shape")
    detector = build(
        [helper.make_node("ReduceMean", ["images"], ["mean"], axes=[2, 3], keepdims=0),
         helper.make_node("MatMul", ["mean", "W"], ["logits"]),
         helper.make_node("Sigmoid", ["logits"], ["scores"]),
         helper.make_node("Concat", ["boxes", "scores"], ["row"], axis=1),
         helper.make_node("Reshape", ["row", "shape"], ["output0"])],
        helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 6, 1]),
        [weights, boxes, shape], "detector")
    return classifier, detector


def run_selftest(verbose: bool = True) -> int:
    FAILS, NOTES = [], []

    def check(label, got, want):
        if got != want:
            FAILS.append("%s\n     got : %r\n     want: %r" % (label, got, want))

    def ok(label, value):
        if not value:
            FAILS.append("%s (was falsy)" % label)

    # ── name patterns ─────────────────────────────────────────────
    check("pattern ok", validate_pattern("{parent}_{n:05}"), None)
    ok("unknown field refused", validate_pattern("{camera}"))
    ok("constant name refused", validate_pattern("photo"))
    ok("path separator refused", validate_pattern("{name}/x"))
    ok("malformed refused", validate_pattern("{n:zz}"))
    check("render", render_pattern("{parent}_{n:03}", "a", 7, "site", "jpg"), "site_007")

    tmp = tempfile.mkdtemp(prefix="annotex_images_selftest_")
    try:
        src = os.path.join(tmp, "src")
        os.makedirs(os.path.join(src, "sub"))
        rgba = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
        rgba.paste((255, 0, 0, 255), (50, 0, 100, 50))
        rgba.save(os.path.join(src, "rgba.png"))
        _exif_photo(os.path.join(src, "photo.jpg"))
        Image.new("L", (64, 64), 90).save(os.path.join(src, "sub", "grey.png"))
        Image.new("CMYK", (50, 50), (0, 255, 255, 0)).save(os.path.join(src, "cmyk.jpg"))
        frames = [Image.new("P", (30, 30), i * 40) for i in range(2)]
        frames[0].save(os.path.join(src, "anim.gif"), save_all=True, append_images=frames[1:])

        items = expand_inputs([src])
        check("expand inputs", len(items), 5)

        # ── convert ───────────────────────────────────────────────
        options = convert.ImageOptions(target="jpg", resize="max", max_side=100)
        planned = convert.plan(items, options)
        by_name = {os.path.basename(s): d for s, d in planned}
        ok("sub-folders kept", by_name["grey.png"].endswith(os.path.join("converted", "sub", "grey.jpg")))
        summary = convert.run(None, planned, options)
        check("convert summary", summary, "Converted 5 image(s)")
        with Image.open(by_name["rgba.png"]) as image:
            check("transparency flattened on white", image.getpixel((5, 5)), (255, 255, 255))
            check("size kept (never upscale)", image.size, (100, 50))
        with Image.open(by_name["photo.jpg"]) as image:
            check("EXIF rotation applied and resized", image.size, (50, 100))
            ok("EXIF stripped", 271 not in image.getexif())
        with Image.open(by_name["cmyk.jpg"]) as image:
            check("CMYK stays JPEG-safe", image.mode in ("CMYK", "RGB"), True)

        keep = convert.ImageOptions(target="keep", strip_metadata=False,
                                    pattern="{parent}_{n:03}", start_number=5)
        planned = convert.plan(items, keep, os.path.join(tmp, "kept"))
        names = sorted(os.path.basename(d) for _s, d in planned)
        check("keep format + pattern", names,
              ["src_005.png", "src_006.jpg", "src_007.jpg", "src_008.png", "sub_009.png"])
        convert.run(None, planned, keep)
        photo_out = [d for s, d in planned if s.endswith("photo.jpg")][0]
        with Image.open(photo_out) as image:
            check("EXIF kept when asked", image.getexif().get(271), "TestCam")
            check("not rotated when EXIF kept", image.size, (400, 200))
        again = convert.plan(items, keep, os.path.join(tmp, "kept"))
        ok("existing outputs are never overwritten",
           all(os.path.basename(d).count("_") == 2 for _s, d in again))

        for target in ("png", "webp", "bmp", "tiff"):
            opts = convert.ImageOptions(target=target, resize="percent", percent=50,
                                        webp_lossless=True, png_level=9)
            planned = convert.plan(items, opts, os.path.join(tmp, target))
            check("%s summary" % target, convert.run(None, planned, opts), "Converted 5 image(s)")
        with Image.open(os.path.join(tmp, "bmp", "rgba.bmp")) as image:
            check("bmp flattened", image.mode, "RGB")
        exact = convert.ImageOptions(target="png", resize="exact", width=40, height=40,
                                     keep_aspect=False, never_upscale=False)
        check("exact size", convert.new_size((100, 50), exact), (40, 40))
        fit = convert.ImageOptions(resize="exact", width=40, height=40)
        check("fit inside", convert.new_size((100, 50), fit), (40, 20))

        # ── sorting by rule ───────────────────────────────────────
        pool = os.path.join(tmp, "pool")
        os.makedirs(pool)
        for name, size in (("SITE1_cam1_001.jpg", (40, 30)), ("SITE1_cam2_002.jpg", (30, 40)),
                           ("SOLO.jpg", (40, 40))):
            path = os.path.join(pool, name)
            Image.new("RGB", size, (10, 120, 200)).save(path)
            stamp = datetime(2025, 3, 14, 9, 30).timestamp()
            os.utime(path, (stamp, stamp))
        images = sorted(os.path.join(pool, n) for n in os.listdir(pool))

        groups, _errors = sorter.preview(images, sorter.RuleCategoriser("name_tokens", tokens=2))
        check("token rule", {k: len(v) for k, v in groups.items()},
              {"SITE1_cam1": 1, "SITE1_cam2": 1, "_unmatched": 1})
        groups, _errors = sorter.preview(images, sorter.RuleCategoriser("name_regex", regex=r"cam(\d+)"))
        check("regex rule", sorted(groups), ["1", "2", "_unmatched"])
        groups, _errors = sorter.preview(images, sorter.RuleCategoriser("date", granularity="month"))
        check("date rule (file date)", sorted(groups), ["2025-03"])
        groups, _errors = sorter.preview(images, sorter.RuleCategoriser("orientation"))
        check("orientation rule", sorted(groups), ["landscape", "portrait", "square"])
        groups, _errors = sorter.preview(images, sorter.RuleCategoriser("resolution"))
        check("resolution rule", sorted(groups), ["30x40", "40x30", "40x40"])
        try:
            sorter.RuleCategoriser("name_regex", regex="(")
            FAILS.append("a broken regex should be refused")
        except ValueError:
            pass

        output = sorter.default_output(pool)
        check("default output", os.path.basename(output), "pool_sorted")
        summary, counts, run_id = sorter.run_sort(None, images,
                                                  sorter.RuleCategoriser("orientation"),
                                                  output, "rules")
        check("sort counts", counts, {"landscape": 1, "portrait": 1, "square": 1})
        ok("originals untouched", all(os.path.isfile(p) for p in images))
        ok("copies made", os.path.isfile(os.path.join(output, "square", "SOLO.jpg")))
        check("log rows", len(sorter.read_log(output)), 3)
        check("runs listed", [(r[1], r[2]) for r in sorter.runs(output)], [("rules", 3)])
        check("undo run", sorter.undo_run(output, run_id), 3)
        ok("undo removed the copies and empty folders", not os.path.isdir(os.path.join(output, "square")))
        check("run no longer live", sorter.runs(output)[0][2], 0)

        session = sorter.SortSession(output, "manual")
        first = session.copy(images[0], "keep")
        session.copy(images[0], "keep")
        check("same file twice is copied once", sorted(os.listdir(os.path.join(output, "keep"))),
              [os.path.basename(images[0])])
        session.copy(images[1], "keep")
        undone = session.undo_last()
        ok("undo last", undone and undone[0] == images[1] and os.path.isfile(first))
        ok("unsafe folder names cleaned", sorter.safe_folder_name('a/b:c') == "a_b_c")

        # annotation-based rules
        from annotex.apps.labelimg.core.annotations import AnnotationFolder
        from annotex.apps.labelimg.core.model import Box
        folder_io = AnnotationFolder(pool)
        folder_io.write("SITE1_cam1_001.jpg", [Box("person", 1, 1, 20, 20)], "PascalVOC", (30, 40, 3))
        folder_io.write("SITE1_cam2_002.jpg", [], "PascalVOC", (40, 30, 3))
        groups, _errors = sorter.preview(images, sorter.RuleCategoriser("labelimg"))
        check("labelimg rule", {k: [os.path.basename(i) for i in v] for k, v in groups.items()},
              {"background": ["SITE1_cam2_002.jpg"], "labelled": ["SITE1_cam1_001.jpg"],
               "unannotated": ["SOLO.jpg"]})
        from annotex.apps.roi.core.store import AnnotationStore
        store = AnnotationStore()
        store.bind(pool)
        store.add(AnnotationStore.make_row("SITE1_cam1_001.jpg", "roi", [[(1, 1), (20, 1), (20, 20)]],
                                           [[(0.1, 0.1), (0.5, 0.1), (0.5, 0.5)]], "", 40, 30, ["polygon"]))
        store.add(AnnotationStore.make_row("SOLO.jpg", "no_roi", [], [], "", 40, 40))
        store.flush()
        groups, _errors = sorter.preview(images, sorter.RuleCategoriser("roi"))
        check("roi rule", {k: len(v) for k, v in groups.items()},
              {"no_roi": 1, "roi": 1, "unannotated": 1})

        # ── AI ────────────────────────────────────────────────────
        try:
            import onnx  # noqa: F401
            have_onnx = True
        except Exception:
            have_onnx = False
        if not ai.available():
            NOTES.append("onnxruntime not installed - AI sorting not tested")
        elif not have_onnx:
            NOTES.append("onnx not installed - AI sorting not tested (needed only to build test models)")
        else:
            classifier_path, detector_path = _onnx_models(tmp)
            shots = {}
            for name, colour in (("red", (255, 0, 0)), ("green", (0, 255, 0)),
                                 ("grey", (128, 128, 128)), ("black", (0, 0, 0)),
                                 ("yellow", (255, 255, 0))):
                shots[name] = os.path.join(tmp, name + ".png")
                Image.new("RGB", (32, 32), colour).save(shots[name])

            model = ai.OnnxModel(classifier_path)
            check("classifier detected", (model.kind, model.labels, model.width), ("classifier", ["red", "green"], 32))
            prediction = model.predict(shots["red"])
            label, confidence = prediction.top()
            ok("classifier: red (%s %.3f)" % (label, confidence), label == "red" and confidence > 0.99)
            check("classifier folder", ai.categorise(prediction, 0.8)[0], ["red"])
            check("low confidence is unsure", ai.categorise(model.predict(shots["grey"]), 0.8)[0], ["_unsure"])
            check("mapping renames the folder", ai.categorise(prediction, 0.8, mapping={"red": "stop"})[0],
                  ["stop"])

            detector = ai.OnnxModel(detector_path, labels=["red", "green"])
            check("detector detected", detector.kind, "detector")
            check("detector finds red", ai.categorise(detector.predict(shots["red"]), 0.6)[0], ["red"])
            check("detector empty", ai.categorise(detector.predict(shots["black"]), 0.6)[0], ["_empty"])
            check("detector all classes", sorted(ai.categorise(detector.predict(shots["yellow"]), 0.6,
                                                               "all")[0]), ["green", "red"])
            ai_out = os.path.join(tmp, "ai_sorted")
            _summary, counts, _run = sorter.run_sort(
                None, [shots["red"], shots["green"], shots["grey"]],
                lambda path: ai.categorise(model.predict(path), 0.8), ai_out, "ai")
            check("AI sort counts", counts, {"_unsure": 1, "green": 1, "red": 1})
            try:
                ai.OnnxModel(os.path.join(tmp, "missing.onnx"))
                FAILS.append("a missing model should be refused")
            except ValueError:
                pass
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if verbose:
        print("=" * 66)
    if FAILS:
        print("SELF TEST FAILED - %d problem(s)  (Image tools)\n" % len(FAILS))
        for entry in FAILS:
            print("  x " + entry)
        print("=" * 66)
        return 1
    if verbose:
        print("SELF TEST PASSED  (Image tools)")
        for note in NOTES:
            print("  " + note)
        print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(run_selftest())
