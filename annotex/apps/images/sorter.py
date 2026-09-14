"""Sorting images into folders - by hand, by rule, or by model.  No Qt.

Sorting always copies: the originals are never moved or changed.  Every copy
is recorded in `sort_log.csv` in the output folder with the run it belongs
to, which is what makes undo possible - undo removes the copies a run made
(only if they are still the file that was copied) and marks them in the log.
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import uuid
from datetime import datetime

from annotex.core.jobs import JobCancelled

from .common import natural_key

LOG_NAME = "sort_log.csv"
LOG_FIELDS = ["run", "time", "mode", "source", "destination", "category", "detail", "state"]
UNMATCHED = "_unmatched"
UNSURE = "_unsure"
EMPTY = "_empty"


def default_output(source_folder):
    folder = os.path.abspath(str(source_folder)).rstrip(os.sep)
    return folder + "_sorted"


def safe_folder_name(name):
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(name)).strip().strip(".")
    return cleaned or UNMATCHED


# ══════════════════════════════════════════════════════════════
class SortSession:
    """Copies into category folders under one output root, with a log."""

    def __init__(self, output_root, mode="manual"):
        self.output_root = os.path.abspath(str(output_root))
        self.mode = mode
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.log_path = os.path.join(self.output_root, LOG_NAME)
        self.copied = []                      # (source, destination, category) this run

    def copy(self, source, category, detail=""):
        category = safe_folder_name(category)
        folder = os.path.join(self.output_root, category)
        os.makedirs(folder, exist_ok=True)
        name = os.path.basename(source)
        destination = os.path.join(folder, name)
        stem, ext = os.path.splitext(name)
        counter = 2
        while os.path.exists(destination):
            if _same_file(source, destination):
                self._log(source, destination, category, detail, "already there")
                return destination
            destination = os.path.join(folder, "%s_%d%s" % (stem, counter, ext))
            counter += 1
        part = os.path.join(folder, "." + os.path.basename(destination) + ".part")
        try:
            shutil.copy2(source, part)
            os.replace(part, destination)
        finally:
            if os.path.exists(part):
                os.remove(part)
        self.copied.append((source, destination, category))
        self._log(source, destination, category, detail, "copied")
        return destination

    def _log(self, source, destination, category, detail, state):
        os.makedirs(self.output_root, exist_ok=True)
        new = not os.path.isfile(self.log_path)
        with open(self.log_path, "a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
            if new:
                writer.writeheader()
            writer.writerow({"run": self.run_id, "time": datetime.now().isoformat(timespec="seconds"),
                             "mode": self.mode, "source": source, "destination": destination,
                             "category": category, "detail": detail, "state": state})

    def undo_last(self):
        """Remove the most recent copy of this session.  Returns it or None."""
        while self.copied:
            source, destination, category = self.copied.pop()
            if _remove_copy(source, destination):
                self._log(source, destination, category, "undo", "undone")
                return source, destination, category
        return None


def _same_file(a, b):
    try:
        return os.path.getsize(a) == os.path.getsize(b) and \
            int(os.path.getmtime(a)) == int(os.path.getmtime(b))
    except OSError:
        return False


def _remove_copy(source, destination):
    if not os.path.isfile(destination):
        return False
    if os.path.isfile(source) and not _same_file(source, destination):
        return False                       # someone replaced it; leave it alone
    os.remove(destination)
    folder = os.path.dirname(destination)
    try:
        if not os.listdir(folder):
            os.rmdir(folder)
    except OSError:
        pass
    return True


def read_log(output_root):
    path = os.path.join(str(output_root), LOG_NAME)
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def runs(output_root):
    """[(run_id, mode, copies still in place, time)] newest first."""
    summary = {}
    for row in read_log(output_root):
        entry = summary.setdefault(row["run"], {"mode": row["mode"], "time": row["time"],
                                                "live": {}})
        if row["state"] == "copied":
            entry["live"][row["destination"]] = row["source"]
        elif row["state"] == "undone":
            entry["live"].pop(row["destination"], None)
    out = [(run, e["mode"], len(e["live"]), e["time"]) for run, e in summary.items()]
    return sorted(out, key=lambda r: r[3], reverse=True)


def undo_run(output_root, run_id):
    """Remove every copy a run made.  Returns how many were removed."""
    live = {}
    for row in read_log(output_root):
        if row["run"] != run_id:
            continue
        if row["state"] == "copied":
            live[row["destination"]] = row
        elif row["state"] == "undone":
            live.pop(row["destination"], None)
    session = SortSession(output_root, "undo")
    removed = 0
    for destination, row in live.items():
        if _remove_copy(row["source"], destination):
            removed += 1
            session.run_id = run_id
            session._log(row["source"], destination, row["category"], "undo run", "undone")
    return removed


# ══════════════════════════════════════════════════════════════
# RULES
# ══════════════════════════════════════════════════════════════
RULES = {
    "name_tokens": "Filename - first parts before '_' (site / camera)",
    "name_regex": "Filename - regular expression",
    "date": "Date taken (EXIF, else file date)",
    "resolution": "Resolution (e.g. 1920x1080)",
    "orientation": "Orientation (landscape / portrait / square)",
    "labelimg": "LabelImg annotation (labelled / background / none)",
    "roi": "ROI Studio annotation (roi / no_roi / none)",
}


def _exif_date(path):
    try:
        from PIL import Image
        with Image.open(path) as image:
            exif = image.getexif()
            value = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        if value:
            return datetime.strptime(str(value).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None
    return None


class RuleCategoriser:
    """Turns an image path into a folder name for one rule."""

    def __init__(self, rule, tokens=2, regex="", granularity="day", save_dir=""):
        if rule not in RULES:
            raise ValueError("Unknown rule %r" % rule)
        self.rule = rule
        self.tokens = max(1, int(tokens))
        self.granularity = granularity
        self.save_dir = save_dir
        self.pattern = None
        if rule == "name_regex":
            try:
                self.pattern = re.compile(regex)
            except re.error as exc:
                raise ValueError("The regular expression is invalid: %s" % exc)
        self._labelimg = {}
        self._roi = {}

    def __call__(self, path):
        name = os.path.basename(path)
        stem = os.path.splitext(name)[0]
        if self.rule == "name_tokens":
            parts = stem.split("_")
            if len(parts) <= self.tokens:
                return UNMATCHED, "fewer than %d parts" % (self.tokens + 1)
            return "_".join(parts[:self.tokens]), ""
        if self.rule == "name_regex":
            match = self.pattern.search(stem)
            if not match:
                return UNMATCHED, "no match"
            if match.groupdict():
                value = next(v for v in match.groupdict().values() if v is not None) \
                    if any(match.groupdict().values()) else match.group(0)
            elif match.groups():
                value = match.group(1) or match.group(0)
            else:
                value = match.group(0)
            return value, ""
        if self.rule == "date":
            taken = _exif_date(path)
            source = "exif"
            if taken is None:
                taken = datetime.fromtimestamp(os.path.getmtime(path))
                source = "file date"
            fmt = {"year": "%Y", "month": "%Y-%m", "day": "%Y-%m-%d",
                   "hour": "%Y-%m-%d_%Hh"}.get(self.granularity, "%Y-%m-%d")
            return taken.strftime(fmt), source
        if self.rule in ("resolution", "orientation"):
            from PIL import Image, ImageOps
            with Image.open(path) as image:
                width, height = ImageOps.exif_transpose(image).size if self.rule == "orientation" \
                    else image.size
            if self.rule == "resolution":
                return "%dx%d" % (width, height), ""
            if abs(width - height) <= max(width, height) * 0.02:
                return "square", "%dx%d" % (width, height)
            return ("landscape" if width > height else "portrait"), "%dx%d" % (width, height)
        if self.rule == "labelimg":
            return self._labelimg_status(path)
        return self._roi_status(path)

    def _labelimg_status(self, path):
        from annotex.apps.labelimg.core.annotations import AnnotationFolder
        folder = os.path.dirname(path)
        io = self._labelimg.get(folder)
        if io is None:
            io = self._labelimg[folder] = AnnotationFolder(folder, self.save_dir)
        summary = io.summarise(os.path.basename(path))
        if summary is None:
            return "unannotated", ""
        return summary.status, "%d box(es) in %s" % (summary.count, summary.fmt)

    def _roi_status(self, path):
        from annotex.apps.roi.core.store import AnnotationStore
        folder = os.path.dirname(path)
        rows = self._roi.get(folder)
        if rows is None:
            store = AnnotationStore()
            store.bind(folder)
            try:
                store.load()
            except Exception:
                pass
            rows = self._roi[folder] = {r["image_name"]: r.get("row_type", "") for r in store.rows}
        kind = rows.get(os.path.basename(path))
        if kind == "roi":
            return "roi", ""
        if kind == "no_roi":
            return "no_roi", ""
        return "unannotated", ""


def preview(images, categoriser, limit=None):
    """{category: [images]} and [(image, error)] without copying anything."""
    groups, errors = {}, []
    for image in images[:limit] if limit else images:
        try:
            category, _detail = categoriser(image)
            groups.setdefault(safe_folder_name(category), []).append(image)
        except Exception as exc:                                   # noqa: BLE001
            errors.append((image, str(exc)))
    return dict(sorted(groups.items(), key=lambda kv: natural_key(kv[0]))), errors


def run_sort(ctx, images, categorise, output_root, mode):
    """Copy every image into the folder `categorise(image)` names.

    `categorise` returns (category, detail) or (list_of_categories, detail).
    Returns (summary, {category: count}, run_id)."""
    session = SortSession(output_root, mode)
    counts, failed = {}, 0
    total = len(images) or 1
    for index, image in enumerate(images):
        if ctx is not None:
            if ctx.cancelled:
                raise JobCancelled()
            ctx.progress(index / float(total), "%d of %d  ·  %s"
                         % (index + 1, len(images), os.path.basename(image)))
        try:
            categories, detail = categorise(image)
            if isinstance(categories, str):
                categories = [categories]
            for category in categories:
                session.copy(image, category, detail)
                key = safe_folder_name(category)
                counts[key] = counts.get(key, 0) + 1
        except Exception as exc:                                   # noqa: BLE001
            failed += 1
            if ctx is not None:
                ctx.warn("%s: %s" % (os.path.basename(image), exc))
    if ctx is not None:
        ctx.progress(1.0)
        ctx.output(output_root)
    parts = ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items(),
                                                          key=lambda kv: natural_key(kv[0])))
    summary = "Sorted %d image(s)%s%s" % (len(images) - failed, (" - " + parts) if parts else "",
                                           ", %d failed" % failed if failed else "")
    return summary, counts, session.run_id
