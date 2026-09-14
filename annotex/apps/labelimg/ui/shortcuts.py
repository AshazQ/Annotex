"""LabelImg Master's action registry.

Every command is declared here once.  The window binds ids to methods, the
settings dialog rebinds keys, the command palette searches the list and the
shortcut sheet prints it.

Defaults follow LabelImg's long-standing keys wherever they existed (W to
draw, D / A to move through the folder, Space to verify, Ctrl+U to open a
folder, Ctrl+M for the Class Manager), so nobody has to relearn them.  Two
moved to line up with the rest of the suite: Ctrl+K is the command palette in
every tool, so the class search is now "/", and Settings has no default key.
"""

from __future__ import annotations

from annotex.ui import shortcuts as _shared

# (id, label, default key, category, icon, description)
ACTIONS = [
    # ── batch ─────────────────────────────────────────────
    ("open_folder", "Open image folder…", "Ctrl+U", "Batch", "folder",
     "Choose the folder of images to label"),
    ("change_save_dir", "Change annotation folder…", "Ctrl+R", "Batch", "folder",
     "Save annotations somewhere other than beside the images"),
    ("reload_folder", "Reload this batch", "F5", "Batch", "refresh",
     "Re-read the folder and its annotations"),
    ("close_folder", "Close batch", "Ctrl+W", "Batch", "cross", ""),
    ("class_manager", "Class Manager…", "Ctrl+M", "Batch", "tag",
     "Create, rename, deprecate and ID the classes of each project"),
    ("cycle_format", "Next save format", "Ctrl+Shift+Y", "Batch", "refresh",
     "Pascal VOC → YOLO → CreateML"),

    # ── navigation ────────────────────────────────────────
    ("next_image", "Next image", "D", "Navigate", "next",
     "Save this image and move on"),
    ("prev_image", "Previous image", "A", "Navigate", "prev", ""),
    ("first_image", "First image", "Home", "Navigate", "prev", ""),
    ("last_image", "Last image", "End", "Navigate", "next", ""),
    ("next_todo", "Next image with no annotation", "Shift+D", "Navigate",
     "next", "Skip ahead to the next image nobody has labelled yet"),

    # ── tools ─────────────────────────────────────────────
    ("tool_select", "Select tool", "V", "Tools", "cursor",
     "Pick, move and resize boxes"),
    ("tool_box", "Box tool", "W", "Tools", "rect",
     "Drag out a new box - hold Ctrl for a square"),
    ("tool_pan", "Pan tool", "H", "Tools", "hand",
     "Drag the image around (or drag with the middle button)"),
    ("cancel", "Cancel / deselect", "Escape", "Tools", "cross", ""),

    # ── editing ───────────────────────────────────────────
    ("undo", "Undo", "Ctrl+Z", "Edit", "undo", ""),
    ("redo", "Redo", "Ctrl+Y", "Edit", "redo", ""),
    ("redo_alt", "Redo (alternate)", "Ctrl+Shift+Z", "Edit", "redo", ""),
    ("delete_box", "Delete selected boxes", "Delete", "Edit", "trash", ""),
    ("duplicate_box", "Duplicate selected boxes", "Ctrl+D", "Edit", "copy", ""),
    ("select_all", "Select all boxes", "Ctrl+A", "Edit", "grid", ""),
    ("clear_all", "Clear every box on this image", "Ctrl+Shift+C", "Edit",
     "clear", "Remove every box from the current image"),
    ("edit_label", "Change the class of the selection…", "Ctrl+E", "Edit",
     "tag", ""),
    ("toggle_difficult", "Mark or unmark selection as difficult", "", "Edit",
     "flag", "The Pascal VOC 'difficult' flag"),
    ("lock_box", "Lock or unlock selection", "Ctrl+L", "Edit", "lock",
     "A locked box cannot be moved or resized by accident"),
    ("hide_box", "Hide or show selection", "", "Edit", "eye",
     "Hidden boxes are still saved; they are just out of the way"),
    ("copy_previous", "Replace with the previous image's boxes", "Ctrl+V",
     "Edit", "layers", "Copy the previous frame's annotation over this one"),
    ("append_previous", "Add every box from the previous image",
     "Ctrl+Shift+V", "Edit", "layers",
     "Append the previous frame's boxes to what is already here"),
    ("apply_to_images", "Apply these boxes to other images…", "Ctrl+Shift+A",
     "Edit", "grid", "Write the current boxes onto a set of images in one step"),
    ("background_many", "Mark several images as background…", "", "Edit",
     "background", "Save an empty annotation for a set of images in one step"),

    # ── classes ───────────────────────────────────────────
    ("find_class", "Find a class", "/", "Classes", "search",
     "Jump to the class search box"),
    ("next_class", "Next class", "Ctrl+.", "Classes", "next", ""),
    ("prev_class", "Previous class", "Ctrl+,", "Classes", "prev", ""),
    ("toggle_sticky", "Keep the last-used class", "", "Classes", "tag",
     "A new box takes the class of the box before it"),
    ("toggle_skip_dialog", "Skip the label dialog", "", "Classes", "tag",
     "Label new boxes with the active class without asking"),

    # ── saving ────────────────────────────────────────────
    ("save", "Save this image", "Ctrl+S", "Save", "save",
     "Write the annotation, and move on when auto-advance is on"),
    ("accept_frame", "Accept this frame as-is", "", "Save", "verified",
     "Save and go to the next image - also Enter"),
    ("mark_background", "Mark as background", "N", "Save", "background",
     "Save an empty annotation: nothing to label on this image"),
    ("verify_image", "Toggle verified", "Space", "Save", "verified",
     "Mark this image as checked"),
    ("toggle_auto_advance", "Auto-advance after saving", "", "Save", "next", ""),
    ("import_annotations", "Import or merge annotations…", "Ctrl+I", "Save",
     "import", "Bring in another annotator's work for these images"),
    ("export_coco", "Export to COCO…", "Ctrl+Shift+E", "Save", "export", ""),
    ("restore_backup", "Restore this image from the backup", "", "Save",
     "history", "Bring back the previous version of this annotation"),
    ("save_project_settings", "Save these settings for this batch", "",
     "Save", "settings", "Write a .labelimg.json beside the images so anyone "
     "who opens this folder gets the same setup"),
    ("delete_image", "Move image to deleted_images", "Ctrl+Shift+D", "Save",
     "trash", "Nothing is erased - the image and its annotation are moved"),
    ("copy_image", "Copy image to copy_images", "", "Save", "image_copy", ""),

    # ── view ──────────────────────────────────────────────
    ("zoom_in", "Zoom in", "Ctrl++", "View", "zoom_in", ""),
    ("zoom_out", "Zoom out", "Ctrl+-", "View", "zoom_out", ""),
    ("zoom_fit", "Fit image to window", "Ctrl+F", "View", "zoom_fit", ""),
    ("zoom_width", "Fit image width", "Ctrl+Shift+F", "View", "zoom_fit", ""),
    ("zoom_actual", "Zoom to 100%", "Ctrl+=", "View", "zoom_fit", ""),
    ("zoom_selection", "Zoom to selection", "Z", "View", "zoom_in", ""),
    ("zoom_all", "Zoom to all boxes", "Shift+Z", "View", "zoom_fit", ""),
    ("brighten", "Brighter", "Ctrl+Up", "View", "brightness",
     "Lift a dark night-time frame"),
    ("darken", "Darker", "Ctrl+Down", "View", "brightness", ""),
    ("reset_brightness", "Reset brightness", "Ctrl+0", "View", "brightness", ""),
    ("toggle_labels", "Show or hide class names on boxes", "Ctrl+Shift+P",
     "View", "eye", ""),
    ("toggle_square", "Always draw squares", "", "View", "square", ""),
    ("toggle_side", "Show or hide the side panel", "Ctrl+Shift+L", "View",
     "list", ""),
    ("toggle_theme", "Switch light / dark", "Ctrl+T", "View", "moon", ""),
    ("toggle_minimap", "Show or hide the minimap", "", "View", "grid", ""),
    ("toggle_crosshair", "Show or hide the crosshair", "", "View", "grid", ""),

    # ── windows ───────────────────────────────────────────
    ("review_mode", "Review mode", "F6", "Windows", "review",
     "Page through the batch at full size with the boxes drawn"),
    ("dashboard", "Summary dashboard", "F7", "Windows", "report",
     "Progress, class balance and throughput for this batch"),
    ("open_report", "Write and open the HTML report", "F8", "Windows",
     "report", ""),
    ("history_log", "Change history", "F9", "Windows", "history", ""),
    ("settings", "Settings…", "", "Windows", "settings", ""),
    ("shortcuts_sheet", "Keyboard shortcuts", "?", "Windows", "keyboard", ""),
    ("command_palette", "Command palette", "Ctrl+K", "Windows", "command", ""),
    ("welcome", "Show the welcome tour", "", "Windows", "info", ""),
    ("about", "About LabelImg Master", "", "Windows", "info", ""),
]

CHECKABLE = {"toggle_sticky", "toggle_skip_dialog", "toggle_auto_advance",
             "toggle_labels", "toggle_square", "toggle_minimap",
             "toggle_crosshair"}

BY_ID = _shared.by_id(ACTIONS)

# Keys the canvas and the class hotkeys own; the settings dialog refuses them.
RESERVED = {"Up", "Down", "Left", "Right", "Return", "Enter", "Shift", "Ctrl",
            "Alt"} | {str(d) for d in range(10)} | {"Shift+%d" % d for d in range(10)}

# Bindings that are not commands in the registry, for the shortcut sheet.
FIXED = [
    ("Always", [
        ("Accept this frame as-is (save and go to the next image)", "Enter", ""),
        ("Assign the 1st – 10th class, or arm it for the next box", "1 … 9, 0", ""),
        ("Assign the 11th – 20th class", "Shift+1 … Shift+0", ""),
        ("Nudge the selection by one pixel", "Arrow keys", ""),
        ("Nudge the selection by ten pixels", "Shift+Arrow keys", ""),
        ("Draw or resize as a square", "hold Ctrl", ""),
    ]),
]

MOUSE_HINT = ("Mouse: drag on the image with the box tool (W) to draw · click a "
              "box to select it, Shift+click to add to the selection · drag a "
              "box to move it, drag a corner or edge handle to resize · "
              "double-click a box to change its class · right-click for its "
              "menu · drag on empty space to rubber-band select · middle-drag "
              "to pan · scroll to zoom.")


def resolve(overrides) -> dict:
    return _shared.resolve(ACTIONS, overrides)


def label(action_id: str) -> str:
    return _shared.label(ACTIONS, action_id)
