"""A disk cache for model answers that cost seconds to work out again.

SAM's encoder spends a few seconds on an image and what it produces - the
image embedding - is only a couple of megabytes.  Reference-image sorting
has the same shape: one vector per image, expensive once and free ever
after.  Both keep their answers here, keyed by the model that produced them
and by the file's identity, so a second visit to a folder costs nothing.

Everything is total.  A cache that cannot be read, written or pruned is a
cache miss, never an error: a lost entry costs a few seconds, and no
feature may fail because a disk filled up.  numpy is an optional install,
so without it the cache reports itself unavailable and every caller carries
on computing as it always did.

Entries are stored as fp16 by default - half the bytes, and far below the
precision any of this is sensitive to - and pruned back to a byte budget
least-recently-read first.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading

from ...config import first_writable, user_data_dir

DEFAULT_BUDGET = 2 * 1024 ** 3          # 2 GB, shared by every namespace
PRUNE_EVERY = 16                        # writes between budget checks
FP16_MAX = 60000.0                      # keep clear of fp16's 65504 ceiling


def cache_root():
    """Where cached model answers live, per user."""
    return first_writable([user_data_dir() / "model_cache"])


def file_identity(path) -> str:
    """Where a file is, how big it is and when it was last written.

    Cheap - three numbers off the directory entry - and good enough for
    anything that lives as long as one sitting.  For an entry that will
    still be on disk in a month, use `content_identity` instead."""
    try:
        stat = os.stat(str(path))
        return "%s|%d|%d" % (os.path.abspath(str(path)), stat.st_size,
                             int(stat.st_mtime_ns))
    except Exception:
        return os.path.abspath(str(path)) if path else ""


_DIGESTS = {}                           # (path, size, mtime_ns) -> digest
_DIGEST_LOCK = threading.Lock()
DIGEST_CHUNK = 1024 * 1024
MAX_REMEMBERED_DIGESTS = 4096


def content_identity(path) -> str:
    """A digest of what the file actually holds.

    A cached answer can outlive many edits of the picture it was worked out
    from, so the key has to say what the picture *was*, not merely when it
    was touched.  A timestamp is not enough on its own: it is a whole second
    on a FAT-formatted memory stick and two on some of them, which is long
    enough to replace an image with another of the same size and be handed
    the wrong answer for it afterwards.

    Reading a few megabytes costs a handful of milliseconds against the
    seconds the answer itself costs.  If the file cannot be read at all,
    this falls back to `file_identity` rather than refusing to cache.

    One honest limit: the digest is remembered for as long as the process
    lives, under the file's size and timestamp, so asking twice is free.
    Inside one run, a file whose contents change while its size and
    timestamp are put back exactly as they were will therefore give its
    previous digest.  Nothing does that by accident, and the next run
    digests it again - which is what matters, because the entries this keys
    are the ones that outlive the run."""
    try:
        stat = os.stat(str(path))
        quick = (os.path.abspath(str(path)), stat.st_size, stat.st_mtime_ns)
    except Exception:
        return file_identity(path)
    with _DIGEST_LOCK:
        remembered = _DIGESTS.get(quick)
    if remembered:
        return remembered
    try:
        digest = hashlib.blake2b(digest_size=16)
        with open(str(path), "rb") as handle:
            while True:
                block = handle.read(DIGEST_CHUNK)
                if not block:
                    break
                digest.update(block)
        answer = "%d:%s" % (stat.st_size, digest.hexdigest())
    except Exception:
        return file_identity(path)
    with _DIGEST_LOCK:
        if len(_DIGESTS) > MAX_REMEMBERED_DIGESTS:
            _DIGESTS.clear()
        _DIGESTS[quick] = answer
    return answer


def _numpy():
    try:
        import numpy
        return numpy
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
class EmbeddingCache:
    """One namespace of cached arrays - "sam", or an embedder's own id.

    Thread-safe: the interface thread reads it while a worker writes to it,
    which is exactly how the labelling tools use it."""

    def __init__(self, namespace, budget_bytes: int = DEFAULT_BUDGET,
                 half: bool = True, root=None):
        self.namespace = str(namespace or "default")
        self.budget = max(0, int(budget_bytes))
        self.half = bool(half)
        self._root = str(root) if root else ""
        self._lock = threading.Lock()
        self._writes = 0
        self._folder = ""

    # ── where it lives ────────────────────────────────────
    def folder(self) -> str:
        """The namespace's directory, created on first use.  "" if unusable."""
        if self._folder:
            return self._folder
        try:
            base = self._root or str(cache_root())
            path = os.path.join(base, self.namespace)
            os.makedirs(path, exist_ok=True)
            self._folder = path
        except Exception:
            self._folder = ""
        return self._folder

    def available(self) -> bool:
        return self.budget > 0 and _numpy() is not None and bool(self.folder())

    # ── keys ──────────────────────────────────────────────
    @staticmethod
    def key(*parts) -> str:
        """A short, stable name for everything that went into an answer."""
        joined = "\x00".join(str(p) for p in parts)
        return hashlib.sha1(joined.encode("utf-8", "replace")).hexdigest()

    def _paths(self, key):
        folder = self.folder()
        if not folder:
            return "", ""
        # Two hex characters of fan-out: one folder holding fifty thousand
        # entries is slow to list on every platform that matters.
        bucket = os.path.join(folder, str(key)[:2])
        stem = os.path.join(bucket, str(key))
        return stem + ".npy", stem + ".json"

    # ── reading ───────────────────────────────────────────
    def get(self, key, dtype="float32"):
        """(array, meta) for this key, or (None, None) on any miss."""
        np = _numpy()
        if np is None or not self.budget:
            return None, None
        array_path, meta_path = self._paths(key)
        if not array_path:
            return None, None
        with self._lock:
            try:
                array = np.load(array_path, allow_pickle=False)
            except Exception:
                return None, None
            meta = {}
            try:
                with open(meta_path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    meta = loaded
            except Exception:
                meta = {}
            # Last-read time is what prune() orders by, so a read is a touch.
            try:
                os.utime(array_path, None)
            except Exception:
                pass
        try:
            if dtype and str(array.dtype) != str(dtype):
                array = array.astype(dtype)
            return np.ascontiguousarray(array), meta
        except Exception:
            return None, None

    def has(self, key) -> bool:
        array_path, _meta = self._paths(key)
        return bool(array_path) and os.path.isfile(array_path)

    # ── writing ───────────────────────────────────────────
    def put(self, key, array, meta=None) -> bool:
        np = _numpy()
        if np is None or not self.budget:
            return False
        array_path, meta_path = self._paths(key)
        if not array_path:
            return False
        try:
            data = np.ascontiguousarray(array)
        except Exception:
            return False
        if self.half and data.dtype == np.float32:
            # fp16 halves the bytes and costs nothing anyone can see - but
            # only where every value actually fits, and where none of them is
            # a nan or an infinity that would come back as something else.
            try:
                largest = float(np.abs(data).max()) if data.size else 0.0
                if bool(np.all(np.isfinite(data))) and largest < FP16_MAX:
                    data = data.astype(np.float16)
            except Exception:
                pass
        with self._lock:
            try:
                os.makedirs(os.path.dirname(array_path), exist_ok=True)
                part = array_path + ".part"
                with open(part, "wb") as handle:
                    np.save(handle, data, allow_pickle=False)
                os.replace(part, array_path)
                if meta:
                    with open(meta_path + ".part", "w", encoding="utf-8") as handle:
                        json.dump(dict(meta), handle)
                    os.replace(meta_path + ".part", meta_path)
            except Exception:
                for leftover in (array_path + ".part", meta_path + ".part"):
                    try:
                        os.remove(leftover)
                    except Exception:
                        pass
                return False
            self._writes += 1
            due = self._writes % PRUNE_EVERY == 0
        if due:
            self.prune()
        return True

    # ── housekeeping ──────────────────────────────────────
    def entries(self):
        """[(last_read, bytes, array_path)] for everything stored here."""
        folder = self.folder()
        if not folder:
            return []
        found = []
        for bucket, _dirs, names in os.walk(folder):
            for name in names:
                if not name.endswith(".npy"):
                    continue
                path = os.path.join(bucket, name)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                found.append((stat.st_mtime, stat.st_size, path))
        return found

    def size_bytes(self) -> int:
        return sum(size for _read, size, _path in self.entries())

    def prune(self, budget=None) -> int:
        """Drop the least recently read entries until inside the budget.

        Returns how many were removed."""
        budget = self.budget if budget is None else max(0, int(budget))
        found = self.entries()
        total = sum(size for _read, size, _path in found)
        if total <= budget:
            return 0
        removed = 0
        for _read, size, path in sorted(found):
            if total <= budget:
                break
            with self._lock:
                try:
                    os.remove(path)
                except Exception:
                    continue
                removed += 1
                total -= size
                try:
                    os.remove(os.path.splitext(path)[0] + ".json")
                except Exception:
                    pass
        return removed

    def clear(self) -> int:
        """Remove everything in this namespace.  Returns how many went."""
        return self.prune(budget=0)

    def describe(self) -> str:
        if not self.available():
            return "not in use"
        count = len(self.entries())
        return "%d entr%s  ·  %.0f MB of %.0f MB" % (
            count, "y" if count == 1 else "ies",
            self.size_bytes() / (1024.0 * 1024.0), self.budget / (1024.0 * 1024.0))


# ══════════════════════════════════════════════════════════════
def model_id(*paths) -> str:
    """A short id for the model that produced an answer.

    The file name alone is not enough - two different exports are often
    called the same thing - so the size goes in as well."""
    parts = []
    for path in paths:
        text = str(path or "")
        if not text:
            continue
        try:
            parts.append("%s:%d" % (os.path.basename(text), os.path.getsize(text)))
        except OSError:
            parts.append(os.path.basename(text))
    return EmbeddingCache.key(*parts)[:16] if parts else "none"
