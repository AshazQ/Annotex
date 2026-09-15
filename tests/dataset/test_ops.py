"""Dataset Tools - the six operations, their undo, and everything that goes
wrong on real folders: files in use, names Windows refuses, folders that
change between the preview and the run, a run cut short.

    python tests/dataset/test_ops.py
"""

import os
import shutil
import stat
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="annotex_dataset_")
os.environ["HOME"] = os.path.join(SANDBOX, "home")
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "home", "config")
os.environ["APPDATA"] = os.path.join(SANDBOX, "home", "appdata")
os.makedirs(os.environ["HOME"], exist_ok=True)

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


class Ctx:
    def __init__(self, cancel_after=None):
        self.warnings = []
        self.calls = 0
        self.cancel_after = cancel_after

    @property
    def cancelled(self):
        return self.cancel_after is not None and self.calls >= self.cancel_after

    def progress(self, fraction, message=None):
        self.calls += 1

    def warn(self, message):
        self.warnings.append(message)


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(text.encode("utf-8") if isinstance(text, str) else text)


def tree(folder):
    """Every file under a folder with its bytes, skipping Annotex's hidden holding place."""
    out = {}
    for current, subfolders, files in os.walk(folder):
        subfolders[:] = [d for d in subfolders if d != ".annotex_removed"]
        for name in files:
            path = os.path.join(current, name)
            with open(path, "rb") as handle:
                out[os.path.relpath(path, folder)] = handle.read()
    return out


def dataset(name, pairs=6, unpaired=2, orphans=1):
    folder = os.path.join(SANDBOX, name)
    os.makedirs(folder)
    for i in range(1, pairs + 1):
        write(os.path.join(folder, "img%d.jpg" % i), b"JPEG%d" % i)
        write(os.path.join(folder, "img%d.txt" % i), "0 0.5 0.5 0.1 0.1  # %d\n" % i)
    for i in range(1, unpaired + 1):
        write(os.path.join(folder, "lonely%d.PNG" % i), b"PNG%d" % i)
    for i in range(1, orphans + 1):
        write(os.path.join(folder, "orphan%d.txt" % i), "1 0.1 0.1 0.2 0.2\n")
    return folder


def main():
    from annotex.apps.dataset import ops
    from annotex.core.jobs import JobCancelled
    history = os.path.join(SANDBOX, "history")

    # ── the basics every operation relies on ──────────────
    ok("natural order puts img2 before img10", sorted(["img10", "img2", "IMG1"], key=ops.natural_key)
       == ["IMG1", "img2", "img10"])
    for bad in ("", "  ", " lead", "trail ", "a/b", "a\\b", "what?", "star*", "pipe|",
                "CON", "com1", "lpt9.txt", "dot.", "x" * 121, ".annotex_tmp_x"):
        ok("a name Windows refuses is refused: %r" % bad, ops.name_problem(bad) != "")
    for good in ("batch", "AB_Project_150926_fc_data", "café-ß 2", "part", "con_2"):
        ok("an ordinary name is fine: %r" % good, ops.name_problem(good) == "")
    try:
        ops.check_root(os.path.join(SANDBOX, "nope"))
        ok("a folder that does not exist is refused", False)
    except ops.DatasetError:
        ok("a folder that does not exist is refused", True)
    write(os.path.join(SANDBOX, "afile.txt"), "x")
    for label, target in (("a file is not taken for a folder", os.path.join(SANDBOX, "afile.txt")),
                          ("the home folder is refused", os.path.expanduser("~")),
                          ("a whole drive is refused", os.path.abspath(os.sep))):
        try:
            ops.check_root(target)
            ok(label, False)
        except ops.DatasetError:
            ok(label, True)
    blank = os.path.join(SANDBOX, "blank")
    for name, content, expected in (("zero.txt", b"", True), ("spaces.txt", b"  \n\t\r\n", True),
                                    ("bom.txt", b"\xef\xbb\xbf\n", True),
                                    ("utf16.txt", "  \n".encode("utf-16"), True),
                                    ("one.txt", b"\n\n0\n", False), ("dot.txt", b".", False),
                                    ("late.txt", b" " * 200000 + b"x", False)):
        write(os.path.join(blank, name), content)
        ok("blank detection: %s" % name, ops.is_blank_text(os.path.join(blank, name)) is expected)
    ok("an unreadable file is neither blank nor not", ops.is_blank_text(os.path.join(blank, "none")) is None)
    try:
        ops.parse_sizes("10, rest, 5")
        ok("\"rest\" in the middle is refused", False)
    except ops.DatasetError:
        ok("\"rest\" in the middle is refused", True)
    ok("sizes parse", ops.parse_sizes(" 500;500 , REST") == [500, 500, "rest"])
    for bad in ("", "0", "-3", "ten", "1.5"):
        try:
            ops.parse_sizes(bad)
            ok("bad sizes refused: %r" % bad, False)
        except ops.DatasetError:
            ok("bad sizes refused: %r" % bad, True)

    # ── 1. empty .txt files ───────────────────────────────
    folder = dataset("empty")
    write(os.path.join(folder, "empty_a.txt"), "")
    write(os.path.join(folder, "empty_b.txt"), "   \n\n")
    write(os.path.join(folder, "sub", "deep", "empty_c.TXT"), "\r\n")
    write(os.path.join(folder, "sub", "kept.txt"), "0 1 1 1 1")
    write(os.path.join(folder, "sub", "photo.jpg"), b"")          # an empty image is not a label
    before = tree(folder)
    plan = ops.plan_empty_labels(folder)
    ok("empty labels are found, sub-folders included", len(plan.actions) == 3)
    ok("images are never in the plan", all(a.source.lower().endswith(".txt") for a in plan.actions))
    shallow = ops.plan_empty_labels(folder, include_subfolders=False)
    ok("sub-folders can be left out", len(shallow.actions) == 2)
    ok("previewing changes nothing", tree(folder) == before)
    ctx = Ctx()
    summary = ops.apply(plan, ctx, history_dir=history)
    after = tree(folder)
    ok("empty labels are removed", summary.startswith("Removed 3") and "empty_a.txt" not in after
       and os.path.join("sub", "deep", "empty_c.TXT") not in after)
    ok("everything else is untouched", all(after[k] == before[k] for k in after) and
       len(after) == len(before) - 3)
    ok("removed files are held, not deleted",
       os.path.isdir(os.path.join(folder, ".annotex_removed")))
    found = ops.runs(history, root=folder)
    ok("the run is in history", len(found) == 1 and found[0]["operation"] == "empty_labels"
       and not found[0]["undone"])
    restored, skipped, _messages = ops.undo(found[0]["run"], history)
    ok("undo puts every file back exactly", restored == 3 and skipped == 0 and tree(folder) == before)
    ok("and tidies the holding folder away", not os.path.exists(os.path.join(folder, ".annotex_removed")))
    ok("history knows it was undone", ops.runs(history, root=folder)[0]["undone"])
    ok("undoing twice does nothing", ops.undo(found[0]["run"], history)[:2] == (0, 0))

    # a file that gains content between preview and run is kept
    plan = ops.plan_empty_labels(folder)
    write(os.path.join(folder, "empty_a.txt"), "0 0 0 1 1")
    ctx = Ctx()
    ops.apply(plan, ctx, history_dir=history)
    ok("a label written to after the preview is kept", os.path.isfile(os.path.join(folder, "empty_a.txt"))
       and any("content now" in w for w in ctx.warnings))

    # ── 2. unpaired images ────────────────────────────────
    folder = dataset("unpaired", pairs=4, unpaired=3, orphans=2)
    write(os.path.join(folder, "Mixed.JPG"), b"J")
    write(os.path.join(folder, "mixed.txt"), "0")                 # a pair, whatever the case
    write(os.path.join(folder, "twin.jpg"), b"1")
    write(os.path.join(folder, "twin.png"), b"2")
    write(os.path.join(folder, "twin.txt"), "0")                  # two images, one label
    write(os.path.join(folder, "sub", "deep.jpg"), b"x")          # sub-folders are not looked at
    before = tree(folder)
    plan = ops.plan_unpaired(folder)
    moved = sorted(os.path.basename(a.source) for a in plan.actions)
    ok("only images without a label move", moved == ["lonely1.PNG", "lonely2.PNG", "lonely3.PNG"])
    ok("names are paired without regard to case", "Mixed.JPG" not in moved)
    ok("a name two images share is left alone and said so",
       "twin.jpg" not in moved and any("twin" in n for n in plan.notes))
    ok("orphan labels are mentioned, not moved", any("have no image" in n for n in plan.notes))
    ops.apply(plan, Ctx(), history_dir=history)
    ok("they land in \"unpaired images\"",
       sorted(os.listdir(os.path.join(folder, "unpaired images"))) == moved)
    run = ops.runs(history, root=folder)[0]
    ops.undo(run["run"], history)
    ok("undo moves them back and removes the folder it made",
       tree(folder) == before and not os.path.exists(os.path.join(folder, "unpaired images")))
    write(os.path.join(folder, "unpaired images", "lonely1.PNG"), b"other")
    plan = ops.plan_unpaired(folder)
    ok("an image already in the target is not overwritten",
       all(os.path.basename(a.source) != "lonely1.PNG" for a in plan.actions)
       and any("already in" in n for n in plan.notes))
    shutil.rmtree(os.path.join(folder, "unpaired images"))
    write(os.path.join(folder, "unpaired images"), b"a file in the way")
    ok("a file where the folder should be stops it", ops.plan_unpaired(folder).problems)

    # ── 3. rename pairs ───────────────────────────────────
    folder = dataset("rename", pairs=12, unpaired=1, orphans=1)
    before = tree(folder)
    ok("a refused name stops the plan", ops.plan_rename_pairs(folder, "CON").problems)
    ok("no pairs stops the plan", ops.plan_rename_pairs(os.path.join(SANDBOX, "blank"), "x").problems)
    write(os.path.join(folder, "proj_001.jpg"), b"someone else's")
    ok("a name that would replace another file stops the plan",
       any("already exists" in p for p in ops.plan_rename_pairs(folder, "proj").problems))
    os.remove(os.path.join(folder, "proj_001.jpg"))
    before = tree(folder)
    plan = ops.plan_rename_pairs(folder, "proj", start=1)
    ok("every pair gets a numbered name", len(plan.actions) == 24)
    ops.apply(plan, Ctx(), history_dir=history)
    after = tree(folder)
    ok("pairs are renamed in natural order",
       after["proj_001.jpg"] == before["img1.jpg"] and after["proj_010.jpg"] == before["img10.jpg"]
       and after["proj_012.txt"] == before["img12.txt"])
    ok("each image keeps its own label", all(after["proj_%03d.txt" % i] == before["img%d.txt" % i]
                                             for i in range(1, 13)))
    ok("unpaired files and orphans keep their names",
       "lonely1.PNG" in after and "orphan1.txt" in after)
    ok("no temporary names are left", not any(n.startswith(".annotex_tmp_") for n in os.listdir(folder)))
    ops.undo(ops.runs(history, root=folder)[0]["run"], history)
    ok("undo restores the original names", tree(folder) == before)
    plan = ops.plan_rename_pairs(folder, "big", start=998)
    ok("numbers widen when they need to", any(a.target.endswith("big_1009.jpg") for a in plan.actions))

    # a failure in the first phase changes nothing at all
    real_rename = os.rename
    calls = {"n": 0}

    def fail_third(src, dst):
        calls["n"] += 1
        if calls["n"] == 3:
            raise PermissionError("the file is open in another program")
        return real_rename(src, dst)

    plan = ops.plan_rename_pairs(folder, "locked")
    ops.os.rename = fail_third
    try:
        ops.apply(plan, Ctx(), history_dir=history)
        ok("a locked file stops the rename", False)
    except ops.DatasetError as exc:
        ok("a locked file stops the rename, with a sentence", "Nothing was changed" in str(exc))
    finally:
        ops.os.rename = real_rename
    ok("and every name is as it was", tree(folder) == before
       and not any(n.startswith(".annotex_tmp_") for n in os.listdir(folder)))

    # a failure in the second phase keeps that pair whole
    plan = ops.plan_rename_pairs(folder, "half")

    def fail_one_label(src, dst):
        if os.path.basename(src).startswith(".annotex_tmp_") and dst.endswith("half_003.txt"):
            raise PermissionError("in use")
        return real_rename(src, dst)

    ops.os.rename = fail_one_label
    ctx = Ctx()
    try:
        ops.apply(plan, ctx, history_dir=history)
    finally:
        ops.os.rename = real_rename
    after = tree(folder)
    ok("the pair that failed keeps both old names",
       "img3.jpg" in after and "img3.txt" in after and "half_003.jpg" not in after)
    ok("the other pairs are renamed", "half_001.jpg" in after and "half_012.txt" in after)
    ok("and it is reported", any("kept its old name" in w for w in ctx.warnings))
    restored, skipped, messages = ops.undo(ops.runs(history, root=folder)[0]["run"], history)
    ok("undo after a partial run restores everything", tree(folder) == before and skipped == 0)

    # the folder changed between preview and run
    plan = ops.plan_rename_pairs(folder, "stale")
    os.remove(os.path.join(folder, "img5.txt"))
    try:
        ops.apply(plan, Ctx(), history_dir=history)
        ok("a rename refuses a folder that changed since the preview", False)
    except ops.DatasetError as exc:
        ok("a rename refuses a folder that changed since the preview", "preview again" in str(exc))
    ok("and changes nothing", "img4.jpg" in os.listdir(folder))

    # ── 4. split into parts ───────────────────────────────
    folder = dataset("split", pairs=10, unpaired=1)
    before = tree(folder)
    ok("sizes larger than what is there stop the plan",
       any("Only" in p for p in ops.plan_split(folder, "8, 5").problems))
    plan = ops.plan_split(folder, "4, 3")
    ok("leftover pairs stay and are mentioned", any("stay where they are" in n for n in plan.notes))
    plan = ops.plan_split(folder, "4, 3, rest")
    ok("a split moves both files of every pair", len(plan.actions) == 20)
    ops.apply(plan, Ctx(), history_dir=history)
    parts = {name: sorted(os.listdir(os.path.join(folder, name)))
             for name in ("part_1", "part_2", "part_3")}
    ok("each part gets its count", [len(parts["part_%d" % i]) // 2 for i in (1, 2, 3)] == [4, 3, 3])
    ok("pairs stay together", all(sorted(os.path.splitext(n)[0] for n in files)[::2] ==
                                  sorted(os.path.splitext(n)[0] for n in files)[1::2]
                                  for files in parts.values()))
    ok("unpaired images do not move", "lonely1.PNG" in os.listdir(folder))
    ops.undo(ops.runs(history, root=folder)[0]["run"], history)
    ok("undo empties and removes the parts", tree(folder) == before
       and not os.path.exists(os.path.join(folder, "part_1")))
    write(os.path.join(folder, "part_1", "img1.txt"), "already")
    ok("a part that already holds a file of that name stops the plan",
       ops.plan_split(folder, "2, rest").problems)
    shutil.rmtree(os.path.join(folder, "part_1"))
    before = tree(folder)

    # one file of a pair cannot move: the other comes back
    plan = ops.plan_split(folder, "rest")
    real_move = ops._move

    def refuse_img2_label(src, dst):
        if os.path.basename(src) == "img2.txt":
            raise PermissionError("in use")
        return real_move(src, dst)

    ops._move = refuse_img2_label
    ctx = Ctx()
    try:
        ops.apply(plan, ctx, history_dir=history)
    finally:
        ops._move = real_move
    ok("an image whose label cannot move is put back beside it",
       os.path.isfile(os.path.join(folder, "img2.jpg")) and os.path.isfile(os.path.join(folder, "img2.txt"))
       and not os.path.exists(os.path.join(folder, "part_1", "img2.jpg")))
    ok("and the rest of the pairs moved", os.path.isfile(os.path.join(folder, "part_1", "img3.jpg")))
    ops.undo(ops.runs(history, root=folder)[0]["run"], history)
    ok("undo restores that run too", tree(folder) == before)

    # cancelled part-way: whole pairs only, and it can be undone
    plan = ops.plan_split(folder, "rest")
    try:
        ops.apply(plan, Ctx(cancel_after=4), history_dir=history)
        ok("a split can be cancelled", False)
    except JobCancelled:
        ok("a split can be cancelled", True)
    moved_names = os.listdir(os.path.join(folder, "part_1"))
    ok("a cancelled split never separates a pair", len(moved_names) % 2 == 0 and moved_names)
    ok("the cancelled run is in history", ops.runs(history, root=folder)[0]["summary"].startswith("Cancelled"))
    ops.undo(ops.runs(history, root=folder)[0]["run"], history)
    ok("and undo puts it all back", tree(folder) == before)

    # ── 5. rename part folders ────────────────────────────
    folder = os.path.join(SANDBOX, "parts")
    for number in (1, 2, 10):
        write(os.path.join(folder, "part_%d" % number, "a%d.jpg" % number), b"x%d" % number)
    write(os.path.join(folder, "PART_3", "b.jpg"), b"y")
    write(os.path.join(folder, "partial", "c.jpg"), b"z")
    before = tree(folder)
    plan = ops.plan_rename_parts(folder, "batch")
    ok("part_<number> folders are found, whatever the case",
       sorted(os.path.basename(a.target) for a in plan.actions) == ["batch_1", "batch_10", "batch_2", "batch_3"])
    ok("other folders are ignored", all("partial" not in a.source for a in plan.actions))
    os.makedirs(os.path.join(folder, "batch_2"))
    ok("a name that is taken stops the plan", ops.plan_rename_parts(folder, "batch").problems)
    os.rmdir(os.path.join(folder, "batch_2"))
    ops.apply(ops.plan_rename_parts(folder, "batch"), Ctx(), history_dir=history)
    ok("folders are renamed with their numbers kept", sorted(os.listdir(folder)) ==
       ["batch_1", "batch_10", "batch_2", "batch_3", "partial"])
    ok("contents are untouched", tree(folder) == {k.replace("part_", "batch_").replace("PART_", "batch_"): v
                                                 for k, v in before.items()})
    ops.undo(ops.runs(history, root=folder)[0]["run"], history)
    ok("undo restores the folder names", tree(folder) == before)
    ok("no parts found stops the plan", ops.plan_rename_parts(os.path.join(SANDBOX, "blank"), "x").problems)

    # ── 6. zip each folder ────────────────────────────────
    folder = os.path.join(SANDBOX, "zips")
    write(os.path.join(folder, "part_1", "a.jpg"), b"A" * 5000)
    write(os.path.join(folder, "part_1", "a.txt"), "0 1 1 1 1")
    write(os.path.join(folder, "part_1", "nested", "b.jpg"), b"B")
    os.makedirs(os.path.join(folder, "part_1", "empty_inside"))
    write(os.path.join(folder, "part_2", "c é.jpg"), b"C")
    os.makedirs(os.path.join(folder, "nothing_here"))
    write(os.path.join(folder, "loose.jpg"), b"L")
    before = tree(folder)
    plan = ops.plan_zip_folders(folder)
    ok("each folder with files is planned", sorted(os.path.basename(a.source) for a in plan.actions)
       == ["part_1", "part_2"])
    ok("an empty folder is skipped and said so", any("empty" in n for n in plan.notes))
    ops.apply(plan, Ctx(), history_dir=history)
    with zipfile.ZipFile(os.path.join(folder, "zipped", "part_1.zip")) as archive:
        names = sorted(archive.namelist())
        content = archive.read("a.jpg")
    ok("a zip holds the folder's contents, not the folder", names ==
       ["a.jpg", "a.txt", "empty_inside/", "nested/b.jpg"])
    ok("the content is intact", content == b"A" * 5000)
    with zipfile.ZipFile(os.path.join(folder, "zipped", "part_2.zip")) as archive:
        ok("non-English names survive", archive.namelist() == ["c é.jpg"])
    ok("the folders themselves are untouched", all(tree(folder)[k] == v for k, v in before.items()))
    ok("no .part files are left", not any(n.endswith(".part") for n in os.listdir(os.path.join(folder, "zipped"))))
    again = ops.plan_zip_folders(folder)
    ok("an existing zip is never overwritten", not again.actions and any("already exists" in n for n in again.notes))
    run = ops.runs(history, root=folder)[0]
    with open(os.path.join(folder, "zipped", "part_2.zip"), "ab") as handle:
        handle.write(b"changed")
    restored, skipped, messages = ops.undo(run["run"], history)
    ok("undo removes the zips it made", not os.path.exists(os.path.join(folder, "zipped", "part_1.zip")))
    ok("but keeps one that was changed since", os.path.exists(os.path.join(folder, "zipped", "part_2.zip"))
       and skipped == 1)
    shutil.rmtree(os.path.join(folder, "zipped"))
    for i in range(120):
        write(os.path.join(folder, "part_3", "f%03d.jpg" % i), b"x" * 100)
    plan = ops.plan_zip_folders(folder)
    try:
        ops.apply(plan, Ctx(cancel_after=3), history_dir=history)
        ok("zipping can be cancelled", False)
    except JobCancelled:
        ok("zipping can be cancelled", True)
    left = os.listdir(os.path.join(folder, "zipped")) if os.path.isdir(os.path.join(folder, "zipped")) else []
    ok("a cancelled zip leaves no half-written file", not any(n.endswith(".part") for n in left)
       and "part_3.zip" not in left)

    # ── 7. check & fix labels ─────────────────────────────
    folder = os.path.join(SANDBOX, "check")
    write(os.path.join(folder, "classes.txt"), "person\ncar\ntruck\n")
    write(os.path.join(folder, "good.txt"), "0 0.5 0.5 0.2 0.2\n1 0.3 0.3 0.1 0.1\n")
    write(os.path.join(folder, "bad.txt"),
          "0 0.5 0.5 0.2 0.2\n0 0.5 0.5 0.2 0.2\n7 0.5 0.5 0.1 0.1\n1.5 0.2 0.2 0.1 0.1\n"
          "foo bar\n2 0.95 0.5 0.2 0.2\n1 0.5 0.5 0 0.1\n2 0.1 0.1\n")
    write(os.path.join(folder, "poly.txt"), "1 0.1 0.1 0.9 0.1 0.9 0.9 1.2 0.9\n")
    write(os.path.join(folder, "crlf.txt"), b"0 0.5 0.5 0.2 0.2\r\n0 0.5 0.5 0.2 0.2\r\n")
    write(os.path.join(folder, "names_list.txt"), "person\ncar\n")
    write(os.path.join(folder, "readme.txt"), "not labels at all")
    before = tree(folder)
    plan = ops.plan_check_labels(folder)
    ok("check: the classes come from classes.txt", any("classes.txt" in n for n in plan.notes))
    planned = sorted(os.path.basename(a.source) for a in plan.actions)
    ok("check: only files with problems are changed", planned == ["bad.txt", "crlf.txt", "poly.txt"])
    ok("check: a .txt of names is not taken for labels", "names_list.txt" not in planned
       and any("not label files" in n for n in plan.notes))
    ok("check: the preview says what changes in each file",
       any("repeated box" in r[2] and "clipped" in r[2] for r in plan.rows()))
    ops.apply(plan, Ctx(), history_dir=history)
    with open(os.path.join(folder, "bad.txt")) as handle:
        fixed = handle.read().splitlines()
    ok("check: bad lines go, a box past the edge is clipped, the good line stays",
       fixed == ["0 0.5 0.5 0.2 0.2", "2 0.925 0.5 0.15 0.2"])
    with open(os.path.join(folder, "poly.txt")) as handle:
        ok("check: polygon points past the edge are clipped",
           handle.read().strip() == "1 0.1 0.1 0.9 0.1 0.9 0.9 1 0.9")
    with open(os.path.join(folder, "crlf.txt"), "rb") as handle:
        ok("check: Windows line endings are kept", handle.read() == b"0 0.5 0.5 0.2 0.2\r\n")
    ok("check: a file that is fine is not touched", tree(folder)["good.txt"] == before["good.txt"])
    ops.undo(ops.runs(history, root=folder)[0]["run"], history)
    ok("check: undo puts every original back", tree(folder) == before)
    report = ops.plan_check_labels(folder, fix_coordinates=False, remove_unusable=False,
                                   remove_duplicates=False)
    ok("check: with every fix off it only reports", not report.actions
       and any("only reported" in n for n in report.notes))
    wide = ops.plan_check_labels(folder, classes=10)
    ok("check: a number of classes can be given instead",
       not any("not one of" in r[2] for r in wide.rows()))
    tiny = ops.plan_check_labels(folder, min_size=0.15)
    ok("check: boxes under the smallest size are found", "good.txt" in
       [os.path.basename(a.source) for a in tiny.actions])
    plan = ops.plan_check_labels(folder)
    write(os.path.join(folder, "bad.txt"), "0 0.5 0.5 0.2 0.2\n")
    ctx = Ctx()
    ops.apply(plan, ctx, history_dir=history)
    ok("check: a label edited after the preview is left alone",
       any("changed since the preview" in w for w in ctx.warnings)
       and tree(folder)["bad.txt"] == b"0 0.5 0.5 0.2 0.2\n")
    ok("check: a bad setting is refused", ops.plan_check_labels(folder, classes=-1).problems)

    # ── 8. class tools ────────────────────────────────────
    folder = os.path.join(SANDBOX, "classtools")
    write(os.path.join(folder, "a.txt"), "0 0.1 0.1 0.1 0.1\n1 0.2 0.2 0.1 0.1\n2 0.3 0.3 0.1 0.1\n")
    write(os.path.join(folder, "b.txt"), "2 0.4 0.4 0.1 0.1\n2 0.5 0.5 0.1 0.1\n")
    write(os.path.join(folder, "sub", "c.txt"), "1 0.6 0.6 0.1 0.1\n")
    before = tree(folder)
    counted = ops.plan_class_tools(folder, "")
    ok("classes: an empty change just counts", not counted.actions
       and "class 2: 3 box(es) in 2 file(s)" in counted.notes)
    for bad in ("3>>1", "x>1", "3>1, 3>2", "3 > cat"):
        ok("classes: a change it cannot read is refused: %r" % bad,
           ops.plan_class_tools(folder, bad).problems)
    ok("classes: mapping parses", ops.parse_class_mapping("3>1; 4 -> 1\n7>delete, 8 to 2")
       == {3: 1, 4: 1, 7: None, 8: 2})
    plan = ops.plan_class_tools(folder, "2>1, 0>delete")
    ok("classes: only files with those classes change", sorted(os.path.basename(a.source)
                                                               for a in plan.actions) == ["a.txt", "b.txt"])
    ops.apply(plan, Ctx(), history_dir=history)
    after = tree(folder)
    ok("classes: renumbered and deleted everywhere",
       after["a.txt"] == b"1 0.2 0.2 0.1 0.1\n1 0.3 0.3 0.1 0.1\n"
       and after["b.txt"] == b"1 0.4 0.4 0.1 0.1\n1 0.5 0.5 0.1 0.1\n")
    ops.undo(ops.runs(history, root=folder)[0]["run"], history)
    ok("classes: undo restores every file", tree(folder) == before)
    ops.apply(ops.plan_class_tools(folder, "0>1, 1>0"), Ctx(), history_dir=history)
    ok("classes: two classes can be swapped", tree(folder)["a.txt"] ==
       b"1 0.1 0.1 0.1 0.1\n0 0.2 0.2 0.1 0.1\n2 0.3 0.3 0.1 0.1\n")

    # ── 9. train / val / test split ───────────────────────
    folder = dataset("sets", pairs=20, unpaired=2, orphans=0)
    for i in range(1, 5):
        write(os.path.join(folder, "img%d.txt" % i), "1 0.5 0.5 0.1 0.1\n")
    write(os.path.join(folder, "classes.txt"), "cat\ndog\n")
    before = tree(folder)
    ok("sets: shares must add up to 100", ops.plan_split_sets(folder, 70, 20, 20).problems)
    ok("sets: train cannot be empty", ops.plan_split_sets(folder, 0, 50, 50).problems)
    plan = ops.plan_split_sets(folder, 70, 20, 10, seed=7)
    copies = [a for a in plan.actions if a.kind == "copy"]
    ok("sets: every pair and background image is placed", len(copies) == 20 * 2 + 2)
    again = ops.plan_split_sets(folder, 70, 20, 10, seed=7)
    other = ops.plan_split_sets(folder, 70, 20, 10, seed=8)
    ok("sets: the same seed gives the same split",
       [a.target for a in again.actions] == [a.target for a in plan.actions])
    ok("sets: another seed gives another", [a.target for a in other.actions] != [a.target for a in plan.actions])

    def set_of(p, name):
        return {os.path.basename(a.target) for a in p.actions
                if a.kind == "copy" and os.sep + "images" + os.sep + name + os.sep in a.target}

    rare = {"img%d.jpg" % i for i in range(1, 5)}
    ok("sets: a rare class still reaches train, val and test",
       all(set_of(plan, name) & rare for name in ("train", "val", "test")))
    ops.apply(plan, Ctx(), history_dir=history)
    ok("sets: YOLO's layout is made", all(os.path.isdir(os.path.join(folder, top, name))
                                         for top in ("images", "labels") for name in ("train", "val", "test")))
    ok("sets: copies leave the originals", os.path.isfile(os.path.join(folder, "img1.jpg")))
    with open(os.path.join(folder, "data.yaml"), encoding="utf-8") as handle:
        yaml_text = handle.read()
    ok("sets: data.yaml names the classes", "names: ['cat', 'dog']" in yaml_text and "nc: 2" in yaml_text
       and "test: images/test" in yaml_text)
    ok("sets: a label goes with its image",
       all(os.path.isfile(os.path.join(folder, "labels", name, os.path.splitext(image)[0] + ".txt"))
           for name in ("train", "val", "test")
           for image in os.listdir(os.path.join(folder, "images", name)) if not image.startswith("lonely")))
    ok("sets: running it twice is refused rather than overwriting",
       ops.plan_split_sets(folder, 70, 20, 10, seed=7).problems)
    ops.undo(ops.runs(history, root=folder)[0]["run"], history)
    ok("sets: undo removes the split and data.yaml", tree(folder) == before
       and not os.path.exists(os.path.join(folder, "images")))
    ops.apply(ops.plan_split_sets(folder, 80, 20, 0, seed=1, move=True), Ctx(), history_dir=history)
    ok("sets: moving takes the files out of the folder", not os.path.exists(os.path.join(folder, "img1.jpg"))
       and not os.path.isdir(os.path.join(folder, "images", "test")))
    ops.undo(ops.runs(history, root=folder)[0]["run"], history)
    ok("sets: and undo moves them back", tree(folder) == before)

    # ── history files are sturdy ──────────────────────────
    record = os.path.join(history, ops.runs(history)[0]["run"] + ".jsonl")
    with open(record, "a", encoding="utf-8") as handle:
        handle.write('{"type": "step", "kind": "mo')                 # a crash mid-line
    ok("a history file cut short still reads", bool(ops.runs(history)))
    ok("runs for every folder can be listed", len(ops.runs(history)) >= 8)
    try:
        ops.undo("20000101-000000-abcdef", history)
        ok("an unknown run is refused", False)
    except ops.DatasetError:
        ok("an unknown run is refused", True)
    plan = ops.plan_unpaired(dataset("nothing", pairs=2, unpaired=0))
    ok("a plan with nothing to do does not run", ops.apply(plan, Ctx(), history_dir=history) == "Nothing to do")

    # ── a folder that cannot be written to ────────────────
    if hasattr(os, "geteuid") and os.geteuid() != 0 and not sys.platform.startswith("win"):
        folder = dataset("readonly", pairs=2, unpaired=1)
        plan = ops.plan_unpaired(folder)
        os.chmod(folder, stat.S_IRUSR | stat.S_IXUSR)
        try:
            ops.apply(plan, Ctx(), history_dir=history)
            ok("a read-only folder is refused with a sentence", False)
        except ops.DatasetError as exc:
            ok("a read-only folder is refused with a sentence", "permission" in str(exc))
        finally:
            os.chmod(folder, stat.S_IRWXU)
    else:
        print("  ..  read-only folder check skipped on this system")

    print("=" * 60)
    if FAILS:
        print("DATASET TESTS FAILED: %s" % ", ".join(FAILS))
        return 1
    print("DATASET TESTS PASSED")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    sys.exit(code)
