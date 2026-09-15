"""The design system: every size in Annotex, named once.

Text, spacing, corners, control heights, icon sizes and motion all come from
here - the stylesheet (annotex.ui.style), the building blocks and every
screen - so a gap, a corner or a font is never decided one screen at a time.
Colours live in the theme (annotex.ui.palette); sizes live here.

Sizes are logical pixels at 100 % interface size; the Interface size setting
scales them all together.

    from annotex.ui import design
    design.margins(layout, "l")            16 on every side
    design.margins(layout, "s", "m")       8 above and below, 12 either side
    layout.setSpacing(design.SPACE["s"])
    label.setFont(design.font("headline"))

tests/workspace/test_design.py holds the rest of the code to these values.
"""

from __future__ import annotations

# ── type ──────────────────────────────────────────────────────
# (size in px, weight: 400 regular, 600 semibold, 700 bold)
TYPE = {
    "caption": (11, 400),       # keys, badges, table headers, stat labels
    "footnote": (12, 400),      # hints, subtitles, the status line, tooltips
    "body": (13, 400),          # everything, by default
    "badge": (11, 600),         # key badges, list group headers
    "label": (12, 600),         # names drawn on the image, thumbnail tiles
    "emphasis": (13, 600),      # the button that commits, chosen items
    "headline": (15, 600),      # card, tile and section titles
    "title": (20, 600),         # page and dialog titles, stat values
    "large": (26, 700),         # the Home greeting
}
MONO_SIZE = 12

# ── spacing ───────────────────────────────────────────────────
SPACE = {"xxs": 2, "xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24, "xxl": 32}
SCALE = tuple(sorted({0} | set(SPACE.values())))

# ── corners ───────────────────────────────────────────────────
RADIUS = {
    "xs": 4,                    # check boxes, keys, progress bars
    "s": 6,                     # buttons, fields, menu items, tooltips
    "m": 10,                    # lists, menus, chips, the suite bar
    "l": 14,                    # cards, panels, sheets
}

# ── controls and icons ────────────────────────────────────────
HAIRLINE = 1
CONTROL_HEIGHT = 30             # every button, field and combo box
TOOL_BUTTON = 32                # square icon buttons
ICON = {"s": 16, "m": 20, "l": 24}
ICON_SIZES = tuple(sorted(ICON.values()))
RAIL_WIDTH = 50                 # the pill-shaped tool rail
RAIL_BUTTON = (36, 36)          # square, so its hover and chosen states are circles
NAV_BUTTON = 38                 # the round previous / next buttons over the image
SCROLLBAR = SPACE["s"]

# ── motion (milliseconds) ─────────────────────────────────────
MOTION = {"fast": 120, "normal": 180, "slow": 240}


def space(name) -> int:
    return SPACE[name]


def margins(layout, *names) -> None:
    """Set a layout's margins from spacing names, the way CSS reads them:
    one name for every side; two for vertical and horizontal; four for top,
    right, bottom, left.  "0" is allowed as a name."""
    values = [0 if name in (0, "0") else SPACE[name] for name in names] or [0]
    if len(values) == 1:
        top = right = bottom = left = values[0]
    elif len(values) == 2:
        top = bottom = values[0]
        right = left = values[1]
    elif len(values) == 4:
        top, right, bottom, left = values
    else:
        raise ValueError("margins takes one, two or four spacing names")
    layout.setContentsMargins(left, top, right, bottom)


def font(style="body", base=None):
    """A QFont in one of the TYPE styles (base: the font to start from)."""
    from PySide6.QtGui import QFont
    size, weight = TYPE[style]
    result = QFont(base) if base is not None else QFont()
    result.setPixelSize(size)
    result.setWeight(QFont.Weight(weight))
    return result


def mono_font(base=None):
    from PySide6.QtGui import QFont, QFontDatabase
    result = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont) if base is None else QFont(base)
    result.setPixelSize(MONO_SIZE)
    return result


def _px(value) -> str:
    return "%dpx" % value


def stylesheet_values() -> dict:
    """Every size the stylesheet may use, by name - it uses no others."""
    values = {"hairline": _px(HAIRLINE), "type_mono": _px(MONO_SIZE)}
    for name, (size, weight) in TYPE.items():
        values["type_%s" % name] = _px(size)
        values["weight_%s" % name] = str(weight)
    for name, value in SPACE.items():
        values["space_%s" % name] = _px(value)
    for name, value in RADIUS.items():
        values["radius_%s" % name] = _px(value)
    # A control's inner height: its full height less the two hairline borders.
    values["control_inner"] = _px(CONTROL_HEIGHT - 2 * HAIRLINE)
    values["tool_button"] = _px(TOOL_BUTTON)
    values["icon_s"] = _px(ICON["s"])
    values["icon_m"] = _px(ICON["m"])
    values["icon_l"] = _px(ICON["l"])
    # Fully round shapes: half their own size.
    values["round_indicator"] = _px(ICON["s"] // 2)
    values["round_rail"] = _px(RAIL_WIDTH // 2)
    # Qt sizes a styled control by its content box, so the two hairline
    # borders come off - the button itself then measures RAIL_BUTTON exactly.
    values["rail_button"] = _px(RAIL_BUTTON[1] - 2 * HAIRLINE)
    values["round_rail_button"] = _px(RAIL_BUTTON[1] // 2)
    values["round_nav"] = _px(NAV_BUTTON // 2)
    values["scrollbar"] = _px(SCROLLBAR)
    values["scrollbar_handle"] = _px(SPACE["xl"] + SPACE["xs"])
    # The slider handle is an icon-sized dot centred on a 4 px groove.
    values["slider_groove"] = _px(SPACE["xs"])
    values["slider_handle"] = _px(ICON["s"])
    values["slider_overhang"] = _px(-(ICON["s"] - SPACE["xs"]) // 2)
    values["progress"] = _px(SPACE["s"])
    values["accent_bar"] = _px(SPACE["xs"])
    values["zero"] = "0"
    return values
