"""Importing another annotator's work and merging it with this batch.

Point it at a folder of annotations for the same images - VOC, YOLO or
CreateML, in any mix - and it matches them to this batch's images by name.
Images only one side has are simply taken.  Images both sides describe
differently are resolved by the chosen strategy and every one of them is
listed, rather than a winner being picked silently.  No Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .annotations import AnnotationFolder
from .model import boxes_match, iou

STRATEGIES = {
    "union": "Keep every box from both (overlapping duplicates merged)",
    "incoming": "On a conflict keep the imported annotation",
    "most": "On a conflict keep whichever has more boxes",
    "keep": "On a conflict keep what this batch already has",
}

DUPLICATE_IOU = 0.9


@dataclass
class ImportResult:
    incoming: int = 0                                  # annotations found
    merged: dict = field(default_factory=dict)         # rel -> boxes to write
    conflicts: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.errors:
            return "Import failed - " + "; ".join(self.errors[:2])
        text = "Found %d annotation(s), %d image(s) to update" % (
            self.incoming, len(self.merged))
        if self.conflicts:
            text += "  |  %d conflict(s)" % len(self.conflicts)
        return text


def read_folder(other_folder, image_folder, rels, probe):
    """{rel: [Box]} for every image of this batch the other folder annotates."""
    other = AnnotationFolder(image_folder, save_dir=other_folder,
                             search_image_dir=False)
    found, notes = {}, []
    for rel in rels:
        fmt, path = other.find(rel)
        if not fmt:
            continue
        shape = probe(other.image_path(rel))
        if not shape:
            notes.append("%s could not be read, so its import was skipped" % rel)
            continue
        result = other.read_path(path, fmt, rel, shape)
        if result.error:
            notes.append(result.notes[-1])
            continue
        found[rel] = result.boxes
    return found, notes


def _union(mine, theirs):
    out = [box.copy() for box in mine]
    for box in theirs:
        if not any(box.label == kept.label and iou(box, kept) >= DUPLICATE_IOU
                   for kept in out):
            out.append(box.copy())
    return out


def merge(current, incoming, strategy="union") -> ImportResult:
    """`current` maps rel -> boxes for images that already have an annotation
    (images without one are simply absent).  Only images whose annotation
    would change appear in the result."""
    result = ImportResult(incoming=len(incoming))
    if strategy not in STRATEGIES:
        strategy = "union"
    for rel, theirs in incoming.items():
        mine = current.get(rel)
        if mine is None:
            result.merged[rel] = [box.copy() for box in theirs]
            continue
        if boxes_match(mine, theirs):
            continue
        result.conflicts.append({"image": rel, "current": len(mine),
                                 "incoming": len(theirs)})
        if strategy == "keep":
            continue
        if strategy == "incoming":
            chosen = theirs
        elif strategy == "most":
            chosen = theirs if len(theirs) > len(mine) else None
        else:
            chosen = _union(mine, theirs)
        if chosen is not None and not boxes_match(mine, chosen):
            result.merged[rel] = [box.copy() for box in chosen]
    result.notes.append("merged with the '%s' strategy" % strategy)
    return result
