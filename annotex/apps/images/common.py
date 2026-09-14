"""Finding images and naming outputs.  No Qt."""

from __future__ import annotations

import os
import re
import string

IMAGE_EXTS = (".jpg", ".jpeg", ".jfif", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif")
SKIP_DIRS = {"converted", "copy_images", "deleted_images", "printed_roi", "no_roi",
             "export_coco", ".labelimg_backup"}
_DIGITS = re.compile(r"(\d+)")


def natural_key(text):
    return [int(p) if p.isdigit() else p for p in _DIGITS.split(str(text).lower())]


def scan_images(folder, recursive=True):
    """Every image under `folder` as absolute paths, in natural order."""
    folder = os.path.abspath(str(folder))
    found = []
    for root, dirs, files in os.walk(folder, onerror=lambda _e: None):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS
                         and not d.endswith("_sorted"))
        for name in files:
            if name.lower().endswith(IMAGE_EXTS) and not name.startswith("."):
                found.append(os.path.join(root, name))
        if not recursive:
            break
    found.sort(key=natural_key)
    return found


def expand_inputs(paths, recursive=True):
    """[(image, root)] for a mix of files and folders.  `root` is the folder
    the image was found under (its own folder for single files), so outputs
    can keep sub-folder structure."""
    items, seen = [], set()
    for path in paths:
        path = os.path.abspath(str(path))
        if os.path.isdir(path):
            pairs = [(image, path) for image in scan_images(path, recursive)]
        elif os.path.isfile(path) and path.lower().endswith(IMAGE_EXTS):
            pairs = [(path, os.path.dirname(path))]
        else:
            pairs = []
        for image, root in pairs:
            if image not in seen:
                seen.add(image)
                items.append((image, root))
    return items


class _Fields(dict):
    def __missing__(self, key):
        raise KeyError(key)


def pattern_fields(pattern):
    return [field for _text, field, _spec, _conv in string.Formatter().parse(pattern) if field]


def validate_pattern(pattern, allowed=("name", "n", "parent", "ext")):
    """None when the pattern is usable, else a sentence saying why not."""
    if not pattern or not pattern.strip():
        return "The name pattern is empty"
    try:
        fields = pattern_fields(pattern)
    except ValueError as exc:
        return "The name pattern is malformed (%s)" % exc
    unknown = [f for f in fields if f not in allowed]
    if unknown:
        return "Unknown field {%s} - use %s" % (unknown[0], ", ".join("{%s}" % a for a in allowed))
    if "n" not in fields and "name" not in fields:
        return "Include {name} or {n}, or every file would get the same name"
    try:
        render_pattern(pattern, "photo", 1, "folder", "jpg")
    except (ValueError, KeyError, IndexError) as exc:
        return "The name pattern is malformed (%s)" % exc
    if any(ch in render_pattern(pattern, "photo", 1, "folder", "jpg") for ch in '/\\:*?"<>|'):
        return "The name pattern would create an invalid file name"
    return None


def render_pattern(pattern, name, number, parent, ext):
    return pattern.format_map(_Fields(name=name, n=number, parent=parent, ext=ext))
