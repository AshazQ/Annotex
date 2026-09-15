"""Batch apply, backup restore, external-change detection, batch settings.

    python tests/test_features.py
"""

import os, sys, json, time, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from annotex.ui.dialogs import messages
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtCore import Qt
from annotex.apps.roi.config import Settings, PROJECT_SETTINGS_NAME, XLSX_NAME, PRINTED_DIR, NO_ROI_DIR
from annotex.apps.roi.ui.main_window import MainWindow
from annotex.apps.roi.ui.dialogs.batch_dialog import BatchApplyDialog
from annotex.apps.roi.core.model import Shape

FAILS=[]
def ok(l,c):
    if not c: FAILS.append(l)
    print(("  ok  " if c else "  XX  ")+l)

app = QApplication(sys.argv[:1]); app.setStyle("Fusion")
tmp = tempfile.mkdtemp(prefix="roi_new_")
names = ["S1_cam1_a.png","S1_cam1_b.png","S1_cam1_c.png","S2_cam2_a.png","S2_cam2_b.png"]
for n in names:
    px = QPixmap(800, 600); px.fill(QColor(50,70,100)); px.save(os.path.join(tmp, n))

settings = Settings(tempfile.mktemp(suffix=".json")); settings.data["first_run_done"]=True
w = MainWindow(settings, app); w.resize(1300,850); w.show(); app.processEvents()
w.open_folder(tmp); app.processEvents()

# draw two shapes on image 1
w.canvas.set_shapes([Shape.rect(80,80,320,300), Shape.circle(500,400,90)])
w.canvas.shapesChanged.emit("test")
app.processEvents()

# ── batch apply ROIs to the other two cam1 frames ─────────────
orig_q = messages.ask
messages.ask = lambda *a, **k: True
d = BatchApplyDialog(w, w.image_files, w.current_name(), w._statuses(), 2, "rois")
d._pick_same_camera()
print("  ..  same-camera picks:", d._checked())
ok("same camera picked 2", len(d._checked()) == 2)
d._accept()
done, skipped, notes = w._apply_to_images(d.selected, [s.copy() for s in w.canvas.shapes])
rep = w._flush()
ok("batch applied to 2 images (%s)" % "; ".join(notes), done == 2 and rep.ok)
ok("saved_shapes now has both", all(len(w.saved_shapes.get(n,[]))==2 for n in names[1:3]))
ok("printed previews written", all(os.path.isfile(os.path.join(tmp, PRINTED_DIR, n)) for n in names[1:3]))
row = w.store.row_for(names[1])
ok("kinds carried across", json.loads(row["shape_types"]) == ["rect","circle"])

# ── batch no_roi on the cam2 frames ───────────────────────────
done2, skipped2, _n = w._apply_to_images(names[3:], None)
w._flush()
ok("batch no_roi applied", done2 == 2 and all(n in w.no_roi_saved for n in names[3:]))
ok("no_roi copies written", all(os.path.isfile(os.path.join(tmp, NO_ROI_DIR, n)) for n in names[3:]))

# ── save image 1 properly, then test restore-from-backup ──────
w.save_current(); app.processEvents()
w.go_to_index(0); app.processEvents()
before = len(w.canvas.shapes)
w.canvas.set_shapes([Shape.rect(10,10,60,60)])
w.canvas.shapesChanged.emit("edit"); w.save_current(); app.processEvents()
w.go_to_index(0); app.processEvents()
ok("image now has 1 shape", len(w.canvas.shapes) == 1)
w.restore_from_backup(); app.processEvents()
ok("restored %d shapes from the .bak" % len(w.canvas.shapes), len(w.canvas.shapes) == before)

# ── external change detection ─────────────────────────────────
ok("no false positive", not w.store.changed_externally())
time.sleep(1.1)
with open(os.path.join(tmp, XLSX_NAME), "ab") as fh:
    fh.write(b"\x00")
ok("external change detected", w.store.changed_externally())
w._flush()          # question() is stubbed to Yes -> should proceed
ok("overwrite accepted after prompt", not w.store.changed_externally())

# ── per-batch settings ────────────────────────────────────────
settings.data["printed_roi_colour"] = "#ff00aa"
settings.data["use_site_format"] = True
w.save_project_settings()
path = os.path.join(tmp, PROJECT_SETTINGS_NAME)
ok("project settings written", os.path.isfile(path))
saved = json.load(open(path))
ok("project settings content", saved["printed_roi_colour"] == "#ff00aa" and saved["use_site_format"] is True)

settings.data["printed_roi_colour"] = "#00dc64"
settings.data["use_site_format"] = False
note = w._load_project_settings(tmp)
ok("project settings reloaded (%s)" % note,
   settings.get("printed_roi_colour") == "#ff00aa" and settings.get("use_site_format") is True)

messages.ask = orig_q
w.lock.release(); w.close(); shutil.rmtree(tmp, ignore_errors=True)
print("="*60)
if FAILS:
    print("FAILED %d" % len(FAILS)); [print("  x "+f) for f in FAILS]; sys.exit(1)
print("NEW-FEATURE TESTS PASSED")
