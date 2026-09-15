"""Thousands of random operations, and nothing may raise.

A labelling session is not a script: people switch tools mid-drag, press
Escape in the middle of a polygon, paste onto an image of another size, undo
past the beginning, mark an empty image as background and then hit Ctrl+Z.
No sequence of those may end in a traceback, whatever order they come in.

Both labelling tools are driven here by a fixed random seed - the same run
every time, so a failure can be reproduced - through their real actions and
real mouse and key events, with the global exception hook armed.  Anything
that reaches it fails the suite and is printed with its step number.

    python tests/robust/test_monkey.py [steps]
"""

import os
import random
import shutil
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SANDBOX = tempfile.mkdtemp(prefix="annotex_monkey_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")

from PySide6.QtCore import QEvent, QPointF, Qt                        # noqa: E402
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent      # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox               # noqa: E402

STEPS = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
ESCAPED = []
FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


def _hook(exc_type, exc_value, exc_tb):
    ESCAPED.append("%s: %s" % (exc_type.__name__, exc_value))
    traceback.print_exception(exc_type, exc_value, exc_tb)


sys.excepthook = _hook

app = QApplication(sys.argv[:1])
app.setStyle("Fusion")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

from annotex.apps.labelimg.core.class_store import ClassStore         # noqa: E402
from annotex.ui.dialogs.ai_dialog import AiModelDialog                # noqa: E402

AiModelDialog.exec = lambda self: 0        # built for real, never waits

STORE = ClassStore.load_or_create(os.path.join(SANDBOX, "classes.json"))


def make_batch(name, count, sizes):
    folder = os.path.join(SANDBOX, name)
    os.makedirs(os.path.join(folder, "sub"), exist_ok=True)
    for index in range(count):
        width, height = sizes[index % len(sizes)]
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor(30 + index * 17 % 200, 90, 130))
        image.save(os.path.join(folder, "img_%02d.png" % index))
    image = QImage(60, 45, QImage.Format.Format_RGB32)
    image.fill(QColor("#884422"))
    image.save(os.path.join(folder, "sub", "small.jpg"))
    return folder


def mouse(canvas, kind, x, y, button=Qt.MouseButton.LeftButton,
          mods=Qt.KeyboardModifier.NoModifier):
    event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, button, mods)
    if kind == QEvent.Type.MouseButtonPress:
        canvas.mousePressEvent(event)
    elif kind == QEvent.Type.MouseButtonRelease:
        canvas.mouseReleaseEvent(event)
    else:
        canvas.mouseMoveEvent(event)


def gesture(canvas, rng, mods=Qt.KeyboardModifier.NoModifier):
    x, y = rng.uniform(10, 900), rng.uniform(10, 700)
    mouse(canvas, QEvent.Type.MouseButtonPress, x, y, mods=mods)
    for _ in range(rng.randrange(0, 3)):
        x += rng.uniform(-80, 80)
        y += rng.uniform(-80, 80)
        mouse(canvas, QEvent.Type.MouseMove, x, y)
    mouse(canvas, QEvent.Type.MouseButtonRelease, x, y, mods=mods)


def press_key(canvas, key, mods=Qt.KeyboardModifier.NoModifier):
    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mods))


KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Escape, Qt.Key.Key_Backspace,
        Qt.Key.Key_Space, Qt.Key.Key_Delete)
MODS = (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier,
        Qt.KeyboardModifier.ControlModifier)


# ══════════════════════════════════════════════════════════════
def monkey_labelimg(steps):
    from annotex.apps.labelimg.config import Settings
    from annotex.apps.labelimg.core.model import Box
    from annotex.apps.labelimg.ui import window as module
    from annotex.apps.labelimg.ui.canvas import T_AI, T_BOX, T_PAN, T_SELECT

    rng = random.Random(20260914)
    module.LabelDialog.ask = classmethod(lambda cls, *a, **k: rng.choice(["a", "b", "c"]))
    folder = make_batch("boxes", 7, [(240, 180), (320, 200), (180, 320), (1, 1)])
    window = module.LabelImgWindow(Settings(os.path.join(SANDBOX, "labelimg.json")),
                                   app, class_store=STORE)
    window.settings.data["first_run_done"] = True
    window.resize(1100, 800)
    window.show()
    window.open_folder(folder)
    for name in ("a", "b", "c"):
        window.register_class(name)
    window.set_current_class("a")
    canvas = window.canvas

    def add_box():
        if not canvas.has_image():
            return
        width, height = canvas.image_size
        x, y = rng.uniform(0, width), rng.uniform(0, height)
        canvas.add_box(Box(rng.choice(["a", "b", "c"]), x, y,
                           x + rng.uniform(-70, 70), y + rng.uniform(-70, 70)))

    def ai_click():
        if canvas.has_image():
            canvas._add_ai_point(QPointF(rng.uniform(0, canvas.image_size[0]),
                                         rng.uniform(0, canvas.image_size[1])),
                                 positive=rng.random() > 0.3)

    moves = [
        window.next_image, window.prev_image, window.next_todo,
        lambda: window.go_to_index(rng.randrange(0, max(1, len(window.image_files)))),
        add_box, lambda: canvas.select_index(rng.randrange(max(1, len(canvas.boxes)))),
        canvas.select_all, window.delete_boxes, canvas.duplicate_selected,
        window.copy_boxes, lambda: window.copy_boxes(cut=True), window.paste_boxes,
        lambda: window.copy_previous(replace=True),
        lambda: window.copy_previous(replace=False),
        window.save_current, window.mark_background, window.toggle_verified,
        window.undo, window.redo, window.clear_all, window.accept_frame,
        lambda: window.set_tool(rng.choice([T_SELECT, T_BOX, T_PAN, T_AI])),
        lambda: rng.choice([canvas.zoom_in, canvas.zoom_out, canvas.fit_to_view,
                            canvas.zoom_to_all, canvas.zoom_to_selection])(),
        lambda: window.set_brightness(rng.randrange(0, 101)),
        window.toggle_hidden, window.toggle_lock, window.toggle_difficult,
        ai_click, window.accept_ai_preview, canvas.clear_ai,
        lambda: canvas.nudge_selected(rng.choice([-10, -1, 1, 10]),
                                      rng.choice([-10, -1, 1, 10])),
        lambda: window.apply_class_choice(rng.choice(["a", "b", "c"])),
        window.cycle_format, lambda: window.write_report(quiet=True),
        lambda: gesture(canvas, rng, rng.choice(MODS)),
        lambda: press_key(canvas, rng.choice(KEYS), rng.choice(MODS)),
        lambda: window.tool_apply_theme(rng.choice(["dark", "light"])),
    ]
    for step in range(steps):
        move = rng.choice(moves)
        try:
            move()
        except Exception:
            ESCAPED.append("LabelImg Master step %d" % step)
            traceback.print_exc()
        if step % 60 == 0:
            app.processEvents()
    app.processEvents()
    window.tool_close()
    window.close()


# ══════════════════════════════════════════════════════════════
def monkey_shapes(steps):
    from annotex.apps.shapes.config import Settings
    from annotex.apps.shapes.ui import window as module
    from annotex.apps.shapes.ui.canvas import (T_AI, T_CIRCLE, T_ELLIPSE, T_FREEHAND,
                                               T_OBB, T_PAN, T_POLYGON, T_SELECT)

    rng = random.Random(4711)
    module.LabelDialog.ask = classmethod(lambda cls, *a, **k: rng.choice(["x", "y"]))
    folder = make_batch("shapes", 5, [(300, 220), (260, 300)])
    window = module.ShapesWindow(Settings(os.path.join(SANDBOX, "shapes.json")),
                                 app, class_store=STORE)
    window.resize(1100, 800)
    window.show()
    window.open_folder(folder)
    for name in ("x", "y"):
        window.register_class(name)
    window.set_current_class("x")
    canvas = window.canvas

    tools = [T_SELECT, T_POLYGON, T_OBB, T_CIRCLE, T_ELLIPSE, T_FREEHAND, T_PAN, T_AI]
    moves = [
        lambda: window.set_tool(rng.choice(tools)),
        lambda: gesture(canvas, rng, rng.choice(MODS)),
        lambda: mouse(canvas, QEvent.Type.MouseButtonPress, rng.uniform(10, 900),
                      rng.uniform(10, 700), Qt.MouseButton.RightButton),
        lambda: press_key(canvas, rng.choice(KEYS), rng.choice(MODS)),
        window.next_image, window.prev_image,
        window.copy_shapes, lambda: window.copy_shapes(cut=True), window.paste_shapes,
        window.copy_previous, window.duplicate_shapes, window.delete_shapes,
        window.undo, window.redo, window.save_current, window.toggle_verified,
        canvas.select_all, lambda: canvas.rotate_selected(rng.choice([-15, 15])),
        window.clear_all, window.accept_ai_preview, canvas.clear_ai,
        lambda: canvas._add_ai_point(QPointF(rng.uniform(0, 300), rng.uniform(0, 220)),
                                     positive=rng.random() > 0.3),
        lambda: rng.choice([canvas.zoom_in, canvas.zoom_out, canvas.fit_to_view,
                            canvas.zoom_to_selection])(),
        lambda: window.apply_class_choice(rng.choice(["x", "y"])),
        lambda: canvas.nudge_selected(rng.choice([-5, 5]), rng.choice([-5, 5])),
    ]
    for step in range(steps):
        move = rng.choice(moves)
        try:
            move()
        except Exception:
            ESCAPED.append("LabelImg Shapes step %d" % step)
            traceback.print_exc()
        if step % 60 == 0:
            app.processEvents()
            canvas.render(QImage(320, 240, QImage.Format.Format_RGB32))
    app.processEvents()
    window.tool_close()
    window.close()


monkey_labelimg(STEPS)
ok("LabelImg Master survives %d random operations" % STEPS, not ESCAPED)
before = len(ESCAPED)
monkey_shapes(STEPS)
ok("LabelImg Shapes survives %d random operations" % STEPS, len(ESCAPED) == before)
for escaped in ESCAPED:
    print("  escaped: " + escaped)

shutil.rmtree(SANDBOX, ignore_errors=True)
print("=" * 60)
if FAILS:
    print("MONKEY TESTS FAILED: %d" % len(FAILS))
    sys.exit(1)
print("MONKEY TESTS PASSED")
