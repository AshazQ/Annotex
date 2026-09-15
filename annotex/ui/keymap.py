"""One keymap for the three annotation tools.

ROI Studio, LabelImg Master and LabelImg Shapes each keep their own action
table (their commands are not all the same), but a command they share has
the same default key in all three.  STANDARD is that promise; TOOL_COMMANDS
says which of a tool's actions is which shared command, and the tests hold
every table to it.  Anyone can still change any key in a tool's Settings.

The shape of it:

* Ctrl+ for file and view commands, plain letters for the drawing tools,
* plain number keys stay free for picking classes,
* D / A step through the images (PgDown / PgUp too).
"""

from __future__ import annotations

STANDARD = {
    # images
    "next_image": "D",
    "prev_image": "A",
    "first_image": "Home",
    "last_image": "End",
    "delete_image": "Ctrl+Shift+D",
    # saving
    "save": "Ctrl+S",
    "verify": "Space",
    "background": "N",
    # editing
    "undo": "Ctrl+Z",
    "redo": "Ctrl+Y",
    "redo_alt": "Ctrl+Shift+Z",
    "copy": "Ctrl+C",
    "cut": "Ctrl+X",
    "paste": "Ctrl+V",
    "duplicate": "Ctrl+D",
    "previous_shapes": "Ctrl+Shift+V",
    "delete": "Delete",
    "clear_all": "Ctrl+Shift+Del",
    "select_all": "Ctrl+A",
    "change_class": "Ctrl+E",
    # windows and files
    "class_manager": "Ctrl+M",
    "settings": "Ctrl+,",
    "open_folder": "Ctrl+O",
    "reload": "F5",
    "export": "Ctrl+Shift+E",
    "toggle_theme": "Ctrl+T",
    # view
    "zoom_fit": "Ctrl+0",
    "zoom_actual": "Ctrl+1",
    "zoom_selection": "Z",
    "zoom_in": "Ctrl+=",
    "zoom_out": "Ctrl+-",
    "toggle_labels": "L",
    # drawing tools
    "tool_select": "V",
    "tool_pan": "H",
    "tool_box": "W",
    "tool_polygon": "P",
    "tool_circle": "C",
    "tool_ellipse": "E",
    "tool_obb": "O",
    "tool_freehand": "F",
    "tool_ai": "S",
    "auto_label": "Y",
}

# {tool: {that tool's action id: shared command}}
TOOL_COMMANDS = {
    "labelimg": {
        "next_image": "next_image", "prev_image": "prev_image", "first_image": "first_image",
        "last_image": "last_image", "delete_image": "delete_image", "save": "save",
        "verify_image": "verify", "mark_background": "background", "undo": "undo",
        "redo": "redo", "redo_alt": "redo_alt", "copy_boxes": "copy", "cut_boxes": "cut",
        "paste_boxes": "paste", "duplicate_box": "duplicate", "copy_previous": "previous_shapes",
        "delete_box": "delete", "clear_all": "clear_all", "select_all": "select_all",
        "edit_label": "change_class", "class_manager": "class_manager", "settings": "settings",
        "open_folder": "open_folder", "reload_folder": "reload", "export_coco": "export",
        "toggle_theme": "toggle_theme", "zoom_fit": "zoom_fit", "zoom_actual": "zoom_actual",
        "zoom_selection": "zoom_selection", "zoom_in": "zoom_in", "zoom_out": "zoom_out",
        "toggle_labels": "toggle_labels", "tool_select": "tool_select", "tool_pan": "tool_pan",
        "tool_box": "tool_box", "tool_ai": "tool_ai", "auto_label": "auto_label",
    },
    "roi": {
        "next_image": "next_image", "prev_image": "prev_image", "first_image": "first_image",
        "last_image": "last_image", "delete_image": "delete_image", "save_roi": "save",
        "mark_no_roi": "background", "undo": "undo", "redo": "redo", "redo_alt": "redo_alt",
        "duplicate_roi": "duplicate", "copy_previous": "previous_shapes", "delete_roi": "delete",
        "clear_all": "clear_all", "select_all": "select_all", "settings": "settings",
        "open_folder": "open_folder", "reload_folder": "reload", "export_formats": "export",
        "toggle_theme": "toggle_theme", "zoom_fit": "zoom_fit", "zoom_actual": "zoom_actual",
        "zoom_selection": "zoom_selection", "zoom_in": "zoom_in", "zoom_out": "zoom_out",
        "tool_select": "tool_select", "tool_pan": "tool_pan", "tool_rect": "tool_box",
        "tool_polygon": "tool_polygon", "tool_circle": "tool_circle", "tool_lasso": "tool_freehand",
    },
    "shapes": {
        "next_image": "next_image", "prev_image": "prev_image", "delete_image": "delete_image",
        "save": "save", "verify": "verify", "undo": "undo", "redo": "redo",
        "copy_shapes": "copy", "cut_shapes": "cut", "paste_shapes": "paste",
        "duplicate": "duplicate", "copy_previous": "previous_shapes", "delete": "delete",
        "clear_all": "clear_all", "select_all": "select_all", "edit_class": "change_class",
        "class_manager": "class_manager", "settings": "settings", "open_folder": "open_folder",
        "export": "export", "toggle_theme": "toggle_theme", "zoom_fit": "zoom_fit",
        "zoom_selection": "zoom_selection", "zoom_in": "zoom_in", "zoom_out": "zoom_out",
        "toggle_labels": "toggle_labels", "tool_select": "tool_select", "tool_pan": "tool_pan",
        "tool_polygon": "tool_polygon", "tool_circle": "tool_circle", "tool_ellipse": "tool_ellipse",
        "tool_obb": "tool_obb", "tool_freehand": "tool_freehand", "tool_ai": "tool_ai",
        "auto_label": "auto_label",
    },
}

# Second keys that come with a command, per tool.  Never one another command
# in that tool already owns (ROI and LabelImg Master have a separate "redo
# (alternate)" action; Shapes folds it into redo).
ALTERNATES = {
    "labelimg": {"next_image": ("PgDown",), "prev_image": ("PgUp",), "zoom_in": ("Ctrl++",),
                 "open_folder": ("Ctrl+U",)},
    "roi": {"next_image": ("PgDown",), "prev_image": ("PgUp",), "zoom_in": ("Ctrl++",)},
    "shapes": {"next_image": ("PgDown",), "prev_image": ("PgUp",), "zoom_in": ("Ctrl++",),
               "redo": ("Ctrl+Shift+Z",), "open_folder": ("Ctrl+U",)},
}


def standard_key(tool, action_id) -> str:
    command = TOOL_COMMANDS.get(tool, {}).get(action_id)
    return STANDARD.get(command, "") if command else ""


def sequences(tool, action_id, key):
    """The key a person chose (or the default), plus that command's second
    keys in this tool - as a list of key strings for QAction.setShortcuts."""
    keys = [key] if key else []
    command = TOOL_COMMANDS.get(tool, {}).get(action_id, action_id)
    for extra in ALTERNATES.get(tool, {}).get(command, ()):
        if extra not in keys:
            keys.append(extra)
    return keys
