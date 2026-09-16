"""What you were working on, so that starting again is not starting over.

Annotex has always remembered which folders a tool had open, by keeping a
list of them in each tool's settings file.  That is enough for a list of
recent folders and not enough for anything else: it does not know when you
were last in one, which image you had reached, how long you had been at it,
whether the run ended or crashed, or even which machine any of it happened
on.  Home's "Continue" strip had to guess the order from the modification
time of the settings file itself, which gives every folder in a tool the
same answer.

So this keeps a record per (tool, folder):

    when it was opened, when it was closed, how long was worked
    which image was reached, and how many there are
    what the view looked like, and whatever else the tool wants kept
    and the machine it all happened on

A record with no closing time is a run that did not end - which is how the
offer to pick up after a crash knows there is anything to offer.

Every record is stamped with a machine id, and records from another machine
are shown but never restored.  That matters more than it sounds: a settings
folder synced through OneDrive or Dropbox is ordinary on Windows, and
without the stamp one laptop would cheerfully reopen the other's absolute
paths and window geometry.

Nothing here raises.  A missing, corrupt or unwritable store yields no
sessions rather than an error: not being able to remember what you were
doing must never stop you from doing it.  And no Qt, so the headless tests
can drive all of it.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import uuid
from datetime import datetime

from ..config import user_data_dir
from .io_safe import read_json, write_text_atomic

SCHEMA = 1
MAX_SESSIONS = 50                       # records kept, least recently touched go
STORE_NAME = "sessions.json"
MACHINE_NAME = "machine.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _now_precise() -> str:
    """A time to sort by, to the millisecond.

    Whole seconds are not enough: one checkpoint writes every open tool in
    the same pass, and to the second they all happen at once - which leaves
    the order of the Continue strip decided by nothing in particular."""
    return datetime.now().isoformat(timespec="milliseconds")


def _newest_first(session):
    """Sort key for "most recently worked in".

    The counter first, because it is exact and the clock is not, with the
    timestamp behind it for records the counter cannot separate."""
    return (session.order, session.touched_at or session.opened_at)


def _key(tool_id, folder) -> str:
    return "%s\x00%s" % (str(tool_id or ""),
                         os.path.normcase(os.path.abspath(str(folder or ""))))


# ══════════════════════════════════════════════════════════════
# THIS MACHINE
# ══════════════════════════════════════════════════════════════
_machine = [""]
_machine_lock = threading.Lock()


def machine_id() -> str:
    """An id for this computer, made once and kept.

    The host name alone will not do - two machines can share one, and one
    machine can change its own - so a random id is written beside the
    settings the first time it is asked for.  If it cannot be written, the
    host name stands in: a shared id is a worse answer than a private one,
    but both are better than refusing to have sessions at all."""
    with _machine_lock:
        if _machine[0]:
            return _machine[0]
    path = user_data_dir() / MACHINE_NAME
    found = ""
    data = read_json(str(path), {}) or {}
    if isinstance(data, dict) and isinstance(data.get("id"), str) and data["id"].strip():
        found = data["id"].strip()
    if not found:
        found = uuid.uuid4().hex[:16]
        write_text_atomic(str(path), json.dumps(
            {"id": found, "host": _host(), "created": _now()}, indent=1),
            verify_json=True, keep_backup=False)
    with _machine_lock:
        _machine[0] = found
    return found


def _host() -> str:
    try:
        return socket.gethostname() or "this machine"
    except Exception:
        return "this machine"


def machine_label(machine) -> str:
    """"" for this machine, and something nameable for anywhere else."""
    return "" if str(machine or "") == machine_id() else "another machine"


# ══════════════════════════════════════════════════════════════
# ONE RECORD
# ══════════════════════════════════════════════════════════════
class WorkSession:
    """One (tool, folder) somebody worked in, and how far they got."""

    FIELDS = ("tool_id", "folder", "machine", "opened_at", "closed_at", "touched_at",
              "order", "active_seconds", "last_image", "images_total", "images_done",
              "view", "tool", "schema")

    def __init__(self, tool_id="", folder="", **rest):
        self.tool_id = str(tool_id or "")
        self.folder = str(folder or "")
        self.machine = str(rest.get("machine") or "")
        self.opened_at = str(rest.get("opened_at") or "")
        self.closed_at = str(rest.get("closed_at") or "")
        self.touched_at = str(rest.get("touched_at") or "")
        # Which write this was, counted by the store.  Two sessions written
        # in the same pass have the same timestamp to any resolution worth
        # writing down, and a clock that goes backwards - a correction, a
        # time zone, the end of summer time - would reorder them anyway.
        self.order = _as_int(rest.get("order"), 0)
        try:
            self.active_seconds = max(0.0, float(rest.get("active_seconds") or 0.0))
        except (TypeError, ValueError):
            self.active_seconds = 0.0
        self.last_image = str(rest.get("last_image") or "")
        self.images_total = _as_int(rest.get("images_total"), 0)
        done = rest.get("images_done")
        self.images_done = None if done is None else _as_int(done, 0)
        self.view = dict(rest.get("view") or {})
        self.tool = dict(rest.get("tool") or {})
        self.schema = _as_int(rest.get("schema"), SCHEMA)

    # ── what it is ────────────────────────────────────────
    @property
    def key(self) -> str:
        return _key(self.tool_id, self.folder)

    @property
    def name(self) -> str:
        return os.path.basename(os.path.normpath(self.folder)) or self.folder

    @property
    def crashed(self) -> bool:
        """Opened and never closed: the run it belonged to did not end."""
        return bool(self.opened_at) and not self.closed_at

    @property
    def here(self) -> bool:
        return self.machine == machine_id()

    @property
    def exists(self) -> bool:
        try:
            return os.path.isdir(self.folder)
        except Exception:
            return False

    def worked_text(self) -> str:
        total = int(self.active_seconds)
        hours, rest = divmod(total, 3600)
        minutes = rest // 60
        if hours:
            return "%dh %02dm" % (hours, minutes)
        if minutes:
            return "%dm" % minutes
        return "under a minute"

    def progress_text(self) -> str:
        if not self.images_total:
            return ""
        if self.images_done is None:
            return "%d image(s)" % self.images_total
        return "%d of %d annotated" % (self.images_done, self.images_total)

    # ── on disk ───────────────────────────────────────────
    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.FIELDS}

    @classmethod
    def from_dict(cls, data):
        """A record from the store, or None if it is not one.

        Anything unrecognisable is dropped rather than repaired: a session
        is a convenience, and a wrong one is worse than none."""
        if not isinstance(data, dict):
            return None
        tool_id, folder = data.get("tool_id"), data.get("folder")
        if not isinstance(tool_id, str) or not isinstance(folder, str):
            return None
        if not tool_id.strip() or not folder.strip():
            return None
        if _as_int(data.get("schema"), SCHEMA) > SCHEMA:
            return None                     # written by a newer build than this
        try:
            return cls(tool_id, folder, **{k: v for k, v in data.items()
                                           if k in cls.FIELDS and k not in
                                           ("tool_id", "folder")})
        except Exception:
            return None

    def __repr__(self):                                 # pragma: no cover
        return "WorkSession(%r, %r)" % (self.tool_id, self.folder)


def _as_int(value, fallback=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


# ══════════════════════════════════════════════════════════════
# THE STORE
# ══════════════════════════════════════════════════════════════
class SessionStore:
    """Every remembered session, in one file beside the settings."""

    def __init__(self, path=None, limit: int = MAX_SESSIONS):
        self.path = str(path or (user_data_dir() / STORE_NAME))
        self.limit = max(1, int(limit))
        self._lock = threading.RLock()

    # ── reading and writing the whole thing ───────────────
    def _read(self) -> dict:
        data = read_json(self.path, {}) or {}
        return data if isinstance(data, dict) else {}

    def sessions(self):
        """Every valid record, newest activity first."""
        raw = self._read().get("sessions")
        found = []
        if isinstance(raw, list):
            for entry in raw:
                session = WorkSession.from_dict(entry)
                if session is not None:
                    found.append(session)
        found.sort(key=_newest_first, reverse=True)
        return found

    def _next_order(self) -> int:
        """The next write's number: one past the highest ever handed out.

        Read back off the records rather than held in memory, so two
        Annotex windows writing the same store still agree."""
        highest = 0
        for session in self.sessions():
            highest = max(highest, session.order)
        return highest + 1

    def _write(self, sessions, extra=None) -> bool:
        keep = sessions[:self.limit]
        payload = dict(self._read())
        payload.update(extra or {})
        payload["schema"] = SCHEMA
        payload["sessions"] = [s.to_dict() for s in keep]
        ok, _error = write_text_atomic(self.path, json.dumps(payload, indent=1),
                                       verify_json=True, keep_backup=False)
        return ok

    # ── one record at a time ──────────────────────────────
    def find(self, tool_id, folder):
        wanted = _key(tool_id, folder)
        for session in self.sessions():
            if session.key == wanted:
                return session
        return None

    # Whether a write says the folder is being worked in.  "live" clears the
    # closing time, "closed" sets it, and "keep" leaves it exactly as it was
    # - which is what counting a folder's images needs, since counting is
    # not working and must not make a finished session look like a crash.
    LIVE, CLOSED, KEEP = "live", "closed", "keep"

    def _put(self, tool_id, folder, state, fields):
        if not tool_id or not folder:
            return None
        ignored = ("tool_id", "folder", "machine", "schema", "closed_at", "touched_at")
        with self._lock:
            sessions = self.sessions()
            wanted = _key(tool_id, folder)
            session = next((s for s in sessions if s.key == wanted), None)
            fresh = session is None
            if fresh:
                session = WorkSession(tool_id, folder, opened_at=_now())
                sessions.insert(0, session)
            session.machine = machine_id()
            if not session.opened_at:
                session.opened_at = _now()
            for name, value in fields.items():
                if name in WorkSession.FIELDS and name not in ignored:
                    setattr(session, name, value)
            session.touched_at = _now_precise()
            if state == self.LIVE:
                session.closed_at = ""
            elif state == self.CLOSED:
                session.closed_at = _now()
            elif fresh:
                # Noted before it was ever opened for real: closed, so that
                # a folder merely looked at is never offered as a crash.
                session.closed_at = _now()
            session.schema = SCHEMA
            session.order = self._next_order()
            sessions.sort(key=_newest_first, reverse=True)
            self._write(sessions)
            return session

    def update(self, tool_id, folder, **fields):
        """Write down where a tool has got to, creating the record if new.

        This also says the folder is being worked in right now: it clears
        the closing time, so a record left without one is a run that never
        finished.  That is what the offer to pick up after a crash reads."""
        return self._put(tool_id, folder, self.LIVE, fields)

    def note(self, tool_id, folder, **fields):
        """Record something about a session without saying it is running.

        Counting the images in a folder tells us something worth keeping,
        but it is not somebody working in it - and if it cleared the closing
        time, every session measured on the way up would look like a crash
        and be offered back."""
        return self._put(tool_id, folder, self.KEEP, fields)

    def end(self, tool_id, folder, **fields):
        """Mark a session finished, so it is not offered as a crash."""
        return self._put(tool_id, folder, self.CLOSED, fields)

    def forget(self, tool_id, folder) -> bool:
        wanted = _key(tool_id, folder)
        with self._lock:
            sessions = self.sessions()
            kept = [s for s in sessions if s.key != wanted]
            if len(kept) == len(sessions):
                return False
            return self._write(kept)

    def clear(self) -> bool:
        with self._lock:
            return self._write([], {"open_tools": []})

    # ── asking questions of it ────────────────────────────
    def recent(self, limit: int = 3, tool_ids=None, here_only: bool = True,
               existing_only: bool = True):
        """The sessions worth offering to continue, newest first."""
        allowed = set(tool_ids) if tool_ids else None
        out = []
        for session in self.sessions():
            if allowed is not None and session.tool_id not in allowed:
                continue
            if here_only and not session.here:
                continue
            if existing_only and not session.exists:
                continue
            out.append(session)
            if limit and len(out) >= int(limit):
                break
        return out

    def unfinished(self, tool_ids=None):
        """Sessions from a run that never ended, on this machine.

        What the offer to pick up after a crash is built from."""
        return [s for s in self.recent(limit=0, tool_ids=tool_ids)
                if s.crashed and (s.last_image or s.images_total)]

    # ── which tools were open ─────────────────────────────
    def open_tools(self):
        """The tools that were showing when the last run ended, in order."""
        data = self._read()
        if str(data.get("open_machine") or "") != machine_id():
            return []                       # another machine's window, not ours
        raw = data.get("open_tools")
        return [str(t) for t in raw if isinstance(t, str)] if isinstance(raw, list) else []

    def set_open_tools(self, tool_ids) -> bool:
        with self._lock:
            return self._write(self.sessions(),
                               {"open_tools": [str(t) for t in tool_ids or []],
                                "open_machine": machine_id()})
