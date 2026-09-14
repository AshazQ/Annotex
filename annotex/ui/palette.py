"""Theme tokens and the application stylesheet.

Two complete palettes plus a "system" mode that follows the desktop.  Every
colour the suite uses is named here, so a theme change is one dictionary swap
and never a hunt through widget code - and every tool looks like the same
product because they all read the same table.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

ACCENT = "#df5e3b"
ACCENT_HOVER = "#c9522f"
ACCENT_PRESSED = "#b0451f"

LIGHT = {
    "name": "light",
    "appBg": "#e9ecee",
    "surface": "#fafcfd",
    "surfaceAlt": "#f1f4f6",
    "surfaceHover": "#e8edf0",
    "border": "#ced5da",
    "borderStrong": "#b6bfc6",
    "title": "#232933",
    "text": "#39404b",
    "sub": "#6b727e",
    "muted": "#8b929c",
    "canvasBg": "#0b0d12",
    "canvasVoid": "#15181e",
    "input": "#ffffff",
    "inputBorder": "#c6ced4",
    "accent": ACCENT,
    "accentHover": ACCENT_HOVER,
    "accentPressed": ACCENT_PRESSED,
    "accentSoft": "#f7e3db",
    "onAccent": "#ffffff",
    "good": "#2f8f43",
    "goodSoft": "#e3f0e6",
    "warn": "#a8730f",
    "warnSoft": "#f8eeda",
    "danger": "#c53437",
    "dangerSoft": "#f9e0e1",
    "info": "#2a6fbd",
    "shadow": "rgba(15, 20, 30, 0.14)",
    "scrollbar": "#c8ced4",
    "tooltipBg": "#232933",
    "tooltipFg": "#fafcfd",
}

DARK = {
    "name": "dark",
    "appBg": "#14171d",
    "surface": "#1e222a",
    "surfaceAlt": "#252a33",
    "surfaceHover": "#2c323c",
    "border": "#333a45",
    "borderStrong": "#454d5a",
    "title": "#e9ecf1",
    "text": "#c8cdd6",
    "sub": "#8b93a1",
    "muted": "#6f7784",
    "canvasBg": "#07080b",
    "canvasVoid": "#101319",
    "input": "#171b22",
    "inputBorder": "#3a424e",
    "accent": ACCENT,
    "accentHover": ACCENT_HOVER,
    "accentPressed": ACCENT_PRESSED,
    "accentSoft": "#3a2620",
    "onAccent": "#ffffff",
    "good": "#5cbf6b",
    "goodSoft": "#1c2a20",
    "warn": "#d9a13f",
    "warnSoft": "#302719",
    "danger": "#e06a6c",
    "dangerSoft": "#331d1f",
    "info": "#5b9cea",
    "shadow": "rgba(0, 0, 0, 0.45)",
    "scrollbar": "#3a414c",
    "tooltipBg": "#0b0d12",
    "tooltipFg": "#e9ecf1",
}

# Canvas colours are deliberately separate from chrome: they sit on the dark
# image plane in both themes, so they do not follow the light palette.
CANVAS = {
    "shape": "#f0a33d",
    "shapeFill": "#f0a33d",
    "selected": ACCENT,
    "selectedFill": ACCENT,
    "drawing": "#ffd166",
    "vertex": "#ffffff",
    "vertexHot": "#38c6ff",
    "handle": "#ffffff",
    "guide": "#4a5568",
    "snap": "#38c6ff",
    "locked": "#8b93a1",
    "marquee": "#7fb2ff",
    "label": "#ffffff",
    "labelShadow": "#000000",
}


def theme_for(name: str) -> dict:
    return DARK if str(name).lower() == "dark" else LIGHT


def resolve_theme(setting: str, app=None) -> dict:
    """Turn the 'theme' setting into a concrete palette.

    'system' asks Qt what the desktop is using; when Qt cannot tell (older
    platform themes) the app falls back to dark, which is the better default
    for looking at photographs."""
    setting = str(setting or "dark").lower()
    if setting in ("light", "dark"):
        return theme_for(setting)
    try:
        if app is not None:
            scheme = app.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Light:
                return LIGHT
            if scheme == Qt.ColorScheme.Dark:
                return DARK
            window = app.palette().color(QPalette.ColorRole.Window)
            return LIGHT if window.lightness() > 127 else DARK
    except Exception:
        pass
    return DARK


def qcolor(value, alpha: int | None = None) -> QColor:
    colour = QColor(value)
    if not colour.isValid():
        colour = QColor("#ff00ff")
    if alpha is not None:
        colour.setAlpha(int(max(0, min(255, alpha))))
    return colour


def readable_on(value) -> str:
    """Black or white, whichever reads better on this background."""
    colour = qcolor(value)
    luminance = (0.299 * colour.red() + 0.587 * colour.green()
                 + 0.114 * colour.blue())
    return "#111111" if luminance > 150 else "#ffffff"


def apply_palette(app, t: dict) -> None:
    """Give Qt's own palette the same colours, so native dialogs, tooltips
    and the window frame match the app instead of fighting it."""
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, qcolor(t["appBg"]))
    pal.setColor(QPalette.ColorRole.WindowText, qcolor(t["text"]))
    pal.setColor(QPalette.ColorRole.Base, qcolor(t["input"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, qcolor(t["surfaceAlt"]))
    pal.setColor(QPalette.ColorRole.Text, qcolor(t["text"]))
    pal.setColor(QPalette.ColorRole.Button, qcolor(t["surface"]))
    pal.setColor(QPalette.ColorRole.ButtonText, qcolor(t["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, qcolor(t["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, qcolor(t["onAccent"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, qcolor(t["tooltipBg"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, qcolor(t["tooltipFg"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, qcolor(t["muted"]))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.Text, qcolor(t["muted"]))
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.ButtonText, qcolor(t["muted"]))
    app.setPalette(pal)


_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def _icon_url(name: str) -> str:
    """A file URL Qt's stylesheet parser accepts on every platform.

    Qt does not support data: URLs in stylesheets, so the two indicator
    glyphs ship as files and are referenced by absolute path with forward
    slashes."""
    return (_ICON_DIR / name).as_posix()


def stylesheet(t: dict) -> str:
    """One stylesheet for the whole suite."""
    values = dict(t)
    values["checkIcon"] = _icon_url("check.svg")
    values["radioIcon"] = _icon_url("radio.svg")
    return """
* { outline: 0; }
QWidget { color: %(text)s; font-size: 13px; }
QMainWindow, QDialog { background: %(appBg)s; }
QToolTip {
    background: %(tooltipBg)s; color: %(tooltipFg)s; border: 0;
    padding: 6px 9px; border-radius: 6px; font-size: 12px;
}

/* ── cards & panels ─────────────────────────────────── */
QFrame#Card, QFrame#Panel {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px;
}
QFrame#Toolbar {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px;
}
QFrame#Divider { background: %(border)s; max-height: 1px; border: 0; }
QFrame#VDivider { background: %(border)s; max-width: 1px; border: 0; }

QLabel#Title { font-size: 19px; font-weight: 600; color: %(title)s; }
QLabel#Subtitle { color: %(sub)s; font-size: 12px; }
QLabel#SectionHeader {
    color: %(muted)s; font-size: 11px; font-weight: 600;
    letter-spacing: 0.06em; text-transform: uppercase;
}
QLabel#StatValue { font-size: 22px; font-weight: 600; color: %(title)s; }
QLabel#StatLabel { color: %(sub)s; font-size: 11px; }
QLabel#Hint { color: %(sub)s; font-size: 12px; }
QLabel#HintGood { color: %(good)s; font-size: 12px; }
QLabel#HintWarn { color: %(warn)s; font-size: 12px; }
QLabel#HintDanger { color: %(danger)s; font-size: 12px; font-weight: 600; }
QLabel#Mono {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 11px; color: %(sub)s;
}

/* ── buttons ────────────────────────────────────────── */
QPushButton {
    background: %(surfaceAlt)s; color: %(text)s;
    border: 1px solid %(border)s; border-radius: 8px;
    padding: 7px 14px; font-size: 13px;
}
QPushButton:hover { background: %(surfaceHover)s; border-color: %(borderStrong)s; }
QPushButton:pressed { background: %(border)s; }
QPushButton:disabled { color: %(muted)s; background: %(surface)s; }
QPushButton:checked {
    background: %(accent)s; color: %(onAccent)s; border-color: %(accent)s;
}
QPushButton#Primary {
    background: %(accent)s; color: %(onAccent)s; border-color: %(accent)s;
    font-weight: 600; padding: 9px 20px;
}
QPushButton#Primary:hover { background: %(accentHover)s; border-color: %(accentHover)s; }
QPushButton#Primary:pressed { background: %(accentPressed)s; }
QPushButton#Primary:disabled {
    background: %(surfaceAlt)s; color: %(muted)s; border-color: %(border)s;
}
QPushButton#Danger { color: %(danger)s; }
QPushButton#Danger:hover { background: %(dangerSoft)s; border-color: %(danger)s; }
QPushButton#Quiet { background: transparent; border-color: transparent; }
QPushButton#Quiet:hover { background: %(surfaceHover)s; border-color: %(border)s; }
QPushButton#Tool {
    background: transparent; border: 1px solid transparent; border-radius: 9px;
    padding: 6px;
}
QPushButton#Tool:hover { background: %(surfaceHover)s; }
QPushButton#Tool:checked { background: %(accent)s; border-color: %(accent)s; }

QToolButton {
    background: transparent; border: 1px solid transparent;
    border-radius: 8px; padding: 5px;
}
QToolButton:hover { background: %(surfaceHover)s; }
QToolButton:checked { background: %(accent)s; }

/* ── inputs ─────────────────────────────────────────── */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: %(input)s; border: 1px solid %(inputBorder)s;
    border-radius: 8px; padding: 6px 9px; color: %(text)s;
    selection-background-color: %(accent)s; selection-color: %(onAccent)s;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: %(accent)s; }
QLineEdit:disabled, QComboBox:disabled { color: %(muted)s; background: %(surfaceAlt)s; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox QAbstractItemView {
    background: %(surface)s; border: 1px solid %(border)s;
    selection-background-color: %(accent)s; selection-color: %(onAccent)s;
    padding: 4px; border-radius: 8px;
}
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox::indicator {
    border: 1px solid %(inputBorder)s; border-radius: 4px; background: %(input)s;
}
QCheckBox::indicator:checked {
    background: %(accent)s; border-color: %(accent)s;
    image: url("%(checkIcon)s");
}
QRadioButton::indicator {
    border: 1px solid %(inputBorder)s; border-radius: 8px; background: %(input)s;
}
QRadioButton::indicator:checked {
    background: %(accent)s; border-color: %(accent)s;
    image: url("%(radioIcon)s");
}
QSlider::groove:horizontal {
    height: 4px; background: %(border)s; border-radius: 2px;
}
QSlider::handle:horizontal {
    background: %(accent)s; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 2px; }

/* ── lists & tables ─────────────────────────────────── */
QListWidget, QTreeWidget, QTableWidget {
    background: %(surface)s; border: 1px solid %(border)s;
    border-radius: 10px; padding: 4px;
    alternate-background-color: %(surfaceAlt)s;
}
QListWidget::item, QTreeWidget::item {
    padding: 6px 8px; border-radius: 6px; color: %(text)s;
}
QListWidget::item:hover, QTreeWidget::item:hover { background: %(surfaceHover)s; }
QListWidget::item:selected, QTreeWidget::item:selected {
    background: %(accent)s; color: %(onAccent)s;
}
QListView::indicator { width: 15px; height: 15px; }
QListView::indicator:unchecked {
    border: 1px solid %(inputBorder)s; border-radius: 4px; background: %(input)s;
}
QListView::indicator:checked {
    background: %(accent)s; border: 1px solid %(accent)s; border-radius: 4px;
    image: url("%(checkIcon)s");
}
QHeaderView::section {
    background: %(surfaceAlt)s; color: %(muted)s; border: 0;
    border-bottom: 1px solid %(border)s; padding: 6px 8px;
    font-size: 11px; font-weight: 600;
}

/* ── scrollbars ─────────────────────────────────────── */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: %(scrollbar)s; border-radius: 5px; min-height: 28px;
}
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: %(scrollbar)s; border-radius: 5px; min-width: 28px;
}
QScrollBar::handle:hover { background: %(borderStrong)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ── menus ──────────────────────────────────────────── */
QMenuBar { background: transparent; }
QMenuBar::item { padding: 6px 10px; border-radius: 6px; }
QMenuBar::item:selected { background: %(surfaceHover)s; }
QMenu {
    background: %(surface)s; border: 1px solid %(border)s;
    border-radius: 10px; padding: 6px;
}
QMenu::item { padding: 7px 26px 7px 12px; border-radius: 6px; }
QMenu::item:selected { background: %(accent)s; color: %(onAccent)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 5px 8px; }

/* ── misc ───────────────────────────────────────────── */
QProgressBar {
    background: %(surfaceAlt)s; border: 0; border-radius: 5px;
    height: 8px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: %(accent)s; border-radius: 5px; }
QSplitter::handle { background: transparent; }
QSplitter::handle:hover { background: %(border)s; }
QStatusBar { background: transparent; color: %(sub)s; }
QStatusBar::item { border: 0; }
QGroupBox {
    border: 1px solid %(border)s; border-radius: 10px;
    margin-top: 18px; padding: 12px;
}
QGroupBox::title {
    subcontrol-origin: margin; left: 12px; padding: 0 5px;
    color: %(muted)s; font-size: 11px; font-weight: 600;
}
QTabWidget::pane { border: 1px solid %(border)s; border-radius: 10px; top: -1px; }
QTabBar::tab {
    background: transparent; padding: 8px 16px; border-radius: 8px;
    color: %(sub)s; margin-right: 3px;
}
QTabBar::tab:selected { background: %(surfaceAlt)s; color: %(title)s; }
QTabBar::tab:hover:!selected { background: %(surfaceHover)s; }

/* ── suite shell ────────────────────────────────────── */
QFrame#SuiteBar {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px;
}
QLabel#SuiteName { font-size: 14px; font-weight: 600; color: %(title)s; }
QPushButton#SuiteTab {
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 6px 12px; color: %(sub)s;
}
QPushButton#SuiteTab:hover { background: %(surfaceHover)s; color: %(text)s; }
QPushButton#SuiteTab:checked {
    background: %(accentSoft)s; color: %(title)s; border-color: transparent;
}
QFrame#ToolCard {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 16px;
}
QFrame#ToolCard:hover { border-color: %(borderStrong)s; }
QFrame#GhostCard {
    background: transparent; border: 1px dashed %(borderStrong)s;
    border-radius: 16px;
}
QLabel#Hero { font-size: 28px; font-weight: 600; color: %(title)s; }
QLabel#CardTitle { font-size: 17px; font-weight: 600; color: %(title)s; }
QLabel#Chip {
    background: %(surfaceAlt)s; border: 1px solid %(border)s;
    border-radius: 10px; padding: 2px 9px; color: %(sub)s; font-size: 11px;
}
QLabel#Kbd {
    background: %(surfaceAlt)s; border: 1px solid %(border)s;
    border-radius: 5px; padding: 1px 6px; font-size: 11px; color: %(sub)s;
}
QPushButton#Link {
    background: transparent; border: 0; color: %(sub)s; padding: 3px 4px;
    text-align: left;
}
QPushButton#Link:hover { color: %(accent)s; }
""" % values
