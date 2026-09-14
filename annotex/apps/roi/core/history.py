"""Undo / redo for ROI Studio - the suite's history with ROI Studio's depth."""

from __future__ import annotations

from annotex.core.history import History as _History

from ..config import MAX_UNDO_STEPS


class History(_History):
    def __init__(self, limit: int = MAX_UNDO_STEPS):
        super().__init__(limit)
