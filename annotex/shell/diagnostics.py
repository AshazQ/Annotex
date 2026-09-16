"""What this machine has, what went wrong, and where to find the proof.

`--check` and `--selftest` have always been able to answer "why is AI select
off?" and "does everything work here?", and both have always needed a
terminal to ask from.  Somebody who downloaded a built application has no
terminal and no reason to want one, so the same two answers live here, in a
window, next to the log and the crash reports they refer to.

The self-tests run as a separate process rather than inside this one.  They
are the part most likely to fall over - that is what they are for - and a
diagnostic that can take the application down with it is not much of a
diagnostic.
"""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QPlainTextEdit

from ..config import SUITE_NAME, SUITE_VERSION, crash_dir, log_path, user_data_dir
from ..core import runlog
from ..ui import design
from ..ui.dialogs.common import Dialog, hint
from ..ui.jobs import open_location

SELFTEST_TIMEOUT = 15 * 60          # seconds; the full set is not quick


def selftest_command():
    """How to run the offline checks again, as a separate process.

    A packaged build is its own interpreter and takes the flag directly; a
    checkout needs its launcher named."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--selftest"]
    here = os.path.dirname(os.path.abspath(__file__))           # annotex/shell
    root = os.path.dirname(os.path.dirname(here))
    launcher = os.path.join(root, "run.py")
    if os.path.isfile(launcher):
        return [sys.executable, launcher, "--selftest"]
    return [sys.executable, "-m", "annotex", "--selftest"]      # pragma: no cover


def _monospace(widget):
    """A report is columns of text; it has to be read in a fixed pitch."""
    widget.setObjectName("Mono")
    try:
        widget.setFont(design.mono_font())
    except Exception:                                   # pragma: no cover
        pass
    return widget


# ══════════════════════════════════════════════════════════════
class _SelfTestRun(QObject):
    """The offline checks, in their own process, off the interface thread."""

    finished = Signal(int, str)

    def run(self):
        try:
            done = subprocess.run(selftest_command(), capture_output=True, text=True,
                                  timeout=SELFTEST_TIMEOUT)
            output = (done.stdout or "") + (done.stderr or "")
            self.finished.emit(int(done.returncode), output)
        except subprocess.TimeoutExpired:
            self.finished.emit(2, "The checks did not finish within %d minutes and "
                                  "were stopped." % (SELFTEST_TIMEOUT // 60))
        except Exception as exc:                                # noqa: BLE001
            self.finished.emit(2, "The checks could not be started: %s" % exc)


class DiagnosticsDialog(Dialog):
    """The environment report, the log, and a way to send both on."""

    def __init__(self, parent=None):
        super().__init__(parent, "Diagnostics",
                         "What %s found on this machine, and where it writes things "
                         "down.  Worth copying into a bug report." % SUITE_NAME,
                         width=680, height=560)
        self._thread = None
        self._runner = None

        self.report = _monospace(QPlainTextEdit())
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.report.setMinimumHeight(190)
        self.body.addWidget(QLabel("This machine"))
        self.body.addWidget(self.report, 1)

        self.body.addWidget(hint("Folders: settings in %s · crash reports in %s"
                                 % (user_data_dir(), crash_dir())))

        self.log_view = _monospace(QPlainTextEdit())
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setMinimumHeight(140)
        self.body.addWidget(QLabel("Recent log"))
        self.body.addWidget(self.log_view, 1)

        self.status = QLabel("")
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)

        self.copy_button = self.add_button(
            "Copy report", slot=self.copy_report,
            tooltip="Put everything above on the clipboard")
        self.add_button("Open log folder", slot=self.open_logs,
                        tooltip=str(log_path().parent))
        self.add_button("Open crash folder", slot=self.open_crashes,
                        tooltip=str(crash_dir()))
        self.test_button = self.add_button(
            "Run self-tests", slot=self.run_selftests,
            tooltip="Check every tool on this machine.  Takes a few minutes; no "
                    "display needed, and nothing of yours is touched.")
        self.add_close_button()
        self.refresh()

    # ── what it shows ─────────────────────────────────────
    def refresh(self) -> None:
        self.report.setPlainText(self._report_text())
        self.log_view.setPlainText(runlog.recent(300)
                                   or "Nothing has been written to the log yet.")
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())

    @staticmethod
    def _report_text() -> str:
        try:
            from ..app import environment_report
            return environment_report()
        except Exception as exc:                                # noqa: BLE001
            return "The report could not be built: %s" % exc

    def full_text(self) -> str:
        return "%s %s diagnostics\n\n%s\n\n--- recent log ---\n%s" % (
            SUITE_NAME, SUITE_VERSION, self.report.toPlainText(),
            self.log_view.toPlainText())

    # ── what its buttons do ───────────────────────────────
    def copy_report(self) -> None:
        try:
            QGuiApplication.clipboard().setText(self.full_text())
            self._say("Copied - paste it into a bug report.", "good")
        except Exception as exc:                                # noqa: BLE001
            self._say("It could not be copied: %s" % exc, "danger")

    def open_logs(self) -> None:
        self._open(str(log_path().parent))

    def open_crashes(self) -> None:
        self._open(str(crash_dir()))

    def _open(self, folder) -> None:
        try:
            if not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            open_location(folder)
        except Exception as exc:                                # noqa: BLE001
            self._say("That folder could not be opened: %s\n%s" % (exc, folder), "warning")

    def run_selftests(self) -> None:
        if self._thread is not None:
            return
        self.test_button.setEnabled(False)
        self._say("Checking every tool - this takes a few minutes…", "info")
        self._thread = QThread(self)
        self._runner = _SelfTestRun()
        self._runner.moveToThread(self._thread)
        self._thread.started.connect(self._runner.run)
        self._runner.finished.connect(self._tests_done)
        self._thread.start()

    def _tests_done(self, code, output) -> None:
        self._stop_thread()
        self.test_button.setEnabled(True)
        runlog.note("self-tests finished with %d" % code, "selftest")
        self.log_view.setPlainText(output.strip() or "The checks said nothing.")
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())
        if code == 0:
            self._say("Every tool passed its checks on this machine.", "good")
        else:
            self._say("Something did not pass.  The output is above - Copy report "
                      "sends it on.", "danger")

    def _stop_thread(self) -> None:
        thread, self._thread, self._runner = self._thread, None, None
        if thread is None:
            return
        try:
            thread.quit()
            thread.wait(3000)
        except Exception:
            pass

    def _say(self, text, level="info") -> None:
        names = {"good": "HintGood", "warning": "HintWarn", "danger": "HintDanger",
                 "info": "Hint"}
        self.status.setObjectName(names.get(level, "Hint"))
        self.status.setText(text)
        try:                            # the name decides the colour, so re-polish
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        except Exception:
            pass

    def reject(self):
        self._stop_thread()
        super().reject()

    def closeEvent(self, event):
        self._stop_thread()
        super().closeEvent(event)
