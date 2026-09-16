#!/usr/bin/env python3
"""Annotex launcher.

Run this file.  It works from a checkout, from a virtual environment, or from
a bundled executable, and it tells you plainly what is missing rather than
failing with a traceback.

    python run.py                          the Home dashboard
    python run.py --tool labelimg          straight into LabelImg Master
    python run.py --tool roi <folder>      ROI Studio with a batch open
    python run.py --selftest               verify the machine, no display needed
    python run.py --check                  print the environment report
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _venv_python():
    """The interpreter inside a local .venv, when there is one."""
    for name in (os.path.join(HERE, ".venv", "Scripts", "python.exe"),
                 os.path.join(HERE, ".venv", "bin", "python3"),
                 os.path.join(HERE, ".venv", "bin", "python")):
        if os.path.isfile(name):
            return name
    return ""


def _relaunch_in_venv():
    """If a private environment exists and this interpreter is not it, use it,
    so double-clicking run.py works even when the system Python has none of
    the dependencies."""
    if os.environ.get("ANNOTEX_NO_RELAUNCH"):
        return False
    target = _venv_python()
    if not target:
        return False
    # Compare environments, not interpreter files: a venv's python is a symlink
    # to the system one, so their real paths are identical.
    try:
        if os.path.normcase(os.path.realpath(sys.prefix)) == os.path.normcase(
                os.path.realpath(os.path.join(HERE, ".venv"))):
            return False
    except Exception:
        return False
    try:
        import PySide6                                       # noqa: F401
        import lxml                                          # noqa: F401
        return False                      # this interpreter is already fine
    except Exception:
        pass
    os.environ["ANNOTEX_NO_RELAUNCH"] = "1"
    try:
        os.execv(target, [target, os.path.abspath(__file__)] + sys.argv[1:])
    except Exception:
        return False
    return True


def main():
    if _relaunch_in_venv():
        return 0
    # Before anything else, because everything else might need to say
    # something: point the output streams at a real file (a windowed build
    # on Windows has none at all, and printing to one is a crash), and give
    # the fault handler somewhere a person can find - otherwise a crash
    # inside Qt's C++ ends as a bare "Segmentation fault" with no trace of
    # the Python that led to it.
    try:
        from annotex.core import runlog
        runlog.start()
    except Exception:
        try:
            import faulthandler
            faulthandler.enable(all_threads=True)
        except Exception:
            pass
    try:
        from annotex.app import main as app_main
    except Exception as exc:
        _cannot_load(exc)
        return 2
    return app_main(sys.argv[1:])


def _cannot_load(exc):
    """Say that the program could not start, wherever there is to say it."""
    message = ("Annotex could not load (%s).\n\n"
               "Run the bootstrap script once to set everything up:\n\n"
               "    python bootstrap.py" % exc)
    try:
        print(message)
    except Exception:
        pass
    # A packaged build has no terminal, so the message has to be a window -
    # but only if there is a display to put one on, since asking Qt for a
    # window without one ends the process rather than returning.
    try:
        if sys.platform.startswith("linux") and not (
                os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return
        # A dialog on a platform that draws nowhere waits for a click that
        # never comes, which would turn this message into a hang.
        if os.environ.get("QT_QPA_PLATFORM", "") in ("offscreen", "minimal"):
            return
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv[:1])
        QMessageBox.critical(None, "Annotex", message)
        del app
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
