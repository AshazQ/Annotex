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
            "sorter", "dataset")


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
                            ("numpy", "optional AI select and AI sorting"),
                            ("onnxruntime", "optional AI select and AI sorting")):
        try:
            imported = __import__(module)
            lines.append("%-10s %s" % (module[:10], getattr(imported, "__version__", "installed")))
        except Exception:
            lines.append("%-10s not installed (%s)" % (module[:10], purpose))
    try:
        from .core.ai.sam import discover_models, missing_packages, models_dir
        if missing_packages():
            lines.append("AI select  off - %s missing (python bootstrap.py --ai)"
                         % " and ".join(missing_packages()))
        else:
            found = discover_models()
            lines.append("AI select  %s"
                         % ("%d model(s) in %s" % (len(found), models_dir()) if found
                            else "ready, but no SAM model in %s" % models_dir()))
    except Exception as exc:
        lines.append("AI select  unavailable (%s)" % exc)
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


def _has_display() -> bool:
    """Whether asking Qt for a window will work.

    Worth knowing before asking: without a display Qt does not decline, it
    ends the process."""
    if not sys.platform.startswith("linux"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                or os.environ.get("QT_QPA_PLATFORM"))


# Platforms that draw nowhere anybody is looking.  A modal dialog on one of
# these waits for a button nobody can press, which turns a message into a
# hang - and these are exactly the platforms a build server uses.
HEADLESS_PLATFORMS = ("offscreen", "minimal")


def _somebody_is_looking() -> bool:
    return os.environ.get("QT_QPA_PLATFORM", "") not in HEADLESS_PLATFORMS


def alert(title, text) -> bool:
    """Say something important where there may be no terminal to say it in.

    A packaged build is started by double-clicking an icon: a message
    printed to a console nobody has is a message nobody gets.  Returns
    whether a window was actually shown.

    Nothing is shown where nothing can be dismissed.  This is waited on
    until somebody clicks it, so a build server running the packaged
    application headless would otherwise stop here for good instead of
    reporting the problem and exiting."""
    if not _has_display() or not _somebody_is_looking():
        return False
    try:
        from .ui.dialogs import messages
        return messages.standalone(title, text)
    except Exception:
        return False


def _report_problems(problems) -> None:
    """Everything stopping the program from starting, in every way available."""
    lines = ["%s cannot start." % SUITE_NAME, ""]
    lines += ["  - %s" % problem for problem in problems]
    lines += ["", "The quickest fix is to run the bootstrap script, which builds a",
              "private environment with everything needed:", "", "    python bootstrap.py"]
    text = "\n".join(lines)
    try:
        print(text)
    except Exception:                                   # pragma: no cover
        pass
    try:
        from .core import runlog
        runlog.note(text.replace("\n", "  "), "cannot-start")
    except Exception:
        pass
    alert(SUITE_NAME, text)


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


# One dialog per distinct fault, and never more than this many in a run: an
# error inside a repaint would otherwise fire on every frame and bury the
# screen under message boxes nobody can dismiss fast enough.
MAX_ERROR_DIALOGS = 8
_seen_faults = set()
_dialogs_shown = [0]
_inside_hook = [False]


def _fault_key(exc_type, exc_tb) -> str:
    frame = exc_tb
    while frame is not None and frame.tb_next is not None:
        frame = frame.tb_next
    where = ""
    if frame is not None:
        where = "%s:%d" % (frame.tb_frame.f_code.co_filename, frame.tb_lineno)
    return "%s@%s" % (exc_type.__name__, where)


def install_excepthook(window_getter=None) -> None:
    """Unhandled exceptions become a message box and a crash file, never a
    silent death and never a wall of dialogs.

    The same fault is reported once: the work carries on, because losing a
    repaint is not a reason to lose an afternoon of annotation."""
    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        if _inside_hook[0]:                       # a fault while reporting one
            traceback.print_exception(exc_type, exc_value, exc_tb)
            return
        _inside_hook[0] = True
        try:
            sys.stderr.write("".join(traceback.format_exception(
                exc_type, exc_value, exc_tb)))
            key = _fault_key(exc_type, exc_tb)
            if key in _seen_faults:
                return
            _seen_faults.add(key)
            path = _write_crash(exc_type, exc_value, exc_tb)
            if _dialogs_shown[0] >= MAX_ERROR_DIALOGS:
                return
            from PySide6.QtWidgets import QApplication
            from .ui.dialogs import messages
            if QApplication.instance() is None:
                return
            _dialogs_shown[0] += 1
            window = None
            try:
                window = window_getter() if window_getter else None
            except Exception:
                window = None
            messages.error(
                window, "Something went wrong",
                "%s hit an unexpected error, but your annotations on disk are untouched.  "
                "You can carry on working.\n\n%s: %s\n\nA report was written to:\n%s"
                % (SUITE_NAME, exc_type.__name__, exc_value, path),
                detail="".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        except Exception:
            pass
        finally:
            _inside_hook[0] = False

    sys.excepthook = hook

    # A worker thread that dies quietly is how a job appears to hang forever.
    try:
        import threading

        def thread_hook(args):
            if issubclass(args.exc_type, SystemExit):
                return
            hook(args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = thread_hook
    except Exception:
        pass


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


def apply_interface_size(settings) -> None:
    """Interface size works through Qt's scale factor, which must be in place
    before the application object exists.  A QT_SCALE_FACTOR someone set
    themselves always wins."""
    if os.environ.get("QT_SCALE_FACTOR"):
        return
    try:
        from .config import interface_factor
        factor = interface_factor(settings)
    except Exception:
        return
    if abs(factor - 1.0) > 0.001:
        os.environ["QT_SCALE_FACTOR"] = "%.2f" % factor


def run(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        print(environment_report())
        return 0
    if args.selftest:
        return run_selftests()

    ok, problems = check_environment(require_gui=True)
    if not ok:
        _report_problems(problems)
        return 2

    from .config import ShellSettings
    settings = ShellSettings()
    if args.reset_settings:
        settings.reset()
    apply_interface_size(settings)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    # Qt's own warnings - a missing image format, a platform plugin that
    # would not load - go to the log rather than to a stream a packaged
    # build does not have.  Installed before the application exists, so
    # nothing it says on the way up is lost.
    try:
        from .core import runlog
        runlog.install_qt_handler()
    except Exception:
        pass

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

    from .shell.window import ShellWindow
    window = ShellWindow(app, settings)
    install_excepthook(lambda: window)
    window.show()

    if args.tool:
        folder = args.folder if args.folder and os.path.isdir(args.folder) else None
        window.open_tool(args.tool, folder)
    else:
        if args.folder:
            print("A folder was given without --tool; opening the Home dashboard.")
        # After the window is up, so a dialog has something to sit over and
        # a slow folder does not hold back the first paint.  An explicit
        # --tool always wins over both.
        from PySide6.QtCore import QTimer

        def _start():
            try:
                if not window.offer_recovery():
                    window.restore_startup()
            except Exception:
                pass
        QTimer.singleShot(0, _start)
    return app.exec()


def main(argv=None) -> int:
    try:
        return run(argv)
    except KeyboardInterrupt:
        return 130
    except Exception:
        info = sys.exc_info()
        path = _write_crash(*info)
        text = ("%s could not start.\n\n%s: %s\n\nA report was written to:\n%s"
                % (SUITE_NAME, info[0].__name__, info[1], path))
        try:
            print(text)
            traceback.print_exc()
        except Exception:                               # pragma: no cover
            pass
        # The one failure nobody can be told about in a window they already
        # have, because there is no window yet.
        alert(SUITE_NAME, text)
        return 1
