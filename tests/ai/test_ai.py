"""The AI (Segment Anything) path, end to end, on any machine.

The real models are hundreds of megabytes, so this builds a stand-in with
the same interface (tests/ai/fake_sam.py) and drives everything around it:
the runtime that loads and feeds the ONNX graphs, the mask-to-shape maths,
the assistant that keeps the embedding off the interface thread, and both
labelling tools' AI tool.

    python tests/ai/test_ai.py

It skips - rather than fails - when numpy, onnxruntime or onnx are not
installed, because none of them is required to use Annotex.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SANDBOX = tempfile.mkdtemp(prefix="annotex_ai_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


def missing():
    absent = []
    for module in ("numpy", "onnxruntime", "onnx"):
        try:
            __import__(module)
        except Exception:
            absent.append(module)
    return absent


def main():
    absent = missing()
    if absent:
        print("SKIPPED - %s not installed (the AI tool is optional)"
              % ", ".join(absent))
        return 0

    import numpy as np
    from fake_sam import build_decoder, build_encoder, build_pair

    from annotex.core.ai import masks
    from annotex.core.ai.sam import SamError, SamRuntime, discover_models

    models = os.path.join(SANDBOX, "models")
    encoder, decoder = build_pair(models)

    # ── discovery ─────────────────────────────────────────
    pairs = discover_models([models])
    ok("an encoder and a decoder in a folder are paired up", len(pairs) == 1)
    ok("the pair is complete", pairs and pairs[0].complete)
    ok("the pair describes itself", bool(pairs and "MB" in pairs[0].describe()))

    # ── loading ───────────────────────────────────────────
    runtime = SamRuntime(encoder, decoder, "fake")
    runtime.load()
    ok("the model loads", runtime.loaded)
    ok("the long side is read off the graph", runtime.long_side == 64)
    ok("a target size keeps the aspect ratio", runtime.target_size(400, 200) == (64, 32))
    ok("a portrait target size keeps the aspect ratio",
       runtime.target_size(200, 400) == (32, 64))

    swapped = SamRuntime(decoder, encoder, "swapped")
    try:
        swapped.load()
        ok("encoder and decoder the wrong way round are refused", False)
    except SamError as exc:
        ok("encoder and decoder the wrong way round are refused", "swapped" in str(exc))
    try:
        SamRuntime(encoder, os.path.join(models, "nope.onnx")).load()
        ok("a missing file is refused with a sentence", False)
    except SamError as exc:
        ok("a missing file is refused with a sentence", "missing" in str(exc))

    corrupt = os.path.join(models, "corrupt.encoder.onnx")
    with open(corrupt, "wb") as handle:
        handle.write(b"this is not a model at all")
    try:
        SamRuntime(corrupt, decoder).load()
        ok("a file that is not a model is refused with a sentence", False)
    except SamError as exc:
        ok("a file that is not a model is refused with a sentence",
           "SAM ONNX export" in str(exc))

    # ── encode and predict ────────────────────────────────
    width, height = 400, 250
    target = runtime.target_size(width, height)
    rgb = np.full((target[1], target[0], 3), 255, dtype=np.uint8)
    embedding = runtime.encode(rgb, (height, width))
    ok("the embedding remembers the real image size", embedding.orig_size == (height, width))
    ok("the embedding carries the scale", abs(embedding.scale - 64.0 / 400.0) < 1e-6)

    mask, size, score = runtime.predict(embedding, points=[(100, 100, True)])
    ok("a click returns a mask the size of the image", size == (height, width))
    ok("the mask is boolean", mask.dtype == bool)
    ok("a score comes back", score > 0)
    ok("the mask becomes a box", masks.mask_to_box(mask) == (0.0, 0.0, 400.0, 250.0))

    empty, _size, _score = runtime.predict(embedding, points=[(10, 10, False)])
    ok("a negative-only prompt returns nothing", not empty.any())
    box_mask, _size, _score = runtime.predict(embedding, box=(10, 10, 200, 200))
    ok("a box prompt is accepted", box_mask.any())
    try:
        runtime.predict(embedding)
        ok("no prompt is refused", False)
    except SamError:
        ok("no prompt is refused", True)

    # ── a huge image is answered at a workable resolution ──
    big = runtime.encode(np.full((40, 64, 3), 255, np.uint8), (5000, 8000))
    mask, size, _score = runtime.predict(big, points=[(4000, 2500, True)], max_side=512)
    ok("a huge image is not answered pixel for pixel", size == (320, 512))

    # ── an export that declares its inputs in another order ──
    from fake_sam import build_decoder as _build_decoder
    reordered = _build_decoder(os.path.join(models, "odd.decoder.onnx"),
                               awkward_order=True)
    odd = SamRuntime(encoder, reordered, "odd order")
    odd.load()
    ok("a flag input is not mistaken for the mask input",
       odd._input("mask_input") == "mask_input"
       and odd._input("has_mask_input") == "has_mask_input")
    ok("and it still predicts",
       odd.predict(odd.encode(np.full((40, 64, 3), 255, np.uint8), (250, 400)),
                   points=[(20, 20, True)])[0].any())

    # ── an export with the normalisation inside it ────────
    uint8_encoder = build_encoder(os.path.join(models, "u8.encoder.onnx"),
                                  side=64, layout="nhwc", dtype="uint8")
    other = SamRuntime(uint8_encoder, decoder, "uint8")
    other.load()
    ok("a uint8 NHWC export is driven without normalising twice",
       other._plan["layout"] == "nhwc" and not other._plan["normalise"])
    ok("it predicts too",
       other.predict(other.encode(np.full((40, 64, 3), 255, np.uint8), (250, 400)),
                     points=[(5, 5, True)])[0].any())

    # ── the assistant, in a real window ───────────────────
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv[:1])
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    # The model chooser is built for real, but never waits for a person.
    from annotex.ui.dialogs.ai_dialog import AiModelDialog
    AiModelDialog.exec = lambda self: 0

    batch = os.path.join(SANDBOX, "batch")
    os.makedirs(batch, exist_ok=True)
    for index in range(2):
        picture = QImage(320, 240, QImage.Format.Format_RGB32)
        picture.fill(QColor("#ffffff"))
        picture.save(os.path.join(batch, "frame_%d.png" % index))

    from annotex.apps.labelimg.config import Settings as BoxSettings
    from annotex.apps.labelimg.core.class_store import ClassStore
    from annotex.apps.labelimg.ui.canvas import T_AI as BOX_AI, T_SELECT as BOX_SELECT
    from annotex.apps.labelimg.ui.window import LabelImgWindow

    store = ClassStore.load_or_create(os.path.join(SANDBOX, "classes.json"))
    window = LabelImgWindow(BoxSettings(os.path.join(SANDBOX, "labelimg.json")), app,
                            class_store=store)
    window.show()

    ok("the AI tool refuses to start without a model", not window.enter_ai_tool())
    window.open_folder(batch)
    window.register_class("person")
    window.set_current_class("person")
    window.ai().set_model(encoder, decoder, "fake")
    window.set_tool(BOX_AI)
    ok("the AI tool turns on", window.canvas.tool == BOX_AI)
    for _ in range(200):
        app.processEvents()
        if not window.ai().is_busy():
            break
    ok("the image is prepared in the background", not window.ai().is_busy())

    window.canvas._add_ai_point(QPointF(160, 120), positive=True)
    app.processEvents()
    ok("a click proposes a box", window.canvas.ai_preview is not None)
    ok("nothing is added until it is accepted", not window.canvas.boxes)
    window.accept_ai_preview()
    ok("Enter keeps the proposal", len(window.canvas.boxes) == 1)
    ok("the box takes the active class", window.canvas.boxes[0].label == "person")
    ok("the prompt is cleared for the next object", not window.canvas.has_ai_prompt())

    window.canvas._add_ai_point(QPointF(50, 50), positive=True)
    app.processEvents()
    window.canvas.clear_ai()
    ok("Escape drops the proposal", window.canvas.ai_preview is None)

    window.next_image()
    app.processEvents()
    ok("the AI tool stays on across images", window.canvas.tool == BOX_AI)
    for _ in range(200):
        app.processEvents()
        if not window.ai().is_busy():
            break
    window.canvas._add_ai_point(QPointF(100, 100), positive=True)
    app.processEvents()
    ok("the next image is prepared too", window.canvas.ai_preview is not None)

    # a model that cannot be opened must not take the tool down with it
    window.canvas.clear_ai()
    window.ai().set_model(os.path.join(models, "gone.onnx"),
                          os.path.join(models, "gone2.onnx"), "broken")
    ok("a missing model turns the tool off instead of crashing",
       not window.enter_ai_tool())

    # a model whose files exist but are rubbish fails in the background,
    # where it can only produce a message
    window.ai().set_model(corrupt, decoder, "corrupt")
    window._ai_offered = True
    window.enter_ai_tool()
    for _ in range(200):
        app.processEvents()
        if not window.ai().is_busy():
            break
    ok("a corrupt model says so instead of crashing",
       "not a model" in window.status_label.text().lower()
       or "could not be opened" in window.status_label.text().lower()
       or "sam onnx export" in window.status_label.text().lower())
    ok("and nothing is left half-prepared", not window.ai().is_busy())
    window.set_tool(BOX_SELECT)
    window.tool_close()

    # ── LabelImg Shapes proposes a polygon ────────────────
    from annotex.apps.shapes.config import Settings as ShapeSettings
    from annotex.apps.shapes.ui.canvas import T_AI as SHAPE_AI
    from annotex.apps.shapes.ui.window import ShapesWindow

    shapes = ShapesWindow(ShapeSettings(os.path.join(SANDBOX, "shapes.json")), app,
                          class_store=store)
    shapes.show()
    shapes.open_folder(batch)
    shapes.register_class("leaf")
    shapes.set_current_class("leaf")
    shapes.ai().set_model(encoder, decoder, "fake")
    shapes.set_tool(SHAPE_AI)
    for _ in range(200):
        app.processEvents()
        if not shapes.ai().is_busy():
            break
    shapes.canvas._add_ai_point(QPointF(160, 120), positive=True)
    app.processEvents()
    ok("a click proposes an outline", len(shapes.canvas.ai_preview or []) >= 3)
    shapes.accept_ai_preview()
    ok("the outline becomes a polygon",
       len(shapes.canvas.shapes) == 1 and shapes.canvas.shapes[0].kind == "polygon")
    ok("the polygon takes the active class", shapes.canvas.shapes[0].label == "leaf")
    shapes.tool_close()

    # ── the picture that reaches the model is the picture ──
    # A numpy array built straight on QImage.constBits() does not keep the
    # image alive: it read freed memory, which showed up as a model that
    # "worked" on garbage and, on bigger images, as a crash.
    import gc

    from annotex.ui.ai_assist import qimage_to_rgb, scaled_rgb
    wrong = []
    for size in ((1, 1), (2, 1), (3, 2), (7, 5), (33, 17), (640, 480), (1024, 768)):
        picture = QImage(size[0], size[1], QImage.Format.Format_RGB32)
        picture.fill(QColor(10, 20, 30))
        array = qimage_to_rgb(picture)
        del picture
        gc.collect()
        if array is None or array.shape != (size[1], size[0], 3) \
                or not (array[:, :, 0] == 10).all() or not (array[:, :, 1] == 20).all() \
                or not (array[:, :, 2] == 30).all():
            wrong.append("%dx%d" % size)
    ok("every image reaches the model unchanged, at any width", not wrong)
    if wrong:
        print("      wrong at: %s" % ", ".join(wrong))
    picture = QImage(300, 200, QImage.Format.Format_RGB32)
    picture.fill(QColor(7, 8, 9))
    small = scaled_rgb(picture, 64, 48)
    del picture
    gc.collect()
    ok("and so does a resized one",
       small is not None and small.shape == (48, 64, 3) and (small == [7, 8, 9]).all())
    ok("an empty image is refused rather than guessed at",
       qimage_to_rgb(QImage()) is None and scaled_rgb(None, 8, 8) is None)

    print("=" * 60)
    if FAILS:
        print("AI TESTS FAILED: %s" % ", ".join(FAILS))
        return 1
    print("AI TESTS PASSED")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        import shutil
        shutil.rmtree(SANDBOX, ignore_errors=True)
    sys.exit(code)
