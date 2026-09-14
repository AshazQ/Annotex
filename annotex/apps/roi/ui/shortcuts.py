"""ROI Studio's action registry.

Every command in the tool is declared here once, with an id, a label, an
icon, a category and a default key.  The window binds ids to methods, the
settings dialog rebinds keys, the command palette searches the same list, and
the shortcut sheet prints it.  Adding a command means adding one row.
"""

from __future__ import annotations

from annotex.ui import shortcuts as _shared

# (id, label, default key, category, icon, description)
ACTIONS = [
    # ── batch ─────────────────────────────────────────────
    ("open_folder", "Open batch folder…", "Ctrl+O", "Batch", "folder",
     "Choose the folder of images to annotate"),
    ("reload_folder", "Reload this batch", "Ctrl+R", "Batch", "refresh",
     "Re-read the folder and the saved annotations"),
    ("close_folder", "Close batch", "Ctrl+W", "Batch", "cross",
     "Finish with this folder"),

    # ── navigation ────────────────────────────────────────
    ("next_image", "Next image", "Q", "Navigate", "next",
     "Save the current image and move on"),
    ("prev_image", "Previous image", "P", "Navigate", "prev",
     "Step back one image"),
    ("first_image", "First image", "Home", "Navigate", "prev", ""),
    ("last_image", "Last image", "End", "Navigate", "next", ""),

    # ── tools ─────────────────────────────────────────────
    ("tool_select", "Select tool", "V", "Tools", "cursor",
     "Pick, move and reshape existing ROIs"),
    ("tool_polygon", "Polygon tool", "W", "Tools", "polygon",
     "Click point by point to draw a polygon"),
    ("tool_rect", "Rectangle tool", "B", "Tools", "rect",
     "Drag out an axis-aligned rectangle"),
    ("tool_circle", "Circle tool", "C", "Tools", "circle",
     "Drag out a circle or ellipse"),
    ("tool_lasso", "Freehand lasso", "G", "Tools", "lasso",
     "Trace freehand; the path is simplified into a polygon"),
    ("tool_pan", "Pan tool", "H", "Tools", "hand",
     "Drag the image around (or hold Space with any tool)"),

    # ── drawing ───────────────────────────────────────────
    ("finish_shape", "Finish shape", "Return", "Draw", "check",
     "Close the polygon being drawn"),
    ("cancel_shape", "Cancel shape / deselect", "Escape", "Draw", "cross", ""),
    ("undo_point", "Undo last point", "Backspace", "Draw", "undo", ""),

    # ── editing ───────────────────────────────────────────
    ("undo", "Undo", "Ctrl+Z", "Edit", "undo", ""),
    ("redo", "Redo", "Ctrl+Shift+Z", "Edit", "redo", ""),
    ("redo_alt", "Redo (alternate)", "Ctrl+Y", "Edit", "redo", ""),
    ("delete_roi", "Delete selected ROI", "Delete", "Edit", "trash", ""),
    ("duplicate_roi", "Duplicate selected ROI", "D", "Edit", "copy", ""),
    ("select_all", "Select all ROIs", "Ctrl+A", "Edit", "grid", ""),
    ("clear_all", "Clear all ROIs on this image", "Ctrl+Shift+C", "Edit",
     "clear", "Remove every ROI from the current image"),
    ("copy_previous", "Copy ROIs from previous image", "Ctrl+D", "Edit", "copy",
     "Reuse the shapes drawn on the image before this one"),
    ("lock_roi", "Lock or unlock selection", "Ctrl+L", "Edit", "lock", ""),
    ("batch_apply", "Apply these ROIs to other images…", "Ctrl+Shift+A", "Edit",
     "grid", "Copy the current shapes onto a set of images in one step"),
    ("batch_no_roi", "Mark several images as no_roi…", "", "Edit", "no_roi",
     "File a set of images under no_roi in one step"),
    ("align_left", "Align left", "", "Arrange", "align_left", ""),
    ("align_hcentre", "Align centres horizontally", "", "Arrange",
     "align_left", ""),
    ("align_right", "Align right", "", "Arrange", "align_left", ""),
    ("align_top", "Align top", "", "Arrange", "align_top", ""),
    ("align_vcentre", "Align centres vertically", "", "Arrange",
     "align_top", ""),
    ("align_bottom", "Align bottom", "", "Arrange", "align_top", ""),
    ("distribute_h", "Distribute horizontally", "", "Arrange", "distribute", ""),
    ("distribute_v", "Distribute vertically", "", "Arrange", "distribute", ""),
    ("equalise", "Match sizes to the first selected", "", "Arrange", "grid", ""),

    # ── saving ────────────────────────────────────────────
    ("save_roi", "Save this image", "S", "Save", "save",
     "Write the ROIs and move to the next image"),
    ("mark_no_roi", "Mark image as no_roi", "N", "Save", "no_roi",
     "Record that this image has nothing to annotate"),
    ("export_now", "Export everything now", "Ctrl+E", "Save", "export",
     "Write the spreadsheet, the JSON files and the report"),
    ("export_formats", "Export to COCO / YOLO / VOC / masks…", "Ctrl+Shift+E",
     "Save", "export", ""),
    ("import_annotations", "Import or merge annotations…", "Ctrl+I", "Save",
     "import", ""),
    ("restore_backup", "Restore this image from the backup", "", "Save",
     "history", "Bring back the annotation held in the rolling .bak copy"),
    ("save_project_settings", "Save these settings for this batch", "", "Save",
     "settings", "Write a .roi_studio.json beside the images so anyone who "
     "opens this folder gets the same setup"),
    ("push_api", "Send to endpoint", "", "Save", "export",
     "POST the JSON to the configured URL"),

    # ── view ──────────────────────────────────────────────
    ("zoom_in", "Zoom in", "+", "View", "zoom_in", ""),
    ("zoom_out", "Zoom out", "-", "View", "zoom_out", ""),
    ("zoom_fit", "Fit image to window", "0", "View", "zoom_fit", ""),
    ("zoom_actual", "Zoom to 100%", "1", "View", "zoom_fit", ""),
    ("zoom_selection", "Zoom to selection", "Z", "View", "zoom_in", ""),
    ("zoom_all_rois", "Zoom to all ROIs", "Shift+Z", "View", "zoom_fit", ""),
    ("toggle_theme", "Switch light / dark", "Ctrl+T", "View", "moon", ""),
    ("toggle_minimap", "Show or hide the minimap", "", "View", "grid", ""),
    ("toggle_crosshair", "Show or hide the crosshair", "", "View", "grid", ""),

    # ── windows ───────────────────────────────────────────
    ("review_mode", "Review mode", "F6", "Windows", "review",
     "Compare the original and the printed ROI image side by side"),
    ("dashboard", "Summary dashboard", "F7", "Windows", "report",
     "Coverage, progress and throughput for this batch"),
    ("open_report", "Write and open the HTML report", "F8", "Windows",
     "report", ""),
    ("history_log", "Change history", "F9", "Windows", "history", ""),
    ("settings", "Settings…", "Ctrl+,", "Windows", "settings", ""),
    ("shortcuts_sheet", "Keyboard shortcuts", "?", "Windows", "keyboard", ""),
    ("command_palette", "Command palette", "Ctrl+K", "Windows", "command", ""),
    ("about", "About ROI Studio", "", "Windows", "info", ""),
]

BY_ID = _shared.by_id(ACTIONS)
CATEGORIES = _shared.categories(ACTIONS)

# Keys the canvas needs for direct manipulation; refuse to steal them.
RESERVED = {"Up", "Down", "Left", "Right", "Space", "Shift", "Ctrl", "Alt"}


def default_key(action_id: str) -> str:
    return _shared.default_key(ACTIONS, action_id)


def label(action_id: str) -> str:
    return _shared.label(ACTIONS, action_id)


def resolve(overrides) -> dict:
    """Merge the user's remaps over the defaults, dropping anything unusable."""
    return _shared.resolve(ACTIONS, overrides)


def conflicts(keys) -> dict:
    """{key: [action ids]} for every key bound more than once."""
    return _shared.conflicts(keys)


def grouped():
    """[(category, [rows])] in declaration order, for the shortcut sheet."""
    return _shared.grouped(ACTIONS)
