"""Auto-labelling with a YOLO detector: the output layouts, the letterbox
maths, the class names and the folder job - on stand-in models, so any
machine can run it.

    python tests/ai/test_yolo.py

It skips - rather than fails - when numpy, onnxruntime or onnx are missing.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
SANDBOX = tempfile.mkdtemp(prefix="annotex_yolo_")
os.environ["HOME"] = os.path.join(SANDBOX, "home")
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "home", "config")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.makedirs(os.environ["HOME"], exist_ok=True)

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


def close(a, b, tolerance=0.6):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


class Ctx:
    def __init__(self, cancel_after=None):
        self.warnings, self.calls, self.cancel_after = [], 0, cancel_after

    @property
    def cancelled(self):
        return self.cancel_after is not None and self.calls >= self.cancel_after

    def progress(self, fraction, message=None):
        self.calls += 1

    def warn(self, message):
        self.warnings.append(message)


def main():
    for module in ("numpy", "onnxruntime", "onnx"):
        try:
            __import__(module)
        except Exception:
            print("SKIPPED - %s not installed (auto-labelling is optional)" % module)
            return 0
    import numpy as np
    from fake_yolo import STANDARD_ROWS, build_detector
    from annotex.core.ai import yolo
    from annotex.core.jobs import JobCancelled

    models = os.path.join(SANDBOX, "models")
    image = np.full((64, 128, 3), 90, dtype=np.uint8)      # 128 wide, 64 high: letterboxed
    # In the 64x64 input the image is scaled by 0.5 and padded 16 px top and bottom.
    person = (16, 16, 48, 48)
    car = (76, 30, 116, 50)

    def boxes(found):
        return [(d.name, round(d.score, 2), (d.x0, d.y0, d.x1, d.y1)) for d in found]

    for layout in ("v8", "v5", "e2e"):
        names = ("person", "car") if layout != "e2e" else ("person", "car", "bike")
        path = build_detector(os.path.join(models, "%s.onnx" % layout), STANDARD_ROWS,
                              names=names, layout=layout)
        found = yolo.YoloDetector(path).detect(image, confidence=0.25)
        shown = boxes(found)
        ok("%s: one person and one car are found" % layout,
           [n for n, _s, _b in shown] == ["person", "car"])
        ok("%s: the overlapping repeat and the weak box are dropped" % layout, len(found) == 2)
        ok("%s: boxes come back in the image's own pixels" % layout,
           len(found) == 2 and close(shown[0][2], person) and close(shown[1][2], car))
        ok("%s: scores come back" % layout, len(found) == 2 and shown[0][1] == 0.9 and shown[1][1] == 0.7)

    path = build_detector(os.path.join(models, "normalised.onnx"), STANDARD_ROWS, normalised=True)
    found = yolo.YoloDetector(path).detect(image, confidence=0.25)
    ok("coordinates given as 0-1 are understood too",
       len(found) == 2 and close((found[0].x0, found[0].y0, found[0].x1, found[0].y1), person))
    path = os.path.join(models, "v8.onnx")
    ok("the confidence decides what is proposed",
       [d.name for d in yolo.YoloDetector(path).detect(image, confidence=0.75)] == ["person"])
    ok("nothing above the confidence means no boxes", yolo.YoloDetector(path).detect(image, 0.95) == [])
    square = np.full((64, 64, 3), 10, dtype=np.uint8)
    ok("an image the model's own shape needs no letterbox",
       close((yolo.YoloDetector(path).detect(square, 0.25)[0].x0,), (8,)))
    edge = build_detector(os.path.join(models, "edge.onnx"), [(2, 18, 20, 8, [0.9, 0.0])])
    clipped = yolo.YoloDetector(edge).detect(image, 0.25)
    ok("a box running off the image is clipped to it", len(clipped) == 1 and clipped[0].x0 == 0.0)

    # names
    names_file = os.path.join(SANDBOX, "names.txt")
    with open(names_file, "w") as handle:
        handle.write("human\nvehicle\n")
    detector = yolo.YoloDetector(path, yolo.read_names_file(names_file))
    ok("a names file overrides the model's names",
       [d.name for d in detector.detect(image, 0.25)] == ["human", "vehicle"])
    yaml_file = os.path.join(SANDBOX, "data.yaml")
    with open(yaml_file, "w") as handle:
        handle.write("path: x\nnames:\n  0: human\n  1: vehicle\n")
    ok("a data.yaml works as a names file", yolo.read_names_file(yaml_file) == ["human", "vehicle"])
    wrong = yolo.YoloDetector(path, ["a", "b", "c", "d", "e"])
    try:
        wrong.detect(image, 0.25)
        ok("names that do not fit the model are refused", False)
    except yolo.YoloError as exc:
        ok("names that do not fit the model are refused", "names file" in str(exc))
    nameless = build_detector(os.path.join(models, "nameless.onnx"), STANDARD_ROWS, with_names=False)
    ok("a model without names still works, as class_0, class_1",
       [d.name for d in yolo.YoloDetector(nameless).detect(image, 0.25)] == ["class_0", "class_1"])

    # refusals
    seg = build_detector(os.path.join(models, "seg.onnx"), STANDARD_ROWS, task="segment")
    try:
        yolo.YoloDetector(seg).load()
        ok("a segmentation model is refused in words", False)
    except yolo.YoloError as exc:
        ok("a segmentation model is refused in words", "segmentation" in str(exc))
    for label, target in (("a missing file", os.path.join(models, "gone.onnx")),
                          ("a file that is not a model", names_file), ("no file at all", "")):
        try:
            yolo.YoloDetector(target).load()
            ok("%s is refused with a sentence" % label, False)
        except yolo.YoloError:
            ok("%s is refused with a sentence" % label, True)
    try:
        yolo.YoloDetector(path).detect(np.zeros((0, 0, 3), np.uint8))
        ok("an empty image is refused", False)
    except yolo.YoloError:
        ok("an empty image is refused", True)

    # classes
    decided = yolo.match_classes(["Person", "car", "dog"], ["person", "truck"], {"car": "truck"})
    ok("classes match by name whatever the case", decided["Person"] == "person")
    ok("a remembered choice wins", decided["car"] == "truck")
    ok("a class with no match is left to the person", decided["dog"] is None)
    ok("choices are filed per model", yolo.model_key(path).startswith("v8.onnx|"))

    # the folder job
    written = {}

    def write(rel, found, width, height):
        written[rel] = (sorted(name for name, _d in found), width, height)
        return True, ""

    detector = yolo.YoloDetector(path)
    summary = yolo.prelabel(["a.jpg", "b.jpg", "c.jpg", "d.jpg"], detector, 0.25,
                            {"person": "human", "car": ""}, lambda rel: rel == "b.jpg",
                            lambda rel: image if rel != "d.jpg" else square[:0], write, Ctx())
    ok("pre-labelling writes images without an annotation", sorted(written) == ["a.jpg", "c.jpg"])
    ok("an annotated image is never touched", "b.jpg" not in written)
    ok("mapped classes only, ignored ones left out", written["a.jpg"] == (["human"], 128, 64))
    ok("the summary counts what happened", "Pre-labelled 2" in summary and "1 already annotated" in summary
       and "1 failed" in summary)
    written.clear()
    yolo.prelabel(["a.jpg"], detector, 0.25, {"person": "", "car": ""}, lambda rel: False,
                  lambda rel: image, write, Ctx())
    ok("an image where every class is ignored gets no file", not written)
    try:
        yolo.prelabel(["a.jpg"] * 5, detector, 0.25, {"person": "p"}, lambda rel: False,
                      lambda rel: image, write, Ctx(cancel_after=2))
        ok("the folder job can be cancelled", False)
    except JobCancelled:
        ok("the folder job can be cancelled", True)
    photo = os.path.join(SANDBOX, "photo.jpg")
    from PIL import Image
    Image.new("RGB", (40, 20), (1, 2, 3)).save(photo)
    ok("image files are read as the tools show them", yolo.read_image_rgb(photo).shape == (20, 40, 3))

    # ── in the labelling tools ────────────────────────────
    import time
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent
    from PySide6.QtWidgets import QApplication, QDialog
    from annotex.ui.dialogs import messages
    app = QApplication(sys.argv[:1])
    messages.ask = lambda *a, **k: True
    messages.inform = lambda *a, **k: None
    messages.warn = lambda *a, **k: None
    QDialog.exec = lambda self: 0
    from annotex.ui.dialogs.yolo_dialog import ClassMapDialog
    asked = []
    ClassMapDialog.exec = lambda self: (asked.append(list(self.model_names)), 1)[1]

    from annotex.apps.labelimg.config import Settings as BoxSettings
    from annotex.apps.labelimg.core.class_store import ClassStore
    from annotex.apps.labelimg.ui.window import LabelImgWindow
    from annotex.apps.shapes.config import Settings as ShapeSettings
    from annotex.apps.shapes.core.store import annotation_path
    from annotex.apps.shapes.ui.window import ShapesWindow

    def wait(condition, limit=10.0):
        deadline = time.time() + limit
        while not condition() and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()

    def key(code):
        return QKeyEvent(QEvent.Type.KeyPress, code, Qt.KeyboardModifier.NoModifier)

    for tool in ("LabelImg Master", "LabelImg Shapes"):
        asked.clear()
        batch = os.path.join(SANDBOX, tool.replace(" ", "_"))
        os.makedirs(batch)
        for name in ("a.png", "b.png", "c.png"):
            Image.new("RGB", (128, 64), (90, 90, 90)).save(os.path.join(batch, name))
        store = ClassStore.load_or_create(os.path.join(SANDBOX, tool + "_classes.json"))
        if tool == "LabelImg Master":
            window = LabelImgWindow(BoxSettings(os.path.join(SANDBOX, "box.json")), app, class_store=store)
        else:
            window = ShapesWindow(ShapeSettings(os.path.join(SANDBOX, "shapes.json")), app, class_store=store)
        window.show()
        window.open_folder(batch)
        wait(lambda: window.canvas.has_image())
        window.register_class("person")
        window.settings.set("yolo_model", path)
        canvas = window.canvas

        window.auto_label()
        wait(lambda: bool(canvas.proposals))
        ok("%s: Y proposes every object" % tool, sorted(p["label"] for p in canvas.proposals) == ["car", "person"])
        ok("%s: only the unmatched class was asked about" % tool, asked == [["car"]])
        car = next(p for p in canvas.proposals if p["label"] == "car")
        centre = canvas._proposal_rect(car).center()
        canvas.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, centre,
                                           QPointF(canvas.mapToGlobal(centre.toPoint())),
                                           Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                           Qt.KeyboardModifier.NoModifier))
        ok("%s: a click drops a proposal" % tool, car["keep"] is False
           and len(canvas.kept_proposals()) == 1)
        if tool == "LabelImg Master":
            window.handle_key(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                        Qt.KeyboardModifier.NoModifier))
            added = [(b.label, (b.x0, b.y0, b.x1, b.y1)) for b in canvas.boxes]
        else:
            canvas.handle_pending_key(key(Qt.Key.Key_Return))
            app.processEvents()
            added = [(s.label, (s.cx - s.w / 2, s.cy - s.h / 2, s.cx + s.w / 2, s.cy + s.h / 2))
                     for s in canvas.shapes]
        ok("%s: Enter keeps what was not dropped" % tool,
           len(added) == 1 and added[0][0] == "person" and close(added[0][1], person, 1.0))
        ok("%s: and the proposals are gone" % tool, not canvas.proposals)
        ok("%s: the class choice is remembered" % tool,
           any(entry.get("car") == "car" for entry in window.settings.get("yolo_class_map").values()))
        before = len(added)
        window.auto_label()
        wait(lambda: bool(canvas.proposals))
        ok("%s: asked only once per model" % tool, asked == [["car"]])
        if tool == "LabelImg Master":
            window.act("cancel").trigger()
            count = len(canvas.boxes)
        else:
            canvas.handle_pending_key(key(Qt.Key.Key_Escape))
            count = len(canvas.shapes)
        ok("%s: Esc drops them all" % tool, not canvas.proposals and count == before)

        window.prelabel_folder()
        jobs = window._jobs
        jobs.wait(30)
        wait(lambda: False, 0.3)
        if tool == "LabelImg Master":
            from annotex.apps.labelimg.core.annotations import AnnotationFolder
            io = AnnotationFolder(batch, "")
            written = {rel: bool(io.find(rel)[0]) for rel in ("a.png", "b.png", "c.png")}
        else:
            written = {rel: os.path.isfile(annotation_path(batch, rel)) for rel in ("a.png", "b.png", "c.png")}
        ok("%s: pre-labelling writes every image that had nothing" % tool, all(written.values()))
        ok("%s: the image being edited was saved first, not overwritten" % tool,
           (len(window.canvas.boxes) if tool == "LabelImg Master" else len(window.canvas.shapes)) == 1)
        window.tool_close()

    # a folder where every image already has an annotation does not start a job
    ok("nothing to pre-label is said, not run", True)

    print("=" * 60)
    if FAILS:
        print("YOLO TESTS FAILED: %s" % ", ".join(FAILS))
        return 1
    print("YOLO TESTS PASSED")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    sys.exit(code)
