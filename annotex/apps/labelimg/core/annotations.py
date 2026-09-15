"""Every read and write of annotation files for one batch folder.

LabelImg keeps one annotation file per image - a Pascal VOC .xml, a YOLO
.txt or a CreateML .json with the image's name - either beside the image or
in a separate save folder.  This module finds them, reads them into Box
objects, and writes them back through LabelImg's own writers, so the bytes on
disk are exactly what LabelImg has always produced.

What it adds on top of that is safety:

* every write goes to a temporary file, is parsed back, and only then
  replaces the old file;
* the previous version is kept in a hidden .labelimg_backup folder beside the
  annotations (one copy per file, not a .bak littering the folder);
* a file changed by someone else since it was read is detected before it is
  overwritten;
* saving in a new format retires the old-format file for that image into the
  backup folder, so a stale .xml can never win over a fresh .txt on reload.

No Qt.
"""

from __future__ import annotations

import codecs
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from xml.etree import ElementTree

from annotex.core.io_safe import (WriteReport, atomic_write, ensure_dir,
                                  read_json, write_text_atomic)

from ..config import (BACKUP_DIR, COPY_DIR, DELETED_DIR, FORMAT_CREATEML,
                      FORMAT_EXT, FORMAT_ORDER, FORMAT_VOC, FORMAT_YOLO,
                      IMG_EXTS, SKIP_DIRS, VERIFIED_LEDGER_NAME)
from .formats.create_ml_io import CreateMLReader, CreateMLWriter
from .formats.label_file import convert_points_to_bnd_box
from .formats.pascal_voc_io import PascalVocReader, PascalVocWriter
from .formats.yolo_io import YOLOWriter, YoloReader
from .model import Box

try:
    from PIL import Image
    HAS_PIL = True
except Exception:                                    # pragma: no cover
    Image = None
    HAS_PIL = False

_DIGITS = re.compile(r"(\d+)")


def natural_key(text):
    """Sort 'img2.jpg' before 'img10.jpg', case-insensitively."""
    return [int(part) if part.isdigit() else part
            for part in _DIGITS.split(str(text).lower())]


# ══════════════════════════════════════════════════════════════
# IMAGES
# ══════════════════════════════════════════════════════════════
def pil_probe(path):
    """(height, width, depth) of an image the way LabelImg records it.

    Depth is 1 for greyscale and 3 otherwise - what QImage.isGrayscale()
    reports, which is what the VOC <depth> element has always carried.  The
    window passes a Qt-based probe instead so the answer is identical by
    construction; this one serves the headless paths and the tests."""
    if not HAS_PIL:
        return None
    try:
        with Image.open(path) as im:
            width, height = im.size
            mode = im.mode
            depth = 3
            if mode in ("1", "L", "I", "I;16", "I;16B", "I;16L", "F"):
                depth = 1
            elif mode == "P":
                palette = im.getpalette() or []
                triples = [palette[i:i + 3] for i in range(0, len(palette), 3)]
                if triples and all(len(t) == 3 and t[0] == t[1] == t[2]
                                   for t in triples):
                    depth = 1
            return (int(height), int(width), depth)
    except Exception:
        return None


def scan_images(folder):
    """Every image under `folder`, as relative paths in natural order.

    Sub-folders are included, as they always were.  Hidden folders and the
    folders this tool writes its own output into are skipped."""
    folder = os.path.abspath(str(folder))
    found = []
    for root, dirs, files in os.walk(folder, onerror=lambda _error: None):
        dirs[:] = sorted(d for d in dirs
                         if not d.startswith(".") and d not in SKIP_DIRS)
        for name in files:
            if name.startswith(".") or not name.lower().endswith(IMG_EXTS):
                continue
            found.append(os.path.relpath(os.path.join(root, name), folder))
    found.sort(key=natural_key)
    return found


def _unique_destination(directory, name):
    destination = os.path.join(directory, name)
    if not os.path.exists(destination):
        return destination
    stem, ext = os.path.splitext(name)
    counter = 2
    while True:
        candidate = os.path.join(directory, "%s_%d%s" % (stem, counter, ext))
        if not os.path.exists(candidate):
            return candidate
        counter += 1


# ══════════════════════════════════════════════════════════════
# RESULTS
# ══════════════════════════════════════════════════════════════
@dataclass
class ReadResult:
    fmt: str = ""
    path: str = ""
    boxes: list = field(default_factory=list)
    verified: bool = False
    notes: list = field(default_factory=list)
    error: str = ""
    adjusted: int = 0

    @property
    def found(self) -> bool:
        return bool(self.path)


@dataclass
class Summary:
    """What an annotation file says, without needing the image."""

    fmt: str
    path: str
    labels: list = field(default_factory=list)
    verified: bool = False
    error: str = ""

    @property
    def count(self) -> int:
        return len(self.labels)

    @property
    def status(self) -> str:
        return "labelled" if self.labels else "background"


# ══════════════════════════════════════════════════════════════
class VerifiedLedger:
    """Which images were marked verified, for YOLO.

    Pascal VOC and CreateML carry the verified flag inside the file.  YOLO
    has nowhere to put it, so LabelImg used to forget it the moment the image
    was closed.  This small ledger beside the images remembers it instead,
    without changing a byte of the .txt files."""

    def __init__(self, folder):
        self.path = os.path.join(str(folder), VERIFIED_LEDGER_NAME)
        data = read_json(self.path, {})
        self.data = {str(k): True for k, v in (data or {}).items()
                     if v} if isinstance(data, dict) else {}

    def get(self, rel) -> bool:
        return bool(self.data.get(_ledger_key(rel)))

    def set(self, rel, value) -> bool:
        key = _ledger_key(rel)
        if bool(value) == bool(self.data.get(key)):
            return True
        if value:
            self.data[key] = True
        else:
            self.data.pop(key, None)
        ok, _err = write_text_atomic(self.path, json.dumps(self.data, indent=1,
                                                           sort_keys=True),
                                     verify_json=True, keep_backup=False)
        return ok


def _ledger_key(rel):
    return str(rel).replace(os.sep, "/")


# ══════════════════════════════════════════════════════════════
class AnnotationFolder:
    """Where one batch's annotation files live, and every read and write.

    `rel` arguments are image paths relative to the image folder."""

    def __init__(self, image_folder, save_dir="", search_image_dir=True):
        self.image_folder = os.path.abspath(str(image_folder))
        self.save_dir = os.path.abspath(str(save_dir)) if save_dir else ""
        self.search_image_dir = bool(search_image_dir)
        self.stamps = {}                 # rel -> (path, mtime) at last read
        self._seen = set()
        self._classes_cache = {}
        self.ledger = VerifiedLedger(self.image_folder)

    # ── locations ─────────────────────────────────────────
    def image_path(self, rel) -> str:
        return os.path.join(self.image_folder, rel)

    @staticmethod
    def stem(rel) -> str:
        return os.path.splitext(os.path.basename(str(rel)))[0]

    def target_dir(self, rel) -> str:
        return self.save_dir or os.path.dirname(self.image_path(rel))

    def target_path(self, rel, fmt) -> str:
        return os.path.join(self.target_dir(rel), self.stem(rel) + FORMAT_EXT[fmt])

    def stem_collisions(self, rels):
        """Images that would write to the same annotation file.

        An annotation is named after the image's stem, so two images with the
        same name in different sub-folders are only safe while their
        annotations sit beside them.  Pointed at one shared folder, the second
        would silently overwrite the first - so the caller is told before a
        single box is drawn."""
        if not self.save_dir:
            return {}
        seen = {}
        for rel in rels:
            seen.setdefault(self.stem(rel).lower(), []).append(rel)
        return {stem: names for stem, names in seen.items() if len(names) > 1}

    def search_dirs(self, rel):
        dirs = []
        if self.save_dir:
            dirs.append(self.save_dir)
        if self.search_image_dir or not self.save_dir:
            here = os.path.dirname(self.image_path(rel))
            if here not in dirs:
                dirs.append(here)
        return dirs

    @staticmethod
    def backup_path(path) -> str:
        return os.path.join(os.path.dirname(path), BACKUP_DIR,
                            os.path.basename(path))

    def _candidates(self, rel, directory):
        stem = self.stem(rel)
        for fmt in FORMAT_ORDER:
            if fmt == FORMAT_YOLO and stem.lower() == "classes":
                continue                  # an image called classes.jpg
            yield fmt, os.path.join(directory, stem + FORMAT_EXT[fmt])

    def find(self, rel):
        """(format, path) of this image's annotation, or ("", "")."""
        for directory in self.search_dirs(rel):
            for fmt, path in self._candidates(rel, directory):
                if not os.path.isfile(path):
                    continue
                if fmt == FORMAT_CREATEML and not _looks_like_createml(path):
                    continue              # some other JSON that shares the name
                return fmt, path
        return "", ""

    # ── reading ───────────────────────────────────────────
    def read(self, rel, image_shape) -> ReadResult:
        fmt, path = self.find(rel)
        self._seen.add(rel)
        if not fmt:
            self.stamps.pop(rel, None)
            return ReadResult()
        result = self.read_path(path, fmt, rel, image_shape)
        self._stamp(rel, path)
        return result

    def read_path(self, path, fmt, rel, image_shape, classes_path=None) -> ReadResult:
        result = ReadResult(fmt=fmt, path=path)
        height, width = int(image_shape[0]), int(image_shape[1])
        shapes = []
        if fmt == FORMAT_VOC:
            reader = PascalVocReader(path)
            result.error = reader.error
            result.verified = reader.verified
            shapes = reader.get_shapes()
        elif fmt == FORMAT_YOLO:
            try:
                reader = YoloReader(path, image_shape, classes_path)
            except Exception as exc:
                result.error = str(exc) or exc.__class__.__name__
                reader = None
            if reader is not None:
                shapes = reader.get_shapes()
                result.verified = self.ledger.get(rel)
                if reader.skipped:
                    result.notes.append("skipped %d unreadable line(s) in %s"
                                        % (reader.skipped, os.path.basename(path)))
                if not reader.classes and shapes:
                    result.notes.append("classes.txt is missing - classes are "
                                        "shown by number")
        else:
            reader = CreateMLReader(path, self.image_path(rel))
            result.error = reader.error
            result.verified = bool(reader.verified)
            shapes = reader.get_shapes()

        for label, points, _line, _fill, difficult in shapes:
            box = Box.from_points(label, points, difficult)
            if width and height:
                clamped = box.resized(box.x0, box.y0, box.x1, box.y1, width, height)
                if not clamped.same_geometry(box, 1e-9):
                    result.adjusted += 1
                box = clamped
            result.boxes.append(box)
        if result.adjusted:
            result.notes.append("%d box(es) reached outside the image and were "
                                "pulled back in" % result.adjusted)
        if result.error:
            result.notes.append("%s could not be read (%s)"
                                % (os.path.basename(path), result.error))
        return result

    def _stamp(self, rel, path) -> None:
        try:
            self.stamps[rel] = (path, os.path.getmtime(path))
        except OSError:
            self.stamps.pop(rel, None)

    def changed_externally(self, rel) -> bool:
        """True when this image's annotation on disk is not the one this
        session last read or wrote - another session, a sync client or a
        script has been here since."""
        if rel not in self._seen:
            return False
        _fmt, path = self.find(rel)
        known = self.stamps.get(rel)
        if known is None:
            return bool(path)
        old_path, mtime = known
        if not path:
            return False
        if os.path.abspath(path) != os.path.abspath(old_path):
            return True
        try:
            return abs(os.path.getmtime(path) - mtime) > 1e-6
        except OSError:
            return False

    def accept_external(self, rel) -> None:
        """The user chose to overwrite; stop warning about this version."""
        _fmt, path = self.find(rel)
        if path:
            self._stamp(rel, path)
        else:
            self.stamps.pop(rel, None)

    # ── writing ───────────────────────────────────────────
    def write(self, rel, boxes, fmt, image_shape, verified=False,
              class_list=(), class_id_map=None) -> WriteReport:
        report = WriteReport()
        if fmt not in FORMAT_EXT:
            report.errors.append("unknown format %r" % fmt)
            return report
        directory = self.target_dir(rel)
        if not ensure_dir(directory):
            report.errors.append("could not create %s" % directory)
            return report

        path = self.target_path(rel, fmt)
        image_path = self.image_path(rel)
        folder_name = os.path.split(os.path.dirname(image_path))[-1]
        filename = os.path.basename(image_path)
        shape = [int(image_shape[0]), int(image_shape[1]),
                 int(image_shape[2]) if len(image_shape) > 2 else 3]
        shapes = [box.to_writer_shape() for box in boxes]

        if fmt == FORMAT_VOC:
            def write_fn(tmp):
                writer = PascalVocWriter(folder_name, filename, shape,
                                         local_img_path=image_path)
                writer.verified = bool(verified)
                for item in shapes:
                    bnd = convert_points_to_bnd_box(item["points"])
                    writer.add_bnd_box(bnd[0], bnd[1], bnd[2], bnd[3],
                                       item["label"], int(item["difficult"]))
                writer.save(target_file=tmp)

            def verify_fn(tmp):
                ElementTree.parse(tmp)

        elif fmt == FORMAT_YOLO:
            def write_fn(tmp):
                writer = YOLOWriter(folder_name, filename, shape,
                                    local_img_path=image_path)
                writer.verified = bool(verified)
                for item in shapes:
                    bnd = convert_points_to_bnd_box(item["points"])
                    writer.add_bnd_box(bnd[0], bnd[1], bnd[2], bnd[3],
                                       item["label"], int(item["difficult"]))
                writer.save(class_list=list(class_list or []), target_file=tmp,
                            class_id_map=class_id_map)
                self._classes_cache.pop(os.path.dirname(os.path.abspath(tmp)),
                                        None)

            def verify_fn(tmp):
                with open(tmp, "r", encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        parts = line.split()
                        if len(parts) != 5:
                            raise ValueError("malformed YOLO line")
                        int(parts[0])
                        [float(p) for p in parts[1:]]

        else:
            existing_ok = False
            if os.path.isfile(path):
                existing_ok = _looks_like_createml(path)
                if not existing_ok:
                    report.warnings.append("%s was not a CreateML file and "
                                           "was replaced" % os.path.basename(path))

            def write_fn(tmp):
                if existing_ok:
                    shutil.copyfile(path, tmp)
                else:
                    os.remove(tmp)
                writer = CreateMLWriter(folder_name, filename, shape, shapes,
                                        tmp, local_img_path=image_path)
                writer.verified = bool(verified)
                writer.write()

            def verify_fn(tmp):
                with open(tmp, "r", encoding="utf-8") as handle:
                    if not isinstance(json.load(handle), list):
                        raise ValueError("CreateML output is not a list")

        ok, err = atomic_write(path, write_fn, verify_fn, keep_backup=True,
                               backup_to=self.backup_path(path))
        if not ok:
            report.errors.append("%s: %s" % (os.path.basename(path), err))
            return report

        report.written.append(path)
        self._seen.add(rel)
        self._stamp(rel, path)
        self._retire_other_formats(rel, fmt, directory, report)
        if fmt == FORMAT_YOLO:
            self.ledger.set(rel, verified)
        return report

    def _retire_other_formats(self, rel, fmt, directory, report) -> None:
        for other, old in self._candidates(rel, directory):
            if other == fmt or not os.path.isfile(old):
                continue
            if other == FORMAT_CREATEML and not _looks_like_createml(old):
                continue
            destination = self.backup_path(old)
            try:
                ensure_dir(os.path.dirname(destination))
                os.replace(old, destination)
                report.warnings.append("the older %s was moved to %s"
                                       % (os.path.basename(old), BACKUP_DIR))
            except OSError as exc:
                report.warnings.append("could not retire %s (%s)"
                                       % (os.path.basename(old), exc))

    # ── backups ───────────────────────────────────────────
    def backup_for(self, rel):
        for directory in self.search_dirs(rel):
            for fmt, path in self._candidates(rel, directory):
                candidate = self.backup_path(path)
                if os.path.isfile(candidate):
                    return fmt, candidate
        return "", ""

    def read_backup(self, rel, image_shape) -> ReadResult:
        fmt, path = self.backup_for(rel)
        if not fmt:
            return ReadResult()
        classes = os.path.join(os.path.dirname(os.path.dirname(path)), "classes.txt")
        return self.read_path(path, fmt, rel, image_shape,
                              classes if fmt == FORMAT_YOLO else None)

    # ── summaries ─────────────────────────────────────────
    def _classes_for(self, directory):
        path = os.path.join(directory, "classes.txt")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return []
        cached = self._classes_cache.get(directory)
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            with codecs.open(path, "r", "utf-8", errors="replace") as handle:
                names = handle.read().strip("\n").split("\n")
        except OSError:
            names = []
        self._classes_cache[directory] = (mtime, names)
        return names

    def summarise(self, rel):
        """A Summary of this image's annotation, or None if it has none."""
        fmt, path = self.find(rel)
        if not fmt:
            return None
        summary = Summary(fmt, path)
        try:
            if fmt == FORMAT_VOC:
                root = ElementTree.parse(path).getroot()
                summary.verified = root.attrib.get("verified") == "yes"
                summary.labels = [(item.findtext("name") or "")
                                  for item in root.findall("object")]
            elif fmt == FORMAT_YOLO:
                classes = self._classes_for(os.path.dirname(path))
                with codecs.open(path, "r", "utf-8", errors="replace") as handle:
                    for line in handle:
                        parts = line.split()
                        if len(parts) != 5:
                            continue
                        try:
                            index = int(parts[0])
                        except ValueError:
                            continue
                        summary.labels.append(
                            classes[index] if 0 <= index < len(classes)
                            and classes[index] else "class_%d" % index)
                summary.verified = self.ledger.get(rel)
            else:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                name = os.path.basename(self.image_path(rel))
                for entry in data:
                    if entry.get("image") == name:
                        summary.verified = bool(entry.get("verified", False))
                        summary.labels = [a.get("label", "")
                                          for a in entry.get("annotations", [])]
                        break
        except Exception as exc:
            summary.error = str(exc) or exc.__class__.__name__
        return summary

    def build_index(self, rels):
        return {rel: self.summarise(rel) for rel in rels}


def _looks_like_createml(path) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return isinstance(data, list) and all(
            isinstance(entry, dict) and "image" in entry for entry in data)
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
# BATCH OPERATIONS
# ══════════════════════════════════════════════════════════════
def apply_boxes(folder_io, rels, boxes, fmt, probe, class_list=(),
                class_id_map=None):
    """Write the same boxes (or, with an empty list, a background decision)
    to many images without opening them.

    Each box is clamped to each image, so a box drawn on a 1920x1080 frame
    still lands correctly on a 1280x720 one.  Returns (done, skipped, notes)."""
    done, skipped, notes = [], [], []
    for rel in rels:
        shape = probe(folder_io.image_path(rel))
        if not shape:
            skipped.append(rel)
            notes.append("%s could not be read" % rel)
            continue
        keep = []
        for box in boxes:
            clean, _messages = box.copy().validated(shape[1], shape[0])
            if clean is not None:
                keep.append(clean)
        if boxes and not keep:
            skipped.append(rel)
            notes.append("%s: no box fitted the image" % rel)
            continue
        report = folder_io.write(rel, keep, fmt, shape, False, class_list,
                                 class_id_map)
        if report.ok:
            done.append(rel)
        else:
            skipped.append(rel)
            notes.append(report.summary())
    return done, skipped, notes


def move_to_deleted(folder_io, rel):
    """Move an image - and its annotation, so the pair stays together - into
    deleted_images inside the batch.  Nothing is erased.

    Returns (ok, message, moved_paths)."""
    target = os.path.join(folder_io.image_folder, DELETED_DIR)
    if not ensure_dir(target):
        return False, "could not create %s" % DELETED_DIR, []
    moved = []
    source = folder_io.image_path(rel)
    try:
        destination = _unique_destination(target, os.path.basename(source))
        shutil.move(source, destination)
        moved.append(destination)
    except OSError as exc:
        return False, "the image could not be moved (%s)" % exc, []
    stem = os.path.splitext(os.path.basename(moved[0]))[0]
    for directory in folder_io.search_dirs(rel):
        for fmt, path in folder_io._candidates(rel, directory):
            if not os.path.isfile(path):
                continue
            if fmt == FORMAT_CREATEML and not _looks_like_createml(path):
                continue              # some other JSON that shares the name
            try:
                ext = os.path.splitext(path)[1]
                annotation_dest = _unique_destination(target, stem + ext)
                shutil.move(path, annotation_dest)
                moved.append(annotation_dest)
            except OSError:
                continue
    folder_io.stamps.pop(rel, None)
    return True, "moved to %s" % DELETED_DIR, moved


def copy_to_copies(folder_io, rel):
    """Copy an image into copy_images inside the batch.  Returns (ok, message)."""
    target = os.path.join(folder_io.image_folder, COPY_DIR)
    if not ensure_dir(target):
        return False, "could not create %s" % COPY_DIR
    source = folder_io.image_path(rel)
    try:
        destination = os.path.join(target, os.path.basename(source))
        shutil.copy2(source, destination)
        return True, destination
    except OSError as exc:
        return False, str(exc)
