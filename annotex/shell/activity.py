"""What you were last working on, for Home's "Continue" strip.  No Qt.

The annotation tools remember their recent folders; this module orders them
by when each tool was last used and measures how far along each folder is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Session:
    tool_id: str
    folder: str
    stamp: float = 0.0
    total: int = 0
    done: int | None = None       # None = this tool does not count per image
    thumb: str = ""
    measured: bool = False

    @property
    def name(self) -> str:
        return os.path.basename(os.path.normpath(self.folder)) or self.folder


def _settings_file(tool_id):
    try:
        if tool_id == "roi":
            from ..apps.roi.config import settings_path
            return str(settings_path())
        if tool_id == "labelimg":
            from ..apps.labelimg.config import settings_dir
            return str(settings_dir() / "settings.json")
        if tool_id == "shapes":
            from ..apps.shapes.config import settings_dir
            return str(settings_dir() / "settings.json")
    except Exception:
        return ""
    return ""


def _stamp(tool_id) -> float:
    path = _settings_file(tool_id)
    try:
        return os.path.getmtime(path) if path else 0.0
    except OSError:
        return 0.0


def recent_sessions(tools, limit=3):
    """The most recent (tool, folder) pairs across every tool that keeps a
    recent-folder list, newest first."""
    sessions = []
    for spec in tools:
        if spec.recent is None:
            continue
        try:
            folders = [f for f in (spec.recent() or []) if os.path.isdir(f)]
        except Exception:
            continue
        stamp = _stamp(spec.id)
        for position, folder in enumerate(folders[:2]):
            sessions.append(Session(spec.id, folder, stamp - position * 1000.0))
    sessions.sort(key=lambda s: -s.stamp)
    seen, out = set(), []
    for session in sessions:
        key = (session.tool_id, os.path.normcase(os.path.abspath(session.folder)))
        if key not in seen:
            seen.add(key)
            out.append(session)
    return out[:limit]


def measure(session) -> Session:
    """Count the images and how many already have an annotation."""
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
    return session
