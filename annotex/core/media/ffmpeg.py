"""Finding, probing and running ffmpeg.  No Qt.

ffmpeg comes from the imageio-ffmpeg package, which ships a static build for
Windows, macOS and Linux, so nobody has to install it by hand.  A system
ffmpeg is used when the bundled one is missing, and ANNOTEX_FFMPEG can point
at any other build.

Probing parses `ffmpeg -i` rather than needing ffprobe, which the bundled
package does not include.  Running streams `-progress` so every job reports a
real percentage, and a cancel request stops the process within a fraction of
a second.
"""

from __future__ import annotations

import collections
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

ENV_VAR = "ANNOTEX_FFMPEG"
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0     # CREATE_NO_WINDOW
_cache = {"exe": "", "encoders": None, "version": ""}


class MediaError(RuntimeError):
    """A user-facing problem with a media file or with ffmpeg itself."""


# ══════════════════════════════════════════════════════════════
# LOCATING
# ══════════════════════════════════════════════════════════════
def find_ffmpeg(refresh: bool = False) -> str:
    if _cache["exe"] and not refresh and os.path.isfile(_cache["exe"]):
        return _cache["exe"]
    candidates = [os.environ.get(ENV_VAR, "")]
    try:
        import imageio_ffmpeg
        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    candidates.append(shutil.which("ffmpeg") or "")
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            _cache.update(exe=candidate, encoders=None, version="")
            return candidate
    return ""


def require_ffmpeg() -> str:
    exe = find_ffmpeg()
    if not exe:
        raise MediaError("ffmpeg was not found. Run `python bootstrap.py` (it installs a "
                         "bundled copy) or install ffmpeg on this machine.")
    return exe


def ffmpeg_version() -> str:
    if not _cache["version"]:
        try:
            out = subprocess.run([require_ffmpeg(), "-hide_banner", "-version"],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=_NO_WINDOW).stdout
            _cache["version"] = out.splitlines()[0].split(" Copyright")[0] if out else "?"
        except Exception as exc:
            _cache["version"] = "unavailable (%s)" % exc
    return _cache["version"]


def encoders() -> set:
    if _cache["encoders"] is None:
        names = set()
        try:
            out = subprocess.run([require_ffmpeg(), "-hide_banner", "-encoders"],
                                 capture_output=True, text=True, timeout=20,
                                 creationflags=_NO_WINDOW).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
                    names.add(parts[1])
        except Exception:
            pass
        _cache["encoders"] = names
    return _cache["encoders"]


def has_encoder(name: str) -> bool:
    return name in encoders()


# ══════════════════════════════════════════════════════════════
# TIME & PATHS
# ══════════════════════════════════════════════════════════════
def parse_time(text) -> float:
    """'90', '1:30', '00:01:30.250' -> seconds.  Raises ValueError."""
    text = str(text).strip()
    if not text:
        raise ValueError("empty time")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError("too many ':' in %r" % text)
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    if seconds < 0:
        raise ValueError("negative time")
    return seconds


def format_time(seconds, precision: int = 3) -> str:
    seconds = max(0.0, float(seconds or 0))
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    text = "%02d:%02d:%02d" % (hours, minutes, secs)
    if precision:
        text += (".%03d" % ms)[:precision + 1]
    return text


def filename_time(seconds) -> str:
    """12.34 -> '00m12s340'; 3723.5 -> '01h02m03s500'.  Sorts correctly."""
    total_ms = int(round(max(0.0, float(seconds)) * 1000))
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return ("%02dh" % hours if hours else "") + "%02dm%02ds%03d" % (minutes, secs, ms)


def unique_path(path) -> str:
    """`path`, or the first free `name_2`, `name_3` … beside it."""
    path = str(path)
    if not os.path.exists(path):
        return path
    folder, name = os.path.split(path)
    stem, ext = (name, "") if os.path.isdir(path) else os.path.splitext(name)
    counter = 2
    while True:
        candidate = os.path.join(folder, "%s_%d%s" % (stem, counter, ext))
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def part_path(final_path) -> str:
    """A hidden working name beside the final file that keeps its extension,
    so ffmpeg still picks the right container."""
    folder, name = os.path.split(str(final_path))
    stem, ext = os.path.splitext(name)
    return os.path.join(folder, ".%s.part%s" % (stem, ext))


def human_size(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


# ══════════════════════════════════════════════════════════════
# PROBING
# ══════════════════════════════════════════════════════════════
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_BITRATE = re.compile(r"bitrate:\s*(\d+)\s*kb/s")
_STREAM = re.compile(r"Stream #\d+:\d+(?:\[[^\]]*\])?(?:\([^)]*\))?:\s*(Video|Audio):\s*(.*)")
_SIZE = re.compile(r"(?<![\w.])(\d{2,5})x(\d{2,5})(?![\w.])")
_FPS = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
_TBR = re.compile(r"(\d+(?:\.\d+)?)(k?)\s*tbr")
_HZ = re.compile(r"(\d+)\s*Hz")
_ROTATION = re.compile(r"rotation of\s*(-?\d+(?:\.\d+)?)\s*degrees")


def _split_top(text):
    """Split on commas that are not inside parentheses."""
    fields, depth, current = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            fields.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        fields.append("".join(current).strip())
    return fields


@dataclass
class MediaInfo:
    path: str
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_codec: str = ""
    pix_fmt: str = ""
    has_video: bool = False
    audio_codec: str = ""
    audio_rate: int = 0
    audio_channels: str = ""
    has_audio: bool = False
    bitrate_kbps: int = 0
    rotation: int = 0
    size_bytes: int = 0

    @property
    def frames(self) -> int:
        return int(round(self.duration * self.fps)) if self.fps else 0

    @property
    def container(self) -> str:
        return os.path.splitext(self.path)[1].lower()

    def describe(self) -> str:
        parts = []
        if self.has_video:
            parts.append("%dx%d" % (self.width, self.height))
            if self.fps:
                parts.append(("%.3g fps" % self.fps))
            parts.append(self.video_codec)
        parts.append(format_time(self.duration, 1))
        parts.append(("audio %s" % self.audio_codec) if self.has_audio else "no audio")
        parts.append(human_size(self.size_bytes))
        return "  ·  ".join(p for p in parts if p)


def parse_probe(path, text) -> MediaInfo:
    info = MediaInfo(path=str(path))
    match = _DURATION.search(text)
    if match:
        info.duration = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    match = _BITRATE.search(text)
    if match:
        info.bitrate_kbps = int(match.group(1))
    in_video = False
    for line in text.splitlines():
        stream = _STREAM.search(line)
        if not stream:
            rotation = _ROTATION.search(line)
            if rotation and in_video and not info.rotation:
                info.rotation = int(round(float(rotation.group(1)))) % 360
            if line.strip().startswith("Stream #"):
                in_video = False
            continue
        kind, rest = stream.groups()
        in_video = False
        fields = _split_top(rest)
        if kind == "Video" and not info.has_video:
            if "attached pic" in rest:
                continue                                  # cover art, not video
            info.has_video = True
            in_video = True
            info.video_codec = fields[0].split()[0] if fields else ""
            if len(fields) > 1:
                info.pix_fmt = fields[1].split("(")[0].strip()
            size = next((_SIZE.search(f) for f in fields[1:] if _SIZE.search(f)), None)
            if size:
                info.width, info.height = int(size.group(1)), int(size.group(2))
            fps = _FPS.search(rest)
            if fps:
                info.fps = float(fps.group(1))
            else:
                tbr = _TBR.search(rest)
                if tbr:
                    info.fps = float(tbr.group(1)) * (1000 if tbr.group(2) else 1)
        elif kind == "Audio" and not info.has_audio:
            info.has_audio = True
            info.audio_codec = fields[0].split()[0] if fields else ""
            hz = _HZ.search(rest)
            if hz:
                info.audio_rate = int(hz.group(1))
            if len(fields) > 2:
                info.audio_channels = fields[2]
    if info.rotation in (90, 270):
        info.width, info.height = info.height, info.width   # ffmpeg autorotates
    return info


def probe(path) -> MediaInfo:
    path = str(path)
    if not os.path.isfile(path):
        raise MediaError("File not found: %s" % path)
    try:
        result = subprocess.run([require_ffmpeg(), "-hide_banner", "-nostdin", "-i", path],
                                capture_output=True, text=True, errors="replace",
                                timeout=60, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise MediaError("ffmpeg took too long to read %s" % os.path.basename(path))
    info = parse_probe(path, result.stderr)
    info.size_bytes = os.path.getsize(path)
    if not info.has_video and not info.has_audio:
        lines = [l for l in result.stderr.strip().splitlines() if l.strip()]
        reason = lines[-1].split(": ", 1)[-1] if lines else "unknown format"
        raise MediaError("%s is not a readable video (%s)" % (os.path.basename(path), reason))
    return info


# ══════════════════════════════════════════════════════════════
# RUNNING
# ══════════════════════════════════════════════════════════════
_PROGRESS_TIME = re.compile(r"^out_time_(?:us|ms)=(\d+)")


@dataclass
class RunResult:
    ok: bool
    cancelled: bool = False
    returncode: int = 0
    error: str = ""
    tail: list = field(default_factory=list)


def _meaningful_error(lines) -> str:
    for line in reversed(list(lines)):
        text = line.strip()
        if text and not text.startswith(("frame=", "size=", "Press [q]")):
            return text
    return "ffmpeg stopped unexpectedly"


def _stop(process) -> None:
    try:
        process.terminate()
        process.wait(timeout=3)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def run_ffmpeg(args, duration: float = 0.0, on_progress=None, cancel=None,
               on_stderr=None) -> RunResult:
    """Run ffmpeg with `args` (inputs, filters, outputs).

    `on_progress(fraction)` is called as the output grows, `cancel` is a
    threading.Event, and `on_stderr(line)` sees every log line (the frame
    extractor reads timestamps from it)."""
    command = [require_ffmpeg(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1",
               "-nostats"] + [str(a) for a in args]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    tail = collections.deque(maxlen=60)

    def drain():
        for raw in process.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            tail.append(line)
            if on_stderr is not None:
                try:
                    on_stderr(line)
                except Exception:
                    pass

    def watch():
        while process.poll() is None:
            if cancel is not None and cancel.is_set():
                _stop(process)
                return
            time.sleep(0.08)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    threading.Thread(target=watch, daemon=True).start()
    for raw in process.stdout:
        line = raw.decode("utf-8", "replace").strip()
        match = _PROGRESS_TIME.match(line)
        if match and on_progress is not None and duration > 0:
            on_progress(min(1.0, int(match.group(1)) / 1e6 / duration))
        elif line == "progress=end" and on_progress is not None:
            on_progress(1.0)
    process.wait()
    reader.join(timeout=5)
    cancelled = bool(cancel is not None and cancel.is_set())
    ok = process.returncode == 0 and not cancelled
    return RunResult(ok=ok, cancelled=cancelled, returncode=process.returncode,
                     error="" if ok else ("cancelled" if cancelled else _meaningful_error(tail)),
                     tail=list(tail))


def ffmpeg_bytes(args, timeout: float = 60.0) -> bytes:
    """Run ffmpeg and return what it writes to stdout (a decoded frame)."""
    result = subprocess.run([require_ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error"]
                            + [str(a) for a in args], capture_output=True, timeout=timeout,
                            creationflags=_NO_WINDOW)
    if result.returncode != 0:
        raise MediaError(_meaningful_error(result.stderr.decode("utf-8", "replace").splitlines()))
    return result.stdout


def open_stream(args):
    """Start ffmpeg writing to stdout for the caller to read incrementally
    (playback).  The caller must close the process."""
    return subprocess.Popen([require_ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error"]
                            + [str(a) for a in args], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=_NO_WINDOW)
