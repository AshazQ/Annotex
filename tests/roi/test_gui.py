"""End-to-end GUI test: every tool, every save path, every dialog.

Runs headless (Qt's offscreen platform), so it works over SSH and in CI:

    python tests/test_gui.py

Set ROI_SHOT_DIR to a folder to keep the screenshots it takes along the way.
"""

import os, sys, json, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QMouseEvent, QPixmap, QPainter, QColor, QLinearGradient
from annotex.apps.roi.config import Settings, XLSX_NAME, JSON_NAME, MAP_NAME, PRINTED_DIR, NO_ROI_DIR
from annotex.apps.roi.ui.main_window import MainWindow
from annotex.apps.roi.ui.canvas import T_POLYGON, T_RECT, T_CIRCLE, T_SELECT, T_LASSO
from annotex.apps.roi.core.model import Shape

OUT = os.environ.get("ROI_SHOT_DIR", tempfile.gettempdir())
FAILS = []
def ok(label, cond):
    if not cond: FAILS.append(label)
    print(("  ok  " if cond else "  XX  ") + label)

app = QApplication(sys.argv[:1]); app.setStyle("Fusion")
tmp = tempfile.mkdtemp(prefix="roi_studio_gui_")
names = ["UBBRAP0006_cam3_2026-08-14_16-00-00.png",
         "UBBRAP0006_cam3_2026-08-14_18-00-00.png",
         "UBBRAP0347_cam5_2026-08-14_16-00-00.png",
         "UBBRAP0412_cam2_2026-08-14_16-00-00.png"]
for i, n in enumerate(names):
    px = QPixmap(900, 640)
    g = QLinearGradient(0, 0, 900, 640)
    g.setColorAt(0, QColor(38 + i*14, 58, 92)); g.setColorAt(1, QColor(120, 70 + i*10, 60))
    p = QPainter(px); p.fillRect(px.rect(), g)
    p.setPen(QColor(230, 230, 230))
    for y in range(0, 640, 64): p.drawLine(0, y, 900, y)
    for x in range(0, 900, 64): p.drawLine(x, 0, x, 640)
    p.end()
    px.save(os.path.join(tmp, n))

settings = Settings(tempfile.mktemp(suffix=".json"))
settings.data["first_run_done"] = True
w = MainWindow(settings, app)
w.resize(1500, 940); w.show(); app.processEvents()

w.open_folder(tmp); app.processEvents()
ok("folder opened", w.folder == tmp)
ok("4 images listed", len(w.image_files) == 4)
ok("no done_roi folder", not os.path.isdir(os.path.join(tmp, "done_roi")))
ok("no_roi + printed_roi created",
   os.path.isdir(os.path.join(tmp, NO_ROI_DIR)) and os.path.isdir(os.path.join(tmp, PRINTED_DIR)))
ok("image loaded on canvas", w.canvas.has_image())

def click(canvas, x, y, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier, kind="press"):
    types = {"press": QEvent.Type.MouseButtonPress, "release": QEvent.Type.MouseButtonRelease,
             "move": QEvent.Type.MouseMove, "dbl": QEvent.Type.MouseButtonDblClick}
    ev = QMouseEvent(types[kind], QPointF(x, y), QPointF(x, y),
                     button, button if kind != "move" else Qt.MouseButton.LeftButton, mods)
    app.sendEvent(canvas, ev); app.processEvents()

c = w.canvas
# ── polygon tool ──────────────────────────────────────────────
w.set_tool(T_POLYGON)
for pt in [(320, 240), (520, 230), (560, 420), (300, 430)]:
    click(c, *pt)
c.finish_draft()
ok("polygon drawn", len(c.shapes) == 1 and c.shapes[0].kind == "polygon")

# ── rectangle tool ────────────────────────────────────────────
w.set_tool(T_RECT)
click(c, 640, 250); click(c, 800, 380, kind="move"); click(c, 800, 380, kind="release")
ok("rect drawn", len(c.shapes) == 2 and c.shapes[1].kind == "rect")
ok("rect has 4 points", len(c.shapes[1].points) == 4)

# ── circle tool ───────────────────────────────────────────────
w.set_tool(T_CIRCLE)
click(c, 380, 470); click(c, 520, 570, kind="move"); click(c, 520, 570, kind="release")
ok("circle drawn", len(c.shapes) == 3 and c.shapes[2].kind == "circle")
ok("circle is a ring", len(c.shapes[2].points) > 20)

# ── select / edit ─────────────────────────────────────────────
w.set_tool(T_SELECT)
click(c, 400, 300)
ok("shape selected by click", c.selection == {0})
before = len(c.shapes[0].points)
mid = c.to_widget(*[(int((c.shapes[0].points[0][0]+c.shapes[0].points[1][0])/2),
                     int((c.shapes[0].points[0][1]+c.shapes[0].points[1][1])/2))][0])
click(c, mid.x(), mid.y(), kind="dbl")
ok("double-click inserts a vertex", len(c.shapes[0].points) == before + 1)
v = c.to_widget(*c.shapes[0].points[0])
click(c, v.x(), v.y(), mods=Qt.KeyboardModifier.ControlModifier)
ok("ctrl+click removes a vertex", len(c.shapes[0].points) == before)

# undo / redo
depth_before = len(c.shapes[0].points)
w.undo(); ok("undo restored the vertex", len(c.shapes[0].points) == depth_before + 1)
w.redo(); ok("redo removed it again", len(c.shapes[0].points) == depth_before)

# duplicate + delete
c.select_index(1); c.duplicate_selected()
ok("duplicate added a shape", len(c.shapes) == 4)
c.delete_selected()
ok("delete removed it", len(c.shapes) == 3)

# nudge + align
c.select_all(); ok("select all", len(c.selection) == 3)
first_y = c.shapes[0].bounds[1]
c.nudge_selected(0, 5)
ok("nudge moved shapes", c.shapes[0].bounds[1] == first_y + 5)
c.align_selected("top")
tops = {s.bounds[1] for s in c.shapes}
ok("align top", len(tops) == 1)
c.distribute_selected(True); ok("distribute ran", True)
c.clear_selection()

# ── screenshot: the editor ────────────────────────────────────
w.comment_box.set_text("Counter and display cabinets.")
w.set_tool(T_SELECT); c.select_index(0)
app.processEvents()
w.grab().save(os.path.join(OUT, "shot_dark.png"))

# ── save ──────────────────────────────────────────────────────
n0 = w.current_name()
w.save_current(); app.processEvents()
ok("saved and advanced", w.index == 1)
ok("xlsx written", os.path.isfile(os.path.join(tmp, XLSX_NAME)))
ok("json written", os.path.isfile(os.path.join(tmp, JSON_NAME)))
ok("map written", os.path.isfile(os.path.join(tmp, MAP_NAME)))
ok("no csv", not os.path.isfile(os.path.join(tmp, "roi_annotations.csv")))
ok("printed preview written", os.path.isfile(os.path.join(tmp, PRINTED_DIR, n0)))
row = w.store.row_for(n0)
ok("shape_types recorded", json.loads(row["shape_types"]) == ["polygon", "rect", "circle"])
ok("comment stored", row["comment"].startswith("Counter"))

# second image: copy from previous
w.copy_from_previous(); app.processEvents()
ok("copied from previous", len(c.shapes) == 3)
w.save_current(); app.processEvents()

# third: no_roi
n2 = w.current_name()
w.mark_no_roi(); app.processEvents()
ok("no_roi copy written", os.path.isfile(os.path.join(tmp, NO_ROI_DIR, n2)))
ok("no_roi recorded", n2 in w.no_roi_saved)

# fourth: lasso
w.set_tool(T_LASSO)
click(c, 300, 300)
for x in range(300, 560, 12): click(c, x, 300 + (x % 40), kind="move")
for y in range(300, 520, 12): click(c, 560, y, kind="move")
for x in range(560, 300, -12): click(c, x, 520, kind="move")
click(c, 300, 520, kind="release")
ok("lasso created a polygon", len(c.shapes) == 1 and len(c.shapes[0].points) >= 3)
w.save_current(); app.processEvents()

# ── merged json ───────────────────────────────────────────────
with open(os.path.join(tmp, MAP_NAME)) as fh: roi_map = json.load(fh)
ok("cameras merged under one key", len(roi_map.get("UBBRAP0006_3", [])) == 6)
with open(os.path.join(tmp, JSON_NAME)) as fh: full = json.load(fh)
ok("no_roi in json", full["no_roi"] == ["UBBRAP0347_5"])
ok("shapes map present", "UBBRAP0006_3" in full["shapes"])

# ── export / report / dashboard ───────────────────────────────
w.export_now(); app.processEvents()
ok("html report written", os.path.isfile(os.path.join(tmp, "roi_report.html")))
ok("coverage json written", os.path.isfile(os.path.join(tmp, "roi_coverage.json")))
from annotex.apps.roi.core import exporters
rep = exporters.run_exports(["coco", "yolo", "voc", "masks"], w.store.rows, tmp)
ok("format exports ok", rep.ok)

# ── light theme screenshot ────────────────────────────────────
w.go_to_index(0); app.processEvents()
w.toggle_theme(); app.processEvents()
c.select_index(1); app.processEvents()
_img = w.grab()
print("PROBE light: theme=%s side=%s head=%s" % (
    w.theme["name"], _img.toImage().pixelColor(_img.width()-60, 300).name(),
    _img.toImage().pixelColor(300, 8).name()))
_img.save(os.path.join(OUT, "shot_light.png"))
w.toggle_theme(); app.processEvents()

# ── dialogs open without error ────────────────────────────────
from annotex.apps.roi.ui.dialogs.review_dialog import ReviewDialog, DashboardDialog, HistoryDialog
from annotex.apps.roi.ui.dialogs.settings_dialog import SettingsDialog
from annotex.apps.roi.ui.dialogs.palette_dialog import CommandPalette, ShortcutSheet
from annotex.apps.roi.ui.dialogs.welcome_dialog import WelcomeDialog, AboutDialog
from annotex.apps.roi.ui.dialogs.transfer_dialog import ExportDialog, ImportDialog

d = ReviewDialog(w, tmp, w.image_files, w._statuses(), w.theme); d.show(); app.processEvents()
d.grab().save(os.path.join(OUT, "shot_review.png")); ok("review dialog", True); d.close()
d = DashboardDialog(w, w.store.rows, tmp, w.image_files,
                    {"elapsed":"14m","images":4,"per_hour":17.0}, w.theme)
d.show(); app.processEvents(); d.grab().save(os.path.join(OUT, "shot_dashboard.png"))
ok("dashboard dialog", True); d.close()
d = SettingsDialog(w, settings); d.show(); app.processEvents()
d.grab().save(os.path.join(OUT, "shot_settings.png")); ok("settings dialog", True); d.close()
d = CommandPalette(w, w.keys, {}, w.theme); d.show(); app.processEvents()
d.grab().save(os.path.join(OUT, "shot_palette.png")); ok("command palette", True); d.close()
d = ShortcutSheet(w, w.keys, w.theme); d.show(); app.processEvents(); ok("shortcut sheet", True); d.close()
d = WelcomeDialog(w, w.theme); d.show(); app.processEvents()
d.grab().save(os.path.join(OUT, "shot_welcome.png")); ok("welcome dialog", True); d.close()
d = AboutDialog(w, [("Version","1.0.0")], w.theme); d.show(); app.processEvents(); ok("about dialog", True); d.close()
d = ExportDialog(w, w.store.rows, tmp); d.show(); app.processEvents()
d.grab().save(os.path.join(OUT, "shot_export.png")); ok("export dialog", True); d.close()
d = ImportDialog(w, tmp); d.show(); app.processEvents(); ok("import dialog", True); d.close()
d = HistoryDialog(w, w.audit.tail(50)); d.show(); app.processEvents(); ok("history dialog", True); d.close()

# ── reopen the folder and check state restores ────────────────
w.reload_folder(); app.processEvents()
ok("reload restored shapes", len(w.saved_shapes) == 3)
ok("reload restored kinds", [s.kind for s in w.saved_shapes[names[0]]] == ["polygon","rect","circle"])
ok("reload restored no_roi", names[2] in w.no_roi_saved)
ok("reload restored comment", w.comments.get(names[0], "").startswith("Counter"))

w.lock.release()
w.close()
shutil.rmtree(tmp, ignore_errors=True)
print("=" * 60)
if FAILS:
    print("GUI TESTS FAILED: %d" % len(FAILS))
    for f in FAILS: print("  x " + f)
    sys.exit(1)
print("GUI TESTS PASSED")
