"""Undo / redo.

Snapshot based rather than command based: an image never holds more than a
few dozen shapes, so copying the whole list is cheap and cannot drift out of
sync the way paired do/undo methods do.  Every entry carries a label so the
UI can say exactly what Ctrl+Z will undo.
"""

from __future__ import annotations

DEFAULT_LIMIT = 200


class History:
    """A labelled undo stack for one image's shapes."""

    def __init__(self, limit: int = DEFAULT_LIMIT):
        self.limit = max(2, int(limit))
        self._undo = []          # [(label, snapshot)]
        self._redo = []
        self._current = None     # snapshot of the live state
        self._label = ""

    # ── lifecycle ─────────────────────────────────────────
    def reset(self, snapshot) -> None:
        """Start a fresh history for a newly loaded image."""
        self._undo.clear()
        self._redo.clear()
        self._current = self._clone(snapshot)
        self._label = ""

    def push(self, label, snapshot) -> None:
        """Record that the state just changed, and what the change was."""
        if self._current is None:
            self._current = self._clone(snapshot)
            return
        self._undo.append((label, self._current))
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()
        self._current = self._clone(snapshot)
        self._label = label

    # ── queries ───────────────────────────────────────────
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_label(self) -> str:
        return self._undo[-1][0] if self._undo else ""

    def redo_label(self) -> str:
        return self._redo[-1][0] if self._redo else ""

    def depth(self):
        return len(self._undo), len(self._redo)

    # ── movement ──────────────────────────────────────────
    def undo(self):
        """Return (label, snapshot) to restore, or None."""
        if not self._undo:
            return None
        label, snapshot = self._undo.pop()
        self._redo.append((label, self._current))
        if len(self._redo) > self.limit:
            self._redo.pop(0)
        self._current = snapshot
        return label, self._clone(snapshot)

    def redo(self):
        if not self._redo:
            return None
        label, snapshot = self._redo.pop()
        self._undo.append((label, self._current))
        self._current = snapshot
        return label, self._clone(snapshot)

    # ── internals ─────────────────────────────────────────
    @staticmethod
    def _clone(snapshot):
        """Snapshots are lists of shapes; copy so later edits cannot mutate
        an entry already on the stack."""
        try:
            return [item.copy() for item in snapshot]
        except AttributeError:
            return list(snapshot)
