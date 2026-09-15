#!/usr/bin/env python3
"""One-command setup for Annotex.

Creates a private virtual environment beside this file, installs everything
the suite needs into it, verifies the result, and offers to create a desktop
shortcut.  Standard library only, so it runs on a bare Python.

    python bootstrap.py                 set up and verify
    python bootstrap.py --run           set up, then start the suite
    python bootstrap.py --shortcut      also create a desktop shortcut
    python bootstrap.py --upgrade       re-install / update the dependencies
    python bootstrap.py --system        install into the current environment
    python bootstrap.py --offline DIR   install from a folder of wheels
    python bootstrap.py --ai            also install the optional AI extras

Nothing outside this folder is touched, except the desktop shortcut you ask
for.  No administrator rights are needed.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import venv

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(HERE, ".venv")
MIN_PYTHON = (3, 9)
APP_NAME = "Annotex"

REQUIREMENTS = [
    ("PySide6-Essentials", ">=6.5", "the user interface"),
    ("pillow", ">=9.0", "reading images"),
    ("openpyxl", ">=3.0", "ROI Studio's spreadsheet"),
    ("lxml", ">=4.9", "LabelImg Master's Pascal VOC files"),
    ("imageio-ffmpeg", ">=0.5", "ffmpeg for the video tools"),
]
VERIFY_MODULES = ("PySide6", "PIL", "openpyxl", "lxml", "imageio_ffmpeg")
AI_PACKAGES = ["onnxruntime>=1.17", "numpy"]


def _supports_colour() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


COLOUR = _supports_colour()


def say(text="", kind="plain") -> None:
    prefixes = {"step": ("==> ", "\033[1;36m"), "ok": ("  ok  ", "\033[32m"),
                "warn": ("  !!  ", "\033[33m"), "fail": ("  xx  ", "\033[31m"),
                "plain": ("", "")}
    prefix, colour = prefixes.get(kind, ("", ""))
    line = prefix + text
    if COLOUR and colour:
        line = colour + line + "\033[0m"
    print(line, flush=True)


def rule() -> None:
    say("-" * 62)


def venv_python(root: str = VENV_DIR) -> str:
    if os.name == "nt":
        return os.path.join(root, "Scripts", "python.exe")
    candidate = os.path.join(root, "bin", "python3")
    return candidate if os.path.isfile(candidate) else os.path.join(root, "bin", "python")


def check_python() -> bool:
    version = ".".join(str(p) for p in sys.version_info[:3])
    if sys.version_info < MIN_PYTHON:
        say("Python %s found, but %d.%d or newer is required."
            % (version, MIN_PYTHON[0], MIN_PYTHON[1]), "fail")
        say("Install a newer Python from https://www.python.org/downloads/")
        return False
    say("Python %s on %s" % (version, platform.platform()), "ok")
    return True


def venv_moved(root: str = VENV_DIR) -> bool:
    """True when .venv was created somewhere else and then moved or renamed
    with its folder: its activate script and pip still point at the old path,
    so `source .venv/bin/activate` silently falls back to the system Python."""
    activate = os.path.join(root, "Scripts" if os.name == "nt" else "bin", "activate")
    try:
        with open(activate, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return False
    return os.path.abspath(root) not in text


def create_venv(upgrade: bool = False) -> str:
    python = venv_python()
    moved = os.path.isfile(python) and venv_moved()
    if os.path.isfile(python) and not upgrade and not moved:
        say("Using the existing environment in .venv", "ok")
        return python
    if moved:
        say("The .venv folder was moved from another location - rebuilding it", "warn")
    say("Creating a private environment in .venv", "step")
    try:
        venv.EnvBuilder(with_pip=True, clear=moved, upgrade=upgrade and not moved).create(VENV_DIR)
    except Exception as exc:
        say("Could not create the environment: %s" % exc, "fail")
        if sys.platform.startswith("linux"):
            say("On Debian or Ubuntu you may need:  sudo apt install python3-venv")
        return ""
    python = venv_python()
    if not os.path.isfile(python):
        say("The environment was created but has no interpreter", "fail")
        return ""
    say("Environment ready", "ok")
    return python


def ensure_pip(python: str) -> bool:
    try:
        subprocess.run([python, "-m", "pip", "--version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        pass
    say("pip is missing from this interpreter; bootstrapping it", "warn")
    try:
        subprocess.run([python, "-m", "ensurepip", "--upgrade"], check=True)
        return True
    except Exception as exc:
        say("Could not install pip: %s" % exc, "fail")
        return False


def pip_install(python: str, packages, offline_dir="") -> bool:
    command = [python, "-m", "pip", "install", "--upgrade"]
    if offline_dir:
        command += ["--no-index", "--find-links", offline_dir]
    command += list(packages)
    say("Installing: %s" % ", ".join(packages), "step")
    try:
        result = subprocess.run(command, cwd=HERE)
    except Exception as exc:
        say("Could not run pip: %s" % exc, "fail")
        return False
    if result.returncode != 0:
        say("pip reported a problem (exit code %d)" % result.returncode, "fail")
        if not offline_dir:
            say("If this machine has no internet access, download the wheels "
                "elsewhere and use:  python bootstrap.py --offline <folder>")
        return False
    return True


def verify(python: str) -> bool:
    say("Verifying the installation", "step")
    script = ("import sys\nrows = []\n"
              "for name in %r:\n"
              "    try:\n"
              "        m = __import__(name)\n"
              "        rows.append((name, getattr(m, '__version__', 'ok')))\n"
              "    except Exception as e:\n"
              "        print('MISSING %%s: %%s' %% (name, e)); sys.exit(1)\n"
              "print('\\n'.join('%%s %%s' %% row for row in rows))\n" % (VERIFY_MODULES,))
    try:
        result = subprocess.run([python, "-c", script], cwd=HERE,
                                capture_output=True, text=True)
    except Exception as exc:
        say("Could not run the check: %s" % exc, "fail")
        return False
    if result.returncode != 0:
        say(result.stdout.strip() or result.stderr.strip(), "fail")
        return False
    for line in result.stdout.strip().splitlines():
        say(line, "ok")
    return True


def run_selftest(python: str) -> bool:
    say("Running the offline self-tests", "step")
    try:
        result = subprocess.run([python, "run.py", "--selftest"], cwd=HERE)
    except Exception as exc:
        say("Could not run the self-test: %s" % exc, "warn")
        return False
    return result.returncode == 0


def desktop_dir() -> str:
    for candidate in (os.path.join(os.path.expanduser("~"), "Desktop"),
                      os.path.join(os.path.expanduser("~"), "desktop")):
        if os.path.isdir(candidate):
            return candidate
    return ""


def make_shortcut(python: str) -> bool:
    """Create a launcher appropriate to the platform.  Best effort only."""
    target = os.path.join(HERE, "run.py")
    desktop = desktop_dir()

    if os.name == "nt":
        pythonw = python.replace("python.exe", "pythonw.exe")
        launcher = pythonw if os.path.isfile(pythonw) else python
        path = os.path.join(desktop or HERE, "%s.cmd" % APP_NAME)
        body = '@echo off\r\nstart "" "%s" "%s" %%*\r\n' % (launcher, target)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            say("Shortcut written to %s" % path, "ok")
            return True
        except Exception as exc:
            say("Could not write the shortcut: %s" % exc, "warn")
            return False

    if sys.platform == "darwin":
        path = os.path.join(desktop or HERE, "%s.command" % APP_NAME)
        body = '#!/bin/sh\ncd "%s"\nexec "%s" "%s" "$@"\n' % (HERE, python, target)
    else:
        applications = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
        try:
            os.makedirs(applications, exist_ok=True)
            entry = os.path.join(applications, "annotex.desktop")
            with open(entry, "w", encoding="utf-8") as fh:
                fh.write("[Desktop Entry]\nType=Application\nName=%s\n"
                         "Comment=ROI Studio and LabelImg Master\n"
                         "Exec=\"%s\" \"%s\"\nPath=%s\nTerminal=false\n"
                         "Categories=Graphics;Science;\n" % (APP_NAME, python, target, HERE))
            os.chmod(entry, 0o755)
            say("Menu entry written to %s" % entry, "ok")
        except Exception as exc:
            say("Could not write the menu entry: %s" % exc, "warn")
        path = os.path.join(desktop or HERE, "%s.sh" % APP_NAME.replace(" ", "-"))
        body = '#!/bin/sh\ncd "%s"\nexec "%s" "%s" "$@"\n' % (HERE, python, target)

    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.chmod(path, 0o755)
        say("Launcher written to %s" % path, "ok")
        return True
    except Exception as exc:
        say("Could not write the launcher: %s" % exc, "warn")
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Set up %s on this machine." % APP_NAME)
    parser.add_argument("--run", action="store_true",
                        help="start the suite when setup finishes")
    parser.add_argument("--shortcut", action="store_true",
                        help="create a desktop shortcut / menu entry")
    parser.add_argument("--upgrade", action="store_true",
                        help="refresh the environment and dependencies")
    parser.add_argument("--system", action="store_true",
                        help="install into the current interpreter instead of .venv")
    parser.add_argument("--offline", default="",
                        help="install from this folder of .whl files")
    parser.add_argument("--no-selftest", action="store_true",
                        help="skip the offline verification step")
    parser.add_argument("--ai", action="store_true",
                        help="also install onnxruntime and numpy, for the AI select "
                             "tool in the labelling tools and AI sorting in the "
                             "Image Sorter")
    args = parser.parse_args(argv)

    rule()
    say("%s setup" % APP_NAME)
    rule()
    if not check_python():
        return 2
    if args.system:
        python = sys.executable
        say("Installing into the current interpreter", "warn")
    else:
        python = create_venv(upgrade=args.upgrade)
        if not python:
            return 2
    if not ensure_pip(python):
        return 2
    if not pip_install(python, ["%s%s" % (n, s) for n, s, _w in REQUIREMENTS], args.offline):
        return 2
    if args.ai and not pip_install(python, AI_PACKAGES, args.offline):
        say("the AI extras could not be installed; everything else works", "warn")
    if not verify(python):
        say("Something is still missing. Try:  python bootstrap.py --upgrade", "fail")
        return 2
    if not args.no_selftest:
        if run_selftest(python):
            say("Self-tests passed", "ok")
        else:
            say("The self-tests reported problems - see the output above", "warn")
    if args.shortcut:
        make_shortcut(python)

    rule()
    say("Ready.")
    say("Start it with:   python run.py")
    say("or jump in:      python run.py --tool labelimg   (or --tool roi)")
    rule()
    if args.run:
        try:
            subprocess.Popen([python, os.path.join(HERE, "run.py")], cwd=HERE)
        except Exception as exc:
            say("Could not start the suite: %s" % exc, "warn")
    return 0


if __name__ == "__main__":
    sys.exit(main())
