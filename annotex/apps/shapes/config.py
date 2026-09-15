"""LabelImg Shapes' constants and settings.  No Qt."""

from __future__ import annotations

from annotex.config import JsonSettings, first_writable, user_data_dir

APP_NAME = "LabelImg Shapes"
APP_SLUG = "labelimg_shapes"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Polygon, oriented box, circle, ellipse and freehand labelling"

# ── files written beside the images ───────────────────────────
# One editable JSON per image.  The double suffix keeps it apart from
# LabelImg Master's CreateML .json and from LabelMe files.
ANNOTATION_SUFFIX = ".shapes.json"
FILE_FORMAT = "annotex-shapes"
FILE_VERSION = 1
LOCK_NAME = ".labelimg_shapes.lock"
BACKUP_DIR = ".labelimg_shapes_backup"
EXPORT_YOLO_SEG = "export_yolo_seg"
EXPORT_YOLO_OBB = "export_yolo_obb"
EXPORT_COCO = "export_coco_shapes"

SKIP_DIRS = {BACKUP_DIR, EXPORT_YOLO_SEG, EXPORT_YOLO_OBB, EXPORT_COCO,
             ".labelimg_backup", "copy_images", "deleted_images", "export_coco",
             "export_yolo", "export_voc", "export_masks"}

IMG_EXTS = (".jpg", ".jpeg", ".jfif", ".png", ".bmp", ".gif", ".ppm", ".pgm",
            ".pbm", ".webp", ".tif", ".tiff")

# ── shape kinds ───────────────────────────────────────────────
KIND_POLYGON = "polygon"
KIND_OBB = "obb"
KIND_CIRCLE = "circle"
KIND_ELLIPSE = "ellipse"
KIND_FREEHAND = "freehand"
KINDS = (KIND_POLYGON, KIND_OBB, KIND_CIRCLE, KIND_ELLIPSE, KIND_FREEHAND)
KIND_LABELS = {KIND_POLYGON: "Polygon", KIND_OBB: "Oriented box", KIND_CIRCLE: "Circle",
               KIND_ELLIPSE: "Ellipse", KIND_FREEHAND: "Freehand"}
PARAMETRIC_KINDS = (KIND_OBB, KIND_CIRCLE, KIND_ELLIPSE)
POINT_KINDS = (KIND_POLYGON, KIND_FREEHAND)

# ── geometry rules ────────────────────────────────────────────
MIN_POINTS = 3
MIN_SIZE = 2.0                   # image px; thinner is a misclick
MAX_SHAPES_PER_IMAGE = 1000
MAX_POINTS = 4000
CURVE_SEGMENTS = 48              # points per circle / ellipse in exports

# ── exports ───────────────────────────────────────────────────
TASK_SEGMENT = "segment"
TASK_OBB = "obb"
TASK_COCO = "coco"

# ── interaction ───────────────────────────────────────────────
HOTKEY_DIGITS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0")
MAX_UNDO_STEPS = 120

DEFAULT_SETTINGS = {
    "theme": "dark",
    "recent_folders": [],
    "fill_opacity": 22,              # 0-100
    "line_width": 2,
    "show_labels": True,
    "show_crosshair": True,
    "skip_label_dialog": True,       # use the active class without asking
    "sticky_class": True,
    "curve_segments": CURVE_SEGMENTS,
    "export_task": TASK_SEGMENT,
    "export_background": True,
    "last_class": "",
    "class_project": "",
    "window_geometry": "",
    # AI (Segment Anything).  Empty until a model is chosen; the tool is
    # simply off until then.
    "sam_encoder": "",
    "sam_decoder": "",
    "ai_keep_prompt": False,         # keep the clicks after accepting a shape
    "ai_smoothing": 1.2,             # px; higher means fewer polygon points
    # Workspace: what is folded away for a bigger image.
    "side_collapsed": False,
    "filmstrip_folded": False,
    "shortcuts": {},                 # action id -> key, over the defaults in ui/shortcuts.py
    # Auto-labelling with your own YOLO detector.
    "yolo_model": "",
    "yolo_names": "",                # optional class names file
    "yolo_confidence": 50,           # percent
    "yolo_class_map": {},            # model key -> {model class: project class, "" = ignore}
}


def settings_dir():
    return first_writable([user_data_dir() / APP_SLUG])


def class_store_path():
    """A class store of its own, apart from LabelImg Master's."""
    return settings_dir() / "classes.json"


class Settings(JsonSettings):
    def __init__(self, path=None):
        super().__init__(path or (settings_dir() / "settings.json"), DEFAULT_SETTINGS)
