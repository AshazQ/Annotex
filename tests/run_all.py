#!/usr/bin/env python3
"""Run every test suite and report one verdict.

    python tests/run_all.py
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = [("roi core", "roi/test_core.py"),
          ("roi gui", "roi/test_gui.py"),
          ("roi features", "roi/test_features.py"),
          ("labelimg core", "labelimg/test_core.py"),
          ("labelimg gui", "labelimg/test_gui.py"),
          ("shapes gui", "shapes/test_gui.py"),
          ("ai", "ai/test_ai.py"),
          ("ai download", "ai/test_download.py"),
          ("yolo auto-label", "ai/test_yolo.py"),
          ("dataset tools", "dataset/test_ops.py"),
          ("dataset tools gui", "dataset/test_gui.py"),
          ("workspace & display", "workspace/test_layout.py"),
          ("one keymap", "workspace/test_keymap.py"),
          ("hostile input", "robust/test_hostile.py"),
          ("random operations", "robust/test_monkey.py"),
          ("media gui", "media/test_gui.py"),
          ("shell", "shell/test_shell.py")]


def main():
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    failures = []
    for name, script in SUITES:
        print("=" * 62)
        print("running %s" % name)
        print("=" * 62, flush=True)
        result = subprocess.run([sys.executable, os.path.join(HERE, script)], env=env)
        if result.returncode != 0:
            failures.append(name)
    print("=" * 62)
    if failures:
        print("FAILED: %s" % ", ".join(failures))
        return 1
    print("ALL SUITES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
