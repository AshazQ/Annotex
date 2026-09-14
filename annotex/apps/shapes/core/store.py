"""Reading and writing the per-image shape files.  No Qt.

    <image stem>.shapes.json   beside the image

    {
      "format": "annotex-shapes", "version": 1,
      "tool": "LabelImg Shapes 1.0.0",
      "image": "sub/photo.jpg", "width": 1280, "height": 720,
      "verified": false,
      "shapes": [{"label": "human", "kind": "ellipse",
                  "cx": 410.5, "cy": 220.0, "w": 80.0, "h": 190.0, "angle": 12.0}, ...]
    }

A file with an empty shape list is a background image: looked at, nothing
to label.  Writes are atomic and the previous version is kept in a hidden
backup folder, so a crash can never leave half a file behind.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from annotex.core.io_safe import write_text_atomic

from ..config import (ANNOTATION_SUFFIX, APP_NAME, APP_VERSION, BACKUP_DIR,
                      FILE_FORMAT, FILE_VERSION, IMG_EXTS, SKIP_DIRS)
from .model import Shape


def natural_key(text):
    """a.jpg < a2.jpg < a10.jpg: numbers compare as numbers and the extension
    is compared last, so it can never outweigh the name."""
    stem, ext = os.path.splitext(str(text))
    return ([int(part) if part.isdigit() else part.lower()
             for part in re.split(r"(\d+)", stem)], ext.lower())


def scan_images(folder):
    """Image paths relative to `folder`, sub-folders included, in natural order."""
    folder = os.path.abspath(str(folder))
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.lower().endswith(IMG_EXTS) and not name.startswith("."):
                found.append(os.path.relpath(os.path.join(root, name), folder))
    return sorted(found, key=natural_key)


def annotation_path(folder, rel) -> str:
    return os.path.join(str(folder), os.path.splitext(str(rel))[0] + ANNOTATION_SUFFIX)


def backup_path(folder, rel) -> str:
    return os.path.join(str(folder), BACKUP_DIR,
                        os.path.splitext(str(rel))[0] + ANNOTATION_SUFFIX)


@dataclass
class ReadResult:
    found: bool = False
    shapes: list = field(default_factory=list)
    width: int = 0
    height: int = 0
    verified: bool = False
    error: str = ""
    skipped: int = 0              # shapes in the file that could not be read


def read_annotation(folder, rel) -> ReadResult:
    path = annotation_path(folder, rel)
    result = ReadResult()
    if not os.path.isfile(path):
        return result
    result.found = True
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        result.error = "could not read %s: %s" % (os.path.basename(path), exc)
        return result
    if not isinstance(payload, dict) or payload.get("format") != FILE_FORMAT:
        result.error = "%s is not a LabelImg Shapes file" % os.path.basename(path)
        return result
    result.width = int(payload.get("width") or 0)
    result.height = int(payload.get("height") or 0)
    result.verified = bool(payload.get("verified", False))
    for item in payload.get("shapes") or []:
        try:
            result.shapes.append(Shape.from_dict(item))
        except Exception:
            result.skipped += 1
    return result


def build_payload(rel, shapes, width, height, verified=False) -> dict:
    return {
        "format": FILE_FORMAT,
        "version": FILE_VERSION,
        "tool": "%s %s" % (APP_NAME, APP_VERSION),
        "image": str(rel).replace(os.sep, "/"),
        "width": int(width),
        "height": int(height),
        "verified": bool(verified),
        "shapes": [shape.to_dict() for shape in shapes],
    }


def write_annotation(folder, rel, shapes, width, height, verified=False):
    """(ok, error)."""
    path = annotation_path(folder, rel)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        return False, "the image's folder no longer exists"
    text = json.dumps(build_payload(rel, shapes, width, height, verified),
                      indent=2, ensure_ascii=False) + "\n"
    return write_text_atomic(path, text, verify_json=True, keep_backup=True,
                             backup_to=backup_path(folder, rel))


def shape_count(folder, rel):
    """None when the image has no file yet, otherwise how many shapes it has."""
    path = annotation_path(folder, rel)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return len(payload.get("shapes") or [])
    except Exception:
        return None


def rename_label(folder, rels, old, new) -> int:
    """Rewrite `old` as `new` in every file of the batch.  Returns files changed."""
    changed = 0
    for rel in rels:
        result = read_annotation(folder, rel)
        if not result.found or result.error:
            continue
        hit = False
        for shape in result.shapes:
            if shape.label == old:
                shape.label = new
                hit = True
        if hit:
            ok, _error = write_annotation(folder, rel, result.shapes, result.width,
                                          result.height, result.verified)
            changed += 1 if ok else 0
    return changed
