"""Sorting by example: show it a few pictures of each thing, and it finds more.

No training and no class list.  A reference folder holds one sub-folder per
category, each with a handful of example images; every image to be sorted
is compared with every example, and goes to the category it is most like.

    references/
        cats/     tabby.jpg  ginger.png
        dogs/     spaniel.jpg
        empty/    road_only.jpg

This is the half with no Qt in it: reading the references, comparing, and
deciding.  Comparing is the slow part and deciding is arithmetic, so the two
are kept apart on purpose - a comparison is worked out once, and then the
threshold and margin can be dragged back and forth over it and every image
re-decided instantly, which is how a person finds numbers that suit their
pictures instead of guessing at them.

How alike two pictures are is a cosine between their vectors (see
core/ai/embed.py), from -1 to 1.  Three rules turn that into a folder:

    the best match is below the threshold     ->  _unmatched
    the runner-up is within the margin of it  ->  _unsure
    otherwise                                 ->  the best match's category

`_unsure` is the honest answer when an image looks about as much like two
categories as each other, and a person would want to look at those.
"""

from __future__ import annotations

import os

from annotex.core.ai import embed
from annotex.core.ai.cache import EmbeddingCache

from .common import natural_key, scan_images
from .sorter import UNMATCHED, UNSURE, safe_folder_name

MODE = "reference"

COMBINE_NEAREST = "nearest"     # like its closest example
COMBINE_AVERAGE = "average"     # like the category's examples on average
EMBED_CLASSIC = "classic"
EMBED_ONNX = "onnx"

DEFAULT_THRESHOLD = 0.70
DEFAULT_MARGIN = 0.03


class ReferenceError(ValueError):
    """The references cannot be used as they are.  Written to be shown."""


# ══════════════════════════════════════════════════════════════
# THE REFERENCES
# ══════════════════════════════════════════════════════════════
def read_references(folder):
    """{category: [example images]} from a reference folder.

    Each sub-folder with images in it is a category, named after the
    sub-folder.  Images lying loose in the reference folder itself make one
    more category, named after the folder - so a folder of examples of a
    single thing works without making a sub-folder for it."""
    folder = os.path.abspath(str(folder or ""))
    if not folder or not os.path.isdir(folder):
        raise ReferenceError("Choose a reference folder: one sub-folder per category, "
                             "each holding a few example images.")
    categories = {}
    try:
        entries = sorted(os.listdir(folder), key=natural_key)
    except OSError as exc:
        raise ReferenceError("The reference folder cannot be read: %s" % exc)
    loose = []
    for name in entries:
        path = os.path.join(folder, name)
        if os.path.isdir(path):
            if name.startswith("."):
                continue
            examples = scan_images(path, recursive=True)
            if examples:
                categories[safe_folder_name(name)] = examples
        elif os.path.isfile(path):
            loose.append(path)
    if loose:
        wanted = set(loose)
        images = [p for p in scan_images(folder, recursive=False) if p in wanted]
        if images:
            own = safe_folder_name(os.path.basename(folder.rstrip(os.sep)) or "reference")
            categories.setdefault(own, []).extend(images)
    if not categories:
        raise ReferenceError("There are no example images in %s.  Put a few in one "
                             "sub-folder per category." % folder)
    return categories


def describe_references(categories) -> str:
    parts = ["%s (%d)" % (name, len(paths)) for name, paths in categories.items()]
    return "%d categor%s: %s" % (len(categories), "y" if len(categories) == 1 else "ies",
                                 ", ".join(parts))


def make_embedder(kind=EMBED_CLASSIC, model_path=""):
    """The embedder a choice in the interface names."""
    if kind == EMBED_ONNX:
        if not str(model_path or "").strip():
            raise ReferenceError("Choose the ONNX image model to compare with.")
        return embed.OnnxEmbedder(model_path)
    return embed.ClassicEmbedder()


def images_to_sort(images, categories):
    """The images to sort, without the examples themselves.

    A reference folder kept inside the folder being sorted is a natural way
    to organise things - and every example would otherwise be found, match
    itself perfectly, and be copied into its own category."""
    examples = {os.path.normcase(os.path.abspath(p))
                for paths in categories.values() for p in paths}
    return [p for p in images if os.path.normcase(os.path.abspath(p)) not in examples]


# ══════════════════════════════════════════════════════════════
# COMPARING
# ══════════════════════════════════════════════════════════════
class Comparison:
    """Every image scored against every category, ready to decide on.

    `scores[i][c]` is how alike image i is to category c.  Deciding reads
    only these numbers, so moving a slider never touches a model."""

    def __init__(self, categories, paths, scores, errors=(), embedder_name="",
                 suggested=(DEFAULT_THRESHOLD, DEFAULT_MARGIN), calibration=""):
        # What the references themselves say the settings should be; see
        # suggest_settings.  A starting point, and the sliders move from it.
        self.suggested = (float(suggested[0]), float(suggested[1]))
        self.calibration = str(calibration or "")
        self.categories = list(categories)
        self.paths = list(paths)
        self.scores = scores
        self.errors = list(errors)
        self.embedder_name = str(embedder_name or "")
        self._index = {os.path.normcase(os.path.abspath(p)): i
                       for i, p in enumerate(self.paths)}

    def __len__(self):
        return len(self.paths)

    def ranked(self, index):
        """[(category, score)] for one image, best first."""
        row = self.scores[index]
        pairs = [(self.categories[c], float(row[c])) for c in range(len(self.categories))]
        return sorted(pairs, key=lambda kv: kv[1], reverse=True)

    def decide(self, index, threshold=DEFAULT_THRESHOLD, margin=DEFAULT_MARGIN,
               multiple="top"):
        """([folders], detail) for one image under these settings."""
        ranked = self.ranked(index)
        if not ranked:
            return [UNMATCHED], "no categories"
        best_name, best = ranked[0]
        detail = "%s %.3f" % (best_name, best)
        if len(ranked) > 1:
            detail += "  (next %s %.3f)" % ranked[1]
        if best < float(threshold):
            return [UNMATCHED], detail
        if multiple == "all":
            chosen = [name for name, score in ranked if score >= float(threshold)]
            return chosen, detail
        if len(ranked) > 1 and best - ranked[1][1] < float(margin):
            return [UNSURE], detail
        return [best_name], detail

    def split(self, threshold=DEFAULT_THRESHOLD, margin=DEFAULT_MARGIN, multiple="top"):
        """{folder: how many images would go there} - what a slider shows."""
        counts = {}
        for index in range(len(self.paths)):
            folders, _detail = self.decide(index, threshold, margin, multiple)
            for folder in folders:
                counts[folder] = counts.get(folder, 0) + 1
        order = self.categories + [UNSURE, UNMATCHED]
        return {name: counts[name] for name in order if name in counts}

    def categoriser(self, threshold=DEFAULT_THRESHOLD, margin=DEFAULT_MARGIN,
                    multiple="top"):
        """What `sorter.run_sort` calls per image: the decision, never a model.

        The settings are copied now, so a slider moved while the copying
        runs changes nothing about a sort already under way."""
        threshold, margin, multiple = float(threshold), float(margin), str(multiple)

        def categorise(path):
            index = self._index.get(os.path.normcase(os.path.abspath(path)))
            if index is None:
                raise ValueError("this image was not part of the comparison")
            return self.decide(index, threshold, margin, multiple)
        return categorise


def suggest_settings(vectors, owners):
    """(threshold, margin, why) worked out from the examples alone.

    How alike two pictures score depends on the embedder and on the pictures
    - near-identical photos from a fixed camera and a mixed bag from the web
    live on quite different parts of the scale - so no fixed number is right
    for everybody, and a wrong default quietly sends everything to
    _unmatched.  The references already say what the scale looks like here:

        within   how alike each example is to the others of its own category
        across   how alike each example is to the nearest one of another

    A new image that belongs is expected to score about like `within`, and
    one that does not about like `across`, so the threshold goes halfway
    between the two, and the margin is a slice of the gap."""
    np = embed._numpy()
    owners = list(owners)
    count = len(owners)
    if count == 0:
        return DEFAULT_THRESHOLD, DEFAULT_MARGIN, "no examples to learn from"
    alike = np.asarray(vectors, dtype=np.float32).dot(np.asarray(vectors, dtype=np.float32).T)
    within, across = [], []
    for i in range(count):
        same = [alike[i, j] for j in range(count) if j != i and owners[j] == owners[i]]
        other = [alike[i, j] for j in range(count) if owners[j] != owners[i]]
        if same:
            within.append(float(max(same)))
        if other:
            across.append(float(max(other)))
    if within and across:
        inside, outside = float(np.median(within)), float(np.median(across))
        if inside > outside:
            threshold = (inside + outside) / 2.0
            margin = max(0.005, min(0.10, (inside - outside) * 0.10))
            why = ("examples of one thing score %.2f alike, of different things %.2f - "
                   "halfway between" % (inside, outside))
        else:
            # The categories look as alike as their own examples do: the
            # threshold cannot separate them, so it only keeps out the clearly
            # unrelated and the margin does the work.
            threshold = inside * 0.9
            margin = 0.02
            why = ("these categories look as alike as their own examples (%.2f against "
                   "%.2f), so expect many in _unsure - more distinct examples help"
                   % (inside, outside))
    elif across:
        outside = float(np.median(across))
        threshold = outside + (1.0 - outside) * 0.25
        margin = DEFAULT_MARGIN
        why = ("one example per category, which differ at %.2f - add a second example "
               "to a category for a better guess" % outside)
    elif within:
        inside = float(min(within))
        threshold = inside * 0.9
        margin = DEFAULT_MARGIN
        why = "one category, whose examples score %.2f alike" % inside
    else:
        return DEFAULT_THRESHOLD, DEFAULT_MARGIN, "a single example - adjust by eye"
    return (float(max(-1.0, min(0.99, threshold))), float(margin), why)


def compare(embedder, categories, images, combine=COMBINE_NEAREST, cache="default",
            progress=None, cancelled=None):
    """Score every image against every category.

    `cache` is an EmbeddingCache, None for none, or "default" for the
    embedder's own namespace - so a second comparison of the same folder,
    with different references or different settings, costs nothing but the
    images that are new."""
    np = embed._numpy()
    progress = progress or (lambda done, total, message="": None)
    cancelled = cancelled or (lambda: False)
    if cache == "default":
        cache = EmbeddingCache("embed-%s" % embedder.id)
        if not cache.available():
            cache = None
    names = list(categories)
    if not names:
        raise ReferenceError("There are no categories to compare with.")

    examples = [p for name in names for p in categories[name]]
    owners = [name for name in names for _p in categories[name]]
    total = len(examples) + len(images) or 1

    def step(offset, label):
        return lambda done, _all: progress(offset + done, total, label)

    ref_vectors, ref_errors, ref_kept = embed.embed_paths(
        embedder, examples, cache=cache, progress=step(0, "Reading the examples"),
        cancelled=cancelled)
    if cancelled():
        return None
    owner_of = dict(zip(examples, owners))
    kept_owners = [owner_of[p] for p in ref_kept]
    usable = [name for name in names if name in kept_owners]
    if not usable:
        raise ReferenceError("None of the example images could be read.")

    image_vectors, image_errors, image_kept = embed.embed_paths(
        embedder, images, cache=cache, progress=step(len(examples), "Comparing images"),
        cancelled=cancelled)
    if cancelled():
        return None
    errors = list(ref_errors) + list(image_errors)
    threshold, margin, why = suggest_settings(ref_vectors, kept_owners)
    if not image_kept:
        return Comparison(usable, [], np.zeros((0, len(usable)), dtype=np.float32),
                          errors, embedder.name, (threshold, margin), why)

    if ref_vectors.shape[1] != image_vectors.shape[1]:
        raise ReferenceError("The examples and the images came out different sizes - "
                             "the model is answering inconsistently.")

    columns = []
    for name in usable:
        rows = ref_vectors[[i for i, owner in enumerate(kept_owners) if owner == name]]
        if combine == COMBINE_AVERAGE:
            centre = embed.unit(rows.mean(axis=0))
            columns.append(image_vectors.dot(centre))
        else:
            columns.append((image_vectors.dot(rows.T)).max(axis=1))
    scores = np.stack(columns, axis=1).astype(np.float32)
    progress(total, total, "Compared")
    return Comparison(usable, image_kept, scores, errors, embedder.name,
                      (threshold, margin), why)
