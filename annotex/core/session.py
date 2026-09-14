"""Crash-safe drafts, the audit log, and the session timer.

Three small services that share one idea: work that has happened should
survive the process that produced it.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime

from ..config import crash_dir
from .io_safe import safe_remove, write_text_atomic


def _default_serializer(shape):
    return {"kind": shape.kind, "points": [list(p) for p in shape.points]}


# ══════════════════════════════════════════════════════════════
class DraftStore:
    """Periodic snapshot of unsaved work, plus crash recovery.

    The draft lives in the batch folder when that is writable and in the
    per-user recovery directory otherwise, so a read-only share still gets
    protection.
    """

    def __init__(self, draft_name: str = ".annotex_draft.json",
                 serializer=None, recovery_dir=None):
        self.draft_name = draft_name
        self.serializer = serializer or _default_serializer
        self.recovery_dir = recovery_dir or crash_dir
        self.path = ""
        self.folder = ""
        self._last_payload = None

    def bind(self, folder) -> None:
        self.folder = str(folder)
        candidate = os.path.join(self.folder, self.draft_name)
        try:
            with open(candidate, "a", encoding="utf-8"):
                pass
            if os.path.getsize(candidate) == 0:
                safe_remove(candidate)
            self.path = candidate
        except Exception:
            # A stable digest, not hash(): str hashes are salted per process,
            # which would put the fallback draft somewhere new on every run and
            # make it unrecoverable after exactly the crash it exists for.
            token = hashlib.sha1(self.folder.encode("utf-8")).hexdigest()[:12]
            stem = os.path.splitext(self.draft_name.lstrip("."))[0]
            self.path = str(self.recovery_dir() / ("%s_%s.json" % (stem, token)))
        self._last_payload = None

    # ── writing ───────────────────────────────────────────
    def save(self, image_name, shapes, comment, force: bool = False,
             extra=None) -> bool:
        """Write a draft for the image being edited.  Returns True if it wrote."""
        if not self.path:
            return False
        payload = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "folder": self.folder,
            "image_name": image_name or "",
            "comment": comment or "",
            "shapes": [self.serializer(s) for s in (shapes or [])],
        }
        if extra:
            payload["extra"] = dict(extra)
        fingerprint = (json.dumps(payload["shapes"], sort_keys=True)
                       + payload["comment"]
                       + json.dumps(payload.get("extra", {}), sort_keys=True))
        if not force and fingerprint == self._last_payload:
            return False
        self._last_payload = fingerprint
        if not payload["shapes"] and not payload["comment"] and not extra:
            self.clear()
            return True
        ok, _err = write_text_atomic(self.path, json.dumps(payload, indent=1),
                                     verify_json=True, keep_backup=False)
        return ok

    def clear(self) -> None:
        self._last_payload = None
        safe_remove(self.path)

    # ── recovery ──────────────────────────────────────────
    def pending(self):
        """Return the recoverable draft for this folder, or None."""
        if not self.path or not os.path.isfile(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or not data.get("image_name"):
                return None
            if not data.get("shapes") and not data.get("comment") \
                    and not data.get("extra"):
                return None
            return data
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════
class AuditLog:
    """Append-only record of every change, one JSON object per line.

    Never blocks and never raises: an unwritable log must not stop annotation.
    """

    def __init__(self, audit_name: str = ".annotex_audit.jsonl",
                 enabled: bool = True):
        self.audit_name = audit_name
        self.path = ""
        self.enabled = bool(enabled)

    def bind(self, folder) -> None:
        self.path = os.path.join(str(folder), self.audit_name)

    def record(self, action, image_name="", detail="", **extra) -> None:
        if not self.enabled or not self.path:
            return
        entry = {"at": datetime.now().isoformat(timespec="seconds"),
                 "action": str(action),
                 "image": str(image_name or ""),
                 "detail": str(detail or "")}
        entry.update({k: v for k, v in extra.items() if v is not None})
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def tail(self, limit: int = 200):
        """Most recent entries, newest last.  Empty on any problem."""
        if not self.path or not os.path.isfile(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()[-int(limit):]
        except Exception:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out


# ══════════════════════════════════════════════════════════════
class SessionTimer:
    """Elapsed working time and throughput.

    Idle time is not counted: the clock only advances while something has
    happened in the last IDLE_AFTER seconds.
    """

    IDLE_AFTER = 120.0

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._active = 0.0
        self._last_tick = None
        self._images = 0
        self._shapes = 0
        self.started_at = datetime.now()

    def touch(self) -> None:
        """Call on any user action."""
        now = time.monotonic()
        if self._last_tick is not None:
            delta = now - self._last_tick
            if delta <= self.IDLE_AFTER:
                self._active += delta
        self._last_tick = now

    def count_image(self, shapes: int = 0) -> None:
        self._images += 1
        self._shapes += max(0, int(shapes))
        self.touch()

    @property
    def active_seconds(self) -> float:
        return self._active

    @property
    def images_done(self) -> int:
        return self._images

    @property
    def shapes_drawn(self) -> int:
        return self._shapes

    def per_hour(self) -> float:
        if self._active < 1.0:
            return 0.0
        return self._images / (self._active / 3600.0)

    def elapsed_text(self) -> str:
        total = int(self._active)
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return "%dh %02dm" % (h, m)
        if m:
            return "%dm %02ds" % (m, s)
        return "%ds" % s

    def summary(self) -> str:
        rate = self.per_hour()
        if not self._images:
            return "Session %s" % self.elapsed_text()
        return "Session %s  ·  %d image(s)  ·  %.0f/hr" % (
            self.elapsed_text(), self._images, rate)
