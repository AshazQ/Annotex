#!/usr/bin/env python3
"""Build Annotex as an application somebody can download and run.

Run this on the platform you are building for - PyInstaller cannot
cross-compile, so a Windows build is made on Windows, a macOS one on macOS
and a Linux one on Linux.  The release workflow does exactly that, once per
platform, on every version tag.

    python build/build_exe.py                  a folder in dist/Annotex
    python build/build_exe.py --archive        ... and a zip / tar.gz of it to ship
    python build/build_exe.py --onefile        a single file instead of a folder
    python build/build_exe.py --clean          remove previous build artefacts first
    python build/build_exe.py --check-tag v1.1.0
                                               stop unless the tag matches the version

A folder is the default, not a single file.  A single-file build unpacks
itself into a temporary directory on every start - a couple of hundred
megabytes with Qt and onnxruntime in it - which makes it slow to open and
is exactly the behaviour antivirus software is suspicious of.  A folder
starts straight away; the archive is what gets downloaded.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")
WORK = os.path.join(ROOT, "build", "_work")
NAME = "Annotex"

sys.path.insert(0, ROOT)


def suite_version() -> str:
    """The one version number, from the one place it is kept."""
    from annotex.config import SUITE_VERSION
    return SUITE_VERSION


def platform_label() -> str:
    """"windows-x64", "macos-arm64", "linux-x64" - for the archive's name."""
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(
        machine, machine or "unknown")
    return "%s-%s" % (system, arch)


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


def _installed(module) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def pyinstaller_command(python, onefile=False, console=False, with_ai=True):
    separator = ";" if os.name == "nt" else ":"
    command = [python, "-m", "PyInstaller", "--name", NAME, "--distpath", DIST,
               "--workpath", WORK, "--specpath", WORK, "--noconfirm",
               "--onefile" if onefile else "--onedir",
               "--add-data", "%s%sannotex/resources" % (
                   os.path.join(ROOT, "annotex", "resources"), separator)]
    if not console:
        command.append("--windowed")
    icon = os.path.join(ROOT, "annotex", "resources", "icons",
                        "annotex.ico" if os.name == "nt" else "annotex.icns"
                        if sys.platform == "darwin" else "annotex.png")
    if os.path.isfile(icon) and sys.platform in ("win32", "darwin"):
        command += ["--icon", icon]

    # Seven of the ten tools are opened by name when their tile is clicked (see
    # shell/registry.py), which no static reading of the imports can see.
    # Without this, a build starts, shows every tile, and fails on seven of
    # them with "No module named ...".  So every module of the package goes
    # in, whether or not anything imports it by name.
    command += ["--collect-submodules", "annotex"]

    excluded = ["PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
                "PySide6.QtMultimedia", "PySide6.QtWebEngineCore", "tkinter",
                "matplotlib", "scipy", "pytest", "onnx", "PyInstaller"]
    if not with_ai:
        excluded += ["numpy", "onnxruntime"]
    for module in excluded:
        command += ["--exclude-module", module]
    for module in ("PySide6.QtSvg", "lxml.etree", "lxml._elementpath"):
        command += ["--hidden-import", module]
    if with_ai:
        command += ["--collect-binaries", "onnxruntime",
                    "--collect-data", "onnxruntime",
                    "--hidden-import", "onnxruntime"]
    # The bundled ffmpeg binary travels with the application.
    command += ["--collect-binaries", "imageio_ffmpeg", "--collect-data", "imageio_ffmpeg"]
    command.append(os.path.join(ROOT, "run.py"))
    return command


def built_path(onefile=False) -> str:
    """Where PyInstaller put what it made."""
    if sys.platform == "darwin" and not onefile:
        bundle = os.path.join(DIST, NAME + ".app")
        if os.path.isdir(bundle):
            return bundle
    if onefile:
        return os.path.join(DIST, NAME + (".exe" if os.name == "nt" else ""))
    return os.path.join(DIST, NAME)


def executable(onefile=False) -> str:
    """The program inside the build, for the smoke test."""
    built = built_path(onefile)
    if built.endswith(".app"):
        return os.path.join(built, "Contents", "MacOS", NAME)
    if onefile:
        return built
    return os.path.join(built, NAME + (".exe" if os.name == "nt" else ""))


def sign_for_macos(path) -> None:
    """An ad-hoc signature, so macOS lets the app open at all.

    Without any signature Gatekeeper reports the app as damaged.  With an
    ad-hoc one it opens after right-click → Open.  Opening it with a plain
    double-click needs a paid Apple Developer ID, which this is not."""
    if sys.platform != "darwin" or not path.endswith(".app"):
        return
    try:
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", path], check=True)
        print("Signed ad hoc: %s" % path)
    except Exception as exc:
        print("Could not sign the app (it will still run after right-click → Open): %s" % exc)


def make_archive(onefile=False) -> str:
    """Pack the build into the one file a person downloads."""
    source = built_path(onefile)
    label = "%s-%s-%s" % (NAME, suite_version(), platform_label())
    if sys.platform.startswith("linux"):
        target = os.path.join(DIST, label + ".tar.gz")
        # tar keeps the executable bit; a zip made here would lose it, and the
        # program would unpack as a file nobody can run.
        with tarfile.open(target, "w:gz") as archive:
            archive.add(source, arcname=os.path.basename(source))
        return target
    target = os.path.join(DIST, label + ".zip")
    if sys.platform == "darwin":
        # ditto keeps the bundle's symlinks, signature and permissions, which
        # Python's zipfile does not.
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        source, target], check=True)
        return target
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        if os.path.isfile(source):
            archive.write(source, os.path.basename(source))
        else:
            base = os.path.dirname(source)
            for folder, _dirs, files in os.walk(source):
                for name in files:
                    full = os.path.join(folder, name)
                    archive.write(full, os.path.relpath(full, base))
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the application.")
    parser.add_argument("--onefile", action="store_true",
                        help="one file instead of a folder (slower to start)")
    parser.add_argument("--onedir", action="store_true",
                        help="a folder (the default; kept for older scripts)")
    parser.add_argument("--archive", action="store_true",
                        help="also pack the build into a zip or tar.gz to ship")
    parser.add_argument("--clean", action="store_true",
                        help="delete previous build output first")
    parser.add_argument("--console", action="store_true",
                        help="keep a console window (useful for debugging)")
    parser.add_argument("--no-ai", action="store_true",
                        help="leave onnxruntime and numpy out, even when they are "
                             "installed (smaller; no AI select, no AI or example sorting)")
    parser.add_argument("--check-tag", default="",
                        help="stop unless this tag (e.g. v1.1.0) matches the version")
    args = parser.parse_args(argv)

    version = suite_version()
    if args.check_tag:
        tag = args.check_tag.strip()
        if tag.rsplit("/", 1)[-1].lstrip("v") != version:
            print("The tag %s does not match the version in annotex/config.py (%s). "
                  "Change one of them so a release cannot ship under the wrong number."
                  % (tag, version))
            return 3
        print("Tag %s matches version %s." % (tag, version))

    python = sys.executable
    if args.clean:
        for path in (DIST, WORK):
            shutil.rmtree(path, ignore_errors=True)
        print("Cleaned.")
    if not ensure_pyinstaller(python):
        return 2

    with_ai = not args.no_ai and _installed("numpy") and _installed("onnxruntime")
    print("Building %s %s for %s  ·  AI features %s"
          % (NAME, version, platform_label(), "included" if with_ai else "left out"))
    command = pyinstaller_command(python, onefile=args.onefile, console=args.console,
                                  with_ai=with_ai)
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print("\nBuild failed (exit code %d)." % result.returncode)
        return result.returncode
    built = built_path(args.onefile)
    sign_for_macos(built)
    print("\nBuilt: %s" % built)
    print("Run:   %s" % executable(args.onefile))
    if args.archive:
        print("Packed: %s" % make_archive(args.onefile))
    return 0


if __name__ == "__main__":
    sys.exit(main())
