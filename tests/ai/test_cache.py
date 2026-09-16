"""The cached-answer layer, and comparing images by vector.

Two things are tested here, because the second is built on the first:

* `annotex.core.ai.cache` - the disk cache that stops the SAM encoder and
  the reference sorter from working out the same answer twice;
* `annotex.core.ai.embed` - turning an image into one vector, so that two
  images can be told apart.

Neither needs onnxruntime or a downloaded model, so this runs everywhere
numpy does.  It skips - rather than fails - without numpy, because numpy is
an optional install.

    python tests/ai/test_cache.py
"""

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="annotex_cache_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


def picture(path, fn, size=(120, 90)):
    from PIL import Image
    width, height = size
    image = Image.new("RGB", size)
    image.putdata([fn(x, y) for y in range(height) for x in range(width)])
    image.save(path)
    return path


def main():
    for module in ("numpy", "PIL"):
        try:
            __import__(module)
        except Exception:
            print("SKIPPED - %s not installed" % module)
            return 0

    import numpy as np

    from annotex.core.ai import embed
    from annotex.core.ai.cache import (EmbeddingCache, content_identity,
                                       file_identity, model_id)

    root = os.path.join(SANDBOX, "cache")

    # ══ the cache ═════════════════════════════════════════
    cache = EmbeddingCache("test", budget_bytes=16 * 1024 * 1024, root=root)
    ok("a cache in a writable place is available", cache.available())

    array = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
    key = cache.key("a model", "an image")
    ok("an answer is stored", cache.put(key, array, {"orig_size": [9, 16], "scale": 0.5}))
    back, meta = cache.get(key)
    ok("it comes back the same", back is not None and np.allclose(back, array))
    ok("it comes back as float32", back is not None and back.dtype == np.float32)
    ok("its notes come back too", meta.get("orig_size") == [9, 16])
    ok("a key that was never stored is a miss", cache.get("nothing") == (None, None))
    ok("has() agrees with get()", cache.has(key) and not cache.has("nothing"))

    # fp16 is the point of the thing: a SAM embedding must halve.
    embedding = np.random.rand(256, 64, 64).astype(np.float32)
    big_key = cache.key("a model", "a big image")
    cache.put(big_key, embedding)
    on_disk = [size for _read, size, path in cache.entries()
               if os.path.basename(path).startswith(big_key)]
    ok("a four-megabyte embedding is stored in two",
       bool(on_disk) and embedding.nbytes * 0.4 < on_disk[0] < embedding.nbytes * 0.6)
    restored, _meta = cache.get(big_key)
    ok("and comes back close enough to be the same answer",
       restored is not None and float(np.abs(restored - embedding).max()) < 0.01)

    # Values fp16 could not hold must not be quietly mangled.
    huge = np.array([1e30, -1e30, 5.0], dtype=np.float32)
    cache.put(cache.key("huge"), huge)
    got, _meta = cache.get(cache.key("huge"))
    ok("numbers too big for fp16 are kept as they are",
       got is not None and np.allclose(got, huge))
    odd = np.array([np.nan, np.inf, 1.0], dtype=np.float32)
    cache.put(cache.key("odd"), odd)
    got, _meta = cache.get(cache.key("odd"))
    ok("a nan stays a nan", got is not None and bool(np.isnan(got[0])))

    # ── the budget is real ────────────────────────────────
    tiny = EmbeddingCache("tiny", budget_bytes=8 * 1024, root=root)
    for index in range(60):
        tiny.put(tiny.key("entry", index), np.zeros(512, dtype=np.float32))
    tiny.prune()
    ok("the cache is pruned back inside its budget", tiny.size_bytes() <= 8 * 1024)
    ok("but it is not emptied", tiny.size_bytes() > 0)

    # Least recently *read* is what goes, not least recently written.
    order = EmbeddingCache("order", budget_bytes=10 ** 9, root=root)
    keys = [order.key("k", i) for i in range(4)]
    for one in keys:
        order.put(one, np.zeros(1024, dtype=np.float32))
        time.sleep(0.01)
    order.get(keys[0])                       # the oldest write becomes the newest read
    per_entry = order.entries()[0][1]
    order.prune(budget=per_entry * 2)
    survivors = {os.path.splitext(os.path.basename(p))[0] for _r, _s, p in order.entries()}
    ok("reading an entry saves it from the next prune", keys[0] in survivors)
    ok("and the ones nobody read went", keys[1] not in survivors)

    ok("clearing empties the namespace", tiny.clear() > 0 and tiny.size_bytes() == 0)
    ok("a cache describes itself", "of" in cache.describe())
    ok("a cache with no budget is not available",
       not EmbeddingCache("off", budget_bytes=0, root=root).available())

    # ── identities and model ids ──────────────────────────
    sample = picture(os.path.join(SANDBOX, "sample.png"), lambda x, y: (x, y, 40))
    identity = file_identity(sample)
    ok("a file has an identity", sample in identity)
    ok("the same file has the same identity", file_identity(sample) == identity)
    time.sleep(0.01)
    picture(sample, lambda x, y: (y, x, 90))
    ok("an edited file has a different one", file_identity(sample) != identity)
    ok("a file that is not there still gives something",
       file_identity(os.path.join(SANDBOX, "gone.png")) != "")

    # What goes on disk is keyed by what the picture holds, not by its
    # timestamp: a second is a long time on a memory stick, and an image
    # swapped for another of the same size inside one must not be answered
    # from the entry made for the first.
    twin_a = os.path.join(SANDBOX, "twin.bin")
    with open(twin_a, "wb") as handle:
        handle.write(b"A" * 4096)
    digest = content_identity(twin_a)
    ok("contents have an identity", ":" in digest)
    ok("asking twice gives the same answer", content_identity(twin_a) == digest)
    stamp = os.stat(twin_a)
    with open(twin_a, "wb") as handle:
        handle.write(b"B" * 4096)
    os.utime(twin_a, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))    # same size, same mtime
    ok("the cheap identity cannot tell them apart",
       file_identity(twin_a) == "%s|%d|%d" % (twin_a, 4096, stamp.st_mtime_ns))
    from annotex.core.ai import cache as cache_module
    cache_module._DIGESTS.clear()                  # as the next run would start
    ok("a fresh look at the contents tells them apart",
       content_identity(twin_a) != digest)
    ok("contents that cannot be read fall back to the cheap identity",
       content_identity(os.path.join(SANDBOX, "gone.png")) != "")
    ok("two models have two ids", model_id(sample) != model_id(__file__))
    ok("and one model keeps one id", model_id(sample) == model_id(sample))

    # ══ the embedders ═════════════════════════════════════
    folder = os.path.join(SANDBOX, "pictures")
    os.makedirs(folder, exist_ok=True)
    red_a = picture(os.path.join(folder, "red_a.png"), lambda x, y: (200 + x % 20, 20, 20))
    red_b = picture(os.path.join(folder, "red_b.png"), lambda x, y: (205 + x % 20, 25, 18))
    blue = picture(os.path.join(folder, "blue.png"), lambda x, y: (20, 20, 200 + y % 20))
    bars = picture(os.path.join(folder, "bars.png"),
                   lambda x, y: (255, 255, 255) if (x // 10) % 2 else (0, 0, 0))

    embedder = embed.ClassicEmbedder()
    vector = embedder.vector(red_a)
    ok("a vector has the length it says it does", vector.size == embedder.dim)
    ok("and it is a unit vector", abs(float(np.linalg.norm(vector)) - 1.0) < 1e-5)
    ok("an embedder names itself for the cache", embedder.id.startswith("classic-"))

    alike = float(vector.dot(embedder.vector(red_b)))
    unalike = float(vector.dot(embedder.vector(blue)))
    striped = float(vector.dot(embedder.vector(bars)))
    ok("two pictures of the same thing score high", alike > 0.8)
    ok("two different pictures score lower", unalike < alike and striped < alike)
    ok("the same picture scores one",
       abs(float(vector.dot(embedder.vector(red_a))) - 1.0) < 1e-5)

    # The structure half is standardised, so exposure must not matter to it.
    from PIL import Image
    with Image.open(bars) as opened:
        opened.point(lambda v: int(v * 0.5) + 40).save(os.path.join(folder, "bars_dim.png"))
    plain, _grey = embedder._structure(Image.open(bars).convert("RGB"))
    dimmed, _grey = embedder._structure(
        Image.open(os.path.join(folder, "bars_dim.png")).convert("RGB"))
    ok("brightness does not change the shape of a picture",
       float(embed.unit(plain.reshape(-1)).dot(embed.unit(dimmed.reshape(-1)))) > 0.999)

    # Odd but real pictures must not throw.
    for mode, name in (("L", "grey.png"), ("CMYK", "cmyk.jpg"), ("RGBA", "alpha.png")):
        path = os.path.join(folder, name)
        Image.new(mode, (40, 30), 128 if mode == "L" else None).save(path)
        try:
            ok("a %s image still gives a vector" % mode,
               embedder.vector(path).size == embedder.dim)
        except Exception as exc:                                   # noqa: BLE001
            ok("a %s image still gives a vector (%s)" % (mode, exc), False)
    for size in ((1, 1), (2000, 3)):
        path = os.path.join(folder, "odd_%dx%d.png" % size)
        Image.new("RGB", size, (10, 200, 10)).save(path)
        try:
            ok("a %dx%d image still gives a vector" % size,
               embedder.vector(path).size == embedder.dim)
        except Exception as exc:                                   # noqa: BLE001
            ok("a %dx%d image still gives a vector (%s)" % (size + (exc,)), False)

    # ══ in bulk, through the cache ════════════════════════
    paths = [red_a, red_b, blue, bars]
    bulk = EmbeddingCache("bulk", root=root)
    matrix, errors, kept = embed.embed_paths(embedder, paths, cache=bulk)
    ok("every image is embedded", matrix.shape == (4, embedder.dim))
    ok("nothing went wrong", errors == [] and kept == paths)

    counted = [0]

    class Counting(embed.ClassicEmbedder):
        @property
        def id(self):
            return embedder.id                   # the same cache entries

        def vector(self, path):
            counted[0] += 1
            return embed.ClassicEmbedder.vector(self, path)

    embed.embed_paths(Counting(), paths, cache=bulk)
    ok("a second pass does not touch the model at all", counted[0] == 0)
    embed.embed_paths(Counting(), paths, cache=None)
    ok("and without a cache it does the work again", counted[0] == 4)

    similarities = embed.cosine_many(matrix[0], matrix)
    ok("an image is most like itself", int(np.argmax(similarities)) == 0)
    ok("a similarity is given for each row", similarities.size == 4)
    ok("comparing against nothing gives nothing",
       embed.cosine_many(matrix[0], np.zeros((0, embedder.dim))).size == 0)

    broken = os.path.join(folder, "broken.png")
    with open(broken, "w", encoding="utf-8") as handle:
        handle.write("this is not a picture")
    matrix, errors, kept = embed.embed_paths(embedder, paths + [broken], cache=None)
    ok("one unreadable file does not lose the others", matrix.shape[0] == 4)
    ok("and it is reported by name", len(errors) == 1 and errors[0][0] == broken)
    ok("the paths that worked come back in order", kept == paths)

    stopped = embed.embed_paths(embedder, paths, cache=None, cancelled=lambda: True)
    ok("cancelling stops it straight away", stopped[0].shape[0] == 0)

    seen = []
    embed.embed_paths(embedder, paths, cache=None,
                      progress=lambda done, total: seen.append((done, total)))
    ok("progress is reported all the way to the end", seen and seen[-1] == (4, 4))

    # An edited image must never be answered from the entry made before.
    first = embed.embed_paths(embedder, [bars], cache=bulk)[0][0]
    time.sleep(0.01)
    picture(bars, lambda x, y: (0, 255, 0))
    second = embed.embed_paths(embedder, [bars], cache=bulk)[0][0]
    ok("an edited image is embedded again, not remembered",
       float(first.dot(second)) < 0.99)

    # ── a missing onnxruntime is a sentence, not a traceback ──
    try:
        embed.OnnxEmbedder(os.path.join(SANDBOX, "not_a_model.onnx"))
        ok("a model that is not there is refused", False)
    except embed.EmbedUnavailable as exc:
        ok("a model that is not there is refused", "not there" in str(exc)
           or "install" in str(exc).lower())
    ok("the install hint names what is missing",
       embed.install_hint(onnx=True) == "" or "onnxruntime" in embed.install_hint(onnx=True))

    print("=" * 60)
    if FAILS:
        print("FAILED: %s" % ", ".join(FAILS))
        return 1
    print("CACHE AND EMBEDDING TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
