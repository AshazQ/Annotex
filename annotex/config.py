"""Suite-wide constants, per-user paths and the shell's own settings.

Free of Qt, like every config module in the suite, so the headless
self-tests can import it on a machine with no display.

Each tool keeps its own settings file (ROI Studio still reads the one it has
always used, so nobody loses their preferences in the move).  This module only
owns what belongs to the suite itself: the theme, the last tool used and the
window geometry.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

SUITE_NAME = "Annotex"
SUITE_SLUG = "annotex"
SUITE_VERSION = "1.1.0"
SUITE_TAGLINE = "Annotation and review tools"

# What Annotex does when it starts.  Home has always been the answer and
# stays the default; the other two need a session to restore, so they fall
# back to Home when there is nothing to reopen.
STARTUP_HOME = "home"
STARTUP_LAST = "last"
STARTUP_ALL = "all"
STARTUP_CHOICES = ((STARTUP_HOME, "Home",
                    "The dashboard, with Continue for where you left off"),
                   (STARTUP_LAST, "The last tool I used",
                    "Straight back into it, with its folder and image"),
                   (STARTUP_ALL, "Everything I had open",
                    "Every tool from last time, in its own tab"))


# ══════════════════════════════════════════════════════════════
# PATHS
# ══════════════════════════════════════════════════════════════
def first_writable(candidates, fallback_name: str = SUITE_SLUG) -> Path:
    """Return the first directory we can actually create and write into.

    A locked-down or read-only home directory must never stop an application
    from starting, so the last resort is a folder in the temp directory."""
    for path in candidates:
        if not path:
            continue
        try:
            path = Path(path)
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return path
        except Exception:
            continue
    fallback = Path(tempfile.gettempdir()) / fallback_name
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return fallback


def user_data_dir(app_name: str = SUITE_NAME, slug: str = SUITE_SLUG) -> Path:
    """The conventional per-user config location on each platform."""
    env = os.environ
    if sys.platform.startswith("win"):
        base = env.get("APPDATA") or env.get("LOCALAPPDATA")
        candidates = [Path(base) / app_name if base else None,
                      Path.home() / "AppData" / "Roaming" / app_name]
    elif sys.platform == "darwin":
        candidates = [Path.home() / "Library" / "Application Support" / app_name]
    else:
        base = env.get("XDG_CONFIG_HOME")
        candidates = [Path(base) / slug if base else None,
                      Path.home() / ".config" / slug]
    return first_writable(candidates, slug)


def crash_dir() -> Path:
    return first_writable([user_data_dir() / "recovery"])


def log_path() -> Path:
    return user_data_dir() / "annotex.log"


# ══════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════
class JsonSettings:
    """A plain JSON settings store with a fixed set of known keys.

    Every read is total - a missing or corrupt file yields the defaults rather
    than an exception, because settings must never be able to stop an
    application from starting.  Unknown keys in the file are ignored, so an
    older build can open a newer file."""

    def __init__(self, path, defaults):
        self.path = Path(path)
        self.defaults = dict(defaults)
        self.data = dict(self.defaults)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if key in self.defaults:
                        self.data[key] = value
        except Exception:
            pass

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    def get(self, key, default=None):
        return self.data.get(key, self.defaults.get(key, default))

    def set(self, key, value) -> None:
        self.data[key] = value
        self.save()

    def update(self, mapping) -> None:
        self.data.update(mapping)
        self.save()

    def reset(self, keep=()) -> None:
        kept = {key: self.data.get(key) for key in keep if key in self.data}
        self.data = dict(self.defaults)
        self.data.update(kept)
        self.save()

    def push_recent(self, folder: str, key: str = "recent_folders",
                    limit: int = 12) -> None:
        folder = str(folder)
        recent = [f for f in (self.get(key, []) or []) if f != folder]
        recent.insert(0, folder)
        self.set(key, recent[:limit])


SHELL_DEFAULTS = {
    "theme": "dark",                 # dark | light | system
    "last_tool": "",
    # What a start looks like.  This replaces reopen_last_tool, which was
    # declared here and read nowhere, so nothing was ever reopened.
    "startup": STARTUP_HOME,         # see STARTUP_CHOICES below
    "offer_recovery": True,          # offer back a run that did not finish
    "window_geometry": "",
    "ui_scale": "auto",              # "auto" or a factor such as 0.9 - see interface_factor
    "auto_scale": 1.0,               # what "auto" worked out on the last screen used
}

# Interface size.  Qt's own scale factor does the work, so text, buttons,
# icons and panels all change together; it is applied as the app starts.
INTERFACE_SIZES = (0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5)
AUTO_FIT = (1280, 760)               # logical pixels the tools are comfortable in


def interface_factor(settings) -> float:
    """The scale factor the Interface size setting asks for (1.0 = none)."""
    value = settings.get("ui_scale", "auto")
    if value in (None, "", "auto"):
        value = settings.get("auto_scale", 1.0)
    try:
        factor = float(value)
    except (TypeError, ValueError):
        factor = 1.0
    return max(0.6, min(2.0, factor))


def auto_factor(width, height) -> float:
    """The largest size - in 5 % steps, never above 100 % - at which a screen
    this big (in unscaled logical pixels) fits the tools without scrolling."""
    try:
        width, height = float(width), float(height)
    except (TypeError, ValueError):
        return 1.0
    if width <= 0 or height <= 0:
        return 1.0
    fit = min(1.0, width / AUTO_FIT[0], height / AUTO_FIT[1])
    return max(0.7, int(fit * 20 + 1e-6) / 20.0)


class ShellSettings(JsonSettings):
    def __init__(self, path=None):
        super().__init__(path or (user_data_dir() / "shell.json"),
                         SHELL_DEFAULTS)
