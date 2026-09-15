"""LabelImg Master's constants and settings.  No Qt."""

from __future__ import annotations

from annotex.config import JsonSettings, first_writable, user_data_dir

APP_NAME = "LabelImg Master"
APP_SLUG = "labelimg"
APP_VERSION = "3.0.0"
APP_TAGLINE = "Bounding-box labelling and review"

# ── files written beside the images ───────────────────────────
LOCK_NAME = ".labelimg.lock"
DRAFT_NAME = ".labelimg_draft.json"
PROJECT_SETTINGS_NAME = ".labelimg.json"
VERIFIED_LEDGER_NAME = ".labelimg_verified.json"
BACKUP_DIR = ".labelimg_backup"
REPORT_NAME = "labelimg_report.html"
SUMMARY_NAME = "labelimg_summary.json"
COPY_DIR = "copy_images"
DELETED_DIR = "deleted_images"
COCO_DIR = "export_coco"

# Folders that hold our own output, never images to label.
SKIP_DIRS = {COPY_DIR, DELETED_DIR, COCO_DIR, BACKUP_DIR, "printed_roi",
             "no_roi", "export_yolo", "export_voc", "export_masks"}

IMG_EXTS = (".jpg", ".jpeg", ".jfif", ".png", ".bmp", ".gif", ".ppm", ".pgm",
            ".pbm", ".webp", ".tif", ".tiff")

# ── formats ───────────────────────────────────────────────────
FORMAT_VOC = "PascalVOC"
FORMAT_YOLO = "YOLO"
FORMAT_CREATEML = "CreateML"
FORMATS = (FORMAT_VOC, FORMAT_YOLO, FORMAT_CREATEML)
FORMAT_EXT = {FORMAT_VOC: ".xml", FORMAT_YOLO: ".txt", FORMAT_CREATEML: ".json"}
FORMAT_LABELS = {FORMAT_VOC: "Pascal VOC (.xml)", FORMAT_YOLO: "YOLO (.txt)",
                 FORMAT_CREATEML: "CreateML (.json)"}
# The order LabelImg has always looked for an existing annotation in.
FORMAT_ORDER = (FORMAT_VOC, FORMAT_YOLO, FORMAT_CREATEML)

# ── geometry rules ────────────────────────────────────────────
MIN_BOX_SIDE = 2.0               # image px; anything thinner is a misclick
MAX_BOXES_PER_IMAGE = 500
DUPLICATE_TOLERANCE = 2.0        # px; same class and this close = duplicate

# ── interaction ───────────────────────────────────────────────
HANDLE_SIZE = 9.0
SNAP_PIXELS = 7.0                # screen px

# Keys 1-9 then 0 address the first ten active classes; Shift+ the same keys
# address classes 11-20.  Anything past that is palette-click only.
HOTKEY_DIGITS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0")
SHIFT_DIGIT_SYMBOLS = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
                       "^": "6", "&": "7", "*": "8", "(": "9", ")": "0"}

AUTOSAVE_SECONDS = 20
MAX_UNDO_STEPS = 120

# ── settings ──────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "theme": "dark",
    "recent_folders": [],
    "label_format": FORMAT_VOC,
    "auto_advance_on_save": False,
    "skip_label_dialog": True,
    "sticky_class": True,
    "show_labels": True,
    "draw_square": False,
    "box_opacity": 18,               # live canvas fill, 0-100
    "box_line_width": 2,
    "show_crosshair": True,
    "show_minimap": True,
    "show_coordinates": True,
    "snap_to_edges": True,
    "snap_to_boxes": True,
    "confirm_clear_all": True,
    "autosave_seconds": AUTOSAVE_SECONDS,
    "first_run_done": False,
    "shortcuts": {},
    "last_class": "",
    "class_project": "",
    # AI (Segment Anything).  Empty until a model is chosen; the tool is
    # simply off until then.
    "sam_encoder": "",
    "sam_decoder": "",
    "ai_keep_prompt": False,         # keep the clicks after accepting a box
    # Workspace: what is folded away for a bigger image.
    "side_collapsed": False,
    "filmstrip_folded": False,
    # Auto-labelling with your own YOLO detector.
    "yolo_model": "",
    "yolo_names": "",                # optional class names file
    "yolo_confidence": 50,           # percent
    "yolo_class_map": {},            # model key -> {model class: project class, "" = ignore}
}

# Settings a batch folder may carry for everyone who opens it.
PROJECT_KEYS = ("label_format", "class_project", "save_dir",
                "auto_advance_on_save", "skip_label_dialog", "sticky_class",
                "show_labels", "draw_square", "snap_to_edges", "snap_to_boxes")


def settings_dir():
    return first_writable([user_data_dir() / APP_SLUG])


class Settings(JsonSettings):
    def __init__(self, path=None):
        super().__init__(path or (settings_dir() / "settings.json"),
                         DEFAULT_SETTINGS)
