"""Vector icons.

Each icon is a small SVG path set drawn on a 24x24 grid and rendered at the
requested size, so they stay crisp on any display scale instead of being
hand-plotted a few pixels at a time.  Colour is injected at render time so
one definition serves both themes and the accent state.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Stroke-based icons: {name: svg body drawn in a 24x24 viewBox}
_BODY = {
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    "polygon": '<path d="M12 3.5 20.5 9.5 17.5 19.5 6.5 19.5 3.5 9.5Z"/>',
    "rect": '<rect x="4" y="6" width="16" height="12" rx="1.5"/>',
    "circle": '<circle cx="12" cy="12" r="7.5"/>',
    "lasso": '<ellipse cx="12" cy="9.5" rx="7.5" ry="5.5"/>'
             '<path d="M8.6 14.4c-.5 1-1.4 1.7-1.4 3 0 1 .6 1.9 1.5 2.3"/>',
    "cursor": '<path d="M5.5 3.5 19 11.5l-5.8 1.4L10.9 19Z"/>',
    "hand": '<path d="M8 12V6.5a1.5 1.5 0 0 1 3 0V11m0-.5V5.5a1.5 1.5 0 0 1 3 0V11m0-.5v-1a1.5 1.5 0 0 1 3 0V15a5 5 0 0 1-5 5h-1a5 5 0 0 1-5-5v-3a1.5 1.5 0 0 1 3 0"/>',
    "undo": '<path d="M4 10h9a5 5 0 0 1 0 10h-3"/><path d="M8 5.5 3.5 10 8 14.5"/>',
    "redo": '<path d="M20 10h-9a5 5 0 0 0 0 10h3"/><path d="M16 5.5 20.5 10 16 14.5"/>',
    "save": '<path d="M5 4h11l3 3v13H5Z"/><path d="M8 4v6h7V4"/><rect x="8" y="13" width="8" height="7"/>',
    "trash": '<path d="M4 7h16"/><path d="M10 4h4"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>',
    # Copy, cut and duplicate sat next to each other in the rail drawn as the
    # same two overlapping squares, so there was no telling them apart: one
    # sheet over another for copy, scissors for cut, a plate with a plus for
    # duplicate.
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 9V6.5A2.5 2.5 0 0 0 12.5 4h-6A2.5 2.5 0 0 0 4 6.5v6A2.5 2.5 0 0 0 6.5 15H9"/><path d="M12 13.5h5M12 16.5h3.5"/>',
    "cut": '<circle cx="6.5" cy="17.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/><path d="M8.3 15.7 18 4"/><path d="M15.7 15.7 6 4"/>',
    "duplicate": '<rect x="3.5" y="6.5" width="11" height="11" rx="2"/><path d="M19 5v7M15.5 8.5h7"/>',
    "clear": '<path d="M4 4 20 20M20 4 4 20"/>',
    "zoom_in": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/><path d="M10.5 7.5v6M7.5 10.5h6"/>',
    "zoom_out": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/><path d="M7.5 10.5h6"/>',
    "zoom_fit": '<path d="M4 9V5.5A1.5 1.5 0 0 1 5.5 4H9"/><path d="M15 4h3.5A1.5 1.5 0 0 1 20 5.5V9"/><path d="M20 15v3.5a1.5 1.5 0 0 1-1.5 1.5H15"/><path d="M9 20H5.5A1.5 1.5 0 0 1 4 18.5V15"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/>',
    "help": '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.4a2.5 2.5 0 0 1 4.9.6c0 1.7-2.5 2.1-2.5 3.7"/><circle cx="12" cy="17" r="0.9" fill="currentColor" stroke="none"/>',
    "comment": '<path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-5 4Z"/>',
    "list": '<path d="M4 7h16M4 12h16M4 17h10"/>',
    "next": '<path d="M9 5.5 15.5 12 9 18.5"/>',
    "prev": '<path d="M15 5.5 8.5 12 15 18.5"/>',
    "check": '<path d="M4.5 12.5 9.5 17.5 19.5 6.5"/>',
    "cross": '<path d="M6 6l12 12M18 6 6 18"/>',
    "no_roi": '<circle cx="12" cy="12" r="8.5"/><path d="M6.5 17.5 17.5 6.5"/>',
    "export": '<path d="M12 15V4"/><path d="M8 8l4-4 4 4"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    "import": '<path d="M12 4v11"/><path d="M8 11l4 4 4-4"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    "report": '<rect x="4.5" y="3.5" width="15" height="17" rx="2"/><path d="M8 9h8M8 13h8M8 17h5"/>',
    "review": '<rect x="3" y="5" width="8" height="14" rx="1.5"/><rect x="13" y="5" width="8" height="14" rx="1.5"/>',
    "lock": '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "unlock": '<rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 7.3-2.2"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>',
    "eye_off": '<path d="M4 4l16 16"/><path d="M9.5 9.6A3 3 0 0 0 12 15a3 3 0 0 0 2.4-1.2"/><path d="M6.6 6.8C4 8.5 2.5 12 2.5 12S6 18.5 12 18.5c1.6 0 3-.4 4.2-1M17.6 15.2c2.4-1.7 3.9-3.2 3.9-3.2S18 5.5 12 5.5c-.7 0-1.3.1-2 .2"/>',
    "rotate": '<path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 4v4.5h-4.5"/>',
    "align_left": '<path d="M4 3v18"/><rect x="7" y="6" width="11" height="4" rx="1"/><rect x="7" y="14" width="7" height="4" rx="1"/>',
    "align_top": '<path d="M3 4h18"/><rect x="6" y="7" width="4" height="11" rx="1"/><rect x="14" y="7" width="4" height="7" rx="1"/>',
    "distribute": '<path d="M3 3v18M21 3v18"/><rect x="8" y="9" width="8" height="6" rx="1"/>',
    "grid": '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/>',
    "sun": '<circle cx="12" cy="12" r="4.5"/><path d="M12 2.5v2M12 19.5v2M21.5 12h-2M4.5 12h-2M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4M18.7 18.7l-1.4-1.4M6.7 6.7 5.3 5.3"/>',
    "moon": '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 9.5h.01M9.5 9.5h.01M13 9.5h.01M16.5 9.5h.01M6 13h.01M9.5 13h4.5M17.5 13h.01"/>',
    "command": '<path d="M9 3a3 3 0 1 0 0 6h6a3 3 0 1 0 0-6 3 3 0 0 0-3 3v12a3 3 0 1 1-3-3h6a3 3 0 1 1 3 3"/>',
    "history": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3.5 4v4.5H8"/><path d="M12 8v4.5l3 1.8"/>',
    "warning": '<path d="M12 4 21 19.5H3Z"/><path d="M12 10v4"/><circle cx="12" cy="17" r="0.9" fill="currentColor" stroke="none"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><circle cx="12" cy="8" r="0.9" fill="currentColor" stroke="none"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "refresh": '<path d="M20.5 11A8.5 8.5 0 0 0 6 6.5L3.5 9"/><path d="M3.5 13A8.5 8.5 0 0 0 18 17.5L20.5 15"/><path d="M3.5 4.5V9H8M20.5 19.5V15H16"/>',
    # ── added for the suite shell and LabelImg Master ───────
    "film": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10 9.5 15 12l-5 2.5Z"/>',
    "frames": '<rect x="3" y="8" width="13" height="11" rx="1.5"/><path d="M7.5 4.5h12A1.5 1.5 0 0 1 21 6v10"/><path d="M8 13.5 10.5 16l3.5-4"/>',
    "scissors": '<circle cx="6.5" cy="17.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/><path d="M8.3 15.6 18 4M15.7 15.6 6 4"/>',
    "merge": '<path d="M6 4v5a4 4 0 0 0 4 4h4a4 4 0 0 1 4 4v3M18 4v5a4 4 0 0 1-4 4"/><path d="M15 17.5l3 3 3-3"/>',
    "convert": '<path d="M4.5 10A7.5 7.5 0 0 1 17.5 6"/><path d="M18 2.5V6h-3.5"/><path d="M19.5 14A7.5 7.5 0 0 1 6.5 18"/><path d="M6 21.5V18h3.5"/>',
    "sort": '<rect x="3" y="14" width="5" height="6" rx="1"/><rect x="9.5" y="14" width="5" height="6" rx="1"/><rect x="16" y="14" width="5" height="6" rx="1"/><path d="M12 3v7M9 7l3 3 3-3"/>',
    "home": '<path d="M3.5 11 12 4l8.5 7"/><path d="M5.5 9.5V20h13V9.5"/><path d="M10 20v-5.5h4V20"/>',
    "tag": '<path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7l8.3 8.3a1.5 1.5 0 0 1 0 2.1l-6.2 6.2a1.5 1.5 0 0 1-2.1 0Z"/><circle cx="8" cy="8" r="1.4"/>',
    "box": '<rect x="4" y="8" width="16" height="12" rx="1.5"/><path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4h6A1.5 1.5 0 0 1 13 5.5V8"/>',
    "image": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="M20.5 16 15 10.5 6 19.5"/>',
    "brightness": '<circle cx="12" cy="12" r="4.5"/><path d="M12 7.5v9"/><path d="M12 2.5v2M12 19.5v2M21.5 12h-2M4.5 12h-2M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4M18.7 18.7l-1.4-1.4M6.7 6.7 5.3 5.3"/>',
    "flag": '<path d="M5.5 21V4"/><path d="M5.5 4.5h11l-2.5 4 2.5 4h-11"/>',
    "verified": '<circle cx="12" cy="12" r="8.5"/><path d="M8 12.3l2.8 2.8L16.2 9.5"/>',
    "layers": '<path d="M12 3.5 21 8l-9 4.5L3 8Z"/><path d="M3 12.5l9 4.5 9-4.5"/><path d="M3 16.5l9 4.5 9-4.5"/>',
    "square": '<rect x="5" y="5" width="14" height="14" rx="1.5"/>',
    "obb": '<path d="M9.2 3.6 21 9.8 14.8 20.4 3 14.2Z"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="9" ry="5.5" transform="rotate(-30 12 12)"/>',
    "freehand": '<path d="M4 16c1.5-6 5-10 8-8s-3 7 1 8 5-6 7-9"/><circle cx="4" cy="16" r="1.2" fill="currentColor" stroke="none"/>',
    "shapes": '<path d="M3.5 10.5 8 3.5l4.5 7Z"/><circle cx="17" cy="7" r="3.5"/><path d="M5.3 14.4 12.3 13.2 13.5 20.2 6.5 21.4Z"/><ellipse cx="18" cy="17.5" rx="3" ry="4"/>',
    "arrow_right": '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
    "image_copy": '<rect x="7.5" y="7.5" width="13" height="12" rx="2"/><path d="M16.5 7.5V6a2 2 0 0 0-2-2h-9a2 2 0 0 0-2 2v8.5a2 2 0 0 0 2 2h2"/><path d="M20.5 16.5 16.5 12.5 10 19.5"/>',
    "magic": '<path d="M4 20 15 9"/><path d="M13.5 7.5 16.5 10.5"/><path d="M18 3v3M21.5 4.5 19 7M21 9.5h-3"/><path d="M6.5 3.5 7.5 6l2.5 1-2.5 1-1 2.5-1-2.5L3 7l2.5-1Z"/>',
    "paste": '<rect x="5" y="5" width="14" height="16" rx="2"/><path d="M9 5V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1Z"/><path d="M9 12h6M9 16h4"/>',
    "background": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M7 16.5 17 7.5"/>',
    # ── workspace folding ───────────────────────────────────
    "chevron_up": '<path d="M5.5 15 12 8.5 18.5 15"/>',
    "chevron_down": '<path d="M5.5 9 12 15.5 18.5 9"/>',
    "panel_open": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M14.5 4.5v15"/><path d="M10.5 9.5 8 12l2.5 2.5"/>',
    "panel_close": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M14.5 4.5v15"/><path d="M8 9.5 10.5 12 8 14.5"/>',
    "dataset": '<path d="M4 7.5 12 3.5l8 4-8 4Z"/><path d="M4 12l8 4 8-4"/><path d="M4 16.5l8 4 8-4"/>',
    "display": '<rect x="3" y="4.5" width="18" height="12" rx="2"/><path d="M9 20.5h6M12 16.5v4"/>',
    "folder_zip": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="M13 9v2M13 13v2M11 11v2M11 15v2"/>',
    "split": '<rect x="3.5" y="4.5" width="7" height="15" rx="1.5"/><rect x="13.5" y="4.5" width="7" height="15" rx="1.5"/>',
    "rename": '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16Z"/><path d="M13.5 6.5l4 4"/>',
    "pair": '<rect x="3" y="6" width="8" height="12" rx="1.5"/><path d="M14 8h7M14 12h7M14 16h5"/>',
    # a box inside viewfinder corners - "the model finds the objects"
    "scan": '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8'
            'M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/>'
            '<rect x="8" y="8.5" width="8" height="7" rx="1"/>',
    # a picture with a cross - "take this image out", unlike the trash can for shapes
    "image_remove": '<path d="M13 19.5H5.5a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2V12"/>'
                    '<circle cx="9" cy="9.5" r="1.6"/><path d="M3.5 16.5 9 11.5l4 3.5"/>'
                    '<path d="M16 16l5 5M21 16l-5 5"/>',
}

_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'width="{size}" height="{size}" fill="none" stroke="{colour}" '
    'stroke-width="{weight}" stroke-linecap="round" stroke-linejoin="round" '
    'color="{colour}">{body}</svg>'
)

_CACHE = {}


def available():
    return sorted(_BODY)


def svg_text(name: str, colour: str = "#000000", size: int = 24,
             weight: float = 1.8) -> str:
    body = _BODY.get(name)
    if body is None:
        body = _BODY["info"]
    return _TEMPLATE.format(size=size, colour=colour, weight=weight, body=body)


def screen_ratio() -> float:
    """The sharpest device pixel ratio of any connected screen.

    Windows at 125 % or 150 % scaling has a ratio of 1.25 or 1.5; a picture
    drawn for 1.0 and stretched to that is what looks jagged."""
    try:
        app = QGuiApplication.instance()
        if app is None:
            return 1.0
        return max([float(s.devicePixelRatio()) for s in app.screens()] or [1.0])
    except Exception:
        return 1.0


def _render(svg: str, painter: QPainter, rect: QRectF) -> None:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter, rect)


def pixmap(name: str, colour: str, size: int = 20, weight: float = 1.8,
           ratio: float = 1.0) -> QPixmap:
    """The icon as a pixmap, drawn for the sharpest screen attached - never
    below the ratio asked for - so it is never stretched up."""
    scale = max(1.0, float(ratio or 1.0), screen_ratio())
    key = (name, colour, int(size), round(weight, 2), round(scale, 2))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    px = QPixmap(max(1, int(round(size * scale))), max(1, int(round(size * scale))))
    px.setDevicePixelRatio(scale)
    px.fill(Qt.GlobalColor.transparent)
    try:
        painter = QPainter(px)
        # The pixmap carries a device pixel ratio, so the painter already
        # works in logical units - the target rect is the logical size, not
        # the device size, or the glyph is drawn oversized and clipped.
        _render(svg_text(name, colour, size, weight), painter, QRectF(0, 0, size, size))
        painter.end()
    except Exception:
        pass
    _CACHE[key] = px
    return px


class SvgIconEngine(QIconEngine):
    """Draws the icon from its SVG at exactly the size and screen scale Qt
    asks for, every time - there is no pre-rendered bitmap to stretch, so it
    is sharp at 100 %, 125 %, 150 % or 300 %."""

    def __init__(self, name, normal, active=None, weight=1.8):
        super().__init__()
        self.name = name
        self.normal = normal
        self.active = active or normal
        self.weight = weight

    def _colour(self, state) -> str:
        return self.active if state == QIcon.State.On else self.normal

    def paint(self, painter, rect, mode, state):
        painter.save()
        try:
            if mode == QIcon.Mode.Disabled:
                painter.setOpacity(0.4)
            side = min(rect.width(), rect.height())
            target = QRectF(rect.x() + (rect.width() - side) / 2.0,
                            rect.y() + (rect.height() - side) / 2.0, side, side)
            _render(svg_text(self.name, self._colour(state), 24, self.weight), painter, target)
        except Exception:
            pass
        finally:
            painter.restore()

    def scaledPixmap(self, size, mode, state, scale):
        scale = max(1.0, float(scale or 1.0))
        px = QPixmap(max(1, int(round(size.width() * scale))),
                     max(1, int(round(size.height() * scale))))
        px.fill(Qt.GlobalColor.transparent)
        px.setDevicePixelRatio(scale)
        painter = QPainter(px)
        self.paint(painter, QRectF(0, 0, size.width(), size.height()).toRect(), mode, state)
        painter.end()
        return px

    def pixmap(self, size, mode, state):
        return self.scaledPixmap(size, mode, state, screen_ratio())

    def clone(self):
        return SvgIconEngine(self.name, self.normal, self.active, self.weight)


def icon(name: str, colour: str, size: int = 20, weight: float = 1.8,
         ratio: float = 2.0) -> QIcon:
    """A vector QIcon: sharp at any size and any display scaling.  `size` and
    `ratio` are kept for callers; the engine draws at whatever is asked."""
    return QIcon(SvgIconEngine(name, colour, None, weight))


def dual_icon(name: str, normal: str, active: str, size: int = 20,
              weight: float = 1.8) -> QIcon:
    """An icon that switches colour when its button is checked or pressed."""
    return QIcon(SvgIconEngine(name, normal, active, weight))


# ── application marks ─────────────────────────────────────────
# The tile is the same for every tool; only the mark inside it changes, so
# the suite and its tools read as one family in a taskbar.
_MARKS = {
    "polygon": (
        '<path d="M32 12 52 26 44.5 50 19.5 50 12 26Z" fill="none" '
        'stroke="{fg}" stroke-width="4" stroke-linejoin="round"/>'
        '<circle cx="32" cy="12" r="4.5" fill="{fg}"/>'
        '<circle cx="52" cy="26" r="4.5" fill="{fg}"/>'
        '<circle cx="44.5" cy="50" r="4.5" fill="{fg}"/>'
        '<circle cx="19.5" cy="50" r="4.5" fill="{fg}"/>'
        '<circle cx="12" cy="26" r="4.5" fill="{fg}"/>'),
    "box": (
        '<rect x="13" y="22" width="38" height="29" rx="3" fill="none" '
        'stroke="{fg}" stroke-width="4"/>'
        '<path d="M13 22v-6a3 3 0 0 1 3-3h15a3 3 0 0 1 3 3v6" fill="{fg}"/>'
        '<circle cx="13" cy="51" r="4" fill="{fg}"/>'
        '<circle cx="51" cy="22" r="4" fill="{fg}"/>'),
    "suite": (
        '<rect x="12" y="12" width="17" height="17" rx="4.5" fill="{fg}"/>'
        '<rect x="35" y="12" width="17" height="17" rx="4.5" fill="none" '
        'stroke="{fg}" stroke-width="4"/>'
        '<rect x="12" y="35" width="17" height="17" rx="4.5" fill="none" '
        'stroke="{fg}" stroke-width="4"/>'
        '<rect x="35" y="35" width="17" height="17" rx="4.5" fill="none" '
        'stroke="{fg}" stroke-width="4"/>'),
}


def app_icon(accent: str = "#df5e3b", background: str = "#14171d",
             mark: str = "polygon") -> QIcon:
    """The window and taskbar icon: a tool's mark on a rounded tile."""
    body = _MARKS.get(mark)
    if body is None:
        # Any 24-grid icon can be a mark: scale it onto the tile.
        body = ('<g transform="translate(12 12) scale(1.6667)" fill="none" stroke="{fg}" '
                'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
                + _BODY.get(mark, _BODY["info"]).replace("{", "{{").replace("}", "}}") + '</g>')
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
               'width="{s}" height="{s}">'
               '<rect width="64" height="64" rx="14" fill="{bg}"/>'
               + body + '</svg>').format(s=size, bg=background, fg=accent)
        px = QPixmap(size, size)
        px.fill(Qt.GlobalColor.transparent)
        try:
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            painter = QPainter(px)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            renderer.render(painter, QRectF(0, 0, size, size))
            painter.end()
        except Exception:
            continue
        result.addPixmap(px)
    return result


def mark_pixmap(mark: str, accent: str, background: str,
                size: int = 48) -> QPixmap:
    """The app tile as a pixmap, for the dashboard cards - drawn for the
    screen's real scale rather than picked from the fixed icon sizes."""
    body = _MARKS.get(mark)
    if body is None:
        body = ('<g transform="translate(12 12) scale(1.6667)" fill="none" stroke="{fg}" '
                'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
                + _BODY.get(mark, _BODY["info"]).replace("{", "{{").replace("}", "}}") + '</g>')
    scale = max(1.0, screen_ratio())
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
           '<rect width="64" height="64" rx="14" fill="{bg}"/>' + body + '</svg>').format(
        bg=background, fg=accent)
    px = QPixmap(max(1, int(round(size * scale))), max(1, int(round(size * scale))))
    px.setDevicePixelRatio(scale)
    px.fill(Qt.GlobalColor.transparent)
    try:
        painter = QPainter(px)
        _render(svg, painter, QRectF(0, 0, size, size))
        painter.end()
    except Exception:
        pass
    return px


def clear_cache() -> None:
    _CACHE.clear()
