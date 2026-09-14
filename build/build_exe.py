#!/usr/bin/env python3
"""Build a single-file executable of the suite with PyInstaller.

Run this on the platform you are building for - PyInstaller cannot
cross-compile, so a Windows .exe must be built on Windows, a macOS .app on
macOS, and a Linux binary on Linux.

    python build/build_exe.py              build for this platform
    python build/build_exe.py --onedir     a folder instead of one file
    python build/build_exe.py --clean      remove previous build artefacts
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build", "_work")
NAME = "Annotex"


def ensure_pyinstaller(python):
    try:
        subprocess.run([python, "-m", "PyInstaller", "--version"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        print("Installing PyInstaller…")
        try:
            subprocess.run([python, "-m", "pip", "install", "pyinstaller>=6.0"], check=True)
            return True
        except Exception as exc:
            print("Could not install PyInstaller: %s" % exc)
            return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the executable.")
    parser.add_argument("--onedir", action="store_true",
                        help="produce a folder instead of a single file")
    parser.add_argument("--clean", action="store_true",
                        help="delete previous build output first")
    parser.add_argument("--console", action="store_true",
                        help="keep a console window (useful for debugging)")
    args = parser.parse_args(argv)

    python = sys.executable
    if args.clean:
        for path in (DIST, WORK):
            shutil.rmtree(path, ignore_errors=True)
        print("Cleaned.")
    if not ensure_pyinstaller(python):
        return 2

    separator = ";" if os.name == "nt" else ":"
    command = [python, "-m", "PyInstaller", "--name", NAME, "--distpath", DIST,
               "--workpath", WORK, "--specpath", WORK, "--noconfirm",
               "--onedir" if args.onedir else "--onefile",
               "--add-data", "%s%sannotex/resources" % (
                   os.path.join(ROOT, "annotex", "resources"), separator)]
    if not args.console:
        command.append("--windowed")
    for module in ("PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
                   "PySide6.Qt3DCore", "PySide6.QtMultimedia",
                   "PySide6.QtWebEngineCore", "tkinter", "matplotlib", "numpy",
                   "scipy", "pytest"):
        command += ["--exclude-module", module]
    for module in ("PySide6.QtSvg", "lxml.etree", "lxml._elementpath"):
        command += ["--hidden-import", module]
    # the bundled ffmpeg binary travels with the executable
    command += ["--collect-binaries", "imageio_ffmpeg", "--collect-data", "imageio_ffmpeg"]
    command.append(os.path.join(ROOT, "run.py"))

    print("Building %s…" % NAME)
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print("\nBuild failed (exit code %d)." % result.returncode)
        return result.returncode
    print("\nBuilt into: %s" % DIST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
