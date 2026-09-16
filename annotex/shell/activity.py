"""What you were last working on, for Home's "Continue" strip.  No Qt.

The order comes from the session store, which knows when each folder was
last actually worked in.  It used to come from the modification time of the
tool's settings file, which gives every folder in a tool the same answer
and gets the order wrong the moment somebody returns to an older one.

A machine with no session store yet - anybody upgrading - still gets its
Continue strip, built from the recent-folder lists the tools have always
kept.  Those have no timestamps, so the order is the tools' own; the first
run in each folder replaces the guess with the real thing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Session:
    """One recent folder, as Home draws it."""

    tool_id: str
    folder: str
    stamp: float = 0.0
    total: int = 0
    done: int | None = None       # None = this tool does not count per image
    thumb: str = ""
    measured: bool = False
    # From the session store, and empty for a folder it has never seen.
    last_image: str = ""
    active_seconds: float = 0.0
    elsewhere: str = ""           # named when the record is another machine's
    crashed: bool = False
    view: dict = field(default_factory=dict)
    tool: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return os.path.basename(os.path.normpath(self.folder)) or self.folder

    def worked_text(self) -> str:
        total = int(self.active_seconds)
        hours, minutes = divmod(total // 60, 60)
        if hours:
            return "%dh %02dm" % (hours, minutes)
        return "%dm" % minutes if minutes else ""


def _store():
    from ..core.sessions import SessionStore
    return SessionStore()


def from_record(record) -> Session:
    """A stored record as the strip's own view of it."""
    from ..core.sessions import machine_label
    return Session(record.tool_id, record.folder,
                   total=record.images_total, done=record.images_done,
                   last_image=record.last_image,
                   active_seconds=record.active_seconds,
                   elsewhere=machine_label(record.machine),
                   crashed=record.crashed,
                   view=dict(record.view), tool=dict(record.tool))


def recent_sessions(tools, limit=3):
    """The most recent (tool, folder) pairs across every tool, newest first."""
    ids = [spec.id for spec in tools if spec.recent is not None]
    try:
        records = _store().recent(limit=limit, tool_ids=ids)
    except Exception:
        records = []
    if records:
        return [from_record(record) for record in records]
    return _from_recent_folders(tools, limit)


def _from_recent_folders(tools, limit):
    """What Home showed before there was a session store."""
    sessions = []
    for spec in tools:
        if spec.recent is None:
            continue
        try:
            folders = [f for f in (spec.recent() or []) if os.path.isdir(f)]
        except Exception:
            continue
        for position, folder in enumerate(folders[:2]):
            sessions.append(Session(spec.id, folder, -float(position)))
    seen, out = set(), []
    for session in sessions:
        key = (session.tool_id, os.path.normcase(os.path.abspath(session.folder)))
        if key not in seen:
            seen.add(key)
            out.append(session)
    return out[:limit]


def measure(session, remember=True) -> Session:
    """Count the images and how many already have an annotation.

    The counts go back into the store, so the next start can show them
    before it has finished counting - which on a folder of several thousand
    images is the difference between a number and a blank."""
    folder = session.folder
    if session.tool_id == "shapes":
        from ..apps.shapes.core.store import annotation_path, scan_images
        rels = scan_images(folder)
        session.done = sum(1 for rel in rels if os.path.isfile(annotation_path(folder, rel)))
    else:
        from ..apps.labelimg.core.annotations import scan_images
        rels = scan_images(folder)
        if session.tool_id == "labelimg":
            done = 0
            for rel in rels:
                base = os.path.join(folder, os.path.splitext(rel)[0])
                if any(os.path.isfile(base + ext) for ext in (".xml", ".txt", ".json")):
                    done += 1
            session.done = done
        else:
            session.done = None
    session.total = len(rels)
    session.thumb = os.path.join(folder, rels[0]) if rels else ""
    session.measured = True
    if remember:
        try:
            # Noted, not updated: counting a folder is not working in it, and
            # must not leave a finished session looking like a crash.
            _store().note(session.tool_id, folder, images_total=session.total,
                          images_done=session.done)
        except Exception:
            pass
    return session
