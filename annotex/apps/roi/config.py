"""Application-wide constants, paths and settings.

Deliberately free of any Qt import so the core package stays testable on a
machine with no GUI stack at all.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "ROI Studio"
APP_SLUG = "roi_studio"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Polygon ROI Annotation"

# ── output file names ─────────────────────────────────────────
XLSX_NAME = "roi_annotations.xlsx"
JSON_NAME = "roi_annotations.json"
MAP_NAME = "roi_map.json"
LOCK_NAME = ".roi_studio.lock"
DRAFT_NAME = ".roi_studio_draft.json"
AUDIT_NAME = ".roi_studio_audit.jsonl"
PROJECT_SETTINGS_NAME = ".roi_studio.json"
REPORT_NAME = "roi_report.html"

# Images already handled are copied into these.  `done_roi` was removed on
# purpose - the printed preview already proves an image was annotated.
NO_ROI_DIR = "no_roi"
PRINTED_DIR = "printed_roi"
OUTPUT_DIRS = (NO_ROI_DIR, PRINTED_DIR)

# ── image support ─────────────────────────────────────────────
# The same list the labelling tools read, so one folder holds the same
# number of images whichever tool opens it.
IMG_EXTS = (".jpg", ".jpeg", ".jfif", ".png", ".bmp", ".gif", ".ppm", ".pgm",
            ".pbm", ".webp", ".tif", ".tiff")

# ── geometry rules ────────────────────────────────────────────
MIN_POINTS = 3
MAX_POINTS_PER_POLY = 500
MAX_POLYS_PER_IMAGE = 50
MIN_POLY_AREA_PX = 4.0
NDIGITS = 2                      # normalised coordinate precision
CIRCLE_SEGMENTS = 64             # points used to render a circle as a polygon

# ── interaction ───────────────────────────────────────────────
SNAP_RADIUS = 12.0               # screen px to snap a closing click
VERTEX_RADIUS = 7.0              # screen px to grab a vertex
EDGE_TOLERANCE = 6.0             # screen px to hit an edge
ZOOM_MIN = 0.05
ZOOM_MAX = 32.0
ZOOM_STEP = 1.15

# ── safety ────────────────────────────────────────────────────
MIN_FREE_BYTES = 8 * 1024 * 1024
AUTOSAVE_SECONDS = 20
MAX_UNDO_STEPS = 200

SHAPE_POLYGON = "polygon"
SHAPE_RECT = "rect"
SHAPE_CIRCLE = "circle"
SHAPE_TYPES = (SHAPE_POLYGON, SHAPE_RECT, SHAPE_CIRCLE)

ROW_TYPES = ("roi", "no_roi", "comment")

# ── spreadsheet schema ────────────────────────────────────────
# One row per image, exactly as the previous build produced, with a single
# appended column recording what each shape was drawn as.  Nothing that
# existed before changed name, position or meaning.
CANON_COLUMNS = ["image_name", "roi_key", "site_id", "cam_number",
                 "pixel_coords", "normalized_coords", "total_polygons",
                 "image_width", "image_height", "row_type", "comment",
                 "shape_types"]

SITE_VIEW = ["image_name", "roi_key", "site_id", "cam_number",
             "roi_coordinate", "total_polygons", "row_type", "comment",
             "shape_types"]

FULL_VIEW = list(CANON_COLUMNS)

TEXT_COLUMNS = {"image_name", "roi_key", "site_id", "cam_number",
                "pixel_coords", "normalized_coords", "roi_coordinate",
                "row_type", "comment", "shape_types"}

COLUMN_WIDTHS = {"image_name": 46, "roi_key": 18, "site_id": 14,
                 "cam_number": 11, "pixel_coords": 60,
                 "normalized_coords": 60, "roi_coordinate": 60,
                 "total_polygons": 14, "image_width": 12,
                 "image_height": 12, "row_type": 10, "comment": 30,
                 "shape_types": 22}


# ══════════════════════════════════════════════════════════════
# PATHS
# ══════════════════════════════════════════════════════════════
def _first_writable(candidates):
    """Return the first path we can actually create, else a temp dir.

    Portable by construction: no registry, no platform branches beyond the
    conventional per-OS config location, and a temp-dir fallback so a locked
    down or read-only home directory can never stop the app from starting."""
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
    fallback = Path(tempfile.gettempdir()) / APP_SLUG
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return fallback


def user_data_dir() -> Path:
    """Per-user directory for settings, logs and recovery drafts."""
    env = os.environ
    if sys.platform.startswith("win"):
        base = env.get("APPDATA") or env.get("LOCALAPPDATA")
        candidates = [Path(base) / APP_NAME if base else None,
                      Path.home() / "AppData" / "Roaming" / APP_NAME]
    elif sys.platform == "darwin":
        candidates = [Path.home() / "Library" / "Application Support" / APP_NAME]
    else:
        base = env.get("XDG_CONFIG_HOME")
        candidates = [Path(base) / APP_SLUG if base else None,
                      Path.home() / ".config" / APP_SLUG]
    return _first_writable(candidates)


def settings_path() -> Path:
    return user_data_dir() / "settings.json"


def log_path() -> Path:
    return user_data_dir() / "roi_studio.log"


def crash_dir() -> Path:
    return _first_writable([user_data_dir() / "recovery"])


# ══════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════
DEFAULT_SETTINGS = {
    "theme": "dark",                    # dark | light | system
    "use_site_format": False,
    "recent_folders": [],
    "printed_roi_colour": "#00dc64",    # burnt-in preview colour ONLY
    "printed_roi_fill_alpha": 70,
    "printed_roi_line_width": 3,
    "printed_label_colour": "#ffff00",
    "roi_opacity": 28,                  # live canvas, 0-100
    "roi_line_width": 2,
    "show_crosshair": True,
    "show_minimap": True,
    "show_coordinates": True,
    "snap_to_edges": True,
    "snap_to_shapes": True,
    "auto_advance_on_save": True,
    "autosave_seconds": AUTOSAVE_SECONDS,
    "confirm_clear_all": True,
    "first_run_done": False,
    "shortcuts": {},                    # action id -> key sequence override
    "export_columns": [],               # empty means "use the view default"
    "api_push_enabled": False,
    "api_push_url": "",
    "api_push_header": "",
    "api_push_timeout": 15,
    "window_geometry": "",
    "window_state": "",
    # Workspace: what is folded away for a bigger image.
    "side_collapsed": False,
    "filmstrip_folded": False,
}


class Settings:
    """A plain JSON settings store.

    Every read is total - a missing or corrupt file yields defaults rather
    than an exception, because settings must never be able to stop the
    application from starting.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else settings_path()
        self.data = dict(DEFAULT_SETTINGS)
        # Keys a batch's own settings file has taken over for this session:
        # key -> the person's own value, which is what saving writes.
        self.overrides = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if key in DEFAULT_SETTINGS:
                        self.data[key] = value
        except Exception:
            pass

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            own = dict(self.data)
            own.update(self.overrides)
            tmp.write_text(json.dumps(own, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    # dict-ish access ------------------------------------------------
    def get(self, key, default=None):
        return self.data.get(key, DEFAULT_SETTINGS.get(key, default))

    def set(self, key, value) -> None:
        self.overrides.pop(key, None)          # chosen now, so it is the person's own
        self.data[key] = value
        self.save()

    def update(self, mapping) -> None:
        for key in mapping:
            self.overrides.pop(key, None)
        self.data.update(mapping)
        self.save()

    def apply_overrides(self, mapping) -> int:
        """Let a batch's settings win for this session without ever saving
        them as the person's own.  The previous batch's are undone first, so
        they do not follow into the next folder.  Returns how many apply."""
        for key, own in self.overrides.items():
            self.data[key] = own
        self.overrides = {}
        applied = 0
        for key, value in (mapping or {}).items():
            if key in DEFAULT_SETTINGS:
                self.overrides[key] = self.data.get(key, DEFAULT_SETTINGS[key])
                self.data[key] = value
                applied += 1
        return applied

    def push_recent(self, folder: str, limit: int = 12) -> None:
        folder = str(folder)
        recent = [f for f in self.get("recent_folders", []) if f != folder]
        recent.insert(0, folder)
        self.set("recent_folders", recent[:limit])
