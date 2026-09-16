"""Sorting by example, from the reference folder to the copies on disk.

The core first, with no window: how a reference folder is read, the three
rules that turn a score into a folder, the settings the examples suggest,
that a second comparison is served from the cache, and that any ONNX image
model works - a tiny one is built here, because the real ones are hundreds
of megabytes.  Then the Image Sorter's tab itself, end to end: compare as a
job, drag the sliders without touching a model, sort, and undo.

    python tests/media/test_reference.py

numpy is required (it is an optional install), so without it this skips.
"""

import os
import random
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SANDBOX = tempfile.mkdtemp(prefix="annotex_reference_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


def picture(path, colour, stripes=False, jitter=0, size=(96, 72)):
    from PIL import Image
    rng = random.Random(path)
    width, height = size
    data = []
    for y in range(height):
        for x in range(width):
            base = (255, 255, 255) if stripes and (x // 8) % 2 else colour
            data.append(tuple(max(0, min(255, v + rng.randint(-jitter, jitter)))
                              for v in base))
    image = Image.new("RGB", size)
    image.putdata(data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path)
    return path


KINDS = (("red", (200, 30, 30), False), ("blue", (30, 30, 200), False),
         ("stripes", (0, 0, 0), True))


def build_world():
    """References, and a folder to sort whose right answers are known."""
    refs = os.path.join(SANDBOX, "examples")
    for name, colour, stripes in KINDS:
        for index in range(2):
            picture(os.path.join(refs, name, "%s_%d.png" % (name, index)), colour, stripes, 10)
    source = os.path.join(SANDBOX, "unsorted")
    truth = {}
    for name, colour, stripes in KINDS:
        for index in range(5):
            shade = tuple(v + 5 for v in colour)
            path = picture(os.path.join(source, "%s_%d.png" % (name, index)), shade, stripes, 25)
            truth[path] = name
    odd = picture(os.path.join(source, "green_odd.png"), (20, 200, 20), jitter=5)
    truth[odd] = "_unmatched"
    return refs, source, truth


def tiny_onnx_model(path):
    """An image model small enough to write here: the mean colour of the
    picture, as a three-number vector.  Crude, but it is a real ONNX graph
    with an image input and a pooled output, which is all the driver needs."""
    import onnx
    from onnx import TensorProto, helper
    image = helper.make_tensor_value_info("pixel_values", TensorProto.FLOAT, [1, 3, 32, 32])
    out = helper.make_tensor_value_info("image_embeds", TensorProto.FLOAT, [1, 3])
    nodes = [helper.make_node("GlobalAveragePool", ["pixel_values"], ["pooled"]),
             helper.make_node("Flatten", ["pooled"], ["image_embeds"], axis=1)]
    graph = helper.make_graph(nodes, "tiny_image_model", [image], [out])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, path)
    return path


def main():
    try:
        import numpy as np                                          # noqa: F401
    except Exception:
        print("SKIPPED - numpy not installed (comparing images is optional)")
        return 0

    from annotex.apps.images import reference
    from annotex.apps.images.common import scan_images
    from annotex.apps.images.sorter import UNMATCHED, UNSURE
    from annotex.core.ai import embed
    from annotex.core.ai.cache import EmbeddingCache

    refs, source, truth = build_world()

    # ══ reading the examples ══════════════════════════════
    categories = reference.read_references(refs)
    ok("each sub-folder is a category", list(categories) == ["blue", "red", "stripes"])
    ok("with its examples in it", all(len(v) == 2 for v in categories.values()))
    ok("and it describes itself", "3 categories" in reference.describe_references(categories))

    loose = os.path.join(SANDBOX, "one_thing")
    picture(os.path.join(loose, "a.png"), (9, 9, 9))
    picture(os.path.join(loose, "b.png"), (9, 9, 9))
    ok("examples lying loose are one category, named for their folder",
       list(reference.read_references(loose)) == ["one_thing"])
    for bad, why in ((os.path.join(SANDBOX, "nowhere"), "a folder that is not there"),
                     (tempfile.mkdtemp(dir=SANDBOX), "a folder with no pictures")):
        try:
            reference.read_references(bad)
            ok("%s is refused" % why, False)
        except reference.ReferenceError as exc:
            ok("%s is refused with a sentence" % why, len(str(exc)) > 20)

    inside = os.path.join(source, "examples_kept_here", "red")
    picture(os.path.join(inside, "kept.png"), (200, 30, 30))
    everything = scan_images(source)
    kept_here = reference.read_references(os.path.dirname(inside))
    ok("examples kept inside the folder being sorted are not sorted themselves",
       all("kept.png" not in p for p in reference.images_to_sort(everything, kept_here)))
    shutil.rmtree(os.path.dirname(inside))

    # ══ the three rules ═══════════════════════════════════
    import numpy
    rules = reference.Comparison(["cats", "dogs"], ["a", "b", "c", "d"],
                                 numpy.array([[0.90, 0.20],    # clearly cats
                                              [0.50, 0.10],    # nothing is alike enough
                                              [0.81, 0.80],    # a coin toss
                                              [0.85, 0.83]], dtype="float32"))
    ok("clearly one thing goes to it", rules.decide(0, 0.7, 0.03)[0] == ["cats"])
    ok("nothing alike enough goes to _unmatched", rules.decide(1, 0.7, 0.03)[0] == [UNMATCHED])
    ok("a near tie goes to _unsure", rules.decide(2, 0.7, 0.03)[0] == [UNSURE])
    ok("a smaller margin lets the tie be decided", rules.decide(2, 0.7, 0.005)[0] == ["cats"])
    ok("every category above the threshold, when asked",
       rules.decide(3, 0.7, 0.03, "all")[0] == ["cats", "dogs"])
    ok("the split counts every image once",
       rules.split(0.7, 0.03) == {"cats": 1, UNSURE: 2, UNMATCHED: 1})
    ok("a stricter threshold moves images out, without any model",
       rules.split(0.95, 0.03) == {UNMATCHED: 4})
    categorise = rules.categoriser(0.7, 0.03)
    ok("the sort asks the comparison, not a model", categorise("a")[0] == ["cats"])
    try:
        categorise("not compared")
        ok("an image that was never compared is an error, not a guess", False)
    except ValueError:
        ok("an image that was never compared is an error, not a guess", True)

    # ══ the settings the examples suggest ═════════════════
    vectors = numpy.array([[1.0, 0.0], [0.96, 0.28], [0.0, 1.0], [0.28, 0.96]], dtype="float32")
    threshold, margin, why = reference.suggest_settings(vectors, ["a", "a", "b", "b"])
    ok("the threshold lands between alike and unalike",
       0.28 < threshold < 0.96 and "halfway" in why)
    ok("the margin is a slice of the gap", 0.0 < margin <= 0.10)
    single = reference.suggest_settings(vectors[[0, 2]], ["a", "b"])
    ok("one example each still gives a usable guess, and says so",
       -1.0 <= single[0] < 1.0 and "one example" in single[2])
    ok("no examples falls back to the defaults",
       reference.suggest_settings(numpy.zeros((0, 2)), [])[:2]
       == (reference.DEFAULT_THRESHOLD, reference.DEFAULT_MARGIN))

    # ══ comparing, for real ═══════════════════════════════
    images = reference.images_to_sort(scan_images(source), categories)
    cache = EmbeddingCache("reference-test", root=os.path.join(SANDBOX, "cache"))
    comparison = reference.compare(embed.ClassicEmbedder(), categories, images, cache=cache)
    t, m = comparison.suggested
    right = sum(1 for i, p in enumerate(comparison.paths)
                if comparison.decide(i, t, m)[0][0] == truth[p])
    ok("with the settings the examples suggest, every image lands right (%d/%d)"
       % (right, len(comparison)), right == len(comparison))
    ok("the odd one out is left out, not forced into a category",
       comparison.decide(comparison.paths.index(os.path.join(source, "green_odd.png")),
                         t, m)[0] == [UNMATCHED])
    ok("the suggestion explains itself", bool(comparison.calibration))
    average = reference.compare(embed.ClassicEmbedder(), categories, images,
                                combine=reference.COMBINE_AVERAGE, cache=cache)
    ok("comparing with each category's average works too",
       average.split(*average.suggested)["red"] == 5)

    counted = [0]

    class Counting(embed.ClassicEmbedder):
        def vector(self, path):
            counted[0] += 1
            return embed.ClassicEmbedder.vector(self, path)

    started = time.monotonic()
    reference.compare(Counting(), categories, images, cache=cache)
    ok("a second comparison is served from the cache", counted[0] == 0)
    ok("so it is quick", time.monotonic() - started < 5.0)
    counted[0] = 0
    more = dict(categories)
    more["extra"] = [picture(os.path.join(SANDBOX, "extra", "x.png"), (120, 120, 0))]
    reference.compare(Counting(), more, images, cache=cache)
    ok("adding an example costs only that example", counted[0] == 1)

    broken = os.path.join(source, "broken.png")
    with open(broken, "w", encoding="utf-8") as handle:
        handle.write("not a picture")
    with_broken = reference.compare(embed.ClassicEmbedder(), categories,
                                    images + [broken], cache=None)
    ok("an unreadable image is reported, and the rest still compared",
       len(with_broken) == len(images) and any(p == broken for p, _w in with_broken.errors))
    os.remove(broken)
    ok("cancelling stops a comparison",
       reference.compare(embed.ClassicEmbedder(), categories, images, cache=None,
                         cancelled=lambda: True) is None)

    # ── any ONNX image model ──────────────────────────────
    try:
        import onnx                                                 # noqa: F401
        import onnxruntime                                          # noqa: F401
        have_onnx = True
    except Exception:
        have_onnx = False
    if have_onnx:
        model = tiny_onnx_model(os.path.join(SANDBOX, "tiny_image_model.onnx"))
        embedder = reference.make_embedder(reference.EMBED_ONNX, model)
        ok("an ONNX image model is read off its graph",
           embedder.width == 32 and embedder.layout == "nchw")
        colours = reference.compare(embedder, {"red": categories["red"],
                                               "blue": categories["blue"]},
                                    [p for p in images if truth[p] in ("red", "blue")],
                                    cache=None)
        t, m = colours.suggested
        ok("and compares pictures by what it sees",
           all(colours.decide(i, t, m)[0][0] == truth[p]
               for i, p in enumerate(colours.paths)))
        ok("its vector is whatever width the model gives", embedder.dim == 3)
    else:
        print("  --  skipping the ONNX model checks (onnx or onnxruntime not installed)")
    try:
        reference.make_embedder(reference.EMBED_ONNX, "")
        ok("no model chosen is refused", False)
    except reference.ReferenceError:
        ok("no model chosen is refused", True)

    # ══ the tab ═══════════════════════════════════════════
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    from annotex.apps.images import sorter
    from annotex.apps.images.ui.sorter_page import SorterPage
    from annotex.core.jobs import DONE
    from annotex.ui.dialogs import messages
    from annotex.ui.jobs import JobManager
    from annotex.ui.media_page import tool_settings
    messages.ask = lambda *a, **k: True

    jobs = JobManager()
    page = SorterPage(app, settings=tool_settings(SorterPage.TOOL_ID, SorterPage.DEFAULTS,
                                                  os.path.join(SANDBOX, "sorter.json")),
                      jobs=jobs)
    page.resize(1280, 800)
    page.show()
    app.processEvents()
    tab = page.reference_tab
    ok("the Image Sorter has a By example tab",
       page.tabs.tabText(page.tabs.indexOf(tab)) == "By example")
    ok("nothing to compare before there are images", not tab.compare_button.isEnabled())

    page.add_paths([source])
    app.processEvents()
    tab.ref_edit.setText(refs)
    tab._references_changed()
    ok("choosing the examples shows what is in them", "3 categories" in tab.ref_summary.text())
    ok("the model row is hidden until a model is wanted", not tab.model_row.isVisibleTo(tab))
    ok("sorting waits for a comparison", not tab.sort_button.isEnabled())

    tab.compare()
    ok("comparing runs as a job", jobs.wait(300))
    ok("and succeeds", all(j.state == DONE for j in jobs.jobs))
    app.processEvents()
    ok("the comparison arrives in the tab", tab.comparison is not None
       and len(tab.comparison) == len(images))
    ok("the sliders start where the examples suggest",
       abs(tab.threshold.value() / 100.0 - tab.comparison.suggested[0]) < 0.011)
    ok("the split is shown", "red 5" in tab.split_label.text()
       and UNMATCHED in tab.split_label.text())
    ok("every image is listed", tab.table.rowCount() == len(images))
    first_score = float(tab.table.item(0, 2).text())
    last_score = float(tab.table.item(tab.table.rowCount() - 1, 2).text())
    ok("weakest matches first", first_score <= last_score)
    tab.table.selectRow(0)
    app.processEvents()
    ok("clicking a row shows the picture", tab.preview.image is not None)

    before = tab.split_label.text()
    tab.threshold.setValue(99)
    app.processEvents()
    ok("dragging the threshold re-decides at once", tab.split_label.text() != before
       and all(tab.table.item(r, 4).text() == UNMATCHED for r in range(tab.table.rowCount())))
    t, m = tab.comparison.suggested
    tab.threshold.setValue(int(round(t * 100)))
    tab.margin.setValue(int(round(m * 100)))
    app.processEvents()
    ok("and moving it back puts them back", "red 5" in tab.split_label.text())
    ok("sorting is ready", tab.sort_button.isEnabled())

    output = page.output_root()
    tab.run_sort()
    ok("sorting runs as a job", jobs.wait(300))
    ok("and succeeds", all(j.state == DONE for j in jobs.jobs))
    for name in ("red", "blue", "stripes"):
        folder = os.path.join(output, name)
        ok("%s got its five" % name,
           os.path.isdir(folder) and len(os.listdir(folder)) == 5
           and all(n.startswith(name) for n in os.listdir(folder)))
    ok("the odd one out went to _unmatched",
       os.listdir(os.path.join(output, UNMATCHED)) == ["green_odd.png"])
    ok("the originals are untouched", len(scan_images(source)) == len(images))
    runs = sorter.runs(output)
    ok("the run is logged as a sort by example", runs and runs[0][1] == reference.MODE)
    removed = sorter.undo_run(output, runs[0][0])
    ok("and can be undone like any other", removed == len(images))

    picture(os.path.join(source, "arrived_later.png"), (200, 30, 30))
    page.set_source(source)
    app.processEvents()
    ok("new images make the comparison out of date", tab.comparison is None
       and not tab.sort_button.isEnabled())
    page.close()
    app.processEvents()

    print("=" * 60)
    shutil.rmtree(SANDBOX, ignore_errors=True)
    if FAILS:
        print("REFERENCE TESTS FAILED: %s" % ", ".join(FAILS))
        return 1
    print("REFERENCE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
