"""Application entry point: environment checks, then the suite window.

Everything that can go wrong before there is a window to show a message in
is handled here - a missing Qt, no display, an unreadable settings file - so
the user gets a sentence they can act on instead of a traceback.

    python run.py                          the Home dashboard
    python run.py --tool labelimg          straight into a tool
    python run.py --tool roi <folder>      a tool, with a folder open
    python run.py --selftest               verify the machine, no display needed
    python run.py --check                  print the environment report
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime

from .config import SUITE_NAME, SUITE_VERSION, crash_dir, log_path

MIN_PYTHON = (3, 9)
PACKAGES = (("PySide6", "PySide6-Essentials", "the user interface"),
            ("PIL", "pillow", "reading images"),
            ("openpyxl", "openpyxl", "ROI Studio's spreadsheet"),
            ("lxml", "lxml", "LabelImg Master's Pascal VOC files"))
TOOL_IDS = ("roi", "labelimg", "shapes", "frames", "trim", "vconvert", "merge", "iconvert",
            "sorter")


# ══════════════════════════════════════════════════════════════
# ENVIRONMENT
# ══════════════════════════════════════════════════════════════
def check_environment(require_gui: bool = True):
    """Return (ok, list_of_problems)."""
    problems = []
    if sys.version_info < MIN_PYTHON:
        problems.append("Python %d.%d or newer is required; this is %s"
                        % (MIN_PYTHON[0], MIN_PYTHON[1],
                           ".".join(str(p) for p in sys.version_info[:3])))
    for module, package, purpose in PACKAGES:
        if module == "PySide6" and not require_gui:
            continue
        try:
            __import__(module)
        except Exception:
            problems.append("%s is not installed - needed for %s" % (package, purpose))
    if require_gui and sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                or os.environ.get("QT_QPA_PLATFORM")):
            problems.append("no display found - a desktop session is required")
    return (not problems), problems


def environment_report() -> str:
    _ok, problems = check_environment(require_gui=True)
    lines = ["%s %s" % (SUITE_NAME, SUITE_VERSION),
             "Python %s" % ".".join(str(p) for p in sys.version_info[:3]),
             "Platform %s" % sys.platform]
    for module, _package, _purpose in PACKAGES:
        try:
            imported = __import__(module)
            version = getattr(imported, "__version__", "installed")
            if module == "lxml":
                from lxml import etree
                version = ".".join(str(p) for p in etree.LXML_VERSION[:3])
            lines.append("%-10s %s" % (module, version))
        except Exception:
            lines.append("%-10s MISSING" % module)
    for module, purpose in (("imageio_ffmpeg", "the bundled ffmpeg"),
                            ("onnxruntime", "optional AI sorting")):
        try:
            imported = __import__(module)
            lines.append("%-10s %s" % (module[:10], getattr(imported, "__version__", "installed")))
        except Exception:
            lines.append("%-10s not installed (%s)" % (module[:10], purpose))
    try:
        from .core.media.ffmpeg import ffmpeg_version, find_ffmpeg
        exe = find_ffmpeg()
        lines.append("ffmpeg     %s" % (("%s  (%s)" % (ffmpeg_version(), exe)) if exe
                                        else "NOT FOUND - the video tools need it"))
    except Exception as exc:
        lines.append("ffmpeg     unavailable (%s)" % exc)
    if problems:
        lines.append("")
        lines.append("Problems:")
        lines.extend("  - " + p for p in problems)
    return "\n".join(lines)


def _print_missing(problems) -> None:
    print("%s cannot start.\n" % SUITE_NAME)
    for problem in problems:
        print("  - %s" % problem)
    print("\nThe quickest fix is to run the bootstrap script, which builds a\n"
          "private environment with everything needed:\n\n"
          "    python bootstrap.py\n")


def run_selftests() -> int:
    from .apps.images.selftest import run_selftest as images_selftest
    from .apps.labelimg.selftest import run_selftest as labelimg_selftest
    from .apps.roi.selftest import run_selftest as roi_selftest
    from .apps.shapes.selftest import run_selftest as shapes_selftest
    from .apps.video.selftest import run_selftest as video_selftest
    failures = 0
    for name, test in (("ROI Studio", roi_selftest), ("LabelImg Master", labelimg_selftest),
                       ("LabelImg Shapes", shapes_selftest), ("Video tools", video_selftest),
                       ("Image tools", images_selftest)):
        print("\n%s" % name)
        failures += 1 if test() else 0
    print("\n%s" % ("ALL SELF TESTS PASSED" if not failures
                    else "%d TOOL(S) FAILED THEIR SELF TEST" % failures))
    return 1 if failures else 0


# ══════════════════════════════════════════════════════════════
# CRASH HANDLING
# ══════════════════════════════════════════════════════════════
def _write_crash(exc_type, exc_value, exc_tb) -> str:
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = crash_dir() / ("crash_%s.txt" % stamp)
    try:
        path.write_text("%s %s\n%s\n\n%s" % (SUITE_NAME, SUITE_VERSION,
                                             datetime.now().isoformat(), text),
                        encoding="utf-8")
    except Exception:
        pass
    try:
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write("[%s] %s" % (datetime.now().isoformat(timespec="seconds"), text))
    except Exception:
        pass
    return str(path)


def install_excepthook(window_getter=None) -> None:
    """Unhandled exceptions become a message box and a crash file, never a
    silent death."""
    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        path = _write_crash(exc_type, exc_value, exc_tb)
        sys.stderr.write("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is not None:
                window = window_getter() if window_getter else None
                box = QMessageBox(window)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle("Something went wrong")
                box.setText("%s hit an unexpected error, but your annotations on "
                            "disk are untouched." % SUITE_NAME)
                box.setInformativeText("%s: %s\n\nA report was written to:\n%s"
                                       % (exc_type.__name__, exc_value, path))
                box.exec()
        except Exception:
            pass
    sys.excepthook = hook


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="annotex",
                                     description="%s %s" % (SUITE_NAME, SUITE_VERSION))
    parser.add_argument("folder", nargs="?", default="",
                        help="folder to open (with --tool)")
    parser.add_argument("--tool", choices=TOOL_IDS, default="",
                        help="open this tool instead of the Home dashboard")
    parser.add_argument("--selftest", action="store_true",
                        help="run every tool's offline checks and exit (no GUI needed)")
    parser.add_argument("--check", action="store_true",
                        help="print the environment report and exit")
    parser.add_argument("--reset-settings", action="store_true",
                        help="start the shell from default settings")
    parser.add_argument("--version", action="version",
                        version="%s %s" % (SUITE_NAME, SUITE_VERSION))
    return parser


def run(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        print(environment_report())
        return 0
    if args.selftest:
        return run_selftests()

    ok, problems = check_environment(require_gui=True)
    if not ok:
        _print_missing(problems)
        return 2

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass

    app = QApplication(sys.argv[:1])
    app.setApplicationName(SUITE_NAME)
    app.setApplicationVersion(SUITE_VERSION)
    app.setOrganizationName("Annotex")
    app.setStyle("Fusion")

    from .config import ShellSettings
    settings = ShellSettings()
    if args.reset_settings:
        settings.reset()

    from .shell.window import ShellWindow
    window = ShellWindow(app, settings)
    install_excepthook(lambda: window)
    window.show()

    if args.tool:
        folder = args.folder if args.folder and os.path.isdir(args.folder) else None
        window.open_tool(args.tool, folder)
    elif args.folder:
        print("A folder was given without --tool; opening the Home dashboard.")
    return app.exec()


def main(argv=None) -> int:
    try:
        return run(argv)
    except KeyboardInterrupt:
        return 130
    except Exception:
        path = _write_crash(*sys.exc_info())
        print("%s could not start. A report was written to:\n  %s" % (SUITE_NAME, path))
        traceback.print_exc()
        return 1
