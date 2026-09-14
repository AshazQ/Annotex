"""Safe file I/O: atomic writes, backups, disk checks, folder locks.

Nothing in this module raises on failure.  Every entry point returns a
(ok, message) pair or a report object, because a write that fails silently
is the one bug that loses a day of annotation work.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from ..config import SUITE_VERSION

MIN_FREE_BYTES = 8 * 1024 * 1024


# ══════════════════════════════════════════════════════════════
# BASICS
# ══════════════════════════════════════════════════════════════
def safe_remove(path) -> bool:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
            return True
    except OSError:
        pass
    return False


def free_bytes(folder):
    try:
        return shutil.disk_usage(str(folder)).free
    except Exception:
        return None


def folder_is_writable(folder):
    """Actually try it.  os.access() lies on Windows network shares."""
    try:
        fd, probe = tempfile.mkstemp(prefix=".fluxbox_wtest_", dir=str(folder))
        os.close(fd)
        os.remove(probe)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def ensure_dir(path) -> bool:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def rotate_backup(path, keep: int = 1, target=None) -> None:
    """Keep the previous good copy before overwriting.

    By default the copy sits beside the file as <name>.bak.  Tools that write
    one small file per image pass `target` instead, so a folder of annotations
    does not fill up with a .bak for every one of them."""
    if keep <= 0 or not os.path.isfile(path):
        return
    destination = str(target) if target else str(path) + ".bak"
    try:
        parent = os.path.dirname(destination)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copy2(path, destination)
    except Exception:
        pass


def timestamped_sibling(path) -> str:
    """<folder>/roi_annotations.xlsx -> <folder>/roi_annotations_20260817_143000.xlsx"""
    root, ext = os.path.splitext(str(path))
    return "%s_%s%s" % (root, datetime.now().strftime("%Y%m%d_%H%M%S"), ext)


def human_bytes(n) -> str:
    try:
        n = float(n)
    except Exception:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f PB" % n


# ══════════════════════════════════════════════════════════════
# ATOMIC WRITE
# ══════════════════════════════════════════════════════════════
def atomic_write(path, write_fn, verify_fn=None, keep_backup: bool = True,
                 backup_to=None):
    """Write via a temp file in the SAME directory then os.replace().

    os.replace is atomic on POSIX and on Windows/NTFS, so a crash, a power
    cut or a full disk can never leave a half-written file behind.  The
    verification callback runs against the temp file BEFORE the swap, so a
    file that does not parse never replaces a good one.

    Returns (ok, error_message).
    """
    path = str(path)
    folder = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(folder):
        return False, "output folder no longer exists"

    free = free_bytes(folder)
    if free is not None and free < MIN_FREE_BYTES:
        return False, "only %s free on disk" % human_bytes(free)

    tmp = None
    try:
        # The temp file keeps the real extension (...xyz.tmp.xlsx) because
        # openpyxl refuses to open anything that does not end in .xlsx.
        ext = os.path.splitext(path)[1]
        fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".",
                                   suffix=".tmp" + ext, dir=folder)
        os.close(fd)
        write_fn(tmp)
        if verify_fn is not None:
            verify_fn(tmp)                     # raises if the file is bad
        if keep_backup:
            rotate_backup(path, target=backup_to)
        os.replace(tmp, path)
        tmp = None
        return True, ""
    except PermissionError as exc:
        return False, "file is locked (open in another program?): %s" % exc
    except Exception as exc:
        return False, str(exc)
    finally:
        if tmp:
            safe_remove(tmp)


def write_text_atomic(path, text, verify_json: bool = False,
                      keep_backup: bool = True, backup_to=None):
    """Convenience wrapper for text payloads."""
    def write(tmp):
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)

    def verify(tmp):
        with open(tmp, "r", encoding="utf-8") as fh:
            json.load(fh)

    return atomic_write(path, write, verify if verify_json else None,
                        keep_backup=keep_backup, backup_to=backup_to)


def read_json(path, default=None):
    """Read a JSON file, falling back to its .bak, then to `default`."""
    for candidate in (str(path), str(path) + ".bak"):
        try:
            if os.path.isfile(candidate):
                with open(candidate, "r", encoding="utf-8") as fh:
                    return json.load(fh)
        except Exception:
            continue
    return default


# ══════════════════════════════════════════════════════════════
# WRITE REPORT
# ══════════════════════════════════════════════════════════════
class WriteReport:
    """What happened during a flush.  The GUI turns this into a status line."""

    def __init__(self):
        self.written = []
        self.errors = []
        self.warnings = []

    @property
    def ok(self) -> bool:
        return not self.errors

    def merge(self, other: "WriteReport") -> "WriteReport":
        self.written.extend(other.written)
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        return self

    def names(self) -> str:
        return ", ".join(os.path.basename(p) for p in self.written)

    def summary(self) -> str:
        if self.errors:
            return "SAVE FAILED - " + "; ".join(self.errors[:2])
        base = "Saved " + (self.names() or "nothing")
        if self.warnings:
            base += "  |  " + "; ".join(self.warnings[:2])
        return base


# ══════════════════════════════════════════════════════════════
# FOLDER LOCK
# ══════════════════════════════════════════════════════════════
def _hostname() -> str:
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "unknown"


def _pid_alive(pid) -> bool:
    try:
        if os.name == "nt":
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        os.kill(int(pid), 0)
        return True
    except (OSError, ProcessLookupError, ValueError, TypeError):
        return False
    except Exception:
        return True                              # unsure -> assume alive


class FolderLock:
    """Stops a second instance from writing the same output files.

    A stale lock (process gone, or older than MAX_AGE) is taken over rather
    than blocking the user forever.  Each tool uses its own lock name, so ROI
    Studio and LabelImg Master can work on the same folder side by side."""

    MAX_AGE = 6 * 3600

    def __init__(self, lock_name: str = ".fluxbox.lock",
                 version: str = SUITE_VERSION):
        self.lock_name = lock_name
        self.version = version
        self.path = ""
        self.held = False

    def acquire(self, folder, force: bool = False):
        """Returns (acquired, message).  A message with acquired=True is a
        note worth showing; with acquired=False it explains the refusal."""
        self.release()
        path = os.path.join(str(folder), self.lock_name)
        other = self._read(path)
        if other and not force and not self._is_stale(other):
            return False, ("another session (pid %s on %s) is using this folder"
                           % (other.get("pid", "?"), other.get("host", "?")))
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"pid": os.getpid(),
                           "host": _hostname(),
                           "started": datetime.now().isoformat(timespec="seconds"),
                           "version": self.version}, fh)
            self.path = path
            self.held = True
            return True, ""
        except Exception as exc:
            # A folder we cannot lock is still a folder we can work in.
            return True, "could not create lock file (%s) - continuing" % exc

    @staticmethod
    def _read(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _is_stale(self, info) -> bool:
        if info.get("host") != _hostname():
            age = self._age(info)
            return age is None or age > self.MAX_AGE
        pid = info.get("pid")
        if pid == os.getpid():
            return True
        if not _pid_alive(pid):
            return True
        age = self._age(info)
        return age is not None and age > self.MAX_AGE

    @staticmethod
    def _age(info):
        try:
            started = datetime.fromisoformat(info.get("started", ""))
            return (datetime.now() - started).total_seconds()
        except Exception:
            return None

    def release(self) -> None:
        if self.held and self.path:
            safe_remove(self.path)
        self.path = ""
        self.held = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.release()
        return False
