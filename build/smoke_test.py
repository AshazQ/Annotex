#!/usr/bin/env python3
"""Run a built application headless and check it actually works.

A build that finished is not a build that runs.  This starts the packaged
program itself - not the source - in a throwaway home directory, and checks
the three things a packaged build gets wrong that running from source never
shows:

    --verify-tools   every tool's window loads, including the seven opened by
                     name that PyInstaller cannot see being imported;
    --selftest       every tool's offline checks pass inside the bundle,
                     with the bundled ffmpeg;
    --check          it starts, reports, and writes its log - which is where
                     a windowed build's output goes, since it has no streams.

    python build/smoke_test.py                    the build in dist/
    python build/smoke_test.py path/to/Annotex    a particular one
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TIMEOUT = 20 * 60


def sandbox_env(home):
    env = dict(os.environ)
    env.update({"QT_QPA_PLATFORM": "offscreen", "HOME": home, "USERPROFILE": home,
                "APPDATA": os.path.join(home, "AppData", "Roaming"),
                "LOCALAPPDATA": os.path.join(home, "AppData", "Local"),
                "XDG_CONFIG_HOME": os.path.join(home, ".config"),
                "ANNOTEX_NO_RELAUNCH": "1"})
    return env


def log_files(home):
    found = []
    for folder, _dirs, files in os.walk(home):
        found += [os.path.join(folder, name) for name in files if name == "annotex.log"]
    return found


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        program = os.path.abspath(argv[0])
    else:
        import build_exe
        program = build_exe.executable()
    if not os.path.isfile(program):
        print("No built program at %s - build it first." % program)
        return 2
    home = tempfile.mkdtemp(prefix="annotex_smoke_")
    env = sandbox_env(home)
    failures = []
    for flag in ("--verify-tools", "--selftest", "--check"):
        print("=" * 62)
        print("%s %s" % (os.path.basename(program), flag), flush=True)
        try:
            done = subprocess.run([program, flag], env=env, cwd=home, timeout=TIMEOUT,
                                  capture_output=True, text=True, errors="replace")
        except subprocess.TimeoutExpired:
            failures.append("%s did not finish within %d minutes" % (flag, TIMEOUT // 60))
            continue
        output = (done.stdout or "") + (done.stderr or "")
        print(output.strip()[-4000:] or "(nothing printed - see the log below)")
        if done.returncode != 0:
            failures.append("%s exited with %d" % (flag, done.returncode))

    logs = log_files(home)
    text = ""
    for path in logs:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text += handle.read()
    print("=" * 62)
    print("log: %s" % (", ".join(logs) or "none written"))
    print(text.strip()[-3000:])
    if "starting" not in text:
        failures.append("the build wrote no log - a windowed build would have been silent")
    if "NoneType' object has no attribute 'write'" in text:
        failures.append("the build tried to print to a stream it does not have")

    print("=" * 62)
    if failures:
        print("SMOKE TEST FAILED:\n  - " + "\n  - ".join(failures))
        return 1
    print("SMOKE TEST PASSED  (%s)" % program)
    return 0


if __name__ == "__main__":
    sys.exit(main())
