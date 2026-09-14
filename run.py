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
    try:
        if os.path.realpath(sys.executable) == os.path.realpath(target):
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
    try:
        from annotex.app import main as app_main
    except Exception as exc:
        print("Annotex could not load (%s).\n\n"
              "Run the bootstrap script once to set everything up:\n\n"
              "    python bootstrap.py\n" % exc)
        return 2
    return app_main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
