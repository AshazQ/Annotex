"""LabelImg Shapes' action registry.

Every command with a key is declared here once, with an id, a label, a
default key, a category and an icon - the same shape as ROI Studio's and
LabelImg Master's tables - so Settings can rebind any of them and the keys
match the other annotation tools (annotex.ui.keymap).  The class number keys
1 … 9, 0 are not here: they pick classes and are not remappable.
"""

from __future__ import annotations

from annotex.ui import shortcuts as _shared

# (id, label, default key, category, icon, description)
ACTIONS = [
    # ── folder and images ─────────────────────────────────
    ("open_folder", "Open folder…", "Ctrl+O", "Folder", "folder", ""),
    ("next_image", "Next image", "D", "Navigate", "next", "Saves this image and moves on"),
    ("prev_image", "Previous image", "A", "Navigate", "prev", ""),
    ("delete_image", "Move image to deleted_images", "Ctrl+Shift+D", "Navigate", "image_remove",
     "Nothing is erased - the image and its shapes file are moved"),

    # ── tools ─────────────────────────────────────────────
    ("tool_select", "Select and edit", "V", "Tools", "cursor", ""),
    ("tool_polygon", "Polygon", "P", "Tools", "polygon", ""),
    ("tool_obb", "Oriented box", "O", "Tools", "obb", ""),
    ("tool_circle", "Circle", "C", "Tools", "circle", ""),
    ("tool_ellipse", "Ellipse", "E", "Tools", "ellipse", ""),
    ("tool_freehand", "Freehand", "F", "Tools", "freehand", ""),
    ("tool_ai", "AI select (SAM)", "S", "Tools", "magic", ""),
    ("tool_pan", "Pan", "H", "Tools", "hand", "Or hold Space and drag"),
    ("auto_label", "Auto-label with your YOLO model", "Y", "Tools", "scan",
     "Your detector proposes a rectangle for every object - click one to drop it, Enter keeps the rest"),
    ("prelabel_folder", "Pre-label the folder with YOLO…", "", "Tools", "scan",
     "Run your detector over every image that has no shapes file yet, in the background"),

    # ── editing ───────────────────────────────────────────
    ("undo", "Undo", "Ctrl+Z", "Edit", "undo", ""),
    ("redo", "Redo", "Ctrl+Y", "Edit", "redo", "Ctrl+Shift+Z works too"),
    ("edit_class", "Change class…", "Ctrl+E", "Edit", "tag", ""),
    ("duplicate", "Duplicate", "Ctrl+D", "Edit", "copy", ""),
    ("copy_shapes", "Copy the selected shapes", "Ctrl+C", "Edit", "copy", ""),
    ("cut_shapes", "Cut the selected shapes", "Ctrl+X", "Edit", "copy", ""),
    ("paste_shapes", "Paste copied shapes", "Ctrl+V", "Edit", "paste", ""),
    ("copy_previous", "Add the previous image's shapes", "Ctrl+Shift+V", "Edit", "layers", ""),
    ("delete", "Delete", "Delete", "Edit", "trash", ""),
    ("select_all", "Select all", "Ctrl+A", "Edit", "grid", ""),
    ("rotate_left", "Rotate 15° left", "[", "Edit", "rotate", ""),
    ("rotate_right", "Rotate 15° right", "]", "Edit", "rotate", ""),
    ("clear_all", "Clear all shapes", "Ctrl+Shift+Del", "Edit", "clear", ""),

    # ── saving ────────────────────────────────────────────
    ("save", "Save", "Ctrl+S", "Save", "save", ""),
    ("verify", "Mark as verified", "Space", "Save", "verified",
     "Tap Space - holding it and dragging pans instead"),
    ("export", "Export YOLO / COCO…", "Ctrl+Shift+E", "Save", "export", ""),

    # ── view ──────────────────────────────────────────────
    ("zoom_in", "Zoom in", "Ctrl+=", "View", "zoom_in", ""),
    ("zoom_out", "Zoom out", "Ctrl+-", "View", "zoom_out", ""),
    ("zoom_fit", "Fit to window", "Ctrl+0", "View", "zoom_fit", ""),
    ("zoom_selection", "Zoom to selection", "Z", "View", "search", ""),
    ("toggle_labels", "Show class names", "L", "View", "tag", ""),
    ("toggle_theme", "Switch light / dark", "Ctrl+T", "View", "moon", ""),

    # ── windows ───────────────────────────────────────────
    ("class_manager", "Class Manager…", "Ctrl+M", "Windows", "tag", ""),
    ("ai_model", "AI model (SAM)…", "", "Windows", "magic", ""),
    ("yolo_model", "YOLO model…", "", "Windows", "scan", "Choose your own YOLO detector (.onnx)"),
    ("settings", "Settings…", "Ctrl+,", "Windows", "settings", ""),
]

BY_ID = _shared.by_id(ACTIONS)

# Keys the canvas and the class number keys own; Settings refuses them.
RESERVED = {"Up", "Down", "Left", "Right", "Return", "Enter", "Escape", "Backspace", "Shift",
            "Ctrl", "Alt"} | {str(d) for d in range(10)}


def resolve(overrides) -> dict:
    return _shared.resolve(ACTIONS, overrides)


def label(action_id: str) -> str:
    return _shared.label(ACTIONS, action_id)
