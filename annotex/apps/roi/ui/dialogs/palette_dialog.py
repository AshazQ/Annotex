"""The command palette and shortcut sheet, fed with ROI Studio's commands."""

from __future__ import annotations

from annotex.ui.dialogs.palette_dialog import CommandPalette as _CommandPalette
from annotex.ui.dialogs.palette_dialog import ShortcutSheet as _ShortcutSheet

from .. import shortcuts as sc

MOUSE_HINT = (
    "Mouse: drag a vertex to reshape · drag inside an ROI to move it · "
    "double-click an edge to insert a point · Ctrl+click a vertex to "
    "remove it · drag on empty space to rubber-band select · "
    "middle-drag or hold Space to pan · scroll to zoom.")


class CommandPalette(_CommandPalette):
    """Ctrl+K: type a few letters, run any command."""

    def __init__(self, parent, keys, enabled=None, theme=None):
        super().__init__(parent, sc.ACTIONS, keys, enabled, theme)


class ShortcutSheet(_ShortcutSheet):
    """Every binding, grouped, in one scrollable sheet."""

    def __init__(self, parent, keys, theme=None):
        super().__init__(parent, sc.ACTIONS, keys, theme, MOUSE_HINT)
