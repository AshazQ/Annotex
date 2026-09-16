"""What a packaged build does differently, and everything that breaks on it.

A build made without a console window has no output streams: `sys.stdout`
and `sys.stderr` are `None`, and any `print()` raises AttributeError.  The
fault handler writes to a stderr that does not exist, so a crash inside
Qt's C++ leaves nothing behind.  Qt's own warnings go the same way.  None of
this shows up when the program is started from a terminal, which is the
only way it is ever started while it is being written - so it is tested
here instead, including in a separate process with the streams actually
taken away.

A locked-down or read-only home directory is checked in the same place,
because it has the same shape: something the machine refuses, which must
never be the reason an application will not start.

    python tests/robust/test_frozen.py
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SANDBOX = tempfile.mkdtemp(prefix="annotex_frozen_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")

# Kept aside now, because half of what follows points sys.stdout at a file.
REAL_STDOUT = sys.stdout
FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label, file=REAL_STDOUT)
    REAL_STDOUT.flush()


# ══════════════════════════════════════════════════════════════
# A BUILD WITH NO STREAMS AT ALL, IN ITS OWN PROCESS
# ══════════════════════════════════════════════════════════════
NO_STREAMS = r'''
import os, sys
sys.path.insert(0, %(root)r)
os.environ["HOME"] = %(sandbox)r
os.environ["XDG_CONFIG_HOME"] = %(config)r
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Exactly what a windowed build on Windows hands the program.
sys.stdout = None
sys.stderr = None

from annotex.core import runlog
runlog.start()

# Every one of these would have ended the program before.
print("a print that would have crashed a windowed build")
from annotex import app
print(app.environment_report())
app._report_problems(["a problem nobody has a terminal to read"])
runlog.note("a note from the run", "test")

# And an error nobody catches still has to be written down somewhere.
raise RuntimeError("the crash a windowed build used to swallow")
'''


def in_a_windowed_build():
    """Run the real code with the streams taken away, as a build has them."""
    folder = os.path.join(SANDBOX, "nostreams")
    config = os.path.join(folder, "config")
    os.makedirs(config, exist_ok=True)
    script = os.path.join(folder, "run_it.py")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(NO_STREAMS % {"root": ROOT, "sandbox": folder, "config": config})
    done = subprocess.run([sys.executable, script], capture_output=True, text=True,
                          timeout=300)
    log = os.path.join(config, "annotex", "annotex.log")
    text = ""
    if os.path.isfile(log):
        with open(log, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    return done, text


def main():
    from annotex.config import first_writable, log_path, user_data_dir
    from annotex.core import runlog

    # ══ the streams, in this process ══════════════════════
    saved = (sys.stdout, sys.stderr)
    try:
        sys.stdout = sys.stderr = None
        runlog._started, runlog._handle = False, None
        handle = runlog.start()
        ok("a log is opened when there are no streams", handle is not None)
        ok("stdout is pointed at it", sys.stdout is handle)
        ok("and so is stderr", sys.stderr is handle)
        print("this print must not raise")
        ok("printing with no streams no longer raises", True)
    except Exception as exc:                                    # noqa: BLE001
        sys.stdout, sys.stderr = saved
        ok("printing with no streams no longer raises (%s)" % exc, False)
    finally:
        sys.stdout, sys.stderr = saved

    ok("what was printed reached the log",
       "this print must not raise" in runlog.recent(400))

    import faulthandler
    ok("the fault handler is armed", faulthandler.is_enabled())

    ok("a note is written", runlog.note("a note for the tests", "test"))
    ok("and can be read back", "a note for the tests" in runlog.recent(50))
    ok("the log lives in the per-user folder",
       str(log_path()).startswith(str(user_data_dir())))

    # ══ Qt's own complaints ═══════════════════════════════
    from PySide6.QtCore import qWarning
    from PySide6.QtWidgets import QApplication
    app_object = QApplication.instance() or QApplication(sys.argv[:1])
    ok("Qt's message handler is installed", runlog.install_qt_handler())
    qWarning("a warning from Qt itself")
    ok("and a Qt warning reaches the log",
       "a warning from Qt itself" in runlog.recent(80))

    # ══ rotation ══════════════════════════════════════════
    big = os.path.join(SANDBOX, "big.log")
    with open(big, "w", encoding="utf-8") as fh:
        fh.write("x" * 4096)
    ok("a small log is left alone", not runlog.rotate(big, limit=10 ** 6))
    ok("a big one is rolled over", runlog.rotate(big, limit=1024))
    ok("and the previous one is kept beside it", os.path.isfile(big + ".1"))
    ok("rotating something that is not there is not an error",
       not runlog.rotate(os.path.join(SANDBOX, "nothing.log")))

    # ══ a home directory that refuses to be written to ════
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("  --  skipping the read-only home checks (running as root)",
              file=REAL_STDOUT)
    else:
        locked = os.path.join(SANDBOX, "locked")
        os.makedirs(locked, exist_ok=True)
        os.chmod(locked, 0o500)
        try:
            fallback = first_writable([os.path.join(locked, "annotex")])
            ok("an unwritable home falls back somewhere that works",
               os.path.isdir(str(fallback)) and not str(fallback).startswith(locked))
            probe = os.path.join(str(fallback), "probe.txt")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            ok("and that somewhere can really be written to", os.path.isfile(probe))
        finally:
            os.chmod(locked, 0o700)

    # ══ saying something with no terminal ═════════════════
    from annotex import app as app_module
    ok("a report can be built at all", "Annotex" in app_module.environment_report())
    try:
        app_module._report_problems(["a pretend problem"])
        ok("problems can be reported without a terminal", True)
    except Exception as exc:                                    # noqa: BLE001
        ok("problems can be reported without a terminal (%s)" % exc, False)
    ok("the problem was written down", "a pretend problem" in runlog.recent(120))

    # A modal dialog is waited on until somebody clicks it.  On a platform
    # that draws nowhere there is nobody to click, so a message must never
    # become a hang - this is exactly what a build server runs.
    ok("nothing is shown where nothing can be dismissed",
       app_module.alert("Annotex", "nobody will ever see this") is False)
    ok("and that is because of the platform, not the display",
       app_module._somebody_is_looking() is False)

    saved_display = os.environ.pop("DISPLAY", None)
    saved_wayland = os.environ.pop("WAYLAND_DISPLAY", None)
    saved_platform = os.environ.pop("QT_QPA_PLATFORM", None)
    try:
        expected = not sys.platform.startswith("linux")
        ok("with no display at all, no window is attempted",
           app_module._has_display() is expected)
        ok("and asking for one anyway is still safe",
           app_module.alert("Annotex", "no display either") is False
           or not sys.platform.startswith("linux"))
    finally:
        for name, value in (("DISPLAY", saved_display),
                            ("WAYLAND_DISPLAY", saved_wayland),
                            ("QT_QPA_PLATFORM", saved_platform)):
            if value is not None:
                os.environ[name] = value

    # ══ the Diagnostics window ════════════════════════════
    from annotex.shell.diagnostics import DiagnosticsDialog, selftest_command
    command = selftest_command()
    ok("the self-tests can be named as a command",
       len(command) >= 2 and "--selftest" in command)
    dialog = DiagnosticsDialog()
    ok("the diagnostics window shows the report",
       "Annotex" in dialog.report.toPlainText())
    ok("and the log beside it", bool(dialog.log_view.toPlainText()))
    dialog.copy_report()
    ok("the whole lot can be copied",
       "diagnostics" in dialog.full_text() and "recent log" in dialog.full_text())
    dialog.refresh()
    ok("refreshing it is safe", bool(dialog.report.toPlainText()))
    dialog._tests_done(0, "ALL SELF TESTS PASSED")
    ok("a passing run is reported as such", "passed" in dialog.status.text().lower())
    dialog._tests_done(1, "SELF TEST FAILED")
    ok("and a failing one is not", "not pass" in dialog.status.text().lower())
    dialog.reject()
    ok("closing it stops anything it started", dialog._thread is None)

    # ══ and the same thing for real, with no streams ══════
    done, log = in_a_windowed_build()
    ok("a build with no streams gets all the way to its own error",
       done.returncode != 0)
    ok("nothing was lost to a missing stdout",
       "a print that would have crashed a windowed build" in log)
    ok("the environment report was written down", "PySide6" in log)
    ok("so was a problem it could not show anybody",
       "a problem nobody has a terminal to read" in log)
    ok("and so was the note", "a note from the run" in log)
    ok("the crash itself is in the log, not lost",
       "the crash a windowed build used to swallow" in log)
    ok("with the traceback that led to it", "Traceback" in log)
    ok("and no AttributeError about NoneType.write",
       "NoneType' object has no attribute 'write'" not in log)

    print("=" * 62, file=REAL_STDOUT)
    if FAILS:
        print("FAILED: %s" % ", ".join(FAILS), file=REAL_STDOUT)
        return 1
    print("PACKAGED-BUILD TESTS PASSED", file=REAL_STDOUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
