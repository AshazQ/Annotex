"""Offline self-test for the video tools, on clips it generates with ffmpeg.

    python run.py --selftest
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

from annotex.core.jobs import CANCELLED, Job, execute
from annotex.core.media.ffmpeg import (MediaError, filename_time, find_ffmpeg, format_time,
                                       parse_probe, parse_time, probe, run_ffmpeg,
                                       unique_path)

from . import core


def make_clip(path, colours=("red", "blue"), seconds=2, size="320x240", fps=25, audio=True):
    args = []
    for colour in colours:
        args += ["-f", "lavfi", "-i", "color=c=%s:s=%s:r=%s:d=%s" % (colour, size, fps, seconds)]
    count = len(colours)
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=%s" % (seconds * count)]
    args += ["-filter_complex", "".join("[%d:v]" % i for i in range(count))
             + "concat=n=%d:v=1:a=0[v]" % count, "-map", "[v]"]
    if audio:
        args += ["-map", "%d:a" % count, "-c:a", "aac"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", str(fps), path]
    result = run_ffmpeg(args)
    if not result.ok:
        raise RuntimeError("could not generate a test clip: %s" % result.error)
    return path


def run_selftest(verbose: bool = True) -> int:
    FAILS = []

    def check(label, got, want):
        if got != want:
            FAILS.append("%s\n     got : %r\n     want: %r" % (label, got, want))

    def ok(label, value):
        if not value:
            FAILS.append("%s (was falsy)" % label)

    def near(label, got, want, tolerance):
        if abs(got - want) > tolerance:
            FAILS.append("%s\n     got : %r\n     want: %r ± %r" % (label, got, want, tolerance))

    # ── pure helpers ──────────────────────────────────────────────
    check("parse seconds", parse_time("90"), 90.0)
    check("parse m:s", parse_time("1:30.5"), 90.5)
    check("parse h:m:s", parse_time("01:02:03.250"), 3723.25)
    check("format time", format_time(3723.25), "01:02:03.250")
    check("filename time", filename_time(12.34), "00m12s340")
    check("filename time hours", filename_time(3723.5), "01h02m03s500")
    check("jpeg qscale", (core.jpeg_qscale(100), core.jpeg_qscale(1)), (2, 31))
    check("quality mapping", core.quality_value(core.PRESETS["mp4_h264"], 100), 16)
    sample = ("  Duration: 00:01:05.50, start: 0.000000, bitrate: 900 kb/s\n"
              "  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), "
              "yuv420p(tv, bt709, progressive), 1920x1080 [SAR 1:1 DAR 16:9], 800 kb/s, "
              "29.97 fps, 29.97 tbr, 30k tbn (default)\n"
              "      Side data:\n        displaymatrix: rotation of -90.00 degrees\n"
              "  Stream #0:1[0x2](eng): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, "
              "stereo, fltp, 96 kb/s (default)\n")
    parsed = parse_probe("x.mp4", sample)
    check("probe parse", (parsed.duration, parsed.video_codec, parsed.pix_fmt, parsed.fps,
                          parsed.audio_codec, parsed.audio_rate, parsed.audio_channels),
          (65.5, "h264", "yuv420p", 29.97, "aac", 48000, "stereo"))
    check("rotation swaps size", (parsed.rotation, parsed.width, parsed.height), (270, 1080, 1920))

    if not find_ffmpeg():
        FAILS.append("ffmpeg not found - install it or run bootstrap.py")
        return _report(FAILS, verbose)

    tmp = tempfile.mkdtemp(prefix="annotex_video_selftest_")
    try:
        clip = make_clip(os.path.join(tmp, "cam1 clip.mp4"))
        info = probe(clip)
        near("probe duration", info.duration, 4.0, 0.1)
        check("probe size", (info.width, info.height, round(info.fps), info.video_codec,
                             info.has_audio), (320, 240, 25, "h264", True))
        check("unique path", os.path.basename(unique_path(clip)), "cam1 clip_2.mp4")
        try:
            probe(os.path.join(tmp, "missing.mp4"))
            FAILS.append("probing a missing file should fail")
        except MediaError:
            pass
        notvideo = os.path.join(tmp, "notes.mp4")
        with open(notvideo, "w") as handle:
            handle.write("not a video")
        try:
            probe(notvideo)
            FAILS.append("probing a text file should fail")
        except MediaError:
            pass

        # ── frames ────────────────────────────────────────────────
        folder, count = core.extract_frames(None, clip, core.FrameOptions(mode="interval",
                                                                          interval=1.0))
        check("interval frames", count, 4)
        check("frames folder name", os.path.basename(folder), "cam1 clip_frames")
        names = sorted(f for f in os.listdir(folder) if f.endswith(".jpg"))
        check("frame names carry the time", names[1], "cam1 clip_00m01s000.jpg")
        ok("frames.csv", os.path.isfile(os.path.join(folder, "frames.csv")))
        ok("no .part left", not any(n.endswith(".part") for n in os.listdir(tmp)))

        folder2, count = core.extract_frames(None, clip, core.FrameOptions(mode="fps", fps=2))
        check("fps frames", count, 8)
        check("second run gets a new folder", os.path.basename(folder2), "cam1 clip_frames_2")
        _f, count = core.extract_frames(None, clip, core.FrameOptions(mode="nth", nth=25,
                                                                     image_format="png"))
        check("every 25th frame", count, 4)
        scene_dir, count = core.extract_frames(None, clip, core.FrameOptions(mode="scene", scene=0.3))
        check("scene change frames", count, 1)
        scene_name = [f for f in os.listdir(scene_dir) if f.endswith(".jpg")][0]
        ok("scene frame at the cut (%s)" % scene_name, "00m02s0" in scene_name or "00m01s9" in scene_name)
        _f, count = core.extract_frames(None, clip, core.FrameOptions(mode="interval", interval=0.5,
                                                                     start=1.0, end=3.0))
        check("time range", count, 4)
        _f, count = core.extract_frames(None, clip, core.FrameOptions(mode="fps", fps=10,
                                                                     max_frames=5))
        check("max frames", count, 5)

        grabbed = core.grab_frame(clip, 3.0, os.path.join(tmp, "grabs"))
        from PIL import Image
        with Image.open(grabbed) as image:
            r, g, b = image.convert("RGB").getpixel((10, 10))
        ok("grabbed frame is from the blue half (%s)" % ((r, g, b),), b > 180 and r < 80)
        size = core.preview_size(info, 160, 160)
        check("preview size", size, (160, 120))
        raw = core.decode_frame(clip, 0.5, size)
        check("decoded frame bytes", len(raw), 160 * 120 * 3)
        ok("decoded frame is red", raw[0] > 180 and raw[2] < 80)

        # ── trim ──────────────────────────────────────────────────
        fast = core.trim_video(None, clip, [core.Segment(1.0, 3.0)], "fast")
        check("fast trim name", os.path.basename(fast[0]), "cam1 clip_trim.mp4")
        near("fast trim duration", probe(fast[0]).duration, 2.0, 1.1)
        exact = core.trim_video(None, clip, [core.Segment(1.0, 1.5), core.Segment(2.5, 3.5)], "exact")
        check("exact trim pieces", [os.path.basename(p) for p in exact],
              ["cam1 clip_trim_01.mp4", "cam1 clip_trim_02.mp4"])
        near("exact trim duration", probe(exact[0]).duration, 0.5, 0.08)
        joined = core.trim_video(None, clip, [core.Segment(0.0, 1.0), core.Segment(3.0, 4.0)],
                                 "exact", join=True)
        near("joined trim duration", probe(joined[0]).duration, 2.0, 0.15)
        ok("no temp folders left in trimmed/",
           not [n for n in os.listdir(os.path.dirname(joined[0])) if n.startswith(".")])
        try:
            core.trim_video(None, clip, [core.Segment(9, 10)])
            FAILS.append("a segment past the end should be refused")
        except MediaError:
            pass

        # ── convert ───────────────────────────────────────────────
        webm = core.convert_video(None, clip, core.ConvertOptions(
            preset="webm_vp9", height=120, fps=10, quality=40, speed="fast"))
        webm_info = probe(webm)
        check("webm result", (webm_info.video_codec, webm_info.width, webm_info.height,
                              round(webm_info.fps), webm_info.audio_codec),
              ("vp9", 160, 120, 10, "opus"))
        upscale = core.convert_video(None, clip, core.ConvertOptions(preset="mkv_h264", height=720))
        check("never upscales", probe(upscale).height, 240)
        avi = core.convert_video(None, clip, core.ConvertOptions(preset="avi_mpeg4"))
        check("avi codec", probe(avi).video_codec, "mpeg4")
        sized = core.convert_video(None, clip, core.ConvertOptions(preset="mp4_h264", target_mb=0.2))
        ok("target size respected (%d bytes)" % os.path.getsize(sized),
           os.path.getsize(sized) <= 0.2 * 1024 * 1024 * 1.5)
        try:
            core.convert_video(None, clip, core.ConvertOptions(target_mb=0.01))
            FAILS.append("an impossible target size should be refused")
        except MediaError:
            pass

        cancelled_job = Job("cancel me", lambda ctx: core.convert_video(
            ctx, clip, core.ConvertOptions(preset="mp4_h265"), os.path.join(tmp, "cancelled")))
        cancelled_job.cancel()
        execute(cancelled_job)
        check("cancelled job state", cancelled_job.state, CANCELLED)
        leftovers = os.listdir(os.path.join(tmp, "cancelled")) if os.path.isdir(
            os.path.join(tmp, "cancelled")) else []
        check("cancel leaves nothing behind", leftovers, [])

        # ── merge ─────────────────────────────────────────────────
        twin = make_clip(os.path.join(tmp, "cam1 later.mp4"), ("green", "yellow"))
        compatible, reasons = core.compatibility([probe(clip), probe(twin)])
        ok("same-settings clips are compatible (%s)" % reasons, compatible)
        lossless = core.merge_videos(None, [clip, twin], os.path.join(tmp, "merged", "same.mp4"))
        near("lossless merge duration", probe(lossless).duration, 8.0, 0.2)

        other = make_clip(os.path.join(tmp, "phone.mp4"), ("white",), seconds=2,
                          size="640x360", fps=30, audio=False)
        compatible, reasons = core.compatibility([probe(clip), probe(other)])
        ok("mixed clips are not compatible", not compatible and "different resolution" in reasons)
        mixed = core.merge_videos(None, [clip, other], os.path.join(tmp, "merged", "mixed.mp4"))
        mixed_info = probe(mixed)
        check("mixed merge matches the first clip", (mixed_info.width, mixed_info.height,
                                                     round(mixed_info.fps), mixed_info.has_audio),
              (320, 240, 25, True))
        near("mixed merge duration", mixed_info.duration, 6.0, 0.3)
        custom = core.merge_videos(None, [other, clip], os.path.join(tmp, "merged", "custom.mp4"),
                                   "normalize", core.MergeTarget(width=426, height=240, fps=15,
                                                                 preset="webm_vp9", quality=30))
        custom_info = probe(custom)
        check("custom merge target", (custom_info.width, custom_info.height,
                                      round(custom_info.fps), custom_info.video_codec,
                                      os.path.splitext(custom)[1]),
              (426, 240, 15, "vp9", ".webm"))
        try:
            core.merge_videos(None, [clip, other], os.path.join(tmp, "merged", "x.mp4"), "lossless")
            FAILS.append("lossless merge of mixed clips should be refused")
        except MediaError:
            pass
        check("scan videos", sorted(os.path.basename(p) for p in core.scan_videos(tmp, False)),
              ["cam1 clip.mp4", "cam1 later.mp4", "notes.mp4", "phone.mp4"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return _report(FAILS, verbose)


def _report(fails, verbose):
    if verbose:
        print("=" * 66)
    if fails:
        print("SELF TEST FAILED - %d problem(s)  (Video tools)\n" % len(fails))
        for entry in fails:
            print("  x " + entry)
        print("=" * 66)
        return 1
    if verbose:
        print("SELF TEST PASSED  (Video tools)")
        print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(run_selftest())
