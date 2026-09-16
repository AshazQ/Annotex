"""The log, and making sure a packaged build can still say anything.

An application started from a terminal reports its troubles to that
terminal.  One started by double-clicking an icon has no terminal, and on
Windows a build made without a console window has no output streams at all:
`sys.stdout` and `sys.stderr` are `None`, and the very first `print()`
anywhere in the program raises

    AttributeError: 'NoneType' object has no attribute 'write'

which is a crash caused entirely by trying to explain something.  The same
build sends a fault handler's stack trace to a stderr nobody will ever
read, so a crash inside Qt's C++ leaves nothing behind at all.

So the first thing that happens, before anything can go wrong, is this:
every stream is pointed somewhere real, the fault handler is given a file,
and both of them are the log in the per-user folder that the Diagnostics
window can open.  Nothing here raises - a log that cannot be written must
not be the reason an application will not start - and nothing here imports
Qt, because it runs before there is any.
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime

from ..config import SUITE_NAME, SUITE_VERSION, log_path

LOG_LIMIT = 2 * 1024 * 1024             # bytes before the log is rolled over
KEEP_ROLLED = 1                         # how many previous logs to keep

_handle = None                          # the open log file, for its lifetime
_lock = threading.Lock()
_started = False


# ══════════════════════════════════════════════════════════════
# WRITING SOMEWHERE REAL
# ══════════════════════════════════════════════════════════════
class _Tee:
    """Writes to the stream it was given and to the log as well.

    Used for a packaged build that does have streams: whatever they are
    attached to, the log is a place the person can actually be pointed at."""

    def __init__(self, stream, log):
        self._stream = stream
        self._log = log

    def write(self, text):
        for target in (self._stream, self._log):
            try:
                target.write(text)
            except Exception:
                pass
        return len(text) if text else 0

    def flush(self):
        for target in (self._stream, self._log):
            try:
                target.flush()
            except Exception:
                pass

    def isatty(self):
        try:
            return bool(self._stream.isatty())
        except Exception:
            return False

    def fileno(self):
        # Whoever wants a real descriptor wants the log's: it is the half of
        # this pair that is certain to have one.
        return self._log.fileno()

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", None) or "utf-8"

    def close(self):                                    # pragma: no cover
        self.flush()


def rotate(path=None, limit: int = LOG_LIMIT) -> bool:
    """Roll the log over once it is too big.  True if it was rolled."""
    target = str(path or log_path())
    try:
        if os.path.getsize(target) < int(limit):
            return False
    except OSError:
        return False
    try:
        for index in range(KEEP_ROLLED, 0, -1):
            older = "%s.%d" % (target, index)
            if index == KEEP_ROLLED:
                try:
                    os.remove(older)
                except OSError:
                    pass
            else:                                       # pragma: no cover
                try:
                    os.replace(older, "%s.%d" % (target, index + 1))
                except OSError:
                    pass
        os.replace(target, "%s.1" % target)
        return True
    except Exception:
        return False


def start(force_bind: bool = False):
    """Open the log, point the streams at it, and arm the fault handler.

    Called once, as early as anything can be.  `force_bind` replaces the
    streams even when they look usable, which is how the tests stand in for
    a windowed build."""
    global _handle, _started
    with _lock:
        if _started and _handle is not None:
            return _handle
        _started = True
        rotate()
        try:
            target = str(log_path())
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            # Line buffered, so a log read during a hang is not a blank file.
            _handle = open(target, "a", encoding="utf-8", errors="replace",
                           buffering=1)
        except Exception:
            _handle = None
        handle = _handle

    if handle is None:
        return None
    try:
        handle.write("\n%s\n[%s] %s %s starting (python %s on %s)\n"
                     % ("-" * 60, datetime.now().isoformat(timespec="seconds"),
                        SUITE_NAME, SUITE_VERSION,
                        ".".join(str(p) for p in sys.version_info[:3]), sys.platform))
    except Exception:
        pass

    frozen = bool(getattr(sys, "frozen", False))
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            if stream is None or force_bind:
                # Nowhere to write at all: the log becomes the stream, and
                # every print() in the program is saved instead of fatal.
                setattr(sys, name, handle)
            elif frozen:
                setattr(sys, name, _Tee(stream, handle))
        except Exception:
            pass

    try:
        import faulthandler
        # Given a file, not left on stderr: in a windowed build stderr is
        # where a crash goes to be forgotten.
        faulthandler.enable(file=handle, all_threads=True)
    except Exception:
        pass
    return handle


def handle():
    """The open log file, or None."""
    return _handle


def note(text, level: str = "info") -> bool:
    """Put one line in the log.  Never raises, never blocks for long."""
    target = _handle
    try:
        if target is None:
            with open(str(log_path()), "a", encoding="utf-8", errors="replace") as fallback:
                fallback.write("[%s] %s %s\n" % (
                    datetime.now().isoformat(timespec="seconds"), level, text))
            return True
        target.write("[%s] %s %s\n" % (
            datetime.now().isoformat(timespec="seconds"), level, text))
        target.flush()
        return True
    except Exception:
        return False


def recent(limit: int = 200) -> str:
    """The tail of the log, for the Diagnostics window.  "" on any problem."""
    try:
        with open(str(log_path()), "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        return "".join(lines[-int(limit):])
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════
# QT'S OWN COMPLAINTS
# ══════════════════════════════════════════════════════════════
_qt_installed = False


def install_qt_handler() -> bool:
    """Send Qt's warnings to the log instead of to nowhere.

    Qt says useful things - a missing image format, a layout that cannot
    work, a platform plugin it could not load - and in a packaged build it
    says them to a stream that does not exist.  They belong in the log a
    person can send on."""
    global _qt_installed
    if _qt_installed:
        return True
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return False
    levels = {QtMsgType.QtDebugMsg: "qt-debug", QtMsgType.QtInfoMsg: "qt-info",
              QtMsgType.QtWarningMsg: "qt-warning",
              QtMsgType.QtCriticalMsg: "qt-critical",
              QtMsgType.QtFatalMsg: "qt-fatal"}

    def handler(kind, context, message):
        where = ""
        try:
            if context is not None and context.file:
                where = "  (%s:%d)" % (context.file, context.line)
        except Exception:
            where = ""
        note("%s%s" % (message, where), levels.get(kind, "qt"))

    try:
        qInstallMessageHandler(handler)
    except Exception:
        return False
    _qt_installed = True
    return True
