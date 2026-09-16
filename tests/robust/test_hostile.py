"""What happens when the folder is not what the tool hoped for.

Every annotator eventually opens a folder with a truncated JPEG in it, an XML
somebody hand-edited, a file named in another alphabet, or a share that has
gone read-only.  None of that may end in a traceback: the tool says what is
wrong and carries on.

This suite feeds both labelling tools exactly those folders, with the global
exception hook armed, and fails if anything reaches it.

    python tests/robust/test_hostile.py
"""

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SANDBOX = tempfile.mkdtemp(prefix="annotex_hostile_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")

from PySide6.QtCore import QPointF, Qt                                # noqa: E402
from PySide6.QtGui import QColor, QImage                              # noqa: E402
from PySide6.QtWidgets import QApplication               # noqa: E402
from annotex.ui.dialogs import messages  # noqa: E402

FAILS = []
ESCAPED = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


def _hook(exc_type, exc_value, exc_tb):
    import traceback
    ESCAPED.append("%s: %s" % (exc_type.__name__, exc_value))
    traceback.print_exception(exc_type, exc_value, exc_tb)


sys.excepthook = _hook

app = QApplication(sys.argv[:1])
messages.ask = lambda *a, **k: True
messages.inform = lambda *a, **k: None
messages.warn = lambda *a, **k: None
messages.error = lambda *a, **k: None

from annotex.ui.dialogs.ai_dialog import AiModelDialog                # noqa: E402
AiModelDialog.exec = lambda self: 0        # built for real, never waits

from annotex.apps.labelimg.config import Settings as BoxSettings      # noqa: E402
from annotex.apps.labelimg.core.class_store import ClassStore         # noqa: E402
from annotex.apps.labelimg.core.model import Box                      # noqa: E402
from annotex.apps.labelimg.ui import window as box_window             # noqa: E402
from annotex.apps.shapes.config import Settings as ShapeSettings      # noqa: E402
from annotex.apps.shapes.ui import window as shape_window             # noqa: E402
from annotex.core import clipboard                                    # noqa: E402

box_window.LabelDialog.ask = classmethod(lambda cls, *a, **k: "thing")
shape_window.LabelDialog.ask = classmethod(lambda cls, *a, **k: "thing")

# ══════════════════════════════════════════════════════════════
# A FOLDER NOBODY WOULD DESIGN
# ══════════════════════════════════════════════════════════════
folder = os.path.join(SANDBOX, "difficult batch (2)")
deep = os.path.join(folder, "sub folder", "deeper")
os.makedirs(deep)


def picture(path, width=64, height=48, colour="#446688"):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(colour))
    image.save(path)


picture(os.path.join(folder, "normal.png"))
picture(os.path.join(folder, "one pixel.png"), 1, 1)
picture(os.path.join(folder, "tall.png"), 4, 3000)
picture(os.path.join(folder, "éè 日本語 الع.png"))
picture(os.path.join(deep, "normal.png"), 32, 24)       # same stem, other folder
picture(os.path.join(folder, "classes.png"))            # collides with classes.txt

# a file that claims to be an image and is not
with open(os.path.join(folder, "truncated.jpg"), "wb") as handle:
    handle.write(b"\xff\xd8\xff\xe0 this is not a JPEG")
with open(os.path.join(folder, "empty.png"), "wb") as handle:
    handle.write(b"")

# annotations somebody edited by hand
with open(os.path.join(folder, "normal.xml"), "w", encoding="utf-8") as handle:
    handle.write("<annotation><object><name>cat</name><bndbox>"
                 "<xmin>-50</xmin><ymin>10</ymin><xmax>99999</xmax><ymax>abc</ymax>"
                 "</bndbox></object><object></object></annotation>")
with open(os.path.join(folder, "tall.txt"), "w", encoding="utf-8") as handle:
    handle.write("0 0.5 0.5 0.2 0.2\nnot a line at all\n9 9 9 9 9\n\n")
with open(os.path.join(folder, "one pixel.json"), "w", encoding="utf-8") as handle:
    handle.write("{ this is not json")

shapes_folder = os.path.join(SANDBOX, "shapes batch")
os.makedirs(shapes_folder)
picture(os.path.join(shapes_folder, "a.png"))
picture(os.path.join(shapes_folder, "b.png"))
with open(os.path.join(shapes_folder, "a.shapes.json"), "w", encoding="utf-8") as handle:
    handle.write('{"format": "annotex-shapes", "version": 1, "width": 64, '
                 '"height": 48, "shapes": [{"kind": "polygon", "label": "ok", '
                 '"points": [[1,1],[40,2],[30,30]]}, {"kind": "banana"}, '
                 '{"kind": "circle", "label": "bad"}, 7, null]}')
with open(os.path.join(shapes_folder, "b.shapes.json"), "w", encoding="utf-8") as handle:
    handle.write("not json at all")

store = ClassStore.load_or_create(os.path.join(SANDBOX, "classes.json"))


# ══════════════════════════════════════════════════════════════
# LABELIMG MASTER
# ══════════════════════════════════════════════════════════════
def drive_labelimg():
    window = box_window.LabelImgWindow(
        BoxSettings(os.path.join(SANDBOX, "labelimg.json")), app, class_store=store)
    window.settings.data["first_run_done"] = True
    window.show()
    window.open_folder(folder)
    app.processEvents()
    ok("a batch of awkward files opens", bool(window.image_files))
    for _ in range(len(window.image_files) + 2):     # walk the whole folder
        window.next_image()
        app.processEvents()
    ok("every image can be reached", window.index == len(window.image_files) - 1)
    ok("the files that are not images are dropped, not crashed on",
       all("truncated" not in name and "empty" not in name
           for name in window.image_files))

    window.go_to_index(0)
    ok("a hand-edited VOC file is read without raising", True)

    # a one-pixel image cannot hold a box; asking for one must not raise
    for position, rel in enumerate(window.image_files):
        window.go_to_index(position)
        app.processEvents()
        window.canvas.add_box(Box("thing", 1, 1, 30, 30))
        window.save_current()
    ok("every image can be saved", True)

    # rubbish on the system clipboard
    for junk in ('{"format": "annotex.annotations/1"}',
                 '{"format": "annotex.annotations/1", "items": [1, 2]}',
                 '{"format": "annotex.annotations/1", "items": [{"bounds": "no"}]}',
                 '{"format": "annotex.annotations/1", "items": [{"bounds": [0,0,1,1]}],'
                 ' "width": "wide", "height": null}',
                 "", "<html/>", "x" * 20000):
        QApplication.clipboard().setText(junk)
        clipboard.invalidate()
        window.paste_boxes()
        app.processEvents()
    ok("rubbish on the system clipboard is survivable", True)

    # a payload with impossible numbers
    clipboard.copy(clipboard.KIND_BOXES,
                   [{"label": "x", "bounds": [-1e9, -1e9, 1e9, 1e9]},
                    {"label": "y", "bounds": [0, 0, 0, 0]},
                    {"label": "", "bounds": [10, 10, 20, 20]}], (0, 0), "nowhere")
    window.paste_boxes()
    ok("impossible coordinates are refused, not pasted",
       all(box.x1 <= window.image_shape[1] + 1 for box in window.canvas.boxes))

    window.copy_boxes()
    window.copy_boxes(cut=True)
    window.paste_boxes()
    window.toggle_hidden()
    window.toggle_hidden()
    window.toggle_lock()
    window.clear_all()
    window.mark_background()
    window.write_report(quiet=True)
    ok("the report survives this batch",
       os.path.isfile(os.path.join(folder, "labelimg_report.html")))

    # the AI tool with nothing installed or configured
    window.set_tool("ai")
    ok("the AI tool refuses politely without a model", window.canvas.tool != "ai")
    window.refresh_ai_preview()
    window.accept_ai_preview()
    ok("asking the AI for a proposal that does not exist is harmless", True)

    window.tool_close()
    window.close()


# ══════════════════════════════════════════════════════════════
# LABELIMG SHAPES
# ══════════════════════════════════════════════════════════════
def drive_shapes():
    window = shape_window.ShapesWindow(
        ShapeSettings(os.path.join(SANDBOX, "shapes.json")), app, class_store=store)
    window.show()
    window.open_folder(shapes_folder)
    app.processEvents()
    ok("a batch with broken shape files opens", len(window.images) == 2)
    ok("the readable shapes in a part-broken file are kept",
       len(window.canvas.shapes) == 1)
    window.next_image()
    app.processEvents()
    ok("a shape file that is not JSON does not stop the image opening",
       window.image_ok)
    ok("and the tool refuses to overwrite it silently", window.saved is None)

    window.copy_shapes()
    window.go_to_index(0)
    window.paste_shapes()
    window.copy_previous()
    clipboard.copy(clipboard.KIND_SHAPES,
                   [{"kind": "polygon", "label": "x", "points": [[0, 0]],
                     "bounds": [0, 0, 1, 1]},
                    {"kind": "nonsense", "bounds": [1, 1, 30, 30]}], (64, 48), "a.png")
    window.paste_shapes()
    ok("a shape that cannot exist is refused, not pasted",
       all(s.kind != "nonsense" for s in window.canvas.shapes))
    window.set_tool("ai")
    ok("the AI tool refuses politely without a model", window.canvas.tool != "ai")
    window.export_with("segment", 24, True)
    window.tool_close()
    window.close()


# ══════════════════════════════════════════════════════════════
# A FOLDER THAT CANNOT BE WRITTEN TO
# ══════════════════════════════════════════════════════════════
def drive_read_only():
    locked = os.path.join(SANDBOX, "locked")
    os.makedirs(locked)
    picture(os.path.join(locked, "a.png"))

    # An account that can write anywhere (root, and Windows in some setups)
    # cannot be shown a folder it may not write to, so the guards are driven
    # directly there; everywhere else the real thing is used.
    really_locked = os.name != "nt" and os.geteuid() != 0
    if really_locked:
        os.chmod(locked, 0o500)
    try:
        from annotex.core.io_safe import folder_is_writable, write_text_atomic
        if really_locked:
            writable, _why = folder_is_writable(locked)
            ok("an unwritable folder is recognised", not writable)
        ok("a folder that is not there is not writable",
           not folder_is_writable(os.path.join(SANDBOX, "no such folder"))[0])

        # Saving must not change who can read the file.  Every write goes
        # through a temp file, which is made readable by its owner alone, and
        # os.replace carries that onto the file it replaces - so a shared
        # folder would quietly become one person's after the first save.
        if os.name != "nt":
            import stat as _stat
            shared = os.path.join(SANDBOX, "shared.json")
            with open(shared, "w", encoding="utf-8") as handle:
                handle.write('{"a": 1}')
            os.chmod(shared, 0o644)
            write_text_atomic(shared, '{"a": 2}', verify_json=True, keep_backup=False)
            ok("saving keeps the permissions a file already had",
               _stat.S_IMODE(os.stat(shared).st_mode) == 0o644)
            os.chmod(shared, 0o600)
            write_text_atomic(shared, '{"a": 3}', verify_json=True, keep_backup=False)
            ok("and does not widen one that was locked down",
               _stat.S_IMODE(os.stat(shared).st_mode) == 0o600)
            fresh = os.path.join(SANDBOX, "fresh.json")
            write_text_atomic(fresh, '{"b": 1}', verify_json=True, keep_backup=False)
            probe = os.path.join(SANDBOX, "probe.json")
            with open(probe, "w", encoding="utf-8") as handle:
                handle.write("{}")
            ok("a new file is made the way any other program would make it",
               _stat.S_IMODE(os.stat(fresh).st_mode) == _stat.S_IMODE(os.stat(probe).st_mode))

        window = box_window.LabelImgWindow(
            BoxSettings(os.path.join(SANDBOX, "labelimg_ro.json")), app, class_store=store)
        window.settings.data["first_run_done"] = True
        window.open_folder(locked)
        app.processEvents()
        if not really_locked:
            window.read_only = True
            window.canvas.read_only = True
            window._sync_actions()
        ok("the batch is open read-only", window.read_only)
        window.canvas.add_box(Box("thing", 1, 1, 20, 20))
        window.save_current()
        window.paste_boxes()
        window.copy_previous()
        window.mark_background()
        window.delete_image()
        window.set_tool("ai")
        app.processEvents()
        ok("nothing is written to a read-only batch",
           not os.path.isfile(os.path.join(locked, "a.xml")))
        ok("the AI tool stays off in a read-only batch", window.canvas.tool != "ai")
        window.tool_close()
        window.close()
    finally:
        if really_locked:
            os.chmod(locked, 0o700)


drive_labelimg()
drive_shapes()
drive_read_only()

ok("nothing reached the crash handler", not ESCAPED)
for escaped in ESCAPED:
    print("  escaped: " + escaped)

shutil.rmtree(SANDBOX, ignore_errors=True)
print("=" * 60)
if FAILS:
    print("HOSTILE INPUT TESTS FAILED: %d" % len(FAILS))
    for failure in FAILS:
        print("  x " + failure)
    sys.exit(1)
print("HOSTILE INPUT TESTS PASSED")
