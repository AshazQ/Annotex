"""End-to-end GUI test for LabelImg Master: every gesture, save path and dialog.

Runs headless (Qt's offscreen platform) inside a throwaway HOME, so it never
touches the real class store or settings:

    python tests/labelimg/test_gui.py

Set LABELIMG_SHOT_DIR to a folder to keep the screenshots it takes.
"""

import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SANDBOX = tempfile.mkdtemp(prefix="labelimg_gui_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")
OUT = os.environ.get("LABELIMG_SHOT_DIR", "")

from PySide6.QtCore import QEvent, QPointF, Qt                      # noqa: E402
from PySide6.QtGui import QColor, QKeyEvent, QLinearGradient, QMouseEvent, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402
from annotex.ui.dialogs import messages  # noqa: E402

from annotex.apps.labelimg.config import (BACKUP_DIR, COPY_DIR, DELETED_DIR,  # noqa: E402
                                          FORMAT_VOC, FORMAT_YOLO,
                                          PROJECT_SETTINGS_NAME, Settings)
from annotex.apps.labelimg.core.annotations import AnnotationFolder, pil_probe  # noqa: E402
from annotex.apps.labelimg.core.class_store import ClassStore       # noqa: E402
from annotex.apps.labelimg.core.model import Box                    # noqa: E402
from annotex.apps.labelimg.ui import window as window_module        # noqa: E402
from annotex.apps.labelimg.ui.canvas import T_BOX, T_SELECT         # noqa: E402
from annotex.apps.labelimg.ui.dialogs import label_dialog           # noqa: E402
from annotex.ui.dialogs.common import Dialog                        # noqa: E402

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


def shot(widget, name):
    if OUT:
        widget.grab().save(os.path.join(OUT, name))


app = QApplication(sys.argv[:1])
app.setStyle("Fusion")
ANSWER = {"value": True}
messages.ask = lambda *a, **k: ANSWER["value"]
messages.inform = lambda *a, **k: None
messages.warn = lambda *a, **k: None

folder = os.path.join(SANDBOX, "batch")
os.makedirs(folder)
names = ["SITE1_cam1_001.png", "SITE1_cam1_002.png", "SITE1_cam1_003.png",
         "SITE2_cam4_001.png", "SITE2_cam4_002.png"]
for i, name in enumerate(names):
    px = QPixmap(800, 600)
    gradient = QLinearGradient(0, 0, 800, 600)
    gradient.setColorAt(0, QColor(40 + i * 12, 60, 90))
    gradient.setColorAt(1, QColor(120, 80 + i * 10, 60))
    painter = QPainter(px)
    painter.fillRect(px.rect(), gradient)
    painter.setPen(QColor(220, 220, 220))
    for y in range(0, 600, 60):
        painter.drawLine(0, y, 800, y)
    painter.end()
    px.save(os.path.join(folder, name))

store = ClassStore(os.path.join(SANDBOX, "classes.json"))
project = store.active_project()
for cls in ("person", "helmet", "weapon"):
    project.add_class(cls)
store.save()

settings = Settings(os.path.join(SANDBOX, "settings.json"))
settings.data["first_run_done"] = True
w = window_module.LabelImgWindow(settings, app, class_store=store)
w.resize(1500, 950)
w.show()
app.processEvents()
c = w.canvas


def mouse(kind, x, y, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier):
    types = {"press": QEvent.Type.MouseButtonPress, "release": QEvent.Type.MouseButtonRelease,
             "move": QEvent.Type.MouseMove, "dbl": QEvent.Type.MouseButtonDblClick}
    point = c.to_widget(x, y)
    event = QMouseEvent(types[kind], point, c.mapToGlobal(point), button,
                        button if kind != "release" else Qt.MouseButton.NoButton, mods)
    app.sendEvent(c, event)
    app.processEvents()


def drag(x0, y0, x1, y1):
    mouse("press", x0, y0)
    mouse("move", (x0 + x1) / 2, (y0 + y1) / 2)
    mouse("move", x1, y1)
    mouse("release", x1, y1)


def key(code, text="", mods=Qt.KeyboardModifier.NoModifier):
    return w.handle_key(QKeyEvent(QEvent.Type.KeyPress, code, mods, text))


def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


try:
    # ── opening ───────────────────────────────────────────────
    w.open_folder(folder)
    app.processEvents()
    ok("folder opened with 5 images", w.folder == folder and len(w.image_files) == 5)
    ok("image on canvas", c.has_image() and w.image_shape == (600, 800, 3))
    ok("class hotkeys", w.class_hotkeys == {"person": "1", "helmet": "2", "weapon": "3"})
    ok("lock taken", os.path.isfile(os.path.join(folder, ".labelimg.lock")))

    # ── drawing with an armed class ───────────────────────────
    ok("digit key handled", key(Qt.Key.Key_1, "1"))
    ok("key 1 arms person", w.current_class == "person")
    w.set_tool(T_BOX)
    drag(100, 100, 300, 260)
    ok("box drawn with the armed class", len(c.boxes) == 1 and c.boxes[0].label == "person")
    ok("box on whole pixels", c.boxes[0].bounds == (100.0, 100.0, 300.0, 260.0))
    ok("tool returns to select", c.tool == T_SELECT)

    c.select_index(0)
    key(Qt.Key.Key_2, "2")
    ok("digit relabels the selection", c.boxes[0].label == "helmet")
    w.undo()
    ok("undo the relabel", c.boxes[0].label == "person")
    w.redo()
    ok("redo the relabel", c.boxes[0].label == "helmet")
    w.undo()
    shifted = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Exclam,
                        Qt.KeyboardModifier.ShiftModifier, "!")
    ok("Shift+1 addresses the 11th class", w._hotkey_index(shifted) == 10)
    ok("Ctrl+digit is not a class key", w._hotkey_index(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier, "1")) is None)

    # ── the label dialog path ─────────────────────────────────
    original_ask = label_dialog.LabelDialog.ask
    label_dialog.LabelDialog.ask = classmethod(lambda cls, *a, **k: "vehicle")
    w.set_pref("skip_label_dialog", False)
    w.set_tool(T_BOX)
    drag(400, 300, 520, 420)
    ok("dialog label adds a new class", c.boxes[-1].label == "vehicle"
       and store.active_project().by_name("vehicle") is not None)
    ok("sticky class follows the new box", w.current_class == "vehicle")
    label_dialog.LabelDialog.ask = original_ask
    w.set_pref("skip_label_dialog", True)
    w.set_current_class("person")

    # ── squares ───────────────────────────────────────────────
    w.set_pref("draw_square", True)
    w._apply_settings()
    w.set_tool(T_BOX)
    drag(600, 100, 700, 160)
    square = c.boxes[-1]
    ok("draw-square makes a square", square.width == square.height == 60)
    w.set_pref("draw_square", False)
    w._apply_settings()

    # ── moving, resizing, nudging ─────────────────────────────
    c.clear_selection()
    drag(200, 180, 230, 200)
    ok("dragging a box moves it", c.boxes[0].bounds == (130.0, 120.0, 330.0, 280.0))
    c.select_index(0)
    drag(330, 280, 360, 300)
    ok("dragging the corner handle resizes", c.boxes[0].bounds == (130.0, 120.0, 360.0, 300.0))
    c.nudge_selected(1, 0)
    ok("nudge", c.boxes[0].x0 == 131.0)
    w.undo()
    ok("undo the nudge", c.boxes[0].x0 == 130.0)

    c.clear_selection()
    drag(20, 20, 560, 460)
    ok("marquee selects the boxes it touches", c.selection == {0, 1})

    c.select_index(0)
    w.toggle_lock()
    ok("lock", c.boxes[0].locked and 0 not in c.selection)
    c.select_all()
    ok("select all skips locked", 0 not in c.selection)
    c.set_locked([0], False)
    c.select_index(1)
    w.toggle_hidden()
    ok("hide", not c.boxes[1].visible)
    rows = lambda: [w.box_panel.list.item(i).text()
                    for i in range(w.box_panel.list.count())]
    ok("the box list says which box is hidden", any("hidden" in r for r in rows()))
    c.selection = {1}
    w.toggle_hidden()
    ok("and hide brings it back", c.boxes[1].visible
       and not any("hidden" in r for r in rows()))
    c.select_index(0)
    w.toggle_lock()
    ok("the box list says which box is locked", any("locked" in r for r in rows()))
    c.set_locked([0], False)
    w._refresh_side()

    c.select_index(2)
    ok("picking a box shows in the list without rebuilding it",
       w.box_panel.selected_indices() == [2])
    c.select_index(0)
    w.toggle_difficult()
    ok("difficult flag", c.boxes[0].difficult)
    count = len(c.boxes)
    c.select_index(0)
    c.duplicate_selected()
    ok("duplicate", len(c.boxes) == count + 1)
    w.delete_boxes()
    ok("delete", len(c.boxes) == count)

    # duplication stops at the per-image limit rather than doubling for ever
    from annotex.apps.labelimg.config import MAX_BOXES_PER_IMAGE
    keep = c.snapshot()
    c.set_boxes([Box("person", 1, 1, 20, 20)] * (MAX_BOXES_PER_IMAGE - 3))
    c.select_all()
    added = c.duplicate_selected()
    ok("duplicate stops at the per-image limit",
       added == 3 and len(c.boxes) == MAX_BOXES_PER_IMAGE)
    ok("and refuses once the image is full", c.duplicate_selected() == 0)
    c.set_boxes(keep)

    shot(w, "labelimg_editor.png")

    # ── saving as VOC, verifying, accepting ───────────────────
    w.set_format(FORMAT_VOC, from_user=True)
    first = w.current_name()
    w.save_current()
    xml_path = os.path.join(folder, "SITE1_cam1_001.xml")
    ok("VOC written", os.path.isfile(xml_path))
    body = read_text(xml_path)
    ok("VOC content", "<name>person</name>" in body and "<difficult>1</difficult>" in body)
    ok("state chip says saved", "saved" in w.state_chip.text())
    ok("index says labelled", w.index_map[first].status == "labelled")

    w.toggle_verified()
    ok("verified written", 'verified="yes"' in read_text(xml_path))
    ok("film strip shows verified", w._statuses()[first] == "verified")

    ok("Enter handled", key(Qt.Key.Key_Return))
    ok("Enter accepts and moves on", w.index == 1)

    # ── copying from the previous frame ───────────────────────
    w.copy_previous(replace=True)
    ok("Ctrl+V copies the previous frame", len(c.boxes) == count)
    w.set_format(FORMAT_YOLO, from_user=True)
    w.save_current()
    txt_path = os.path.join(folder, "SITE1_cam1_002.txt")
    ok("YOLO written", os.path.isfile(txt_path))
    classes = read_text(os.path.join(folder, "classes.txt")).split("\n")
    ok("classes.txt follows class IDs", classes[:3] == ["person", "helmet", "weapon"])
    ids = sorted({int(line.split()[0]) for line in read_text(txt_path).splitlines()})
    ok("YOLO uses the stable IDs", ids == sorted({store.active_project().by_name(b.label).id
                                                  for b in c.boxes}))
    w.copy_previous(replace=False)
    ok("Ctrl+Shift+V appends", len(c.boxes) >= count)
    w.undo()
    ok("undo the append", len(c.boxes) == count)

    # ── copying chosen boxes onto another image ───────────────
    from annotex.core import clipboard
    clipboard.clear()
    ok("nothing is on the clipboard to begin with", clipboard.count() == 0)
    ok("paste is off until something is copied", not w.act("paste_boxes").isEnabled())
    c.selection = {0}
    wanted = c.boxes[0].copy()
    w.copy_boxes()
    ok("Ctrl+C copies only the selected box", clipboard.count() == 1)
    ok("paste turns on once something is copied", w.act("paste_boxes").isEnabled())
    w.go_to_index(4)
    before = len(c.boxes)
    w.paste_boxes()
    ok("Ctrl+V pastes it onto the next image", len(c.boxes) == before + 1)
    pasted = c.boxes[-1]
    ok("the pasted box keeps its class", pasted.label == wanted.label)
    ok("the pasted box keeps its place",
       pasted.same_geometry(wanted, 1.0))
    ok("the pasted box is selected, ready to move", c.selection == {len(c.boxes) - 1})
    w.undo()
    ok("undo takes the paste back", len(c.boxes) == before)

    c.selection = set()
    c.add_box(Box("person", 5, 5, 40, 40))
    everything = len(c.boxes)
    w.copy_boxes()
    ok("copying with nothing selected copies the whole image",
       clipboard.count() == everything)
    w.copy_boxes(cut=True)
    ok("cut empties the image", not c.boxes)
    w.paste_boxes()
    ok("and paste puts it all back", len(c.boxes) == everything)
    while c.boxes:
        c.select_all()
        w.delete_boxes()
    clipboard.clear()

    # ── background, and leaving commits ───────────────────────
    w.go_to_index(2)
    w.mark_background()
    third = os.path.join(folder, "SITE1_cam1_003.txt")
    ok("background writes an empty annotation", os.path.isfile(third)
       and read_text(third).strip() == "")
    ok("background moves on", w.index == 3)
    ok("background status", w._statuses()["SITE1_cam1_003.png"] == "background")

    c.add_box(Box("weapon", 50, 50, 150, 150))
    w.go_to_index(0)
    ok("navigating away commits the work", os.path.isfile(os.path.join(folder, "SITE2_cam4_001.txt")))
    ok("an untouched image stays unannotated", w.index_map["SITE2_cam4_002.png"] is None)
    ok("TAI / BAI in the status bar", "TAI 4/5" in w.progress_label.text()
       and "BAI 1/4" in w.progress_label.text())

    # ── image 0 was opened as VOC: the format follows the file ─
    ok("format follows the opened file", w.fmt == FORMAT_VOC)

    # ── external change detection ─────────────────────────────
    stamp = os.path.getmtime(xml_path) + 5
    os.utime(xml_path, (stamp, stamp))
    c.add_box(Box("helmet", 500, 400, 560, 470))
    ANSWER["value"] = False
    w.save_current()
    ok("refusing the overwrite keeps the file", w.dirty and "helmet" not in read_text(xml_path)
       .split("<name>person</name>")[0])
    ANSWER["value"] = True
    w.save_current()
    ok("accepting the overwrite saves", not w.dirty)

    # ── backups ───────────────────────────────────────────────
    ok("backup kept", os.path.isfile(os.path.join(folder, BACKUP_DIR, "SITE1_cam1_001.xml")))
    before = len(c.boxes)
    w.restore_from_backup()
    ok("restore brings the previous version back", len(c.boxes) == before - 1)
    w.undo()
    ok("undo the restore", len(c.boxes) == before)

    w.set_format(FORMAT_YOLO, from_user=True)
    w.save_current()
    ok("switching format retires the old file", not os.path.isfile(xml_path)
       and os.path.isfile(os.path.join(folder, "SITE1_cam1_001.txt")))

    # ── apply to many ─────────────────────────────────────────
    from annotex.apps.labelimg.ui.dialogs.batch_dialog import BatchApplyDialog

    class SameCamera(BatchApplyDialog):
        def exec(self):
            self._pick_same_camera()
            self._accept()
            return Dialog.DialogCode.Accepted

    window_module.BatchApplyDialog = SameCamera
    w.go_to_index(0)
    boxes_here = len(c.boxes)
    w.batch_apply("boxes")
    for other in ("SITE1_cam1_002.png", "SITE1_cam1_003.png"):
        ok("applied to %s" % other, w.index_map[other].count == boxes_here)
    w.go_to_index(3)
    w.batch_apply("background")
    ok("background applied to the same camera", w.index_map["SITE2_cam4_002.png"] is not None
       and w.index_map["SITE2_cam4_002.png"].count == 0)
    window_module.BatchApplyDialog = BatchApplyDialog

    # ── review, dashboard, report, export, import ─────────────
    from annotex.apps.labelimg.ui.dialogs.review_dialog import ReviewDialog
    captured = {}

    class CapturedReview(ReviewDialog):
        def exec(self):
            captured["dialog"] = self
            return 0

    window_module.ReviewDialog = CapturedReview
    w.open_review()
    review = captured["dialog"]
    review.show()
    app.processEvents()
    shot(review, "labelimg_review.png")
    ok("review lists every image", review.list.count() == len(w.image_files))
    review.filter_box.setCurrentIndex(review.filter_box.findData("background"))
    ok("review filter", review.list.count() == 1)
    target = "SITE1_cam1_002.png"
    was = w.index_map[target].verified
    review.verifyRequested.emit(target)
    ok("verify from review mode", w.index_map[target].verified != was)
    review.close()
    window_module.ReviewDialog = ReviewDialog

    w.write_report(quiet=True)
    ok("HTML report", os.path.isfile(os.path.join(folder, "labelimg_report.html")))
    ok("summary json", os.path.isfile(os.path.join(folder, "labelimg_summary.json")))
    stats = w._stats()
    ok("stats add up", stats["totals"]["images"] == 5 and stats["totals"]["remaining"] == 0)

    from annotex.apps.labelimg.ui.dialogs.transfer_dialog import (CocoExportDialog,
                                                                  ImportDialog,
                                                                  ImportReviewDialog)

    class AcceptAll(CocoExportDialog):
        def exec(self):
            self._accept()
            return Dialog.DialogCode.Accepted

    window_module.CocoExportDialog = AcceptAll
    w.export_coco()
    coco_path = os.path.join(folder, "export_coco", "annotations.json")
    ok("COCO export", os.path.isfile(coco_path)
       and len(json.load(open(coco_path))["images"]) == 5)
    window_module.CocoExportDialog = CocoExportDialog

    other_dir = os.path.join(SANDBOX, "other_annotator")
    AnnotationFolder(folder, save_dir=other_dir).write(
        "SITE2_cam4_002.png", [Box("person", 10, 10, 90, 90)], FORMAT_VOC,
        pil_probe(os.path.join(folder, "SITE2_cam4_002.png")))

    class ChooseOther(ImportDialog):
        def exec(self):
            self.folder, self.strategy = other_dir, "incoming"
            return Dialog.DialogCode.Accepted

    class AcceptReview(ImportReviewDialog):
        def exec(self):
            return Dialog.DialogCode.Accepted

    window_module.ImportDialog, window_module.ImportReviewDialog = ChooseOther, AcceptReview
    w.import_annotations()
    ok("import writes the other annotator's box", w.index_map["SITE2_cam4_002.png"].count == 1)
    window_module.ImportDialog, window_module.ImportReviewDialog = ImportDialog, ImportReviewDialog

    # ── class rename rewrites files ───────────────────────────
    w.go_to_index(4)                       # opening follows the file's format...
    w.set_format(FORMAT_VOC, from_user=True)   # ...so choose VOC after opening
    w.save_current()
    entry = store.active_project().by_name("person")
    store.active_project().rename_class(entry.id, "pedestrian")
    w.apply_class_rename("person", "pedestrian")
    ok("rename rewrites the saved VOC", "<name>pedestrian</name>" in
       read_text(os.path.join(folder, "SITE2_cam4_002.xml")))
    ok("rename relabels the canvas", all(b.label != "person" for b in c.boxes))
    ok("no false conflict after the rename", w._commit_current())

    # ── batch settings ────────────────────────────────────────
    w.save_project_settings()
    project_file = os.path.join(folder, PROJECT_SETTINGS_NAME)
    ok("batch settings written", os.path.isfile(project_file))
    ok("batch settings content", json.load(open(project_file))["label_format"] == FORMAT_VOC)

    # ── a separate annotation folder ──────────────────────────
    annotations = os.path.join(SANDBOX, "annotations")
    os.makedirs(annotations)
    w.set_save_dir(annotations)
    c.add_box(Box("weapon", 300, 300, 380, 380))
    w.save_current()
    ok("saving into the annotation folder",
       os.path.isfile(os.path.join(annotations, "SITE2_cam4_002.xml")))
    w.set_save_dir(folder)
    ok("back beside the images", w.save_dir == "")

    # ── copy and delete image ─────────────────────────────────
    w.go_to_index(1)
    w.copy_image()
    ok("copy image", os.path.isfile(os.path.join(folder, COPY_DIR, "SITE1_cam1_002.png")))
    w.delete_image()
    ok("delete image moves it out", len(w.image_files) == 4
       and os.path.isfile(os.path.join(folder, DELETED_DIR, "SITE1_cam1_002.png")))
    ok("copies and deletions are not rescanned", len(window_module.scan_images(folder)) == 4)

    # ── brightness, theme, dialogs ────────────────────────────
    w.set_brightness(80)
    app.processEvents()
    w.grab()
    ok("brightness", c.brightness == 80 and "brightness" in w.brightness_label.text())
    w.set_brightness(50)
    w.toggle_theme()
    app.processEvents()
    ok("theme switched", w.theme["name"] == "light")
    shot(w, "labelimg_light.png")
    w.toggle_theme()

    from annotex.apps.labelimg.ui.dialogs.class_manager import ClassManagerDialog
    from annotex.apps.labelimg.ui.dialogs.review_dialog import DashboardDialog
    from annotex.apps.labelimg.ui.dialogs.settings_dialog import SettingsDialog
    from annotex.apps.labelimg.ui.dialogs.welcome_dialog import AboutDialog, WelcomeDialog
    from annotex.ui.dialogs.palette_dialog import CommandPalette, ShortcutSheet
    from annotex.apps.labelimg.ui import shortcuts as sc
    for dialog in (ClassManagerDialog(w, store, w.annotation_dirs()),
                   SettingsDialog(w, settings),
                   DashboardDialog(w, w._stats(), w.theme),
                   CommandPalette(w, sc.ACTIONS, w.keys, {}, w.theme),
                   ShortcutSheet(w, sc.ACTIONS, w.keys, w.theme, sc.MOUSE_HINT, sc.FIXED),
                   WelcomeDialog(w, w.theme), AboutDialog(w, [("Version", "x")], w.theme),
                   label_dialog.LabelDialog(w, store.active_project().active_classes(), "pe"),
                   BatchApplyDialog(w, w.image_files, w.current_name(), w._statuses(), 1)):
        dialog.show()
        app.processEvents()
        shot(dialog, "labelimg_%s.png" % type(dialog).__name__)
        dialog.close()
    ok("every dialog opens", True)
    settings_dialog = SettingsDialog(w, settings)
    settings_dialog._save()
    ok("settings dialog round trip", settings_dialog.result_values()["label_format"] in
       ("PascalVOC", "YOLO", "CreateML"))

    # ── crash-safe drafts ─────────────────────────────────────
    w.go_to_index(3)
    c.add_box(Box("helmet", 222, 222, 333, 333))
    w._write_draft()
    ok("draft written", os.path.isfile(os.path.join(folder, ".labelimg_draft.json")))
    rel_with_draft = w.current_name()
    boxes_with_draft = len(c.boxes)
    w.canvas.set_boxes(w.saved.get(rel_with_draft, []))       # pretend we crashed
    w.lock.release()
    w2 = window_module.LabelImgWindow(Settings(os.path.join(SANDBOX, "settings2.json")),
                                      app, class_store=store)
    w2.settings.data["first_run_done"] = True
    w2.open_folder(folder)
    app.processEvents()
    ok("draft offered and restored", w2.current_name() == rel_with_draft
       and len(w2.canvas.boxes) == boxes_with_draft)
    w2.tool_close()
    w2.close()
    w.canvas.set_boxes(w.saved.get(rel_with_draft, []))
    w.history.reset(w.canvas.snapshot())

    # ── the film strip stays where it was put ─────────────────
    strip = w.filmstrip
    strip.resize(420, 110)
    many = ["frame_%03d.png" % i for i in range(60)]
    strip.set_batch(folder, many, {})
    strip.set_index(45)
    app.processEvents()
    where, which = strip._offset, strip.index
    ok("the strip scrolls to the current image", where > 0)
    strip.set_batch(folder, many, {"frame_000.png": "labelled"})   # what a save does
    ok("saving does not send the strip back to the first image",
       (strip._offset, strip.index) == (where, which))
    strip.set_batch(folder + "_elsewhere", many, {})
    ok("a different folder does start again",
       (strip._offset, strip.index) == (0.0, 0))
    strip.set_batch(folder, w.image_files, w._statuses())
    strip.set_index(w.index)
finally:
    try:
        w.tool_close()
        w.close()
    except Exception as exc:
        FAILS.append("closing raised %s" % exc)
    shutil.rmtree(SANDBOX, ignore_errors=True)

print("=" * 60)
if FAILS:
    print("LABELIMG GUI TESTS FAILED: %d" % len(FAILS))
    for failure in FAILS:
        print("  x " + failure)
    sys.exit(1)
print("LABELIMG GUI TESTS PASSED")
