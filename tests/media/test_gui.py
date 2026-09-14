"""End-to-end GUI test for the six media tools, on generated videos and images.

Runs headless in a throwaway HOME:

    python tests/media/test_gui.py

Set ANNOTEX_SHOT_DIR to a folder to keep screenshots.
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
SANDBOX = tempfile.mkdtemp(prefix="annotex_media_gui_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")
OUT = os.environ.get("ANNOTEX_SHOT_DIR", "")

from PIL import Image                                                # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox              # noqa: E402

from annotex.apps.images import ai, sorter                           # noqa: E402
from annotex.apps.images.selftest import _onnx_models                # noqa: E402
from annotex.apps.images.ui.convert_page import ImageConvertPage     # noqa: E402
from annotex.apps.images.ui.sorter_page import SorterPage            # noqa: E402
from annotex.apps.video.selftest import make_clip                    # noqa: E402
from annotex.apps.video.ui.convert_page import ConvertPage           # noqa: E402
from annotex.apps.video.ui.frames_page import FramesPage             # noqa: E402
from annotex.apps.video.ui.merge_page import MergePage               # noqa: E402
from annotex.apps.video.ui.trim_page import TrimPage                 # noqa: E402
from annotex.core.jobs import DONE                                   # noqa: E402
from annotex.core.media.ffmpeg import probe                          # noqa: E402
from annotex.ui.jobs import JobManager                               # noqa: E402
from annotex.ui.media_page import tool_settings                      # noqa: E402

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


def pump(condition, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def finish_jobs(label):
    ok("%s: jobs finished" % label, jobs.wait(300))
    bad = [j for j in jobs.jobs if j.state != DONE]
    for job in bad:
        print("      %s -> %s %s" % (job.title, job.state, job.error))
    ok("%s: every job succeeded" % label, not bad)
    jobs.clear_finished()


def shot(widget, name):
    if OUT:
        for _ in range(3):
            QApplication.processEvents()
        widget.grab().save(os.path.join(OUT, name))


def page(cls):
    instance = cls(app, settings=tool_settings(cls.TOOL_ID, cls.DEFAULTS,
                                               os.path.join(SANDBOX, cls.TOOL_ID + ".json")),
                   jobs=jobs)
    instance.resize(1500, 950)
    instance.show()
    QApplication.processEvents()
    return instance


app = QApplication(sys.argv[:1])
app.setStyle("Fusion")
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
jobs = JobManager()

videos = os.path.join(SANDBOX, "videos")
os.makedirs(videos)
clip = make_clip(os.path.join(videos, "clip.mp4"))
phone = make_clip(os.path.join(videos, "phone.mp4"), ("white",), seconds=2, size="640x360",
                  fps=30, audio=False)
pages = []

try:
    # ── Video to Images ───────────────────────────────────────────
    frames = page(FramesPage)
    pages.append(frames)
    frames.add_paths([videos])
    ok("videos listed", len(frames.files.paths()) == 2)
    frames.files.select(clip)
    ok("preview decoded", pump(lambda: frames.player.view.image is not None))
    frames.mode.setCurrentIndex(frames.mode.findData("interval"))
    frames.interval.setValue(1.0)
    ok("estimate shown", "About 4 frame" in frames.estimate.text())
    shot(frames, "media_frames.png")
    frames.extract([clip])
    finish_jobs("frames")
    frames_dir = os.path.join(videos, "clip_frames")
    ok("4 frames written", len([f for f in os.listdir(frames_dir) if f.endswith(".jpg")]) == 4)
    frames.player.seek(2.5)
    frames.grab_current_frame()
    ok("manual grab adds a frame", len([f for f in os.listdir(frames_dir) if f.endswith(".jpg")]) == 5)
    ok("grab marked on the timeline", frames.player.timeline.marks == [2.5])
    frames.player.seek(0)
    frames.player.toggle_play()
    ok("playback moves", pump(lambda: frames.player.position > 0.3, 10))
    frames.player.toggle_play()
    ok("pause stops playback", not frames.player.playback.playing)
    frames.use_range.setChecked(True)
    frames.start.setText("3")
    frames.end.setText("1")
    ok("bad range caught", "Check the times" in frames.estimate.text())
    frames.use_range.setChecked(False)

    # ── Trimmer ───────────────────────────────────────────────────
    trim = page(TrimPage)
    pages.append(trim)
    trim.add_paths([clip])
    ok("trim preview", pump(lambda: trim.player.view.image is not None))
    trim.player.seek(1.0)
    trim.set_start()
    trim.player.seek(2.0)
    trim.set_end()
    ok("piece added", len(trim.current_segments()) == 1 and trim.table.rowCount() == 1)
    trim.table.item(0, 2).setText("00:00:02.500")
    ok("edited end time", abs(trim.current_segments()[0].end - 2.5) < 1e-6)
    trim.table.item(0, 2).setText("00:00:00.500")
    ok("invalid edit refused", abs(trim.current_segments()[0].end - 2.5) < 1e-6)
    ok("pieces drawn on the timeline", trim.player.timeline.segments == [(1.0, 2.5)])
    trim.exact.setChecked(True)
    shot(trim, "media_trim.png")
    trim.trim([clip])
    finish_jobs("trim")
    trimmed = os.path.join(videos, "trimmed", "clip_trim.mp4")
    ok("exact trim length", os.path.isfile(trimmed) and abs(probe(trimmed).duration - 1.5) < 0.1)

    # ── Converter ─────────────────────────────────────────────────
    convert = page(ConvertPage)
    pages.append(convert)
    convert.add_paths([clip])
    convert.preset.setCurrentIndex(convert.preset.findData("webm_vp9"))
    convert.height_box.setCurrentIndex(convert.height_box.findData(360))
    pump(lambda: convert.player.info is not None)
    ok("after-summary shown", "After: 320x240" in convert.info_label.text())
    convert.height_box.setCurrentIndex(convert.height_box.findData(0))
    convert.fps_box.setCurrentIndex(convert.fps_box.findData(10))
    shot(convert, "media_convert.png")
    convert.convert([clip])
    finish_jobs("convert")
    webm = os.path.join(videos, "converted", "clip.webm")
    ok("webm written", os.path.isfile(webm) and probe(webm).video_codec == "vp9"
       and round(probe(webm).fps) == 10)

    # ── Merger ────────────────────────────────────────────────────
    merge = page(MergePage)
    pages.append(merge)
    merge.add_paths([clip, phone])
    ok("merge order", [os.path.basename(p) for p in merge.files.paths()] == ["clip.mp4", "phone.mp4"])
    ok("differences explained", "differ" in merge.verdict.text())
    ok("default name", merge.name.text() == "clip_merged")
    merge.files.list.setCurrentRow(1)
    merge.files.move(-1)
    ok("reorder", [os.path.basename(p) for p in merge.files.paths()] == ["phone.mp4", "clip.mp4"])
    merge.files.move(1)
    shot(merge, "media_merge.png")
    merge.merge()
    finish_jobs("merge")
    merged = os.path.join(videos, "merged", "clip_merged.mp4")
    info = probe(merged) if os.path.isfile(merged) else None
    ok("merged video", info is not None and (info.width, info.height) == (320, 240)
       and abs(info.duration - 6.0) < 0.3)

    # ── Image Converter ───────────────────────────────────────────
    images = os.path.join(SANDBOX, "images")
    os.makedirs(os.path.join(images, "sub"))
    for name, size, colour in (("red.png", (80, 60), (255, 0, 0)), ("green.png", (60, 80), (0, 255, 0)),
                               ("sub/blue.jpg", (50, 50), (0, 0, 255))):
        Image.new("RGB", size, colour).save(os.path.join(images, name))
    iconvert = page(ImageConvertPage)
    pages.append(iconvert)
    iconvert.add_paths([images])
    ok("images listed", len(iconvert.files.paths()) == 3)
    iconvert.target.setCurrentIndex(iconvert.target.findData("webp"))
    iconvert.pattern.setText("{bad}")
    ok("bad pattern blocks the run", not iconvert.run.isEnabled() and iconvert.pattern_error.text())
    iconvert.pattern.setText("{parent}_{n:03}")
    ok("names previewed", "images_001.webp" in iconvert.names.text())
    iconvert.resize_mode.setCurrentIndex(iconvert.resize_mode.findData("percent"))
    iconvert.percent.setValue(50)
    iconvert.files.select(os.path.join(images, "red.png"))
    ok("before/after", "After: 40x30 WEBP" in iconvert.before_after.text())
    shot(iconvert, "media_iconvert.png")
    iconvert.convert_all()
    finish_jobs("image convert")
    ok("sub-folders kept", os.path.isfile(os.path.join(images, "converted", "sub", "sub_003.webp")))

    # ── Image Sorter ──────────────────────────────────────────────
    sorter_page = page(SorterPage)
    pages.append(sorter_page)
    sorter_page.add_paths([images])
    ok("sorter sees the images", len(sorter_page.images) == 3)
    output = sorter_page.output_root()
    ok("default output", output.endswith("images_sorted"))
    sorter_page.folder_edits[0].setText("keep")
    first = sorter_page.current_image()
    sorter_page.assign(0)
    ok("key copies and advances", os.path.isfile(os.path.join(output, "keep", os.path.basename(first)))
       and sorter_page.position == 1)
    sorter_page.undo_last()
    ok("undo removes the copy and goes back", not os.path.isdir(os.path.join(output, "keep"))
       and sorter_page.position == 0)
    shot(sorter_page, "media_sorter_manual.png")

    sorter_page.tabs.setCurrentIndex(1)
    sorter_page.rule.setCurrentIndex(sorter_page.rule.findData("orientation"))
    sorter_page.preview_rule()
    ok("rule preview", sorter_page.preview_table.rowCount() == 3)
    sorter_page.run_rule()
    finish_jobs("rule sort")
    ok("rule copies", sorted(os.listdir(output)) == ["landscape", "portrait", "sort_log.csv", "square"])
    live = [r for r in sorter.runs(output) if r[2]]
    ok("undo a run", live and sorter.undo_run(output, live[0][0]) == 3)

    try:
        import onnx  # noqa: F401  - only needed to build the test models
        have_onnx = True
    except ImportError:
        have_onnx = False
    if ai.available() and have_onnx:
        classifier, _detector = _onnx_models(SANDBOX)
        sorter_page.tabs.setCurrentIndex(2)
        sorter_page.model_edit.setText(classifier)
        sorter_page.load_model()
        ok("model loaded", sorter_page.model is not None and sorter_page.mapping.rowCount() == 2)
        sorter_page.threshold.setValue(80)
        sorter_page.position = 0
        sorter_page.test_model()
        ok("model test", "→" in sorter_page.test_label.text())
        shot(sorter_page, "media_sorter_ai.png")
        sorter_page.run_ai()
        finish_jobs("AI sort")
        ok("AI copies", os.path.isdir(os.path.join(output, "red")) and os.path.isdir(os.path.join(output, "green")))
    else:
        print("  ..  onnxruntime or onnx not installed - AI sorting skipped")

    for instance in pages:
        instance.toggle_theme()
    QApplication.processEvents()
    ok("theme switch", all(p.theme["name"] == "light" for p in pages))
finally:
    for instance in pages:
        try:
            instance.tool_close()
            instance.close()
        except Exception as exc:
            FAILS.append("closing %s raised %s" % (type(instance).__name__, exc))
    shutil.rmtree(SANDBOX, ignore_errors=True)

print("=" * 60)
if FAILS:
    print("MEDIA GUI TESTS FAILED: %d" % len(FAILS))
    for failure in FAILS:
        print("  x " + failure)
    sys.exit(1)
print("MEDIA GUI TESTS PASSED")
