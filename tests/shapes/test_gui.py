"""End-to-end GUI test for LabelImg Shapes: every drawing tool, editing
gesture, save path and export.

Runs headless inside a throwaway HOME, so it never touches real settings:

    python tests/shapes/test_gui.py

Set ANNOTEX_SHOT_DIR to a folder to keep the screenshots it takes.
"""

import json
import math
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SANDBOX = tempfile.mkdtemp(prefix="shapes_gui_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")
OUT = os.environ.get("ANNOTEX_SHOT_DIR", "")

from PySide6.QtCore import QEvent, QPointF, Qt                      # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent, QPixmap              # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox             # noqa: E402

from annotex.apps.labelimg.core.class_store import ClassStore       # noqa: E402
from annotex.apps.shapes.config import (EXPORT_COCO, EXPORT_YOLO_OBB,  # noqa: E402
                                        EXPORT_YOLO_SEG, KIND_CIRCLE, KIND_ELLIPSE,
                                        KIND_FREEHAND, KIND_OBB, KIND_POLYGON,
                                        LOCK_NAME, Settings, TASK_COCO, TASK_OBB,
                                        TASK_SEGMENT)
from annotex.apps.shapes.core.model import Shape                     # noqa: E402
from annotex.apps.shapes.core.store import annotation_path, read_annotation  # noqa: E402
from annotex.apps.shapes.ui import window as window_module          # noqa: E402
from annotex.apps.shapes.ui.canvas import (T_CIRCLE, T_ELLIPSE, T_FREEHAND,  # noqa: E402
                                           T_OBB, T_POLYGON, T_SELECT)

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


app = QApplication(sys.argv[:1])
app.setStyle("Fusion")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
answers = []
window_module.LabelDialog.ask = classmethod(lambda cls, *a, **k: answers.pop(0) if answers else None)

folder = os.path.join(SANDBOX, "grocery")
os.makedirs(os.path.join(folder, "window"))
for rel, colour in (("shop_1.png", (60, 80, 110)), ("shop_2.png", (90, 70, 60)),
                    (os.path.join("window", "shop_3.png"), (40, 90, 60))):
    px = QPixmap(800, 600)
    px.fill(QColor(*colour))
    px.save(os.path.join(folder, rel))

settings = Settings(os.path.join(SANDBOX, "settings.json"))
settings.data["skip_label_dialog"] = False
store = ClassStore(os.path.join(SANDBOX, "classes.json"))
w = window_module.ShapesWindow(settings, app, class_store=store)
w.resize(1500, 950)
w.show()
app.processEvents()
canvas = w.canvas


def settle():
    for _ in range(3):
        app.processEvents()


def mouse(kind, x, y, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier,
          image=True):
    pos = canvas.to_widget(x, y) if image else QPointF(x, y)
    buttons = button if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
    event = QMouseEvent(kind, pos, QPointF(canvas.mapToGlobal(pos.toPoint())), button, buttons, mods)
    {QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
     QEvent.Type.MouseMove: canvas.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
     QEvent.Type.MouseButtonDblClick: canvas.mouseDoubleClickEvent}[kind](event)


def drag(points, mods=Qt.KeyboardModifier.NoModifier, image=True):
    mouse(QEvent.Type.MouseButtonPress, *points[0], mods=mods, image=image)
    for point in points[1:]:
        mouse(QEvent.Type.MouseMove, *point, mods=mods, image=image)
    mouse(QEvent.Type.MouseButtonRelease, *points[-1], mods=mods, image=image)


def shot(name):
    if OUT:
        settle()
        w.grab().save(os.path.join(OUT, name))


try:
    w.open_folder(folder)
    settle()
    ok("folder opens with sub-folders", w.images == ["shop_1.png", "shop_2.png",
                                                      os.path.join("window", "shop_3.png")])
    ok("first image on the canvas", canvas.has_image() and canvas.image_size == (800, 600))
    ok("folder is locked", os.path.isfile(os.path.join(folder, LOCK_NAME)))
    ok("separate class store starts empty", len(w.project()) == 0)

    # ── polygon, with the class dialog ────────────────────
    w.set_tool(T_POLYGON)
    answers.append("cookies")
    for x, y in ((100, 100), (220, 110), (200, 230), (90, 210)):
        mouse(QEvent.Type.MouseButtonPress, x, y)
        mouse(QEvent.Type.MouseButtonRelease, x, y)
    mouse(QEvent.Type.MouseButtonPress, 100, 100)          # click the first point closes it
    ok("polygon drawn", len(canvas.shapes) == 1 and canvas.shapes[0].kind == KIND_POLYGON)
    ok("polygon got the class from the dialog", canvas.shapes[0].label == "cookies")
    ok("dialog added the class with id 0", w.project().by_name("cookies").id == 0)
    ok("polygon has its four points", len(canvas.shapes[0].points) == 4)

    settings.data["skip_label_dialog"] = True
    w.register_class("coke")
    w.register_class("human")

    # ── oriented box ──────────────────────────────────────
    canvas.clear_selection()          # a class key with a selection relabels it
    w.assign_class_by_index(2)
    ok("key 3 picks the third class", w.current_class == "human")
    w.set_tool(T_OBB)
    drag([(300, 100), (340, 160), (380, 280)])
    obb = canvas.shapes[-1]
    ok("oriented box drawn", obb.kind == KIND_OBB and obb.label == "human")
    ok("oriented box has the dragged size", abs(obb.w - 80) < 1.5 and abs(obb.h - 180) < 1.5)

    # ── circle ────────────────────────────────────────────
    canvas.clear_selection()
    w.assign_class_by_index(1)
    w.set_tool(T_CIRCLE)
    drag([(500, 150), (530, 150), (550, 150)])
    circle = canvas.shapes[-1]
    ok("circle drawn from its centre", circle.kind == KIND_CIRCLE and abs(circle.radius - 50) < 1.5
       and abs(circle.cx - 500) < 1.5)

    # ── ellipse ───────────────────────────────────────────
    w.set_tool(T_ELLIPSE)
    drag([(600, 300), (700, 360)])
    ellipse = canvas.shapes[-1]
    ok("ellipse drawn from its box", ellipse.kind == KIND_ELLIPSE and abs(ellipse.w - 100) < 1.5
       and abs(ellipse.h - 60) < 1.5)

    # ── freehand ──────────────────────────────────────────
    w.set_tool(T_FREEHAND)
    ring = [(150 + 60 * math.cos(t / 20.0 * 2 * math.pi), 420 + 40 * math.sin(t / 20.0 * 2 * math.pi))
            for t in range(21)]
    drag(ring)
    free = canvas.shapes[-1]
    ok("freehand drawn and simplified", free.kind == KIND_FREEHAND and 3 <= len(free.points) <= 21)
    ok("five shapes, five history steps", len(canvas.shapes) == 5 and w.history.depth()[0] == 5)
    ok("shape list follows the canvas", w.shape_panel.list.count() == 5)
    shot("shapes_drawn.png")

    # ── editing ───────────────────────────────────────────
    w.set_tool(T_SELECT)
    mouse(QEvent.Type.MouseButtonPress, 340, 190)
    mouse(QEvent.Type.MouseButtonRelease, 340, 190)
    ok("click selects the oriented box", canvas.selected_indices() == [1])
    ok("panel shows the selection", w.shape_panel.selected_rows() == [1])
    anchor, handle = canvas._rotate_point(1)
    centre = canvas.to_widget(obb.cx, obb.cy)
    radius = math.hypot(handle.x() - centre.x(), handle.y() - centre.y())
    target = QPointF(centre.x() + radius, centre.y())
    drag([(handle.x(), handle.y()), (target.x(), target.y())], image=False)
    ok("dragging the round handle rotates the box", abs(canvas.shapes[1].angle - 90) < 3)
    ok("rotation keeps the size", abs(canvas.shapes[1].w - 80) < 0.01)

    canvas.select_index(3)
    east = canvas._handle_points(3)["e"]
    drag([(east.x(), east.y()), (east.x() + canvas.to_widget(740, 0).x() - canvas.to_widget(700, 0).x(),
                                 east.y())], image=False)
    ok("the right handle widens the ellipse", abs(canvas.shapes[3].w - 140) < 2)
    ok("and keeps its left edge", abs((canvas.shapes[3].cx - canvas.shapes[3].w / 2) - 600) < 2)

    canvas.select_index(2)
    north = canvas._handle_points(2)["n"]
    drag([(north.x(), north.y()), (north.x(), canvas.to_widget(0, 80).y())], image=False)
    ok("a circle handle changes the radius only", abs(canvas.shapes[2].radius - 70) < 2
       and canvas.shapes[2].w == canvas.shapes[2].h)

    before = canvas.shapes[0].points[0]
    canvas.select_index(0)
    drag([(150, 160), (170, 180)])
    ok("dragging a shape moves it", abs(canvas.shapes[0].points[0][0] - (before[0] + 20)) < 1)

    w.undo()
    ok("undo puts it back", abs(canvas.shapes[0].points[0][0] - before[0]) < 0.01)
    w.redo()
    ok("redo moves it again", abs(canvas.shapes[0].points[0][0] - (before[0] + 20)) < 1)

    canvas.select_index(0)
    w.assign_class_by_index(1)
    ok("a class key relabels the selection", canvas.shapes[0].label == "coke")
    w.act("rotate_right").trigger()
    ok("a class key with a selection relabels only the selection", canvas.shapes[1].label == "human")
    count = len(canvas.shapes)
    canvas.select_index(4)
    w.duplicate_shapes()
    ok("duplicate adds a copy", len(canvas.shapes) == count + 1)
    w.delete_shapes()
    ok("delete removes it", len(canvas.shapes) == count)

    # ── saving ────────────────────────────────────────────
    drawn = [s.to_dict() for s in canvas.shapes]
    w.next_image()
    settle()
    ok("moving on saves the image", os.path.isfile(annotation_path(folder, "shop_1.png")))
    saved = read_annotation(folder, "shop_1.png")
    ok("every shape saved exactly", [s.to_dict() for s in saved.shapes] == drawn)
    ok("image size recorded", (saved.width, saved.height) == (800, 600))
    ok("filmstrip shows it labelled", w._statuses()["shop_1.png"] == "labelled")

    w.save_current()
    ok("saving an empty image marks background", read_annotation(folder, "shop_2.png").shapes == []
       and w._statuses()["shop_2.png"] == "background")
    w.next_image()
    w.set_tool(T_OBB)
    drag([(50, 50), (150, 120)])
    w.toggle_verified()
    ok("verified is saved", read_annotation(folder, os.path.join("window", "shop_3.png")).verified)
    ok("filmstrip shows verified", w._statuses()[os.path.join("window", "shop_3.png")] == "verified")
    shot("shapes_third.png")

    w.go_to_index(0)
    settle()
    ok("reopening restores the shapes", [s.to_dict() for s in canvas.shapes] == drawn)
    ok("nothing to save after reopening", not w.is_dirty())
    ok("history starts fresh", w.history.depth() == (0, 0))

    # duplication stops at the per-image limit rather than doubling for ever
    from annotex.apps.shapes.config import MAX_SHAPES_PER_IMAGE
    keep = canvas.snapshot()
    filler = Shape.polygon("cola", [(5, 5), (30, 6), (20, 25)])
    canvas.set_shapes([filler.copy() for _ in range(MAX_SHAPES_PER_IMAGE - 2)])
    canvas.select_all()
    added = canvas.duplicate_selected()
    ok("duplicate stops at the per-image limit",
       added == 2 and len(canvas.shapes) == MAX_SHAPES_PER_IMAGE)
    ok("and refuses once the image is full", canvas.duplicate_selected() == 0)
    canvas.set_shapes(keep)
    settle()

    # ── copying chosen shapes onto another image ──────────
    from annotex.core import clipboard
    clipboard.clear()
    ok("paste is off until something is copied", not w.act("paste_shapes").isEnabled())
    canvas.select_indices([0])
    wanted = canvas.shapes[0].to_dict()
    w.copy_shapes()
    ok("Ctrl+C copies only the selected shape", clipboard.count() == 1)
    ok("paste turns on once something is copied", w.act("paste_shapes").isEnabled())
    w.go_to_index(1)
    settle()
    before = len(canvas.shapes)
    w.paste_shapes()
    ok("Ctrl+V pastes it onto the next image", len(canvas.shapes) == before + 1)
    ok("the pasted shape is identical", canvas.shapes[-1].to_dict() == wanted)
    w.undo()
    ok("undo takes the paste back", len(canvas.shapes) == before)

    w.copy_previous()
    ok("the previous image's shapes can be added in one step",
       len(canvas.shapes) == before + len(drawn))
    w.undo()

    clipboard.copy(clipboard.KIND_BOXES,
                   [{"label": "crate", "bounds": [10, 10, 110, 60]}], (800, 600), "x.jpg")
    w.paste_shapes()
    ok("a box copied in LabelImg Master pastes as an oriented box",
       canvas.shapes[-1].kind == KIND_OBB and round(canvas.shapes[-1].w) == 100)
    w.undo()
    clipboard.clear()
    w.go_to_index(0)
    settle()

    # ── exports ───────────────────────────────────────────
    seg = w.export_with(TASK_SEGMENT, 24, True)
    lines = open(os.path.join(folder, EXPORT_YOLO_SEG, "labels", "shop_1.txt")).read().splitlines()
    ok("YOLO segmentation export", seg.ok and len(lines) == 5)
    ok("sub-folders mirrored", os.path.isfile(os.path.join(folder, EXPORT_YOLO_SEG, "labels", "window",
                                                           "shop_3.txt")))
    obb_report = w.export_with(TASK_OBB, 24, True)
    obb_lines = open(os.path.join(folder, EXPORT_YOLO_OBB, "labels", "shop_1.txt")).read().splitlines()
    ok("YOLO OBB export", obb_report.ok and all(len(l.split()) == 9 for l in obb_lines))
    coco = w.export_with(TASK_COCO, 24, True)
    payload = json.load(open(os.path.join(folder, EXPORT_COCO, "annotations.json")))
    ok("COCO export", coco.ok and len(payload["annotations"]) == 6 and len(payload["images"]) == 3)
    ok("exports are not scanned as images", len(w.images) == 3)

    # ── class changes reach the files ─────────────────────
    w.project().rename_class(w.project().by_name("coke").id, "cola")
    w.apply_class_changes([("coke", "cola")])
    ok("a renamed class is rewritten in the files",
       "cola" in {s.label for s in read_annotation(folder, "shop_1.png").shapes}
       and "coke" not in {s.label for s in read_annotation(folder, "shop_1.png").shapes})
    ok("and on the canvas", "cola" in {s.label for s in canvas.shapes})
    ok("separate from LabelImg Master's classes",
       not os.path.isfile(os.path.join(SANDBOX, "config", "annotex", "labelimg", "classes.json"))
       or "cola" not in open(os.path.join(SANDBOX, "config", "annotex", "labelimg", "classes.json")).read())

    w.toggle_theme()
    settle()
    ok("theme switches", w.theme["name"] == "light")
    shot("shapes_light.png")
    w.toggle_theme()
finally:
    w.close()
    settle()
    ok("closing released the lock", not os.path.isfile(os.path.join(folder, LOCK_NAME)))
    shutil.rmtree(SANDBOX, ignore_errors=True)

print("=" * 60)
if FAILS:
    print("SHAPES GUI TESTS FAILED: %d" % len(FAILS))
    for failure in FAILS:
        print("  x " + failure)
    sys.exit(1)
print("SHAPES GUI TESTS PASSED")
