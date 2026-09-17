#!/usr/bin/env python3
"""The notes for a GitHub release, from its section of CHANGELOG.md.

    python build/release_notes.py v1.1.0 > notes.md

Stops with an error when the changelog has no section for the version, so a
release cannot go out saying nothing about what is in it.  What every
release needs to tell somebody downloading it for the first time - which
file to take, and how to get past a warning about an unsigned application -
is added after the changes, and the application icon above them.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The application icon at the top of the page, taken from the tag itself so
# an old release keeps the icon it shipped with.
HEADER = """<p align="center">
  <img src="https://raw.githubusercontent.com/AshazQ/Annotex/{tag}/annotex/resources/icons/annotex.png" width="120" alt="Annotex">
</p>
<h1 align="center">Annotex {version}</h1>

"""

FIRST_RUN = """
---

### Which file

| You have | Download |
|---|---|
| Windows 10 or 11 | `Annotex-{version}-windows-x64.zip` |
| A Mac with Apple silicon (M1 or later) | `Annotex-{version}-macos-arm64.zip` |
| Linux (glibc 2.35 or newer - Ubuntu 22.04, Fedora 36 and later) | `Annotex-{version}-linux-x64.tar.gz` |

Unpack it anywhere and run **Annotex**.  Nothing is installed; delete the
folder to remove it.  Settings live in your user folder and survive updates.

### The first time you open it

These builds are not signed with a paid certificate, so your system will be
cautious the first time:

- **Windows** may show *"Windows protected your PC"*.  Choose **More info**,
  then **Run anyway**.
- **macOS** may say the app *"cannot be opened"*.  Right-click **Annotex**,
  choose **Open**, then **Open** again.  After that it opens normally.
- **Linux**: if it does not start from the file manager, run `./Annotex` from
  a terminal in the unpacked folder.

AI select downloads its model the first time you use it (Settings → AI).
If something goes wrong, **Diagnostics** (F1) collects what a bug report needs.
"""


def section(text, version):
    """The body of '## <version>' up to the next '## ', or None."""
    pattern = re.compile(r"^##\s+\[?v?%s\]?[^\n]*\n(.*?)(?=^##\s|\Z)" % re.escape(version),
                         re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: release_notes.py <tag>", file=sys.stderr)
        return 2
    version = argv[0].rsplit("/", 1)[-1].lstrip("v")
    with open(os.path.join(ROOT, "CHANGELOG.md"), "r", encoding="utf-8") as handle:
        body = section(handle.read(), version)
    if not body:
        print("CHANGELOG.md has no section for %s - write one before releasing." % version,
              file=sys.stderr)
        return 1
    header = HEADER.format(tag="v" + version, version=version) if os.path.isfile(
        os.path.join(ROOT, "annotex", "resources", "icons", "annotex.png")) else ""
    sys.stdout.write(header + body + "\n" + FIRST_RUN.format(version=version))
    return 0


if __name__ == "__main__":
    sys.exit(main())
