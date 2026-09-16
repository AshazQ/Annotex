"""The application stylesheet, built only from named values.

Colours come from the theme (annotex.ui.palette), sizes from the design
system (annotex.ui.design).  TEMPLATE contains no raw pixel numbers - every
size is a %(name)s - and tests/workspace/test_design.py keeps it that way.

The look is quiet on purpose: surfaces separated by hairlines rather than
heavy borders, one control height, one accent colour for what is chosen or
about to happen, and sentence case throughout.
"""

from __future__ import annotations

from . import design

TEMPLATE = """
* { outline: %(zero)s; }
QWidget { color: %(text)s; font-size: %(type_body)s; }
QMainWindow, QDialog { background: %(appBg)s; }
QToolTip {
    background: %(tooltipBg)s; color: %(tooltipFg)s; border: %(zero)s;
    padding: %(space_xs)s %(space_s)s; border-radius: %(radius_s)s; font-size: %(type_footnote)s;
}

/* ── surfaces ───────────────────────────────────────────── */
QFrame#Card, QFrame#Panel {
    background: %(surface)s; border: %(hairline)s solid %(border)s; border-radius: %(radius_l)s;
}
QFrame#Toolbar {
    background: %(surface)s; border: %(hairline)s solid %(border)s; border-radius: %(radius_m)s;
}
QFrame#Rail {
    background: %(surface)s; border: %(hairline)s solid %(border)s; border-radius: %(round_rail)s;
}
QScrollArea#RailScroll, QWidget#RailBody, QWidget#DialogBody { background: transparent; border: %(zero)s; }
QFrame#RailSep, QFrame#Divider { background: %(border)s; border: %(zero)s; max-height: %(hairline)s; }
QFrame#VDivider { background: %(border)s; border: %(zero)s; max-width: %(hairline)s; }
/* Square and round: the rail's buttons keep their size, so hover and the
   chosen tool are circles.  The plain #Tool rule below lets min-height fall
   to zero for the smaller buttons elsewhere, which would squash these. */
QFrame#Rail QPushButton#Tool {
    border: %(hairline)s solid transparent; border-radius: %(round_rail_button)s; padding: %(zero)s;
    min-width: %(rail_button)s; min-height: %(rail_button)s;
}
QPushButton#NavRound {
    background: %(surface)s; border: %(hairline)s solid %(borderStrong)s;
    border-radius: %(round_nav)s; padding: %(zero)s; min-height: %(zero)s;
}
QPushButton#NavRound:hover { background: %(accent)s; border-color: %(accent)s; }
QPushButton#NavRound:pressed { background: %(accentPressed)s; }

/* ── text ───────────────────────────────────────────────── */
QLabel#Large, QLabel#Greeting, QLabel#Hero {
    font-size: %(type_large)s; font-weight: %(weight_large)s; color: %(title)s;
}
QLabel#Title { font-size: %(type_title)s; font-weight: %(weight_title)s; color: %(title)s; }
QLabel#Headline, QLabel#CardTitle, QLabel#TileTitle, QLabel#SuiteName {
    font-size: %(type_headline)s; font-weight: %(weight_headline)s; color: %(title)s;
}
QLabel#Subtitle { font-size: %(type_footnote)s; color: %(sub)s; }
QLabel#SectionHeader {
    font-size: %(type_caption)s; font-weight: %(weight_emphasis)s; color: %(muted)s;
}
QLabel#StatValue { font-size: %(type_headline)s; font-weight: %(weight_headline)s; color: %(title)s; }
QLabel#StatLabel { font-size: %(type_caption)s; color: %(sub)s; }
QLabel#Hint { font-size: %(type_footnote)s; color: %(sub)s; }
QLabel#HintGood { font-size: %(type_footnote)s; color: %(good)s; }
QLabel#HintWarn { font-size: %(type_footnote)s; color: %(warn)s; }
QLabel#HintDanger { font-size: %(type_footnote)s; font-weight: %(weight_emphasis)s; color: %(danger)s; }
QLabel#Mono {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace;
    font-size: %(type_mono)s; color: %(sub)s;
}
QLabel#Chip, QLabel#ToolChip {
    background: %(surfaceAlt)s; border: %(hairline)s solid %(border)s; border-radius: %(radius_m)s;
    padding: %(space_xxs)s %(space_s)s; font-size: %(type_caption)s; color: %(sub)s;
}
QLabel#Kbd {
    background: %(surfaceAlt)s; border: %(hairline)s solid %(border)s; border-radius: %(radius_xs)s;
    padding: %(zero)s %(space_xs)s; font-size: %(type_caption)s; color: %(sub)s;
}

/* ── buttons ────────────────────────────────────────────── */
QPushButton {
    background: %(surfaceAlt)s; color: %(text)s;
    border: %(hairline)s solid %(border)s; border-radius: %(radius_s)s;
    min-height: %(control_inner)s; padding: %(zero)s %(space_m)s; font-size: %(type_body)s;
}
QPushButton:hover { background: %(surfaceHover)s; border-color: %(borderStrong)s; }
QPushButton:pressed { background: %(border)s; }
QPushButton:disabled { color: %(muted)s; background: %(surface)s; border-color: %(border)s; }
QPushButton:checked { background: %(accent)s; color: %(onAccent)s; border-color: %(accent)s; }
QPushButton#Primary {
    background: %(accent)s; color: %(onAccent)s; border-color: %(accent)s;
    font-weight: %(weight_emphasis)s; padding: %(zero)s %(space_l)s;
}
QPushButton#Primary:hover { background: %(accentHover)s; border-color: %(accentHover)s; }
QPushButton#Primary:pressed { background: %(accentPressed)s; border-color: %(accentPressed)s; }
QPushButton#Primary:disabled { background: %(surfaceAlt)s; color: %(muted)s; border-color: %(border)s; }
QPushButton#DangerFilled {
    background: %(danger)s; color: %(onDanger)s; border-color: %(danger)s; font-weight: %(weight_emphasis)s;
}
QPushButton#DangerFilled:hover { background: %(dangerHover)s; border-color: %(dangerHover)s; }
QLabel#MessageText { color: %(text)s; }
QPushButton#Danger { color: %(danger)s; }
QPushButton#Danger:hover { background: %(dangerSoft)s; border-color: %(danger)s; }
QPushButton#Quiet { background: transparent; border-color: transparent; }
QPushButton#Quiet:hover { background: %(surfaceHover)s; border-color: %(border)s; }
QPushButton#Tool {
    background: transparent; border: %(hairline)s solid transparent; border-radius: %(radius_s)s;
    padding: %(zero)s; min-height: %(zero)s;
}
QPushButton#Tool:hover { background: %(surfaceHover)s; }
QPushButton#Tool:checked { background: %(accent)s; border-color: %(accent)s; }
QPushButton#Link {
    background: transparent; border: %(zero)s; color: %(sub)s;
    padding: %(space_xxs)s %(space_xs)s; min-height: %(zero)s; text-align: left;
}
QPushButton#Link:hover { color: %(accent)s; }
QToolButton {
    background: transparent; border: %(hairline)s solid transparent;
    border-radius: %(radius_s)s; padding: %(space_xs)s;
}
QToolButton:hover { background: %(surfaceHover)s; }
QToolButton:checked { background: %(accent)s; }

/* ── fields ─────────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {
    background: %(input)s; border: %(hairline)s solid %(inputBorder)s; border-radius: %(radius_s)s;
    min-height: %(control_inner)s; padding: %(zero)s %(space_s)s; color: %(text)s;
    selection-background-color: %(accent)s; selection-color: %(onAccent)s;
}
QPlainTextEdit, QTextEdit {
    background: %(input)s; border: %(hairline)s solid %(inputBorder)s; border-radius: %(radius_s)s;
    padding: %(space_xs)s %(space_s)s; color: %(text)s;
    selection-background-color: %(accent)s; selection-color: %(onAccent)s;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus { border-color: %(accent)s; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: %(muted)s; background: %(surfaceAlt)s;
}
QComboBox::drop-down { border: %(zero)s; width: %(space_xl)s; }
QComboBox QAbstractItemView {
    background: %(surface)s; border: %(hairline)s solid %(border)s; border-radius: %(radius_m)s;
    padding: %(space_xs)s; selection-background-color: %(accent)s; selection-color: %(onAccent)s;
}
QCheckBox, QRadioButton { spacing: %(space_s)s; }
QCheckBox::indicator, QRadioButton::indicator { width: %(icon_s)s; height: %(icon_s)s; }
QCheckBox::indicator {
    border: %(hairline)s solid %(inputBorder)s; border-radius: %(radius_xs)s; background: %(input)s;
}
QCheckBox::indicator:checked {
    background: %(accent)s; border-color: %(accent)s; image: url("%(checkIcon)s");
}
QRadioButton::indicator {
    border: %(hairline)s solid %(inputBorder)s; border-radius: %(round_indicator)s; background: %(input)s;
}
QRadioButton::indicator:checked {
    background: %(accent)s; border-color: %(accent)s; image: url("%(radioIcon)s");
}
QSlider::groove:horizontal {
    height: %(slider_groove)s; background: %(border)s; border-radius: %(space_xxs)s;
}
QSlider::handle:horizontal {
    background: %(accent)s; width: %(slider_handle)s; height: %(slider_handle)s;
    margin: %(slider_overhang)s %(zero)s; border-radius: %(round_indicator)s;
}
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: %(space_xxs)s; }

/* ── lists and tables: grouped, with hairline separators ── */
QListWidget, QTreeWidget, QTableWidget, QListView, QTreeView, QTableView {
    background: %(surface)s; border: %(hairline)s solid %(border)s; border-radius: %(radius_m)s;
    padding: %(space_xs)s; alternate-background-color: %(surfaceAlt)s;
}
QListWidget::item, QTreeWidget::item {
    padding: %(space_s)s %(space_m)s; border-radius: %(radius_s)s; color: %(text)s;
}
QListWidget::item:hover, QTreeWidget::item:hover { background: %(surfaceHover)s; }
QListWidget::item:selected, QTreeWidget::item:selected { background: %(accent)s; color: %(onAccent)s; }
QListView::indicator { width: %(icon_s)s; height: %(icon_s)s; }
QListView::indicator:unchecked {
    border: %(hairline)s solid %(inputBorder)s; border-radius: %(radius_xs)s; background: %(input)s;
}
QListView::indicator:checked {
    background: %(accent)s; border: %(hairline)s solid %(accent)s; border-radius: %(radius_xs)s;
    image: url("%(checkIcon)s");
}
QHeaderView::section {
    background: %(surfaceAlt)s; color: %(muted)s; border: %(zero)s;
    border-bottom: %(hairline)s solid %(border)s; padding: %(space_s)s;
    font-size: %(type_caption)s; font-weight: %(weight_emphasis)s;
}

/* ── scrollbars: thin, out of the way ───────────────────── */
QScrollBar:vertical { background: transparent; width: %(scrollbar)s; margin: %(space_xxs)s; }
QScrollBar:horizontal { background: transparent; height: %(scrollbar)s; margin: %(space_xxs)s; }
QScrollBar::handle:vertical {
    background: %(scrollbar)s; border-radius: %(radius_xs)s; min-height: %(scrollbar_handle)s;
}
QScrollBar::handle:horizontal {
    background: %(scrollbar)s; border-radius: %(radius_xs)s; min-width: %(scrollbar_handle)s;
}
QScrollBar::handle:hover { background: %(borderStrong)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: %(zero)s; width: %(zero)s; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ── menus ──────────────────────────────────────────────── */
QMenuBar { background: transparent; }
QMenuBar::item { padding: %(space_xs)s %(space_s)s; border-radius: %(radius_s)s; }
QMenuBar::item:selected { background: %(surfaceHover)s; }
QMenu {
    background: %(surface)s; border: %(hairline)s solid %(border)s;
    border-radius: %(radius_m)s; padding: %(space_xs)s;
}
QMenu::item { padding: %(space_xs)s %(space_xl)s %(space_xs)s %(space_m)s; border-radius: %(radius_s)s; }
QMenu::item:selected { background: %(accent)s; color: %(onAccent)s; }
QMenu::separator { height: %(hairline)s; background: %(border)s; margin: %(space_xs)s %(space_s)s; }

/* ── progress, splitters, status, groups, tabs ──────────── */
QProgressBar {
    background: %(surfaceAlt)s; border: %(zero)s; border-radius: %(radius_xs)s;
    height: %(progress)s; text-align: center; color: transparent;
}
QProgressBar::chunk { background: %(accent)s; border-radius: %(radius_xs)s; }
QSplitter::handle { background: transparent; }
QSplitter::handle:hover { background: %(border)s; }
QStatusBar { background: transparent; color: %(sub)s; font-size: %(type_footnote)s; }
QStatusBar::item { border: %(zero)s; }
QGroupBox {
    border: %(hairline)s solid %(border)s; border-radius: %(radius_m)s;
    margin-top: %(space_xl)s; padding: %(space_m)s;
}
QGroupBox::title {
    subcontrol-origin: margin; left: %(space_m)s; padding: %(zero)s %(space_xs)s;
    color: %(muted)s; font-size: %(type_caption)s; font-weight: %(weight_emphasis)s;
}
QTabWidget::pane {
    border: %(hairline)s solid %(border)s; border-radius: %(radius_m)s; top: -%(hairline)s;
}
QTabBar::tab {
    background: transparent; padding: %(space_s)s %(space_l)s; border-radius: %(radius_s)s;
    color: %(sub)s; margin-right: %(space_xxs)s;
}
QTabBar::tab:selected { background: %(surfaceAlt)s; color: %(title)s; }
QTabBar::tab:hover:!selected { background: %(surfaceHover)s; }

/* ── the suite shell ────────────────────────────────────── */
QFrame#SuiteBar {
    background: %(surface)s; border: %(hairline)s solid %(border)s; border-radius: %(radius_l)s;
}
QPushButton#SuiteTab {
    background: transparent; border: %(hairline)s solid transparent; border-radius: %(radius_s)s;
    padding: %(zero)s %(space_m)s; color: %(sub)s;
}
QPushButton#SuiteTab:hover { background: %(surfaceHover)s; color: %(text)s; }
QPushButton#SuiteTab:checked { background: %(accentSoft)s; color: %(title)s; border-color: transparent; }
QWidget#SuiteTabHolder { background: transparent; }
QPushButton#SuiteTabClose {
    background: transparent; border: %(hairline)s solid transparent; border-radius: %(radius_s)s;
    padding: %(zero)s; min-height: %(zero)s; min-width: %(space_xl)s;
}
QPushButton#SuiteTabClose:hover { background: %(dangerSoft)s; border-color: %(danger)s; }
/* The arrows either side of the tab strip: a tab's side padding would leave
   a chevron this narrow no room at all, so they carry none. */
QPushButton#SuiteTabScroll {
    background: transparent; border: %(hairline)s solid transparent;
    border-radius: %(radius_s)s; padding: %(zero)s; min-width: %(space_l)s;
    color: %(sub)s; font-size: %(type_headline)s;
}
QPushButton#SuiteTabScroll:hover { background: %(surfaceHover)s; color: %(text)s; }
QPushButton#SuiteTabScroll:disabled { color: %(border)s; }
QScrollArea#SuiteTabStrip { background: transparent; border: %(zero)s; }
QFrame#ToolCard, QFrame#FeatureCard, QFrame#TileCard, QFrame#ContinueCard {
    background: %(surface)s; border: %(hairline)s solid %(border)s; border-radius: %(radius_l)s;
}
QFrame#ToolCard:hover { border-color: %(borderStrong)s; }

/* ── toasts ─────────────────────────────────────────────── */
QFrame#Toast {
    background: %(tooltipBg)s; border: %(hairline)s solid %(borderStrong)s; border-radius: %(radius_m)s;
}
QLabel#ToastText { color: %(tooltipFg)s; font-size: %(type_body)s; }
QFrame#ToastMark { border: %(zero)s; border-radius: %(radius_xs)s; background: %(good)s; }
QFrame#ToastMark[tone="info"] { background: %(info)s; }
QFrame#ToastMark[tone="warn"] { background: %(warn)s; }
QFrame#ToastMark[tone="danger"] { background: %(danger)s; }
QPushButton#ToastAction {
    background: transparent; border: %(zero)s; color: %(accent)s; font-weight: %(weight_emphasis)s;
    padding: %(zero)s %(space_xs)s; min-height: %(zero)s;
}
QPushButton#ToastAction:hover { color: %(accentHover)s; }

/* ── tones: a label that says how things stand ──────────── */
QLabel[tone="good"] { color: %(good)s; }
QLabel[tone="warn"] { color: %(warn)s; }
QLabel[tone="danger"] { color: %(danger)s; }
QLabel[tone="accent"] { color: %(accent)s; }
QLabel[tone="info"] { color: %(info)s; }
QLabel[tone="sub"] { color: %(sub)s; }
QLabel[tone="muted"] { color: %(muted)s; }
QLabel[tone="text"] { color: %(text)s; }
QLabel[tone="title"] { color: %(title)s; }
"""

# Rules repeated for every tool, in that tool's own hue: its tab in the
# suite bar, and its card on Home.  A widget opts in with the "tool" property.
TOOL_TEMPLATE = """
QPushButton#SuiteTab[tool="%(tool)s"]:checked { background: %(accentSoft)s; color: %(title)s; }
QFrame[tool="%(tool)s"]:hover { border-color: %(accent)s; }
QFrame[tool="%(tool)s"] QPushButton#Primary {
    background: %(accent)s; border-color: %(accent)s; color: %(onAccent)s;
}
QFrame[tool="%(tool)s"] QPushButton#Primary:hover { background: %(accentHover)s; border-color: %(accentHover)s; }
QFrame[tool="%(tool)s"] QPushButton#Link:hover { color: %(accent)s; }
QFrame[tool="%(tool)s"] QLabel#ToolChip {
    background: %(accentSoft)s; color: %(accent)s; border-color: transparent;
    font-weight: %(weight_badge)s;
}
QFrame#ContinueCard[tool="%(tool)s"] { border-left: %(accent_bar)s solid %(accent)s; }
"""


def build(theme: dict) -> str:
    """The stylesheet for a theme."""
    from .palette import TOOL_HUES, _icon_url, with_tool
    sizes = design.stylesheet_values()
    values = dict(theme)
    values.update(sizes)
    values["checkIcon"] = _icon_url("check.svg")
    values["radioIcon"] = _icon_url("radio.svg")
    parts = [TEMPLATE % values]
    for tool in TOOL_HUES:
        tool_values = dict(with_tool(theme, tool))
        tool_values.update(sizes)
        tool_values["tool"] = tool
        parts.append(TOOL_TEMPLATE % tool_values)
    return "".join(parts)


TONES = ("good", "warn", "danger", "accent", "info", "sub", "muted", "text", "title")


def _repolish(widget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_tone(label, tone) -> None:
    """Colour a label by how things stand: good, warn, danger, accent, info,
    sub, muted, text or title - always the theme's colour, never a hex."""
    if label.property("tone") != tone:
        label.setProperty("tone", tone)
        _repolish(label)


def set_tool(widget, tool) -> None:
    """Draw a tab or card in a tool's own hue (see TOOL_TEMPLATE)."""
    if widget.property("tool") != tool:
        widget.setProperty("tool", tool)
        # The rules reach the widget's children (its buttons and chips), and
        # Qt only re-reads a child's rules when the child itself is polished.
        from PySide6.QtWidgets import QWidget
        for child in [widget] + widget.findChildren(QWidget):
            _repolish(child)


def swatch(widget, colour, text_colour, selector="QLabel") -> None:
    """A chip or button filled with a colour that is data, not theme - a
    class colour, a picked colour - still with the design system's corner,
    padding and weight."""
    sizes = design.stylesheet_values()
    widget.setStyleSheet(
        "%s { background: %s; color: %s; border: %s solid rgba(128, 128, 128, 0.45); "
        "border-radius: %s; padding: %s %s; font-weight: %s; }"
        % (selector, colour, text_colour, sizes["hairline"], sizes["radius_s"], sizes["space_xxs"],
           sizes["space_s"], sizes["weight_badge"]))


def clear_swatch(widget) -> None:
    widget.setStyleSheet("")
