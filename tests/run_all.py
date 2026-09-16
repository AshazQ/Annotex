#!/usr/bin/env python3
"""Run every test suite and report one verdict.

    python tests/run_all.py                      every suite
    python tests/run_all.py "workspace & display" shell
                                                 just these, by name or file

Each suite runs in its own throwaway home folder and against a time limit,
so none of them can touch your own settings, and a suite that hangs says
which one it was instead of stalling the whole run.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = [("roi core", "roi/test_core.py"),
          ("roi gui", "roi/test_gui.py"),
          ("roi features", "roi/test_features.py"),
          ("labelimg core", "labelimg/test_core.py"),
          ("labelimg gui", "labelimg/test_gui.py"),
          ("shapes gui", "shapes/test_gui.py"),
          ("ai", "ai/test_ai.py"),
          ("cached answers & embedding", "ai/test_cache.py"),
          ("ai download", "ai/test_download.py"),
          ("yolo auto-label", "ai/test_yolo.py"),
          ("dataset tools", "dataset/test_ops.py"),
          ("dataset tools gui", "dataset/test_gui.py"),
          ("workspace & display", "workspace/test_layout.py"),
          ("one keymap", "workspace/test_keymap.py"),
          ("design system", "workspace/test_design.py"),
          ("hostile input", "robust/test_hostile.py"),
          ("packaged build", "robust/test_frozen.py"),
          ("random operations", "robust/test_monkey.py"),
          ("media gui", "media/test_gui.py"),
          ("sort by example", "media/test_reference.py"),
          ("shell", "shell/test_shell.py"),
          ("sessions", "shell/test_sessions.py")]


SUITE_TIMEOUT = 20 * 60          # seconds; a suite this slow is stuck, not slow

# Settings a fresh machine does not have yet, and which would otherwise open a
# welcome sheet that waits for a click - on a build server, for ever.
FIRST_RUN_DONE = """
from annotex.apps.labelimg.config import Settings as LabelImgSettings
from annotex.apps.roi.config import Settings as RoiSettings
for settings in (LabelImgSettings(), RoiSettings()):
    settings.set("first_run_done", True)
"""


def sandbox_env(base):
    """An environment whose every per-user folder is a fresh one.

    Each suite gets its own, so no suite can read or write the settings of
    the person running the tests - and a suite that forgot to make its own
    sandbox behaves the same on a fresh build server as on a machine that
    has been used for months, which is exactly where the two used to differ."""
    home = tempfile.mkdtemp(prefix="annotex_suite_")
    env = dict(base)
    env.update({"HOME": home, "USERPROFILE": home,
                "APPDATA": os.path.join(home, "AppData", "Roaming"),
                "LOCALAPPDATA": os.path.join(home, "AppData", "Local"),
                "XDG_CONFIG_HOME": os.path.join(home, ".config"),
                "PYTHONUNBUFFERED": "1"})
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    subprocess.run([sys.executable, "-c", FIRST_RUN_DONE], env=env,
                   cwd=os.path.dirname(HERE), timeout=120)
    return env


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    wanted = [a for a in argv if not a.startswith("-")]
    suites = [(n, s) for n, s in SUITES if not wanted or n in wanted or s in wanted]
    if wanted and not suites:
        print("No suite called %s.  The suites are: %s"
              % (", ".join(wanted), ", ".join(n for n, _s in SUITES)))
        return 2
    base = dict(os.environ)
    failures = []
    for name, script in suites:
        print("=" * 62)
        print("running %s" % name)
        print("=" * 62, flush=True)
        env = sandbox_env(base)
        try:
            result = subprocess.run([sys.executable, os.path.join(HERE, script)], env=env,
                                    timeout=SUITE_TIMEOUT)
            if result.returncode != 0:
                failures.append(name)
        except subprocess.TimeoutExpired:
            print("TIMED OUT after %d minutes - something in %s is waiting for "
                  "something that will not happen" % (SUITE_TIMEOUT // 60, name), flush=True)
            failures.append("%s (timed out)" % name)
        finally:
            shutil.rmtree(env["HOME"], ignore_errors=True)
    print("=" * 62)
    if failures:
        print("FAILED: %s" % ", ".join(failures))
        return 1
    print("ALL SUITES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
