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
EMBED_ONNX = "onnx"                 # an ONNX image model the person chose
EMBED_MODEL = "model:"              # + a catalogue key: one Annotex downloads

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


def catalog_kind(key) -> str:
    """The embedder choice that names a downloadable model."""
    return EMBED_MODEL + str(key)


def catalog_model(kind):
    """The catalogue model an embedder choice names, or None."""
    if not str(kind or "").startswith(EMBED_MODEL):
        return None
    from annotex.core.ai.catalog import embed_by_key
    return embed_by_key(str(kind)[len(EMBED_MODEL):])


def make_embedder(kind=EMBED_CLASSIC, model_path=""):
    """The embedder a choice in the interface names."""
    if str(kind or "").startswith(EMBED_MODEL):
        model = catalog_model(kind)
        if model is None:
            raise ReferenceError("That image model is not one Annotex knows.")
        if not model.installed():
            raise ReferenceError("%s has not been downloaded yet." % model.name)
        return embed.OnnxEmbedder(model.path(), recipe=model.recipe, name=model.name)
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
                 suggested=(DEFAULT_THRESHOLD, DEFAULT_MARGIN), calibration="",
                 rescue=None):
        # (floor, lead): an image below the threshold still goes to its best
        # category when it scores above `floor` - what different things score
        # - and leads every other category by `lead`, as the examples do.
        # Strangers look about equally unlike every category; a picture of
        # one of them, taken badly, still clearly points at it.  `floor` is
        # for the suggested threshold, and follows it.  None: off.
        self.rescue = (float(rescue[0]), float(rescue[1])) if rescue else None
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
            if self.rescue is not None and len(ranked) > 1:
                floor, lead = self.rescue
                # The floor follows the slider: the band below the threshold
                # narrows as it rises towards 1, so a strict threshold is
                # strict for rescued images too.
                room = max(1e-6, 1.0 - self.suggested[0])
                band = (self.suggested[0] - floor) * max(0.0, 1.0 - float(threshold)) / room
                floor = float(threshold) - max(0.0, band)
                if best >= floor and best - ranked[1][1] >= lead:
                    return [best_name], detail + "  - below the threshold, but clearly this"
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
    rescue = rescue_settings(ref_vectors, kept_owners)
    if rescue is not None:
        why += ("; below it an image still counts when it scores over %.2f and leads "
                "every other category by %.2f" % rescue)
    elif len(usable) == 1 and getattr(embedder, "semantic", False):
        # Only for a model that sees what is in a picture: comparing looks,
        # strangers score among the category's own pictures, and taking the
        # less typical ones would take them too.
        threshold, note = single_category_threshold(threshold, scores[:, 0])
        if note:
            why += "; " + note
    return Comparison(usable, image_kept, scores, errors, embedder.name,
                      (threshold, margin), why, rescue)


def rescue_settings(vectors, owners):
    """(floor, lead) for rescuing an image below the threshold, from the
    examples alone - or None with a single category, where there is nothing
    to lead.

    floor   how alike examples of different categories are: a stranger
            scores about this, so an image below it is never rescued;
    lead    how far an example's own category is ahead of the nearest other
            one, taken low (the tenth percentile), since a real picture of
            a category is less typical than the examples chosen for it.

    Measured over a sample of pictures from ten everyday kinds of thing,
    this kept the examples' threshold where it was right and recovered most
    of the real members it had wrongly left out - without letting in the
    strangers it was right to leave out."""
    np = embed._numpy()
    owners = list(owners)
    if len(set(owners)) < 2 or len(owners) < 3:
        return None
    alike = np.asarray(vectors, dtype=np.float32).dot(np.asarray(vectors, dtype=np.float32).T)
    across, leads = [], []
    for i, owner in enumerate(owners):
        same = [alike[i, j] for j in range(len(owners)) if j != i and owners[j] == owner]
        other = [alike[i, j] for j in range(len(owners)) if owners[j] != owner]
        if other:
            across.append(float(max(other)))
        if same and other:
            leads.append(float(max(same)) - float(max(other)))
    if not across or not leads:
        return None
    lead = float(np.percentile(leads, 10))
    if lead <= 0.0:
        return None                     # the examples do not keep their categories apart
    return (float(np.median(across)), lead)


def single_category_threshold(threshold, scores):
    """(threshold, note) for one category, now that its images are scored.

    With one category the examples say how alike its own pictures are, but
    nothing about strangers.  When the images show no separate group of low
    scores - no strangers in sight - and most of them clear the threshold,
    the rest are most likely the category's less typical pictures, so the
    threshold comes down to take them, a little and no further."""
    np = embed._numpy()
    values = np.asarray(scores, dtype=np.float64).reshape(-1)
    if len(values) < 8 or float(np.median(values)) < threshold or has_low_group(values):
        return threshold, ""
    lowered = max(threshold - 0.12, min(threshold, float(np.percentile(values, 2)) - 0.01))
    if lowered >= threshold - 1e-6:
        return threshold, ""
    return lowered, ("no strangers among the images, so it starts lower, at %.2f, to take "
                     "the less typical ones" % lowered)


def has_low_group(values) -> bool:
    """Whether the scores fall into two groups with a clear dip between them
    - the low one being strangers.  A smoothed histogram, and a dip less than
    half the smaller peak with at least a few scores on either side."""
    np = embed._numpy()
    x = np.sort(np.asarray(values, dtype=np.float64).reshape(-1))
    n = len(x)
    if n < 8 or x[-1] - x[0] < 1e-6:
        return False
    spread = float(np.percentile(x, 90) - np.percentile(x, 10))
    width = max(1e-3, 0.9 * min(float(x.std()), spread / 1.34 if spread > 0 else float(x.std()))
                * n ** -0.2)
    grid = np.linspace(x[0], x[-1], 200)
    density = np.exp(-0.5 * ((grid[:, None] - x[None, :]) / width) ** 2).sum(axis=1)
    for i in range(1, len(grid) - 1):
        if density[i] > density[i - 1] or density[i] > density[i + 1]:
            continue
        below = int((x < grid[i]).sum())
        if min(below, n - below) < max(2, int(0.03 * n)):
            continue
        if density[i] < 0.5 * min(density[:i].max(), density[i:].max()):
            return True
    return False
