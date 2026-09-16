"""Dataset Tools - the operations.  No Qt.

Six independent operations for folders of images with YOLO-style .txt labels
beside them (a.jpg + a.txt).  None depends on another having run first.

    empty_labels     remove .txt files that hold nothing but whitespace
    unpaired         move images without a .txt into "unpaired images"
    rename_pairs     rename every image + .txt pair to <name>_001, _002, …
    split            move pairs into part_1, part_2, … of sizes you choose
    rename_parts     rename part_1, part_2, … folders to <name>_1, _2, …
    zip_folders      compress each sub-folder into zipped/<folder>.zip

Every operation is two calls, so nothing ever happens that was not shown:

    plan = plan_xxx(root, …)     look only - the disk is not touched
    summary = apply(plan, ctx)   do exactly the plan, reporting as it goes

and every change is written to a history file first, so any run can be
undone later - after closing the app too:

    runs()                       what has been done, newest first
    undo(run_id)                 put it back

Nothing is ever deleted outright: a "removed" file is moved into a hidden
.annotex_removed folder inside the dataset, on the same drive, and undo moves
it back.  Renames go through temporary names in two phases, so an
interruption can never leave two files wanting the same name, and a pair's
image and label move together or not at all.

Written for folders on Windows, macOS and Linux alike: names are checked
against Windows' rules, extensions and stems are compared without case (as
Windows does), and files a permission problem or a lock refuses are reported
and skipped rather than stopping the run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

from annotex.config import first_writable, user_data_dir
from annotex.core.jobs import JobCancelled

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp")
LABEL_EXT = ".txt"
UNPAIRED_FOLDER = "unpaired images"
ZIP_FOLDER = "zipped"
HOLDING_FOLDER = ".annotex_removed"
TEMP_PREFIX = ".annotex_tmp_"
DEFAULT_PART = "part"

OPERATIONS = (
    ("empty_labels", "Delete empty .txt files",
     "Finds .txt label files with nothing in them - or only spaces and blank lines - in "
     "the folder and its sub-folders, and removes them.  Files with any content at all "
     "are left alone, and images are never touched."),
    ("unpaired", "Move unpaired images",
     "Moves every image that has no .txt file of the same name into an "
     "\"unpaired images\" folder.  Complete pairs, and .txt files, stay where they are."),
    ("rename_pairs", "Rename image + label pairs",
     "Renames every image and its .txt file to one name with a number - "
     "name_001.jpg and name_001.txt - so they always stay matched."),
    ("split", "Split into parts",
     "Moves the pairs into part_1, part_2, … with as many pairs in each as you choose.  "
     "An image and its .txt always go to the same part."),
    ("rename_parts", "Rename part folders",
     "Renames part_1, part_2, … to a name of your choice, keeping each folder's number.  "
     "Only the folder names change, never what is inside."),
    ("zip_folders", "Zip each folder",
     "Compresses every sub-folder into its own .zip in a \"zipped\" folder.  The "
     "folders themselves are left exactly as they are."),
    ("check_labels", "Check & fix labels",
     "Reads every .txt label and finds the lines that break training: class ids that are "
     "not whole numbers or not one of your classes, the wrong number of values, "
     "coordinates outside the image, boxes with no size and repeated boxes.  You choose "
     "what is fixed; the rest is only reported."),
    ("split_sets", "Train / val / test split",
     "Divides the image + label pairs into train, val and test in the layout YOLO expects "
     "(images/train, labels/train, …), the same way every time for the same seed, keeps "
     "every class in each set where there are enough images, and writes data.yaml."),
    ("class_tools", "Class tools",
     "Counts the boxes of every class across the labels, and changes class ids everywhere "
     "at once: renumber a class, merge several into one, or delete a class's boxes."),
)
TITLES = {key: title for key, title, _text in OPERATIONS}

_RESERVED = {"con", "prn", "aux", "nul"} | {"com%d" % i for i in range(1, 10)} | \
    {"lpt%d" % i for i in range(1, 10)}
_BAD_CHARS = set('<>:"/\\|?*')


class DatasetError(RuntimeError):
    """Stops an operation.  The message is written for a person."""


# ══════════════════════════════════════════════════════════════
# BASICS
# ══════════════════════════════════════════════════════════════
def natural_key(text):
    """"img2" before "img10", and case does not matter."""
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", str(text))]


def name_problem(name, what="name") -> str:
    """Why `name` cannot be a file or folder name everywhere, or ""."""
    name = "" if name is None else str(name)
    if not name.strip():
        return "Enter a %s." % what
    if name != name.strip():
        return "The %s cannot start or end with a space." % what
    bad = sorted({c for c in name if c in _BAD_CHARS or ord(c) < 32})
    if bad:
        shown = " ".join(repr(c)[1:-1] if ord(c) < 32 else c for c in bad)
        return "The %s cannot contain %s" % (what, shown)
    if name.endswith("."):
        return "The %s cannot end with a dot." % what
    if name.split(".")[0].casefold() in _RESERVED:
        return "\"%s\" is a reserved name on Windows." % name
    if len(name) > 120:
        return "The %s is too long (120 characters at most)." % what
    if name.casefold().startswith(TEMP_PREFIX) or name.casefold() == HOLDING_FOLDER:
        return "That %s is used by Annotex itself." % what
    return ""


def check_root(root) -> str:
    if not root or not str(root).strip():
        raise DatasetError("Choose a folder first.")
    root = os.path.abspath(os.path.expanduser(str(root).strip().strip('"')))
    if not os.path.exists(root):
        raise DatasetError("That folder does not exist:\n%s" % root)
    if not os.path.isdir(root):
        raise DatasetError("That is a file, not a folder:\n%s" % root)
    if not os.access(root, os.R_OK):
        raise DatasetError("That folder cannot be read (permission denied):\n%s" % root)
    home = os.path.normcase(os.path.abspath(os.path.expanduser("~")))
    if os.path.dirname(root) == root or os.path.normcase(root) == home:
        raise DatasetError("Choose the dataset folder itself, not a whole drive or your "
                           "home folder:\n%s" % root)
    return root


def _entries(folder):
    """Top-level (files, folders) of a folder, natural order, skipping
    Annotex's own working names."""
    try:
        with os.scandir(folder) as found:
            entries = list(found)
    except OSError as exc:
        raise DatasetError("The folder cannot be read: %s" % exc)
    files, folders = [], []
    for entry in entries:
        lowered = entry.name.casefold()
        if lowered.startswith(TEMP_PREFIX) or lowered == HOLDING_FOLDER:
            continue
        try:
            if entry.is_file(follow_symlinks=False):
                files.append(entry.name)
            elif entry.is_dir(follow_symlinks=False):
                folders.append(entry.name)
        except OSError:
            continue
    return sorted(files, key=natural_key), sorted(folders, key=natural_key)


@dataclass
class Pair:
    image: str
    label: str


@dataclass
class PairScan:
    pairs: list = field(default_factory=list)          # [Pair]
    unpaired: list = field(default_factory=list)       # image names
    orphans: list = field(default_factory=list)        # .txt names with no image
    clashes: list = field(default_factory=list)        # [[names]] sharing one stem


def scan_pairs(folder) -> PairScan:
    """Match images to .txt files by name, without regard to case - as
    Windows does, so a folder behaves the same on every system."""
    files, _folders = _entries(folder)
    images, labels = {}, {}
    for name in files:
        stem, ext = os.path.splitext(name)
        key = stem.casefold()
        ext = ext.lower()
        if ext in IMAGE_EXTS:
            images.setdefault(key, []).append(name)
        elif ext == LABEL_EXT:
            labels.setdefault(key, []).append(name)
    scan = PairScan()
    for key in sorted(set(images) | set(labels), key=natural_key):
        found_images, found_labels = images.get(key, []), labels.get(key, [])
        if found_images and found_labels:
            if len(found_images) > 1 or len(found_labels) > 1:
                scan.clashes.append(sorted(found_images + found_labels, key=natural_key))
            else:
                scan.pairs.append(Pair(found_images[0], found_labels[0]))
        elif found_images:
            scan.unpaired.extend(found_images)
        else:
            scan.orphans.extend(found_labels)
    scan.pairs.sort(key=lambda pair: natural_key(pair.image))
    return scan


def is_blank_text(path):
    """True when a file holds nothing but whitespace (a byte-order mark alone
    counts as nothing), False when it holds anything else, None when it
    cannot be read.  Reads in chunks, so a huge file costs nothing."""
    try:
        with open(path, "rb") as handle:
            first = True
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    return True
                if first:
                    first = False
                    for mark in (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"):
                        if chunk.startswith(mark):
                            chunk = chunk[len(mark):]
                            break
                if chunk.translate(None, b" \t\r\n\x0b\x0c\x00"):
                    return False
    except OSError:
        return None


# ══════════════════════════════════════════════════════════════
# PLANS
# ══════════════════════════════════════════════════════════════
@dataclass
class Action:
    kind: str            # remove | move | rename | zip | rewrite | copy | write
    source: str          # absolute path
    target: str = ""     # absolute path ("" for remove: the holding folder is chosen later)
    group: int = 0       # actions sharing a group move together or not at all
    detail: str = ""     # what a rewrite changes, for the preview
    content: str = ""    # the new text of a rewrite or a written file
    stamp: tuple = ()    # (size, mtime) at preview time, to notice a file changed since


@dataclass
class Plan:
    operation: str
    root: str
    actions: list = field(default_factory=list)
    problems: list = field(default_factory=list)       # any of these stop the run
    notes: list = field(default_factory=list)          # worth knowing; do not stop it
    options: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        return TITLES.get(self.operation, self.operation)

    @property
    def runnable(self) -> bool:
        return bool(self.actions) and not self.problems

    def rows(self, limit=None):
        """(what, from, to) for a preview table, paths relative to the folder."""
        verbs = {"remove": "Remove", "move": "Move", "rename": "Rename", "zip": "Zip",
                 "copy": "Copy", "write": "Write",
                 "rewrite": "Fix" if self.operation == "check_labels" else "Change"}
        out = []
        for action in self.actions[:limit] if limit else self.actions:
            verb = verbs.get(action.kind, action.kind)
            if action.kind == "remove":
                out.append((verb, _relative(action.source, self.root),
                            "(kept in .annotex_removed until undone)"))
            elif action.kind == "rewrite":
                out.append((verb, _relative(action.source, self.root), action.detail))
            elif action.kind == "write":
                out.append((verb, "", _relative(action.target, self.root)))
            else:
                out.append((verb, _relative(action.source, self.root),
                            _relative(action.target, self.root)))
        return out


def _relative(path, root) -> str:
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def plan_empty_labels(root, include_subfolders=True) -> Plan:
    root = check_root(root)
    plan = Plan("empty_labels", root, options={"include_subfolders": bool(include_subfolders)})
    kept, unreadable, walk_errors = 0, [], []
    skip = {HOLDING_FOLDER, ZIP_FOLDER.casefold()}
    for folder, subfolders, files in os.walk(root, onerror=walk_errors.append):
        subfolders[:] = sorted((d for d in subfolders if d.casefold() not in skip
                                and not d.casefold().startswith(TEMP_PREFIX)), key=natural_key)
        if not include_subfolders:
            subfolders[:] = []
        for name in sorted(files, key=natural_key):
            if not name.lower().endswith(LABEL_EXT) or name.casefold().startswith(TEMP_PREFIX):
                continue
            path = os.path.join(folder, name)
            if os.path.islink(path):
                continue
            blank = is_blank_text(path)
            if blank is None:
                unreadable.append(_relative(path, root))
            elif blank:
                plan.actions.append(Action("remove", path))
            else:
                kept += 1
    plan.notes.append("%d .txt file(s) have content and are left alone." % kept)
    if unreadable:
        plan.notes.append("%d .txt file(s) could not be read and are left alone: %s"
                          % (len(unreadable), ", ".join(unreadable[:5])))
    if walk_errors:
        plan.notes.append("%d folder(s) could not be opened: %s"
                          % (len(walk_errors), walk_errors[0]))
    if not plan.actions:
        plan.notes.insert(0, "No empty .txt files were found.")
    return plan


def plan_unpaired(root) -> Plan:
    root = check_root(root)
    plan = Plan("unpaired", root)
    target_folder = os.path.join(root, UNPAIRED_FOLDER)
    if os.path.exists(target_folder) and not os.path.isdir(target_folder):
        plan.problems.append("There is a file called \"%s\" where the folder should go."
                             % UNPAIRED_FOLDER)
        return plan
    scan = scan_pairs(root)
    for image in scan.unpaired:
        target = os.path.join(target_folder, image)
        if os.path.lexists(target):
            plan.notes.append("\"%s\" is already in \"%s\" - left where it is."
                              % (image, UNPAIRED_FOLDER))
            continue
        plan.actions.append(Action("move", os.path.join(root, image), target))
    plan.notes.append("%d complete pair(s) stay where they are." % len(scan.pairs))
    if scan.orphans:
        plan.notes.append("%d .txt file(s) have no image; they are not moved." % len(scan.orphans))
    for clash in scan.clashes:
        plan.notes.append("These share one name, so they are left alone: %s" % ", ".join(clash))
    if not plan.actions and not plan.problems:
        plan.notes.insert(0, "Every image already has a .txt file.")
    return plan


def _pair_problems(plan, scan) -> None:
    for clash in scan.clashes:
        plan.notes.append("These share one name and are left out: %s" % ", ".join(clash))
    if scan.unpaired:
        plan.notes.append("%d image(s) without a .txt are not included." % len(scan.unpaired))


def plan_rename_pairs(root, base_name, start=1, digits=0) -> Plan:
    root = check_root(root)
    base_name = "" if base_name is None else str(base_name)
    plan = Plan("rename_pairs", root, options={"base_name": base_name, "start": start})
    problem = name_problem(base_name)
    if problem:
        plan.problems.append(problem)
        return plan
    try:
        start = int(start)
    except (TypeError, ValueError):
        plan.problems.append("The first number must be a whole number.")
        return plan
    if start < 0:
        plan.problems.append("The first number cannot be negative.")
        return plan
    scan = scan_pairs(root)
    _pair_problems(plan, scan)
    if not scan.pairs:
        plan.problems.append("No image + .txt pairs were found in this folder.")
        return plan
    width = max(3, int(digits or 0), len(str(start + len(scan.pairs) - 1)))
    files, folders = _entries(root)
    moving = set()
    for pair in scan.pairs:
        moving.add(pair.image.casefold())
        moving.add(pair.label.casefold())
    taken = {name.casefold() for name in files + folders} - moving
    unchanged = 0
    for index, pair in enumerate(scan.pairs):
        number = str(start + index).zfill(width)
        for name in (pair.image, pair.label):
            ext = os.path.splitext(name)[1]
            target = "%s_%s%s" % (base_name, number, ext)
            if target.casefold() in taken:
                plan.problems.append("\"%s\" already exists and is not one of the pairs "
                                     "being renamed - choose another name." % target)
                return plan
            if target == name:
                unchanged += 1
                continue
            plan.actions.append(Action("rename", os.path.join(root, name),
                                       os.path.join(root, target), group=index))
    if unchanged:
        plan.notes.append("%d file(s) already have their new name." % unchanged)
    plan.notes.insert(0, "%d pair(s) will be numbered %s_%s to %s_%s."
                      % (len(scan.pairs), base_name, str(start).zfill(width), base_name,
                         str(start + len(scan.pairs) - 1).zfill(width)))
    return plan


def parse_sizes(text):
    """"500, 500, rest" -> [500, 500, "rest"].  Raises DatasetError."""
    parts = [p.strip().lower() for p in re.split(r"[,;\s]+", str(text or "")) if p.strip()]
    if not parts:
        raise DatasetError("Enter how many pairs go in each part, e.g. 500, 500, rest")
    sizes = []
    for position, part in enumerate(parts):
        if part in ("rest", "*", "remaining"):
            if position != len(parts) - 1:
                raise DatasetError("\"rest\" can only be the last part.")
            sizes.append("rest")
            continue
        if not part.isdigit():
            raise DatasetError("\"%s\" is not a whole number (or \"rest\")." % part)
        if int(part) <= 0:
            raise DatasetError("Each part needs at least one pair.")
        sizes.append(int(part))
    return sizes


def plan_split(root, sizes, prefix=DEFAULT_PART) -> Plan:
    root = check_root(root)
    plan = Plan("split", root, options={"sizes": sizes, "prefix": prefix})
    problem = name_problem(prefix, "part name")
    if problem:
        plan.problems.append(problem)
        return plan
    if isinstance(sizes, str):
        try:
            sizes = parse_sizes(sizes)
        except DatasetError as exc:
            plan.problems.append(str(exc))
            return plan
    scan = scan_pairs(root)
    _pair_problems(plan, scan)
    total = len(scan.pairs)
    if not total:
        plan.problems.append("No image + .txt pairs were found in this folder.")
        return plan
    counts, remaining = [], total
    for position, size in enumerate(sizes, start=1):
        if remaining <= 0:
            plan.problems.append("Every pair is already placed before %s_%d." % (prefix, position))
            return plan
        count = remaining if size == "rest" else int(size)
        if count > remaining:
            plan.problems.append("Only %d pair(s) are left for %s_%d, not %d."
                                 % (remaining, prefix, position, count))
            return plan
        counts.append(count)
        remaining -= count
    if remaining:
        plan.notes.append("%d pair(s) are not in any part and stay where they are." % remaining)
    _files, folders = _entries(root)
    existing_folders = {name.casefold(): name for name in folders}
    files_casefold = {name.casefold() for name in _files}
    cursor = 0
    for part_number, count in enumerate(counts, start=1):
        folder_name = "%s_%d" % (prefix, part_number)
        folder = os.path.join(root, existing_folders.get(folder_name.casefold(), folder_name))
        if folder_name.casefold() in files_casefold:
            plan.problems.append("There is a file called \"%s\" where a part folder should go."
                                 % folder_name)
            return plan
        present = set()
        if os.path.isdir(folder):
            try:
                present = {name.casefold() for name in os.listdir(folder)}
            except OSError as exc:
                plan.problems.append("\"%s\" cannot be read: %s" % (folder_name, exc))
                return plan
        for pair in scan.pairs[cursor:cursor + count]:
            for name in (pair.image, pair.label):
                if name.casefold() in present:
                    plan.problems.append("\"%s\" already has a file called \"%s\"."
                                         % (folder_name, name))
                    return plan
            group = cursor
            plan.actions.append(Action("move", os.path.join(root, pair.image),
                                       os.path.join(folder, pair.image), group=group))
            plan.actions.append(Action("move", os.path.join(root, pair.label),
                                       os.path.join(folder, pair.label), group=group))
            cursor += 1
        plan.notes.append("%s_%d: %d pair(s)" % (prefix, part_number, count))
    return plan


def plan_rename_parts(root, base_name, prefix=DEFAULT_PART) -> Plan:
    root = check_root(root)
    base_name = "" if base_name is None else str(base_name)
    plan = Plan("rename_parts", root, options={"base_name": base_name, "prefix": prefix})
    for problem in (name_problem(prefix, "folder name to look for"), name_problem(base_name)):
        if problem:
            plan.problems.append(problem)
            return plan
    pattern = re.compile(r"^%s_(\d+)$" % re.escape(prefix), re.IGNORECASE)
    files, folders = _entries(root)
    found = []
    for name in folders:
        match = pattern.match(name)
        if match:
            found.append((int(match.group(1)), name))
    found.sort()
    if not found:
        plan.problems.append("No %s_<number> folders were found here." % prefix)
        return plan
    renaming = {name.casefold() for _n, name in found}
    taken = {name.casefold() for name in files + folders} - renaming
    for number, name in found:
        target = "%s_%d" % (base_name, number)
        if target.casefold() in taken:
            plan.problems.append("\"%s\" already exists - choose another name." % target)
            return plan
        if target == name:
            plan.notes.append("\"%s\" already has its new name." % name)
            continue
        plan.actions.append(Action("rename", os.path.join(root, name), os.path.join(root, target),
                                   group=number))
    return plan


def plan_zip_folders(root, output=ZIP_FOLDER) -> Plan:
    root = check_root(root)
    output = ZIP_FOLDER if not output else str(output)
    plan = Plan("zip_folders", root, options={"output": output})
    problem = name_problem(output, "output folder name")
    if problem:
        plan.problems.append(problem)
        return plan
    out_folder = os.path.join(root, output)
    if os.path.exists(out_folder) and not os.path.isdir(out_folder):
        plan.problems.append("There is a file called \"%s\" where the output folder should go."
                             % output)
        return plan
    _files, folders = _entries(root)
    for name in folders:
        if name.casefold() == output.casefold():
            continue
        source = os.path.join(root, name)
        target = os.path.join(out_folder, name + ".zip")
        if os.path.lexists(target):
            plan.notes.append("\"%s.zip\" already exists - \"%s\" is skipped." % (name, name))
            continue
        count = sum(len(files) for _d, _s, files in os.walk(source))
        if not count:
            plan.notes.append("\"%s\" is empty - skipped." % name)
            continue
        plan.actions.append(Action("zip", source, target))
    if not plan.actions and not plan.problems:
        plan.notes.insert(0, "There are no folders to zip here.")
    return plan


# ══════════════════════════════════════════════════════════════
# LABEL CONTENTS - checking, splitting into sets, classes
# ══════════════════════════════════════════════════════════════
NOT_LABEL_FILES = {"classes.txt", "obj.names", "names.txt", "labels.txt", "notes.txt",
                   "readme.txt", "license.txt"}
MAX_LABEL_BYTES = 20 * 1024 * 1024


def read_class_names(root):
    """(names, where they came from) - classes.txt or obj.names, else the
    names in data.yaml / dataset.yaml.  ([], "") when there are none."""
    for name in ("classes.txt", "obj.names"):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8-sig", errors="replace") as handle:
                    names = [line.strip() for line in handle if line.strip()]
            except OSError:
                names = []
            if names:
                return names, name
    for name in ("data.yaml", "dataset.yaml"):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        inline = re.search(r"^names\s*:\s*\[(.*?)\]", text, re.M | re.S)
        if inline:
            names = [part.strip().strip("'\"") for part in inline.group(1).split(",")]
            names = [n for n in names if n]
            if names:
                return names, name
        block = re.search(r"^names\s*:\s*\n((?:[ \t]+.*\n?)+)", text, re.M)
        if block:
            names = []
            for line in block.group(1).splitlines():
                item = re.match(r"^\s*(?:-\s*|\d+\s*:\s*)(.+?)\s*$", line)
                if item:
                    names.append(item.group(1).strip("'\""))
            if names:
                return names, name
    return [], ""


def _class_label(names, cls) -> str:
    return "class %d (%s)" % (cls, names[cls]) if 0 <= cls < len(names) else "class %d" % cls


def _label_files(root, include_subfolders=True):
    """Every .txt that could be a label file, and the folders that could not be read."""
    skip = {HOLDING_FOLDER, ZIP_FOLDER.casefold()}
    out, errors = [], []
    for folder, subfolders, files in os.walk(root, onerror=errors.append):
        subfolders[:] = sorted((d for d in subfolders if d.casefold() not in skip
                                and not d.casefold().startswith(TEMP_PREFIX)), key=natural_key)
        if not include_subfolders:
            subfolders[:] = []
        for name in sorted(files, key=natural_key):
            lowered = name.casefold()
            if not lowered.endswith(LABEL_EXT) or lowered in NOT_LABEL_FILES \
                    or lowered.startswith(TEMP_PREFIX):
                continue
            path = os.path.join(folder, name)
            if not os.path.islink(path):
                out.append(path)
    return out, errors


def _read_label_text(path):
    """(text, newline) - the newline the file already uses is kept on rewrite."""
    if os.path.getsize(path) > MAX_LABEL_BYTES:
        raise OSError("larger than 20 MB - not a label file")
    with open(path, "rb") as handle:
        raw = handle.read()
    return raw.decode("utf-8-sig", errors="replace"), ("\r\n" if b"\r\n" in raw else "\n")


def _file_stamp(path):
    try:
        info = os.stat(path)
        return (info.st_size, info.st_mtime_ns)
    except OSError:
        return ()


def _number(value) -> str:
    text = ("%.6f" % value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _clip(value) -> float:
    return min(1.0, max(0.0, value))


def plan_check_labels(root, classes=0, fix_coordinates=True, remove_unusable=True,
                      remove_duplicates=True, min_size=0.0, include_subfolders=True) -> Plan:
    root = check_root(root)
    plan = Plan("check_labels", root, options={
        "classes": classes, "fix_coordinates": bool(fix_coordinates),
        "remove_unusable": bool(remove_unusable), "remove_duplicates": bool(remove_duplicates),
        "min_size": min_size, "include_subfolders": bool(include_subfolders)})
    try:
        classes = int(classes or 0)
        min_size = float(min_size or 0.0)
    except (TypeError, ValueError):
        plan.problems.append("The number of classes and the smallest size must be numbers.")
        return plan
    if classes < 0 or not 0.0 <= min_size < 0.5:
        plan.problems.append("The number of classes cannot be negative, and the smallest size "
                             "must be between 0 and 0.5.")
        return plan
    names, source = read_class_names(root)
    if classes <= 0 and names:
        classes = len(names)
        plan.notes.append("Class ids are checked against the %d names in %s." % (classes, source))
    elif classes <= 0:
        plan.notes.append("There is no classes.txt or data.yaml here, so class ids are only "
                          "checked for being whole numbers - enter the number of classes to "
                          "check them fully.")
    files, errors = _label_files(root, include_subfolders)
    totals, reported, fine, not_labels, unreadable = {}, 0, 0, 0, []

    for path in files:
        try:
            text, newline = _read_label_text(path)
        except OSError:
            unreadable.append(_relative(path, root))
            continue
        kept, seen, found = [], set(), {}
        numeric, changed = 0, False

        def note(what, fixed):
            nonlocal reported
            key = ("%s - %s" % (fixed, what)) if fixed else what
            found[key] = found.get(key, 0) + 1
            totals[key] = totals.get(key, 0) + 1
            if not fixed:
                reported += 1

        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                values = [float(part) for part in line.split()]
            except ValueError:
                values = None
            if values is None or any(v != v or v in (float("inf"), float("-inf")) for v in values):
                note("not numbers", "removed" if remove_unusable else "")
                if remove_unusable:
                    changed = True
                else:
                    kept.append(line)
                continue
            numeric += 1
            cls_value, coords = values[0], values[1:]
            problem = ""
            if cls_value < 0 or cls_value != int(cls_value):
                problem = "class id is not a whole number"
            elif classes and int(cls_value) >= classes:
                problem = "class id is not one of the %d classes" % classes
            elif len(coords) != 4 and (len(coords) < 6 or len(coords) % 2):
                problem = "wrong number of values"
            if problem:
                note(problem, "removed" if remove_unusable else "")
                if remove_unusable:
                    changed = True
                else:
                    kept.append(line)
                continue
            cls, rewritten = int(cls_value), False
            if len(coords) == 4:
                cx, cy, w, h = coords
                x0, y0, x1, y1 = cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0
                outside = min(x0, y0) < -1e-9 or max(x1, y1) > 1 + 1e-9
                if outside and fix_coordinates and w > 0 and h > 0:
                    x0, x1, y0, y1 = _clip(x0), _clip(x1), _clip(y0), _clip(y1)
                    coords = [(x0 + x1) / 2.0, (y0 + y1) / 2.0, x1 - x0, y1 - y0]
                    rewritten = True
                    note("coordinates outside the image", "clipped")
                elif outside:
                    note("coordinates outside the image", "")
                width, height = coords[2], coords[3]
                too_small = width <= 0 or height <= 0 or (min_size and min(width, height) < min_size)
            else:
                outside = any(c < -1e-9 or c > 1 + 1e-9 for c in coords)
                if outside and fix_coordinates:
                    coords = [_clip(c) for c in coords]
                    rewritten = True
                    note("coordinates outside the image", "clipped")
                elif outside:
                    note("coordinates outside the image", "")
                xs, ys = coords[0::2], coords[1::2]
                area = abs(sum(xs[i] * ys[i - 1] - xs[i - 1] * ys[i] for i in range(len(xs)))) / 2.0
                too_small = area <= 0 or (min_size and min(max(xs) - min(xs), max(ys) - min(ys)) < min_size)
            if too_small:
                note("no size, or smaller than the minimum", "removed" if remove_unusable else "")
                if remove_unusable:
                    changed = True
                    continue
            identity = (cls, tuple(round(c, 6) for c in coords))
            if identity in seen:
                note("repeated box", "removed" if remove_duplicates else "")
                if remove_duplicates:
                    changed = True
                    continue
            seen.add(identity)
            if rewritten:
                changed = True
                kept.append(" ".join([str(cls)] + [_number(c) for c in coords]))
            else:
                kept.append(line)
        if not numeric and found and set(found) <= {"not numbers", "removed - not numbers"}:
            for key in found:
                totals[key] -= found[key]
                if not key.startswith("removed"):
                    reported -= found[key]
            not_labels += 1
            continue
        if changed:
            detail = ", ".join("%s (%d)" % (key, count) for key, count in found.items()
                               if key.startswith(("removed", "clipped")))
            plan.actions.append(Action("rewrite", path, detail=detail,
                                       content=newline.join(kept) + (newline if kept else ""),
                                       stamp=_file_stamp(path)))
        elif not found:
            fine += 1

    plan.notes.insert(0, "%d label file(s) read: %d fine, %d to change."
                      % (len(files) - len(unreadable) - not_labels, fine, len(plan.actions)))
    for key, count in sorted(totals.items(), key=lambda kv: -kv[1]):
        if count:
            plan.notes.append("%d × %s" % (count, key))
    if reported:
        plan.notes.append("%d problem(s) are only reported - turn on the matching fix to change "
                          "them." % reported)
    if not_labels:
        plan.notes.append("%d .txt file(s) hold no numbers at all and are not label files - "
                          "left alone." % not_labels)
    if unreadable:
        plan.notes.append("%d file(s) could not be read: %s" % (len(unreadable), ", ".join(unreadable[:5])))
    if errors:
        plan.notes.append("%d folder(s) could not be opened." % len(errors))
    return plan


def parse_class_mapping(text):
    """"3>1, 4>1, 7>delete" -> {3: 1, 4: 1, 7: None}.  Raises DatasetError."""
    mapping = {}
    for chunk in re.split(r"[,;\n]+", str(text or "")):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = re.match(r"^(\d+)\s*(?:->|>|→|=|\bto\b)\s*(\d+|delete|del|remove|x)$", chunk, re.I)
        if not match:
            raise DatasetError("\"%s\" is not understood - write each change like 3>1, or 7>delete "
                               "to remove a class's boxes." % chunk)
        old, new = int(match.group(1)), match.group(2).lower()
        value = int(new) if new.isdigit() else None
        if old in mapping and mapping[old] != value:
            raise DatasetError("Class %d is given two different changes." % old)
        mapping[old] = value
    return mapping


def plan_class_tools(root, mapping="", include_subfolders=True) -> Plan:
    root = check_root(root)
    plan = Plan("class_tools", root, options={"mapping": mapping,
                                               "include_subfolders": bool(include_subfolders)})
    try:
        changes = parse_class_mapping(mapping) if isinstance(mapping, str) else dict(mapping or {})
    except DatasetError as exc:
        plan.problems.append(str(exc))
        return plan
    names, source = read_class_names(root)
    files, errors = _label_files(root, include_subfolders)
    before, after = {}, {}                 # class -> [boxes, files]
    label_files = 0
    for path in files:
        try:
            text, newline = _read_label_text(path)
        except OSError:
            continue
        kept, numeric, changed = [], False, False
        renumbered = removed = 0
        seen_before, seen_after = set(), set()
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            try:
                cls_value = float(parts[0])
            except ValueError:
                kept.append(line)
                continue
            numeric = True
            if cls_value < 0 or cls_value != int(cls_value):
                kept.append(line)
                continue
            cls = int(cls_value)
            before.setdefault(cls, [0, 0])[0] += 1
            seen_before.add(cls)
            if cls in changes:
                new = changes[cls]
                if new is None:
                    removed += 1
                    changed = True
                    continue
                if new != cls:
                    parts[0] = str(new)
                    line = " ".join(parts)
                    renumbered += 1
                    changed = True
                cls = new
            after.setdefault(cls, [0, 0])[0] += 1
            seen_after.add(cls)
            kept.append(line)
        if not numeric:
            continue
        label_files += 1
        for cls in seen_before:
            before[cls][1] += 1
        for cls in seen_after:
            after[cls][1] += 1
        if changed:
            bits = []
            if renumbered:
                bits.append("%d box(es) renumbered" % renumbered)
            if removed:
                bits.append("%d box(es) removed" % removed)
            plan.actions.append(Action("rewrite", path, detail=", ".join(bits),
                                       content=newline.join(kept) + (newline if kept else ""),
                                       stamp=_file_stamp(path)))
    if not changes:
        plan.notes.append("Counting only - write changes like 3>1 or 7>delete to change classes.")
    plan.notes.append("%d label file(s)%s." % (label_files, " - names from %s" % source if source else ""))
    for cls in sorted(before):
        boxes, count = before[cls]
        line = "%s: %d box(es) in %d file(s)" % (_class_label(names, cls), boxes, count)
        if changes and cls in changes:
            line += "  →  %s" % ("deleted" if changes[cls] is None else _class_label(names, changes[cls]))
        plan.notes.append(line)
    if changes:
        missing = sorted(c for c in changes if c not in before)
        if missing:
            plan.notes.append("Not in these labels: %s." % ", ".join("class %d" % c for c in missing))
        merged = [cls for cls in sorted(after) if cls not in before or after[cls][0] != before[cls][0]]
        for cls in merged:
            plan.notes.append("After: %s has %d box(es) in %d file(s)"
                              % (_class_label(names, cls), after[cls][0], after[cls][1]))
        if names:
            plan.notes.append("%s is not changed - update the names if the numbering changed."
                              % source)
    if not files:
        plan.notes.insert(0, "There are no .txt label files here.")
    if errors:
        plan.notes.append("%d folder(s) could not be opened." % len(errors))
    return plan


def _yaml_text(value) -> str:
    return "'%s'" % str(value).replace("'", "''")


def plan_split_sets(root, train=70, val=20, test=10, seed=42, balanced=True,
                    include_background=True, move=False) -> Plan:
    import random
    root = check_root(root)
    plan = Plan("split_sets", root, options={"train": train, "val": val, "test": test, "seed": seed,
                                              "balanced": bool(balanced), "move": bool(move),
                                              "include_background": bool(include_background)})
    try:
        shares = [("train", int(train)), ("val", int(val)), ("test", int(test))]
        seed = int(seed)
    except (TypeError, ValueError):
        plan.problems.append("The shares and the seed must be whole numbers.")
        return plan
    total_share = sum(share for _name, share in shares)
    if any(share < 0 for _name, share in shares) or total_share != 100:
        plan.problems.append("Train, val and test must add up to 100 %% (they add up to %d %%)."
                             % total_share)
        return plan
    if shares[0][1] == 0:
        plan.problems.append("The train share cannot be 0 %.")
        return plan
    for folder_name in ("images", "labels"):
        path = os.path.join(root, folder_name)
        if os.path.exists(path) and not os.path.isdir(path):
            plan.problems.append("There is a file called \"%s\" where a folder should go." % folder_name)
            return plan
    names, source = read_class_names(root)
    scan = scan_pairs(root)
    classes_of, frequency, items = {}, {}, []
    for pair in scan.pairs:
        present = set()
        try:
            text, _newline = _read_label_text(os.path.join(root, pair.label))
            for line in text.splitlines():
                parts = line.split()
                if parts:
                    try:
                        value = float(parts[0])
                        if value >= 0 and value == int(value):
                            present.add(int(value))
                    except ValueError:
                        pass
        except OSError:
            pass
        classes_of[pair.image] = present
        for cls in present:
            frequency[cls] = frequency.get(cls, 0) + 1
        items.append((pair.image, pair.label))
    if include_background:
        for image in scan.unpaired:
            classes_of[image] = set()
            items.append((image, None))
    for clash in scan.clashes:
        plan.notes.append("These share one name and are left out: %s" % ", ".join(clash))
    if not items:
        plan.problems.append("No images were found directly in this folder.")
        return plan

    rng = random.Random(seed)
    groups = {}
    for image, label in items:
        present = classes_of[image]
        if balanced and present:
            key = "class %06d" % min(present, key=lambda c: (frequency[c], c))
        else:
            key = "background" if balanced else "all"
        groups.setdefault(key, []).append((image, label))
    chosen = {name: [] for name, _share in shares}
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda member: natural_key(member[0]))
        rng.shuffle(members)
        count = len(members)
        raw = [count * share / 100.0 for _name, share in shares]
        counts = [int(value) for value in raw]
        for index in sorted(range(3), key=lambda i: (-(raw[i] - counts[i]), i))[:count - sum(counts)]:
            counts[index] += 1
        for index in (1, 2):        # a rare class still reaches val and test when it can
            if shares[index][1] > 0 and counts[index] == 0 and counts[0] > 1 and count >= 3:
                counts[index] += 1
                counts[0] -= 1
        cursor = 0
        for (name, _share), amount in zip(shares, counts):
            chosen[name].extend(members[cursor:cursor + amount])
            cursor += amount

    kind = "move" if move else "copy"
    group = 0
    for name, _share in shares:
        for image, label in sorted(chosen[name], key=lambda member: natural_key(member[0])):
            pieces = [("images", image)] + ([("labels", label)] if label else [])
            for folder_name, file_name in pieces:
                target = os.path.join(root, folder_name, name, file_name)
                if os.path.lexists(target):
                    plan.problems.append("%s/%s/%s already exists - move the old split away first."
                                         % (folder_name, name, file_name))
                    return plan
                plan.actions.append(Action(kind, os.path.join(root, file_name), target, group=group))
            group += 1
        labelled = sum(1 for _image, label in chosen[name] if label)
        plan.notes.append("%s: %d image(s), %d with labels" % (name, len(chosen[name]), labelled))
    for cls in sorted(frequency):
        missing = [name for name, share in shares
                   if share > 0 and not any(cls in classes_of[image] for image, _l in chosen[name])]
        if missing:
            plan.notes.append("%s is in only %d image(s), so it is not in %s."
                              % (_class_label(names, cls), frequency[cls], " or ".join(missing)))
    yaml_path = os.path.join(root, "data.yaml")
    if os.path.lexists(yaml_path):
        plan.notes.append("data.yaml already exists and is left as it is.")
    else:
        count = len(names) if names else (max(frequency) + 1 if frequency else 0)
        listed = names if names else ["class_%d" % i for i in range(count)]
        lines = ["# written by Annotex Dataset Tools",
                 "path: %s" % _yaml_text(root.replace(os.sep, "/")),
                 "train: images/train",
                 "val: images/%s" % ("val" if shares[1][1] else "train")]
        if shares[2][1]:
            lines.append("test: images/test")
        lines += ["nc: %d" % count, "names: [%s]" % ", ".join(_yaml_text(n) for n in listed), ""]
        plan.actions.append(Action("write", "", yaml_path, content="\n".join(lines)))
        if not names:
            plan.notes.append("No classes.txt here, so data.yaml names the classes class_0, class_1, "
                              "… - edit it to give their real names.")
    plan.notes.insert(0, "Copies - the originals stay where they are." if not move else
                      "Moves the pairs out of the folder into images/ and labels/.")
    return plan


PLANNERS = {"empty_labels": plan_empty_labels, "unpaired": plan_unpaired,
            "rename_pairs": plan_rename_pairs, "split": plan_split,
            "rename_parts": plan_rename_parts, "zip_folders": plan_zip_folders,
            "check_labels": plan_check_labels, "split_sets": plan_split_sets,
            "class_tools": plan_class_tools}


# ══════════════════════════════════════════════════════════════
# HISTORY (what makes undo possible)
# ══════════════════════════════════════════════════════════════
def history_folder():
    return first_writable([user_data_dir() / "dataset_history"])


class History:
    """One run's record: a JSON line per change, written *before* the change,
    so even a crash leaves a record undo can work from."""

    def __init__(self, plan, folder=None):
        self.folder = str(folder or history_folder())
        os.makedirs(self.folder, exist_ok=True)
        # Down to the microsecond, so two runs in the same second still sort
        # in the order they happened - "undo the latest" must mean the latest.
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f-") + uuid.uuid4().hex[:4]
        self.root = plan.root
        self.path = os.path.join(self.folder, self.run_id + ".jsonl")
        self._handle = open(self.path, "a", encoding="utf-8")
        self.steps = 0
        self._write({"type": "run", "run": self.run_id, "operation": plan.operation,
                     "title": plan.title, "root": plan.root,
                     "time": datetime.now().isoformat(timespec="seconds"),
                     "options": _jsonable(plan.options)})

    def _write(self, record) -> None:
        self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._handle.flush()

    def step(self, kind, source, target, **extra) -> None:
        self.steps += 1
        record = {"type": "step", "kind": kind, "source": source, "target": target}
        record.update(extra)
        self._write(record)

    def finish(self, summary, changed) -> None:
        self._write({"type": "finish", "summary": summary, "changed": changed,
                     "time": datetime.now().isoformat(timespec="seconds")})
        self.close()

    def close(self) -> None:
        try:
            self._handle.close()
        except Exception:
            pass

    def holding_path(self, path) -> str:
        return os.path.join(self.root, HOLDING_FOLDER, self.run_id, _relative(path, self.root))


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _read(path):
    records = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue            # a line cut short by a crash
    except OSError:
        return []
    return records


def runs(folder=None, root=None):
    """[dict] newest first: run, operation, title, root, time, changed,
    summary, undone.  `root` narrows it to one dataset folder."""
    folder = str(folder or history_folder())
    out = []
    try:
        names = [n for n in os.listdir(folder) if n.endswith(".jsonl")]
    except OSError:
        return []
    for name in names:
        records = _read(os.path.join(folder, name))
        head = next((r for r in records if r.get("type") == "run"), None)
        if head is None:
            continue
        if root and os.path.normcase(os.path.abspath(head.get("root", ""))) != \
                os.path.normcase(os.path.abspath(str(root))):
            continue
        finish = next((r for r in records if r.get("type") == "finish"), {})
        steps = [r for r in records if r.get("type") == "step"]
        out.append({"run": head.get("run", name[:-6]), "operation": head.get("operation", ""),
                    "title": head.get("title", ""), "root": head.get("root", ""),
                    "time": head.get("time", ""), "changed": finish.get("changed", len(steps)),
                    "summary": finish.get("summary", "stopped before it finished"),
                    "undone": any(r.get("type") == "undone" for r in records),
                    "steps": len(steps)})
    return sorted(out, key=lambda r: r["run"], reverse=True)


def _move(source, target) -> None:
    folder = os.path.dirname(target)
    if folder:
        os.makedirs(folder, exist_ok=True)
    try:
        os.rename(source, target)
    except OSError:
        shutil.move(source, target)        # another drive


def undo(run_id, folder=None, ctx=None):
    """Put back everything a run changed that is still as the run left it.
    Returns (restored, skipped, messages)."""
    folder = str(folder or history_folder())
    path = os.path.join(folder, "%s.jsonl" % run_id)
    records = _read(path)
    head = next((r for r in records if r.get("type") == "run"), None)
    if head is None:
        raise DatasetError("That run's record could not be found.")
    if any(r.get("type") == "undone" for r in records):
        return 0, 0, ["This run was already undone."]
    steps = [r for r in records if r.get("type") == "step"]
    restored, skipped, messages = 0, 0, []
    made_folders = []
    total = len(steps) or 1
    for position, step in enumerate(reversed(steps)):
        if ctx is not None:
            ctx.progress(position / float(total), "Undoing %d of %d" % (position + 1, len(steps)))
        kind, source, target = step.get("kind"), step.get("source", ""), step.get("target", "")
        try:
            if kind == "mkdir":
                made_folders.append(source)
            elif kind == "create":
                if os.path.isfile(source) and os.path.getsize(source) == step.get("size", -1):
                    os.remove(source)
                    restored += 1
                elif os.path.exists(source):
                    skipped += 1
                    messages.append("%s was changed since, so it is kept." % source)
            elif kind == "rewrite":
                # target is the untouched original, kept aside when the file was rewritten
                if os.path.isfile(target):
                    os.replace(target, source)
                    restored += 1
                else:
                    skipped += 1
                    messages.append("The original of %s is no longer kept." % source)
            elif kind in ("move", "rename", "remove"):
                there, back = os.path.lexists(target), os.path.lexists(source)
                if there and not back:
                    _move(target, source)
                    restored += 1
                elif back and not there:
                    continue                    # never happened, or already back
                elif there and back:
                    skipped += 1
                    messages.append("%s is back already and %s exists too - both are kept."
                                    % (source, target))
                else:
                    skipped += 1
                    messages.append("%s is no longer there." % target)
        except OSError as exc:
            skipped += 1
            messages.append("%s could not be put back: %s" % (source or target, exc))
    for made in made_folders:
        _remove_empty_tree(made)
    root = head.get("root", "")
    if root:
        _remove_empty_tree(os.path.join(root, HOLDING_FOLDER, run_id))
        _remove_empty_tree(os.path.join(root, HOLDING_FOLDER), only_if_empty=True)
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "undone", "restored": restored, "skipped": skipped,
                                     "time": datetime.now().isoformat(timespec="seconds")}) + "\n")
    except OSError:
        messages.append("The history file could not be updated.")
    if ctx is not None:
        ctx.progress(1.0)
    return restored, skipped, messages


def _remove_empty_tree(folder, only_if_empty=False) -> None:
    if not folder or not os.path.isdir(folder):
        return
    if only_if_empty:
        try:
            if not os.listdir(folder):
                os.rmdir(folder)
        except OSError:
            pass
        return
    for current, _subfolders, _files in os.walk(folder, topdown=False):
        try:
            if not os.listdir(current):
                os.rmdir(current)
        except OSError:
            pass


def _hide_on_windows(path) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)   # FILE_ATTRIBUTE_HIDDEN
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
# APPLYING
# ══════════════════════════════════════════════════════════════
def _tick(ctx, done, total, message) -> None:
    if ctx is not None:
        ctx.progress(done / float(total or 1), message)


def _cancelled(ctx) -> bool:
    return ctx is not None and ctx.cancelled


def _warn(ctx, warnings, message) -> None:
    warnings.append(message)
    if ctx is not None:
        ctx.warn(message)


def _still_valid(action, ctx, warnings) -> bool:
    if not os.path.lexists(action.source):
        _warn(ctx, warnings, "%s is gone since the preview - skipped."
              % os.path.basename(action.source))
        return False
    if action.target and os.path.lexists(action.target) and \
            os.path.normcase(action.target) != os.path.normcase(action.source):
        _warn(ctx, warnings, "%s appeared since the preview - skipped."
              % os.path.basename(action.target))
        return False
    return True


def _made_folder(history, folder) -> None:
    """Create a folder and record every level of it that did not exist, so
    undo takes away images/ as well as images/train."""
    missing, current = [], folder
    while current and not os.path.isdir(current):
        missing.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    if missing:
        os.makedirs(folder, exist_ok=True)
        for path in reversed(missing):
            history.step("mkdir", path, "")


def _apply_remove(plan, history, ctx, warnings):
    done = 0
    holding_root = os.path.join(plan.root, HOLDING_FOLDER)
    for position, action in enumerate(plan.actions):
        if _cancelled(ctx):
            raise JobCancelled()
        _tick(ctx, position, len(plan.actions), "Removing %s" % os.path.basename(action.source))
        if not _still_valid(action, ctx, warnings):
            continue
        if is_blank_text(action.source) is not True:
            _warn(ctx, warnings, "%s has content now - kept." % os.path.basename(action.source))
            continue
        target = history.holding_path(action.source)
        history.step("remove", action.source, target)
        try:
            new_holding = not os.path.isdir(holding_root)
            _move(action.source, target)
            if new_holding:
                _hide_on_windows(holding_root)
            done += 1
        except OSError as exc:
            _warn(ctx, warnings, "%s could not be removed: %s" % (os.path.basename(action.source), exc))
    return done, "Removed %d empty .txt file(s)" % done


def _apply_moves(plan, history, ctx, warnings, verb):
    """Moves, a group at a time: if one file of a pair fails, the other is
    put back, so pairs never come apart."""
    groups = {}
    order = []
    for action in plan.actions:
        if action.group not in groups:
            order.append(action.group)
        groups.setdefault(action.group, []).append(action)
    done_files, done_groups = 0, 0
    for position, key in enumerate(order):
        if _cancelled(ctx):
            raise JobCancelled()
        actions = groups[key]
        _tick(ctx, position, len(order), "%s %s" % (verb, os.path.basename(actions[0].source)))
        if not all(_still_valid(a, ctx, warnings) for a in actions):
            continue
        moved = []
        try:
            for action in actions:
                _made_folder(history, os.path.dirname(action.target))
                history.step("move", action.source, action.target)
                _move(action.source, action.target)
                moved.append(action)
            done_files += len(moved)
            done_groups += 1
        except OSError as exc:
            for action in reversed(moved):
                try:
                    _move(action.target, action.source)
                    history.step("move", action.target, action.source)
                except OSError:
                    pass
            _warn(ctx, warnings, "%s could not be moved (%s) - it stays where it was."
                  % (os.path.basename(actions[0].source), exc))
    return done_files, done_groups


def _apply_unpaired(plan, history, ctx, warnings):
    files, _groups = _apply_moves(plan, history, ctx, warnings, "Moving")
    return files, "Moved %d unpaired image(s) into \"%s\"" % (files, UNPAIRED_FOLDER)


def _apply_split(plan, history, ctx, warnings):
    files, groups = _apply_moves(plan, history, ctx, warnings, "Moving")
    return files, "Moved %d pair(s) into parts" % groups


def _apply_renames(plan, history, ctx, warnings, noun):
    """Two phases: everything to a unique temporary name, then to its new
    name.  If phase one fails part-way, it is rolled back and nothing has
    changed; phase two cannot collide, because every final name is free."""
    actions = [a for a in plan.actions if _still_valid(a, ctx, warnings)]
    if len(actions) != len(plan.actions):
        raise DatasetError("The folder changed since the preview - preview again before renaming.")
    if _cancelled(ctx):
        raise JobCancelled()
    staged = []
    total = len(actions) * 2 or 1
    for position, action in enumerate(actions):
        folder = os.path.dirname(action.source)
        ext = os.path.splitext(action.source)[1] if action.kind == "rename" and \
            os.path.isfile(action.source) else ""
        temporary = os.path.join(folder, "%s%s_%d%s" % (TEMP_PREFIX, history.run_id, position, ext))
        _tick(ctx, position, total, "Preparing %s" % os.path.basename(action.source))
        try:
            history.step("rename", action.source, temporary)
            os.rename(action.source, temporary)
            staged.append((action, temporary))
        except OSError as exc:
            for done_action, done_temp in reversed(staged):
                try:
                    os.rename(done_temp, done_action.source)
                    history.step("rename", done_temp, done_action.source)
                except OSError:
                    pass
            raise DatasetError("%s could not be renamed (%s).  Nothing was changed - close any "
                               "program using the files and try again."
                               % (os.path.basename(action.source), exc))
    # Phase two, a group (an image and its label) at a time: if one of them
    # cannot take its new name, both go back to their old names, so a pair
    # never ends up with two different numbers.
    finished = 0
    groups, order = {}, []
    for action, temporary in staged:
        if action.group not in groups:
            order.append(action.group)
        groups.setdefault(action.group, []).append((action, temporary))
    step = len(staged)
    for key in order:
        members = groups[key]
        placed = []
        try:
            for action, temporary in members:
                step += 1
                _tick(ctx, step, total, "Renaming %s" % os.path.basename(action.target))
                history.step("rename", temporary, action.target)
                os.rename(temporary, action.target)
                placed.append(action)
            finished += len(members)
        except OSError as exc:
            # Back to the old name - unless another pair has taken it by now,
            # which renumbering does all the time.  os.rename would replace
            # that file without a word on Linux and macOS, so the file waits
            # under its unique temporary name instead, and undo still knows
            # where it is.
            temporaries = dict((id(a), t) for a, t in members)
            for action in reversed(placed):
                back = action.source if not os.path.lexists(action.source) \
                    else temporaries[id(action)]
                try:
                    history.step("rename", action.target, back)
                    os.rename(action.target, back)
                except OSError:
                    pass
            for action, temporary in members:
                if action in placed or not os.path.lexists(temporary) \
                        or os.path.lexists(action.source):
                    continue
                try:
                    history.step("rename", temporary, action.source)
                    os.rename(temporary, action.source)
                except OSError:
                    pass
            _warn(ctx, warnings, "%s kept its old name - it could not be renamed (%s)."
                  % (" + ".join(os.path.basename(a.source) for a, _t in members), exc))
    return finished, "Renamed %d %s" % (finished, noun)


def _apply_rename_pairs(plan, history, ctx, warnings):
    return _apply_renames(plan, history, ctx, warnings, "file(s)")


def _apply_rename_parts(plan, history, ctx, warnings):
    return _apply_renames(plan, history, ctx, warnings, "folder(s)")


def _apply_zip(plan, history, ctx, warnings):
    made = 0
    for position, action in enumerate(plan.actions):
        if _cancelled(ctx):
            raise JobCancelled()
        name = os.path.basename(action.source)
        if not os.path.isdir(action.source):
            _warn(ctx, warnings, "%s is gone since the preview - skipped." % name)
            continue
        if os.path.lexists(action.target):
            _warn(ctx, warnings, "%s.zip appeared since the preview - skipped." % name)
            continue
        _made_folder(history, os.path.dirname(action.target))
        part = os.path.join(os.path.dirname(action.target), "." + os.path.basename(action.target) + ".part")
        try:
            files = []
            for folder, subfolders, names in os.walk(action.source):
                subfolders.sort(key=natural_key)
                if not names and not subfolders and folder != action.source:
                    files.append((folder, True))
                for file_name in sorted(names, key=natural_key):
                    files.append((os.path.join(folder, file_name), False))
            with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, allowZip64=True,
                                 strict_timestamps=False) as archive:
                for index, (path, is_empty_folder) in enumerate(files):
                    if _cancelled(ctx):
                        raise JobCancelled()
                    if index % 25 == 0:
                        _tick(ctx, position + index / float(len(files) or 1), len(plan.actions),
                              "Zipping %s  ·  %d of %d files" % (name, index + 1, len(files)))
                    arcname = os.path.relpath(path, action.source).replace(os.sep, "/")
                    if is_empty_folder:
                        archive.writestr(arcname + "/", b"")
                    else:
                        archive.write(path, arcname)
            with zipfile.ZipFile(part) as check:
                if len(check.namelist()) != len(files):
                    raise OSError("the archive came out incomplete")
            os.replace(part, action.target)
            history.step("create", action.target, "", size=os.path.getsize(action.target))
            made += 1
        except JobCancelled:
            _discard(part)
            raise
        except (OSError, zipfile.BadZipFile, ValueError) as exc:
            _discard(part)
            _warn(ctx, warnings, "%s could not be zipped: %s" % (name, exc))
    return made, "Created %d zip file(s)" % made


def _discard(path) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _apply_rewrites(plan, history, ctx, warnings):
    """Rewrite label files: the original is copied aside first (that copy is
    what undo puts back), then the new text replaces it in one step."""
    done = 0
    holding_root = os.path.join(plan.root, HOLDING_FOLDER)
    for position, action in enumerate(plan.actions):
        if _cancelled(ctx):
            raise JobCancelled()
        name = os.path.basename(action.source)
        _tick(ctx, position, len(plan.actions), "Updating %s" % name)
        if action.stamp and _file_stamp(action.source) != action.stamp:
            _warn(ctx, warnings, "%s changed since the preview - skipped." % name)
            continue
        keep = history.holding_path(action.source)
        part = os.path.join(os.path.dirname(action.source), "%s%s.part" % (TEMP_PREFIX, name))
        try:
            new_holding = not os.path.isdir(holding_root)
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            if new_holding:
                _hide_on_windows(holding_root)
            shutil.copy2(action.source, keep)
            history.step("rewrite", action.source, keep)
            with open(part, "w", encoding="utf-8", newline="") as handle:
                handle.write(action.content)
            os.replace(part, action.source)
            done += 1
        except OSError as exc:
            _discard(part)
            _warn(ctx, warnings, "%s could not be updated: %s" % (name, exc))
    verb = "Fixed" if plan.operation == "check_labels" else "Changed"
    return done, "%s %d label file(s)" % (verb, done)


def _apply_copies(plan, history, ctx, warnings):
    """Copies, a group (an image and its label) at a time; if one fails, what
    the group already copied is removed again."""
    groups, order = {}, []
    for action in plan.actions:
        if action.group not in groups:
            order.append(action.group)
        groups.setdefault(action.group, []).append(action)
    files = done_groups = 0
    for position, key in enumerate(order):
        if _cancelled(ctx):
            raise JobCancelled()
        actions = groups[key]
        _tick(ctx, position, len(order), "Copying %s" % os.path.basename(actions[0].source))
        if not all(_still_valid(a, ctx, warnings) for a in actions):
            continue
        made, part = [], ""
        try:
            for action in actions:
                _made_folder(history, os.path.dirname(action.target))
                part = os.path.join(os.path.dirname(action.target),
                                    "%s%s.part" % (TEMP_PREFIX, os.path.basename(action.target)))
                shutil.copy2(action.source, part)
                os.replace(part, action.target)
                history.step("create", action.target, "", size=os.path.getsize(action.target))
                made.append(action)
            files += len(made)
            done_groups += 1
        except OSError as exc:
            _discard(part)
            for action in made:
                _discard(action.target)
            _warn(ctx, warnings, "%s could not be copied (%s) - left out."
                  % (os.path.basename(actions[0].source), exc))
    return files, done_groups


def _apply_split_sets(plan, history, ctx, warnings):
    moving = bool(plan.options.get("move"))
    transfers = Plan(plan.operation, plan.root,
                     [a for a in plan.actions if a.kind in ("copy", "move")], options=plan.options)
    if moving:
        files, groups = _apply_moves(transfers, history, ctx, warnings, "Moving")
    else:
        files, groups = _apply_copies(transfers, history, ctx, warnings)
    wrote = False
    for action in (a for a in plan.actions if a.kind == "write"):
        if os.path.lexists(action.target):
            _warn(ctx, warnings, "data.yaml appeared since the preview - left as it is.")
            continue
        part = os.path.join(os.path.dirname(action.target), TEMP_PREFIX + "data.yaml.part")
        try:
            with open(part, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(action.content)
            os.replace(part, action.target)
            history.step("create", action.target, "", size=os.path.getsize(action.target))
            wrote = True
        except OSError as exc:
            _discard(part)
            _warn(ctx, warnings, "data.yaml could not be written: %s" % exc)
    summary = "%s %d image(s) into train / val / test" % ("Moved" if moving else "Copied", groups)
    return files + (1 if wrote else 0), summary + (", wrote data.yaml" if wrote else "")


APPLIERS = {"empty_labels": _apply_remove, "unpaired": _apply_unpaired,
            "rename_pairs": _apply_rename_pairs, "split": _apply_split,
            "rename_parts": _apply_rename_parts, "zip_folders": _apply_zip,
            "check_labels": _apply_rewrites, "class_tools": _apply_rewrites,
            "split_sets": _apply_split_sets}


def apply(plan, ctx=None, history_dir=None):
    """Carry out a plan.  Returns a one-line summary; per-file problems go
    to ctx.warn.  Raises DatasetError when the plan cannot run at all."""
    if plan.problems:
        raise DatasetError(plan.problems[0])
    if not plan.actions:
        return "Nothing to do"
    try:
        check_root(plan.root)
    except DatasetError:
        raise
    if not os.access(plan.root, os.W_OK):
        raise DatasetError("Annotex cannot change files in this folder (permission denied).")
    handler = APPLIERS[plan.operation]
    history = History(plan, history_dir)
    warnings = []
    changed, summary = 0, "Stopped"
    try:
        changed, summary = handler(plan, history, ctx, warnings)
        if warnings:
            summary += ", %d skipped" % len(warnings)
        return summary
    except JobCancelled:
        summary = "Cancelled - what was already done can be undone"
        raise
    except DatasetError as exc:
        summary = str(exc)
        raise
    finally:
        history.finish(summary, changed if changed else history.steps)
        if not history.steps:
            try:
                os.remove(history.path)          # nothing happened; nothing to undo
            except OSError:
                pass
        if ctx is not None:
            ctx.progress(1.0)
