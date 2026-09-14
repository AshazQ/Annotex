"""The work behind the four video tools.  No Qt.

Every function that produces files follows the same rules:

* output goes to a hidden `.name.part` sibling first and is renamed into
  place only when ffmpeg finished cleanly - a cancelled or failed job leaves
  nothing half-written behind;
* an existing file is never overwritten; a free `name_2` is chosen instead;
* progress and cancellation go through the JobContext.
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field

from annotex.core.jobs import JobCancelled
from annotex.core.media.ffmpeg import (MediaError, ffmpeg_bytes, filename_time,
                                       format_time, open_stream, part_path, probe,
                                       run_ffmpeg, unique_path)

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg",
              ".wmv", ".flv", ".ts", ".mts", ".m2ts", ".3gp", ".ogv")

FRAMES_SUFFIX = "_frames"
TRIM_DIR = "trimmed"
CONVERT_DIR = "converted"
MERGE_DIR = "merged"


class _Silent:
    """A stand-in JobContext for callers that just want the result."""

    cancelled = False
    cancel_event = None

    def check(self):
        return None

    def progress(self, *_args, **_kw):
        return None

    def output(self, _path):
        return None

    def warn(self, _message):
        return None


def _ctx(ctx):
    return ctx if ctx is not None else _Silent()


def scan_videos(folder, recursive=True):
    found = []
    for root, dirs, files in os.walk(str(folder)):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")
                         and not d.endswith(FRAMES_SUFFIX)
                         and d not in (TRIM_DIR, CONVERT_DIR, MERGE_DIR))
        for name in sorted(files):
            if name.lower().endswith(VIDEO_EXTS) and not name.startswith("."):
                found.append(os.path.join(root, name))
        if not recursive:
            break
    return found


def _finish(ctx, result, part):
    """Turn an ffmpeg RunResult into success, JobCancelled or MediaError."""
    if result.ok:
        return
    if isinstance(part, (list, tuple)):
        for item in part:
            _discard(item)
    else:
        _discard(part)
    if result.cancelled:
        raise JobCancelled()
    raise MediaError(result.error)


def _discard(path):
    if not path:
        return
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def fps_mode_args():
    return ["-fps_mode", "vfr"]


# ══════════════════════════════════════════════════════════════
# VIDEO → IMAGES
# ══════════════════════════════════════════════════════════════
@dataclass
class FrameOptions:
    mode: str = "interval"            # interval | fps | nth | scene
    interval: float = 1.0             # seconds between frames
    fps: float = 1.0                  # frames per second
    nth: int = 30                     # every Nth frame
    scene: float = 0.3                # 0..1 change threshold
    start: float = 0.0
    end: float = 0.0                  # 0 = to the end
    image_format: str = "jpg"         # jpg | png
    quality: int = 92                 # 1..100 (jpg)
    max_frames: int = 0               # 0 = no limit


def jpeg_qscale(quality) -> int:
    """1..100 → ffmpeg's -q:v 31..2 (lower is better)."""
    quality = max(1, min(100, int(quality)))
    return int(round(31 - (quality - 1) * 29 / 99.0))


def frames_dir_for(video, base_dir=""):
    stem = os.path.splitext(os.path.basename(str(video)))[0]
    return os.path.join(base_dir or os.path.dirname(os.path.abspath(str(video))),
                        stem + FRAMES_SUFFIX)


_SHOWINFO = re.compile(r"Parsed_showinfo.*?\bn:\s*(\d+).*?\bpts_time:\s*(-?[\d.]+(?:e[-+]?\d+)?)")


def _frame_filter(options: FrameOptions) -> str:
    if options.mode == "fps":
        if options.fps <= 0:
            raise MediaError("Frames per second must be above zero")
        chain = "fps=%s" % options.fps
    elif options.mode == "nth":
        if options.nth < 1:
            raise MediaError("Every Nth frame needs N of at least 1")
        chain = "select='not(mod(n\\,%d))'" % int(options.nth)
    elif options.mode == "scene":
        if not 0 < options.scene < 1:
            raise MediaError("Scene sensitivity must be between 0 and 1")
        chain = "select='gt(scene\\,%s)'" % options.scene
    else:
        if options.interval <= 0:
            raise MediaError("The interval must be above zero seconds")
        chain = "fps=1/%s" % options.interval
    return chain + ",showinfo"


def extract_frames(ctx, video, options: FrameOptions, output_dir=""):
    """Write frames of `video` into `<stem>_frames/`.  Returns (folder, count)."""
    ctx = _ctx(ctx)
    info = probe(video)
    if not info.has_video:
        raise MediaError("%s has no video stream" % os.path.basename(video))
    start = max(0.0, float(options.start or 0))
    end = float(options.end or 0)
    if end and end <= start:
        raise MediaError("The end time must be after the start time")
    window = (min(end, info.duration) if end else info.duration) - start
    if window <= 0:
        raise MediaError("The start time is past the end of the video")

    final_dir = unique_path(output_dir or frames_dir_for(video))
    parent = os.path.dirname(final_dir)
    os.makedirs(parent, exist_ok=True)
    part_dir = os.path.join(parent, "." + os.path.basename(final_dir) + ".part")
    _discard(part_dir)
    os.makedirs(part_dir)

    ext = "png" if options.image_format == "png" else "jpg"
    args = []
    if start:
        args += ["-ss", "%.3f" % start]
    args += ["-i", video]
    if end:
        args += ["-t", "%.3f" % window]
    args += ["-an", "-sn", "-vf", _frame_filter(options)] + fps_mode_args()
    if options.max_frames:
        args += ["-frames:v", int(options.max_frames)]
    if ext == "jpg":
        args += ["-q:v", jpeg_qscale(options.quality)]
    args.append(os.path.join(part_dir, "%06d." + ext))

    times = []

    def on_stderr(line):
        match = _SHOWINFO.search(line)
        if match:
            times.append(float(match.group(2)))

    ctx.progress(0.0, "Reading %s" % os.path.basename(video))
    result = run_ffmpeg(args, window, lambda f: ctx.progress(f * 0.97, "Extracting frames"),
                        ctx.cancel_event, on_stderr)
    _finish(ctx, result, part_dir)

    stem = os.path.splitext(os.path.basename(video))[0]
    files = sorted(f for f in os.listdir(part_dir) if f.endswith("." + ext))
    rows, used = [], set()
    for position, name in enumerate(files):
        seconds = start + (times[position] if position < len(times) else position)
        target = "%s_%s" % (stem, filename_time(seconds))
        candidate, counter = target, 2
        while candidate in used:
            candidate = "%s_%d" % (target, counter)
            counter += 1
        used.add(candidate)
        os.replace(os.path.join(part_dir, name), os.path.join(part_dir, candidate + "." + ext))
        rows.append((candidate + "." + ext, "%.3f" % seconds, format_time(seconds)))
    with open(os.path.join(part_dir, "frames.csv"), "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "seconds", "timecode"])
        writer.writerows(rows)
    os.replace(part_dir, final_dir)
    ctx.output(final_dir)
    ctx.progress(1.0, "%d frame(s)" % len(rows))
    return final_dir, len(rows)


def grab_frame(video, seconds, output_dir="", image_format="jpg", quality=92):
    """Save the frame at `seconds` at full size.  Returns the path."""
    final_dir = output_dir or frames_dir_for(video)
    os.makedirs(final_dir, exist_ok=True)
    ext = "png" if image_format == "png" else "jpg"
    stem = os.path.splitext(os.path.basename(str(video)))[0]
    target = unique_path(os.path.join(final_dir, "%s_%s.%s" % (stem, filename_time(seconds), ext)))
    part = part_path(target)
    args = ["-ss", "%.3f" % max(0.0, seconds), "-i", video, "-frames:v", "1", "-an"]
    if ext == "jpg":
        args += ["-q:v", jpeg_qscale(quality)]
    args.append(part)
    result = run_ffmpeg(args)
    if not result.ok or not os.path.isfile(part):
        _discard(part)
        raise MediaError(result.error or "no frame at %s" % format_time(seconds))
    os.replace(part, target)
    log = os.path.join(final_dir, "frames.csv")
    new_log = not os.path.isfile(log)
    with open(log, "a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_log:
            writer.writerow(["file", "seconds", "timecode"])
        writer.writerow([os.path.basename(target), "%.3f" % seconds, format_time(seconds)])
    return target


def preview_size(info, max_width=960, max_height=720):
    """An even-numbered size that fits the box and keeps the aspect ratio."""
    width, height = info.width or 640, info.height or 360
    scale = min(1.0, max_width / float(width), max_height / float(height))
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def decode_frame(video, seconds, size):
    """RGB bytes of the frame at `seconds`, scaled to `size` (w, h)."""
    width, height = size
    data = ffmpeg_bytes(["-ss", "%.3f" % max(0.0, seconds), "-i", video, "-frames:v", "1",
                         "-an", "-vf", "scale=%d:%d" % (width, height), "-f", "rawvideo",
                         "-pix_fmt", "rgb24", "pipe:1"])
    if len(data) < width * height * 3:
        raise MediaError("no frame at %s" % format_time(seconds))
    return data[:width * height * 3]


def playback_process(video, seconds, size, fps):
    width, height = size
    return open_stream(["-ss", "%.3f" % max(0.0, seconds), "-i", video, "-an", "-vf",
                        "fps=%s,scale=%d:%d" % (fps, width, height), "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "pipe:1"])


# ══════════════════════════════════════════════════════════════
# ENCODING PRESETS
# ══════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    ext: str
    video: tuple                      # encoder arguments
    quality_flag: str                 # -crf or -q:v
    quality_range: tuple              # (best, worst) values for the flag
    audio: tuple
    audio_kbps: int
    extra: tuple = ()
    encoder: str = ""


PRESETS = {
    "mp4_h264": Preset("mp4_h264", "MP4 · H.264 (plays everywhere)", ".mp4",
                       ("-c:v", "libx264", "-pix_fmt", "yuv420p"), "-crf", (16, 35),
                       ("-c:a", "aac", "-b:a", "160k"), 160, ("-movflags", "+faststart"),
                       "libx264"),
    "mp4_h265": Preset("mp4_h265", "MP4 · H.265 (smaller files)", ".mp4",
                       ("-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"), "-crf",
                       (18, 38), ("-c:a", "aac", "-b:a", "160k"), 160,
                       ("-movflags", "+faststart"), "libx265"),
    "webm_vp9": Preset("webm_vp9", "WebM · VP9", ".webm",
                       ("-c:v", "libvpx-vp9", "-row-mt", "1"), "-crf", (20, 50),
                       ("-c:a", "libopus", "-b:a", "128k"), 128, (), "libvpx-vp9"),
    "mkv_h264": Preset("mkv_h264", "MKV · H.264", ".mkv",
                       ("-c:v", "libx264", "-pix_fmt", "yuv420p"), "-crf", (16, 35),
                       ("-c:a", "aac", "-b:a", "160k"), 160, (), "libx264"),
    "avi_mpeg4": Preset("avi_mpeg4", "AVI · MPEG-4 (older players)", ".avi",
                        ("-c:v", "mpeg4", "-vtag", "xvid"), "-q:v", (2, 20),
                        ("-c:a", "libmp3lame", "-b:a", "192k"), 192, (), "mpeg4"),
}

SPEEDS = {"fast": ("veryfast", "5"), "balanced": ("medium", "3"), "small": ("slow", "1")}


def quality_value(preset: Preset, quality) -> int:
    """0..100 (100 best) → the encoder's own scale."""
    best, worst = preset.quality_range
    quality = max(0, min(100, int(quality)))
    return int(round(worst - (worst - best) * quality / 100.0))


def video_args(preset: Preset, quality=70, speed="balanced", target_video_kbps=0):
    args = list(preset.video)
    x264_speed, vpx_cpu = SPEEDS.get(speed, SPEEDS["balanced"])
    if preset.encoder in ("libx264", "libx265"):
        args += ["-preset", x264_speed]
    elif preset.encoder == "libvpx-vp9":
        args += ["-deadline", "good", "-cpu-used", vpx_cpu]
    if target_video_kbps:
        kbps = max(64, int(target_video_kbps))
        args += ["-b:v", "%dk" % kbps, "-maxrate", "%dk" % int(kbps * 1.5),
                 "-bufsize", "%dk" % int(kbps * 2)]
    else:
        args += [preset.quality_flag, str(quality_value(preset, quality))]
        if preset.encoder == "libvpx-vp9":
            args += ["-b:v", "0"]
    return args


def exact_codec_args(container):
    """Encoder settings for a frame-accurate trim that keep the container."""
    container = container.lower()
    if container == ".webm":
        preset = PRESETS["webm_vp9"]
    elif container == ".avi":
        preset = PRESETS["avi_mpeg4"]
    else:
        preset = PRESETS["mp4_h264"]
    extra = list(preset.extra) if container in (".mp4", ".mov", ".m4v") else []
    return video_args(preset, quality=85) + list(preset.audio) + extra


# ══════════════════════════════════════════════════════════════
# TRIM
# ══════════════════════════════════════════════════════════════
@dataclass
class Segment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def trim_video(ctx, video, segments, mode="fast", output_dir="", join=False):
    """Cut `segments` out of `video`.  `mode` is "fast" (lossless, snaps to
    keyframes) or "exact" (frame-accurate, re-encodes).  Returns the paths."""
    ctx = _ctx(ctx)
    info = probe(video)
    segments = [s for s in segments if s.duration > 0]
    if not segments:
        raise MediaError("Add at least one segment with an end after its start")
    for segment in segments:
        if segment.start >= info.duration:
            raise MediaError("A segment starts at %s, after the video ends (%s)"
                             % (format_time(segment.start), format_time(info.duration)))
    output_dir = output_dir or os.path.join(os.path.dirname(os.path.abspath(video)), TRIM_DIR)
    os.makedirs(output_dir, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(video))
    ext = ext.lower() or ".mp4"
    total = sum(min(s.end, info.duration) - s.start for s in segments) or 1.0

    pieces, done = [], 0.0
    working_dir = tempfile.mkdtemp(prefix=".annotex_trim_", dir=output_dir) if join else ""
    try:
        for position, segment in enumerate(segments, start=1):
            ctx.check()
            length = min(segment.end, info.duration) - segment.start
            if join:
                target = os.path.join(working_dir, "piece_%03d%s" % (position, ext))
            elif len(segments) == 1:
                target = unique_path(os.path.join(output_dir, "%s_trim%s" % (stem, ext)))
            else:
                target = unique_path(os.path.join(output_dir, "%s_trim_%02d%s"
                                                  % (stem, position, ext)))
            part = part_path(target)
            args = ["-ss", "%.3f" % segment.start, "-i", video, "-t", "%.3f" % length,
                    "-map", "0:v:0?", "-map", "0:a?", "-sn", "-dn"]
            if mode == "exact":
                args += exact_codec_args(ext)
            else:
                args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
            args.append(part)
            label = "Segment %d of %d" % (position, len(segments))
            base = done
            result = run_ffmpeg(args, length,
                                lambda f, b=base, l=length: ctx.progress(
                                    (b + f * l) / total * (0.9 if join else 1.0), label),
                                ctx.cancel_event)
            _finish(ctx, result, part)
            os.replace(part, target)
            pieces.append(target)
            done += length

        if not join:
            for piece in pieces:
                ctx.output(piece)
            ctx.progress(1.0, "%d file(s)" % len(pieces))
            return pieces

        final = unique_path(os.path.join(output_dir, "%s_trimmed%s" % (stem, ext)))
        joined = concat_copy(ctx, pieces, final, total, offset=0.9)
        ctx.output(joined)
        return [joined]
    finally:
        if working_dir:
            _discard(working_dir)


def _concat_list(paths, folder):
    handle, list_path = tempfile.mkstemp(prefix=".annotex_concat_", suffix=".txt", dir=folder)
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        for path in paths:
            escaped = os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")
            out.write("file '%s'\n" % escaped)
    return list_path


def concat_copy(ctx, paths, final, duration, offset=0.0):
    """Join files that share codec settings without re-encoding."""
    ctx = _ctx(ctx)
    folder = os.path.dirname(final)
    list_path = _concat_list(paths, folder)
    part = part_path(final)
    try:
        args = ["-f", "concat", "-safe", "0", "-i", list_path, "-map", "0:v?", "-map", "0:a?",
                "-c", "copy"]
        if final.lower().endswith((".mp4", ".mov", ".m4v")):
            args += ["-movflags", "+faststart"]
        args.append(part)
        result = run_ffmpeg(args, duration,
                            lambda f: ctx.progress(offset + f * (1 - offset), "Joining"),
                            ctx.cancel_event)
        _finish(ctx, result, part)
        os.replace(part, final)
    finally:
        _discard(list_path)
    ctx.progress(1.0, "Joined %d piece(s)" % len(paths))
    return final


# ══════════════════════════════════════════════════════════════
# CONVERT
# ══════════════════════════════════════════════════════════════
@dataclass
class ConvertOptions:
    preset: str = "mp4_h264"
    height: int = 0                   # 0 = keep
    never_upscale: bool = True
    fps: float = 0.0                  # 0 = keep
    quality: int = 70                 # 0..100
    target_mb: float = 0.0            # >0 = aim for this file size instead
    speed: str = "balanced"


def convert_video(ctx, video, options: ConvertOptions, output_dir=""):
    ctx = _ctx(ctx)
    preset = PRESETS.get(options.preset)
    if preset is None:
        raise MediaError("Unknown preset %r" % options.preset)
    info = probe(video)
    if not info.has_video:
        raise MediaError("%s has no video stream" % os.path.basename(video))
    output_dir = output_dir or os.path.join(os.path.dirname(os.path.abspath(video)), CONVERT_DIR)
    os.makedirs(output_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video))[0]
    final = unique_path(os.path.join(output_dir, stem + preset.ext))
    part = part_path(final)

    filters = []
    if options.height and (not options.never_upscale or options.height < info.height):
        filters.append("scale=-2:%d" % int(options.height))
    if options.fps and options.fps > 0:
        filters.append("fps=%s" % options.fps)

    target_kbps = 0
    if options.target_mb and options.target_mb > 0:
        if info.duration <= 0:
            raise MediaError("The video's length is unknown, so a target size cannot be used")
        total_kbps = options.target_mb * 8192.0 / info.duration
        audio_kbps = preset.audio_kbps if info.has_audio else 0
        target_kbps = total_kbps - audio_kbps
        if target_kbps < 64:
            raise MediaError("%.1f MB is too small for %s of video"
                             % (options.target_mb, format_time(info.duration, 0)))

    args = ["-i", video, "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn"]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += video_args(preset, options.quality, options.speed, target_kbps)
    args += list(preset.audio) + list(preset.extra) + [part]
    ctx.progress(0.0, "Converting %s" % os.path.basename(video))
    result = run_ffmpeg(args, info.duration, lambda f: ctx.progress(f, "Encoding"),
                        ctx.cancel_event)
    _finish(ctx, result, part)
    os.replace(part, final)
    ctx.output(final)
    ctx.progress(1.0, "Converted")
    return final


# ══════════════════════════════════════════════════════════════
# MERGE
# ══════════════════════════════════════════════════════════════
@dataclass
class MergeTarget:
    width: int = 0
    height: int = 0
    fps: float = 0.0
    preset: str = "mp4_h264"
    quality: int = 75


def compatibility(infos):
    """(True, []) when the clips can be joined without re-encoding, else
    (False, [reasons])."""
    if len(infos) < 2:
        return True, []
    first = infos[0]
    reasons = []
    checks = (("container", lambda i: i.container),
              ("video codec", lambda i: i.video_codec),
              ("resolution", lambda i: (i.width, i.height)),
              ("pixel format", lambda i: i.pix_fmt),
              ("frame rate", lambda i: round(i.fps, 2)),
              ("audio", lambda i: (i.has_audio, i.audio_codec, i.audio_rate, i.audio_channels)))
    for label, key in checks:
        values = {key(info) for info in infos}
        if len(values) > 1:
            reasons.append("different %s" % label)
    return not reasons, reasons


def merge_videos(ctx, videos, output_path, mode="auto", target: MergeTarget = None):
    """Join `videos` in order.  mode: auto | lossless | normalize."""
    ctx = _ctx(ctx)
    if len(videos) < 2:
        raise MediaError("Add at least two videos to merge")
    infos = [probe(v) for v in videos]
    for info in infos:
        if not info.has_video:
            raise MediaError("%s has no video stream" % os.path.basename(info.path))
    total = sum(i.duration for i in infos) or 1.0
    compatible, reasons = compatibility(infos)
    if mode == "lossless" and not compatible:
        raise MediaError("These clips cannot be joined losslessly: %s" % ", ".join(reasons))
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if mode != "normalize" and compatible:
        final = unique_path(os.path.splitext(output_path)[0] + infos[0].container)
        ctx.progress(0.0, "Joining without re-encoding")
        result = concat_copy(ctx, videos, final, total)
        ctx.output(result)
        return result

    target = target or MergeTarget()
    preset = PRESETS.get(target.preset) or PRESETS["mp4_h264"]
    width = target.width or infos[0].width
    height = target.height or infos[0].height
    width, height = max(2, width // 2 * 2), max(2, height // 2 * 2)
    fps = target.fps or infos[0].fps or 25
    any_audio = any(i.has_audio for i in infos)

    args, labels, extra_inputs = [], [], 0
    for info in infos:
        args += ["-i", info.path]
    filters = []
    for index, info in enumerate(infos):
        filters.append("[%d:v:0]scale=%d:%d:force_original_aspect_ratio=decrease,"
                       "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=%s,"
                       "format=yuv420p[v%d]" % (index, width, height, width, height, fps, index))
        if any_audio:
            if info.has_audio:
                source = "%d:a:0" % index
            else:
                args += ["-f", "lavfi", "-t", "%.3f" % max(0.1, info.duration),
                         "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
                source = "%d:a:0" % (len(infos) + extra_inputs)
                extra_inputs += 1
            filters.append("[%s]aresample=48000,aformat=sample_fmts=fltp:"
                           "channel_layouts=stereo[a%d]" % (source, index))
            labels.append("[v%d][a%d]" % (index, index))
        else:
            labels.append("[v%d]" % index)
    filters.append("%sconcat=n=%d:v=1:a=%d[v]%s" % ("".join(labels), len(infos),
                                                     1 if any_audio else 0,
                                                     "[a]" if any_audio else ""))
    final = unique_path(os.path.splitext(output_path)[0] + preset.ext)
    part = part_path(final)
    args += ["-filter_complex", ";".join(filters), "-map", "[v]"]
    if any_audio:
        args += ["-map", "[a]"] + list(preset.audio)
    args += video_args(preset, target.quality) + list(preset.extra) + [part]
    ctx.progress(0.0, "Converting %d clips to %dx%d · %.3g fps" % (len(infos), width, height, fps))
    result = run_ffmpeg(args, total, lambda f: ctx.progress(f, "Merging"), ctx.cancel_event)
    _finish(ctx, result, part)
    os.replace(part, final)
    ctx.output(final)
    ctx.progress(1.0, "Merged %d clips" % len(infos))
    return final
