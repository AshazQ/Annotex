"""The annotation clipboard.

Copy the two boxes you want, move to the next image, paste.  That is the
whole feature, and it works across images, across the two labelling tools
and across a restart, because every entry is plain JSON that also goes onto
the system clipboard.

The store itself is Qt-free so the headless self-tests can exercise it.  The
window installs a bridge (`set_bridge`) that mirrors the payload to and from
the system clipboard; without a bridge everything still works inside one
running process.

Every item carries a `bounds` rectangle as well as its own geometry, so a
tool can always paste something another tool copied: LabelImg Shapes turns a
box into a rectangle, LabelImg Master turns a polygon into its bounding box.
"""

from __future__ import annotations

import json
import time

FORMAT = "annotex.annotations/1"
KIND_BOXES = "boxes"
KIND_SHAPES = "shapes"
MAX_ITEMS = 2000


def _clean_size(size):
    try:
        width, height = int(size[0]), int(size[1])
    except Exception:
        return (0, 0)
    return (max(0, width), max(0, height))


def _clean_bounds(item):
    bounds = item.get("bounds")
    try:
        x0, y0, x1, y1 = [float(v) for v in bounds]
    except Exception:
        return None
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


class Payload:
    """What was copied: items, the size of the image they came from, and
    which tool they came from."""

    __slots__ = ("kind", "items", "size", "stamp", "source")

    def __init__(self, kind, items, size, stamp=None, source=""):
        self.kind = str(kind or KIND_BOXES)
        self.items = list(items or [])
        self.size = _clean_size(size)
        self.stamp = float(stamp if stamp is not None else time.time())
        self.source = str(source or "")

    def __len__(self):
        return len(self.items)

    def to_json(self) -> str:
        return json.dumps({"format": FORMAT, "kind": self.kind, "source": self.source,
                           "width": self.size[0], "height": self.size[1],
                           "stamp": self.stamp, "items": self.items})

    @classmethod
    def from_json(cls, text):
        """A Payload, or None for anything that is not ours."""
        if not text or len(text) > 40 * 1024 * 1024:
            return None
        try:
            data = json.loads(text)
        except Exception:
            return None
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            return None
        items = data.get("items")
        if not isinstance(items, list):
            return None
        clean = []
        for item in items[:MAX_ITEMS]:
            if isinstance(item, dict) and _clean_bounds(item) is not None:
                clean.append(item)
        if not clean:
            return None
        return cls(data.get("kind", KIND_BOXES), clean,
                   (data.get("width", 0), data.get("height", 0)),
                   data.get("stamp"), data.get("source", ""))

    def scale_to(self, size):
        """The same items, resized for an image of another size.

        Copying between frames of the same camera is the common case and
        needs no scaling at all; a different size is scaled proportionally so
        a paste lands in the same place on the picture rather than in the
        corner."""
        width, height = _clean_size(size)
        if not width or not height or not self.size[0] or not self.size[1]:
            return list(self.items), 1.0, 1.0
        fx = float(width) / float(self.size[0])
        fy = float(height) / float(self.size[1])
        if abs(fx - 1.0) < 1e-6 and abs(fy - 1.0) < 1e-6:
            return list(self.items), 1.0, 1.0
        return [_scaled_item(item, fx, fy) for item in self.items], fx, fy


def _scaled_item(item, fx, fy):
    out = dict(item)
    bounds = _clean_bounds(item)
    if bounds is not None:
        out["bounds"] = [bounds[0] * fx, bounds[1] * fy, bounds[2] * fx, bounds[3] * fy]
    for key in ("x0", "x1", "cx", "w", "r"):
        if key in out:
            try:
                out[key] = float(out[key]) * fx
            except Exception:
                pass
    for key in ("y0", "y1", "cy", "h"):
        if key in out:
            try:
                out[key] = float(out[key]) * fy
            except Exception:
                pass
    if isinstance(out.get("points"), list):
        points = []
        for point in out["points"]:
            try:
                points.append([float(point[0]) * fx, float(point[1]) * fy])
            except Exception:
                continue
        out["points"] = points
    return out


# ══════════════════════════════════════════════════════════════
# THE STORE
# ══════════════════════════════════════════════════════════════
_payload = None
_read_text = None
_write_text = None

# Reading the system clipboard is a round trip to whichever application owns
# it, and the windows ask "is there anything to paste?" on every selection
# change.  The answer is therefore cached for a moment, and thrown away the
# instant the clipboard actually changes.
_POLL_SECONDS = 0.3
_cache = {"at": 0.0, "text": None, "payload": None}


def set_bridge(read_text=None, write_text=None) -> None:
    """Mirror the clipboard to the system one.  Both callables may raise;
    nothing here lets that reach the caller."""
    global _read_text, _write_text
    _read_text, _write_text = read_text, write_text
    invalidate()


def invalidate() -> None:
    """Forget what the system clipboard last held (call it on dataChanged)."""
    _cache["at"] = 0.0
    _cache["text"] = None
    _cache["payload"] = None


def _external():
    if _read_text is None:
        return None
    now = time.monotonic()
    if _cache["at"] and (now - _cache["at"]) < _POLL_SECONDS:
        return _cache["payload"]
    try:
        text = _read_text()
    except Exception:
        text = None
    _cache["at"] = now
    if text == _cache["text"]:
        return _cache["payload"]
    _cache["text"] = text
    try:
        _cache["payload"] = Payload.from_json(text)
    except Exception:
        _cache["payload"] = None
    return _cache["payload"]


def copy(kind, items, size, source="") -> Payload:
    """Put items on the clipboard.  Returns the payload that was stored."""
    global _payload
    _payload = Payload(kind, list(items)[:MAX_ITEMS], size, source=source)
    invalidate()
    if _write_text is not None:
        try:
            _write_text(_payload.to_json())
        except Exception:
            pass
    return _payload


def clear() -> None:
    global _payload
    _payload = None
    invalidate()


def content():
    """What is on the clipboard now, ours or the system's, or None."""
    external = _external()
    if external is None:
        return _payload
    if _payload is None or external.stamp > _payload.stamp + 1e-6:
        return external
    return _payload


def count() -> int:
    payload = content()
    return len(payload) if payload else 0


def describe() -> str:
    payload = content()
    if not payload:
        return "nothing copied yet"
    what = "shape(s)" if payload.kind == KIND_SHAPES else "box(es)"
    return "%d %s%s" % (len(payload), what,
                        (" from %s" % payload.source) if payload.source else "")
