"""Theme tokens and the application stylesheet.

Every colour the suite uses is named here, so a theme change is one
dictionary swap and never a hunt through widget code.

A theme is a complete palette plus nine hues taken from the same scheme
(red, orange, yellow, green, teal, cyan, blue, purple, pink).  Each tool has
its own hue, so it keeps its identity in every theme while the colours still
belong to that theme:

    resolve_theme("dracula", app, tool="shapes")   Dracula, violet accent

`theme["name"]` stays "dark" or "light" (what kind of theme it is); the
theme's own id is `theme["id"]`, and Ctrl+T switches to `theme["partner"]`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

ACCENT = "#df5e3b"
ACCENT_HOVER = "#c9522f"
ACCENT_PRESSED = "#b0451f"

HUE_KEYS = ("red", "orange", "yellow", "green", "teal", "cyan", "blue", "purple", "pink")

# The colour each tool is known by.  Home, the tabs and the tool itself use it.
TOOL_HUES = {
    "roi": "orange",
    "labelimg": "blue",
    "shapes": "purple",
    "frames": "cyan",
    "trim": "red",
    "vconvert": "yellow",
    "merge": "pink",
    "iconvert": "green",
    "sorter": "teal",
}


# ══════════════════════════════════════════════════════════════
# COLOUR HELPERS
# ══════════════════════════════════════════════════════════════
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


def mix(a, b, amount: float) -> str:
    """`amount` of colour a over colour b, as #rrggbb."""
    ca, cb = qcolor(a), qcolor(b)
    t = max(0.0, min(1.0, float(amount)))
    return QColor(round(ca.red() * t + cb.red() * (1 - t)),
                  round(ca.green() * t + cb.green() * (1 - t)),
                  round(ca.blue() * t + cb.blue() * (1 - t))).name()


def luminance(value) -> float:
    """Relative luminance, 0 (black) to 1 (white)."""
    def channel(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    colour = qcolor(value)
    return (0.2126 * channel(colour.red()) + 0.7152 * channel(colour.green())
            + 0.0722 * channel(colour.blue()))


def contrast(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ══════════════════════════════════════════════════════════════
# THEMES
# ══════════════════════════════════════════════════════════════
def _derive(t: dict) -> dict:
    """Fill in every token a theme did not spell out."""
    dark = t["kind"] == "dark"
    surface = t["surface"]
    accent = t["accent"]
    t.setdefault("accentHover", mix(accent, "#ffffff", 0.86) if dark else mix(accent, "#000000", 0.88))
    t.setdefault("accentPressed", mix(accent, "#000000", 0.8))
    t.setdefault("accentSoft", mix(accent, surface, 0.22 if dark else 0.15))
    t.setdefault("onAccent", readable_on(accent))
    for key in ("good", "warn", "danger"):
        t.setdefault(key + "Soft", mix(t[key], surface, 0.16 if dark else 0.14))
    t.setdefault("info", t["hues"]["blue"])
    t.setdefault("canvasBg", mix(t["appBg"], "#000000", 0.45) if dark else "#0b0d12")
    t.setdefault("canvasVoid", mix(t["appBg"], "#000000", 0.7) if dark else "#15181e")
    t.setdefault("shadow", "rgba(0, 0, 0, 0.45)" if dark else "rgba(15, 20, 30, 0.14)")
    t.setdefault("scrollbar", t["borderStrong"])
    t.setdefault("tooltipBg", mix(t["appBg"], "#000000", 0.55) if dark else t["title"])
    t.setdefault("tooltipFg", t["title"] if dark else t["surface"])
    return t


def _theme(theme_id, label, kind, partner, hues, **colours) -> dict:
    t = dict(colours)
    t.update(id=theme_id, label=label, kind=kind, name=kind, partner=partner,
             hues=dict(zip(HUE_KEYS, hues)))
    return _derive(t)


THEMES = {}


def _add(theme: dict) -> dict:
    THEMES[theme["id"]] = theme
    return theme


DARK = _add(_theme(
    "dark", "Annotex Dark", "dark", "light",
    ("#e06a6c", "#df5e3b", "#e3b341", "#5cbf6b", "#3fb8a6", "#4fb6d8", "#5b9cea", "#a67bf0", "#e46fb0"),
    appBg="#14171d", surface="#1e222a", surfaceAlt="#252a33", surfaceHover="#2c323c",
    border="#333a45", borderStrong="#454d5a", title="#e9ecf1", text="#c8cdd6", sub="#8b93a1",
    muted="#6f7784", canvasBg="#07080b", canvasVoid="#101319", input="#171b22",
    inputBorder="#3a424e", accent=ACCENT, accentHover=ACCENT_HOVER, accentPressed=ACCENT_PRESSED,
    accentSoft="#3a2620", onAccent="#ffffff", good="#5cbf6b", goodSoft="#1c2a20", warn="#d9a13f",
    warnSoft="#302719", danger="#e06a6c", dangerSoft="#331d1f", info="#5b9cea",
    shadow="rgba(0, 0, 0, 0.45)", scrollbar="#3a414c", tooltipBg="#0b0d12", tooltipFg="#e9ecf1"))

LIGHT = _add(_theme(
    "light", "Annotex Light", "light", "dark",
    ("#c53437", "#d2552f", "#a8730f", "#2f8f43", "#13867a", "#1b7fa6", "#2a6fbd", "#7a4fd6", "#c0407f"),
    appBg="#e9ecee", surface="#fafcfd", surfaceAlt="#f1f4f6", surfaceHover="#e8edf0",
    border="#ced5da", borderStrong="#b6bfc6", title="#232933", text="#39404b", sub="#6b727e",
    muted="#8b929c", canvasBg="#0b0d12", canvasVoid="#15181e", input="#ffffff",
    inputBorder="#c6ced4", accent=ACCENT, accentHover=ACCENT_HOVER, accentPressed=ACCENT_PRESSED,
    accentSoft="#f7e3db", onAccent="#ffffff", good="#2f8f43", goodSoft="#e3f0e6", warn="#a8730f",
    warnSoft="#f8eeda", danger="#c53437", dangerSoft="#f9e0e1", info="#2a6fbd",
    shadow="rgba(15, 20, 30, 0.14)", scrollbar="#c8ced4", tooltipBg="#232933", tooltipFg="#fafcfd"))

_add(_theme(
    "oled", "True Black (OLED)", "dark", "light",
    ("#ff6b6b", "#ff7a45", "#ffd24a", "#5cd67a", "#33d1b8", "#4dd2ff", "#62a8ff", "#b388ff", "#ff79c6"),
    appBg="#000000", surface="#0a0a0a", surfaceAlt="#121212", surfaceHover="#1a1a1a",
    border="#1f1f1f", borderStrong="#2e2e2e", title="#f2f2f2", text="#d0d0d0", sub="#8f8f8f",
    muted="#6b6b6b", canvasBg="#000000", canvasVoid="#000000", input="#050505",
    inputBorder="#2a2a2a", accent="#ff7a45", good="#5cd67a", warn="#f0b43c", danger="#ff6b6b",
    info="#62a8ff", tooltipBg="#1a1a1a", shadow="rgba(0, 0, 0, 0.8)"))

_add(_theme(
    "dark_modern", "Dark Modern", "dark", "light_modern",
    ("#f14c4c", "#f0883e", "#d7ba7d", "#73c991", "#4ec9b0", "#9cdcfe", "#3794ff", "#c586c0", "#d670d6"),
    appBg="#181818", surface="#1f1f1f", surfaceAlt="#2b2b2b", surfaceHover="#2a2d2e",
    border="#2b2b2b", borderStrong="#3c3c3c", title="#ffffff", text="#cccccc", sub="#9d9d9d",
    muted="#6e7681", input="#313131", inputBorder="#3c3c3c", accent="#0078d4",
    good="#89d185", warn="#cca700", danger="#f85149", info="#3794ff"))

_add(_theme(
    "light_modern", "Light Modern", "light", "dark_modern",
    ("#cd3131", "#c24e00", "#a27b00", "#388a34", "#16825d", "#0070c1", "#005fb8", "#af00db", "#c7318b"),
    appBg="#f8f8f8", surface="#ffffff", surfaceAlt="#f3f3f3", surfaceHover="#e8e8e8",
    border="#e5e5e5", borderStrong="#cecece", title="#1f1f1f", text="#3b3b3b", sub="#616161",
    muted="#8b949e", input="#ffffff", inputBorder="#cecece", accent="#005fb8",
    good="#388a34", warn="#bf8803", danger="#e51400", info="#1a85ff"))

_add(_theme(
    "monokai", "Monokai", "dark", "light",
    ("#f92672", "#fd971f", "#e6db74", "#a6e22e", "#7ee0c3", "#66d9ef", "#78a9ff", "#ae81ff", "#ff6eb4"),
    appBg="#1e1f1c", surface="#272822", surfaceAlt="#3e3d32", surfaceHover="#414339",
    border="#414339", borderStrong="#75715e", title="#f8f8f2", text="#e6e6dc", sub="#a59f85",
    muted="#75715e", input="#1e1f1c", inputBorder="#49483e", accent="#f92672",
    good="#a6e22e", warn="#e6db74", danger="#ff4d7d", info="#66d9ef"))

_add(_theme(
    "dracula", "Dracula", "dark", "light",
    ("#ff5555", "#ffb86c", "#f1fa8c", "#50fa7b", "#5af2c3", "#8be9fd", "#6e9bf5", "#bd93f9", "#ff79c6"),
    appBg="#21222c", surface="#282a36", surfaceAlt="#343746", surfaceHover="#3b3e51",
    border="#44475a", borderStrong="#6272a4", title="#f8f8f2", text="#e2e2dc", sub="#9aa0c0",
    muted="#6272a4", input="#191a21", inputBorder="#44475a", accent="#bd93f9",
    good="#50fa7b", warn="#f1fa8c", danger="#ff5555", info="#8be9fd"))

_add(_theme(
    "one_dark", "One Dark", "dark", "one_light",
    ("#e06c75", "#d19a66", "#e5c07b", "#98c379", "#4db5bd", "#56b6c2", "#61afef", "#c678dd", "#e86fa8"),
    appBg="#21252b", surface="#282c34", surfaceAlt="#2c313a", surfaceHover="#323842",
    border="#3a3f4b", borderStrong="#4b5263", title="#e6e6e6", text="#abb2bf", sub="#7f848e",
    muted="#5c6370", input="#1d2025", inputBorder="#3e4451", accent="#61afef",
    good="#98c379", warn="#e5c07b", danger="#e06c75", info="#61afef"))

_add(_theme(
    "one_light", "One Light", "light", "one_dark",
    ("#e45649", "#b76b01", "#c18401", "#50a14f", "#0f8f8a", "#0184bc", "#4078f2", "#a626a4", "#ca1243"),
    appBg="#eaeaeb", surface="#fafafa", surfaceAlt="#f0f0f0", surfaceHover="#e5e5e6",
    border="#dbdbdc", borderStrong="#c2c2c3", title="#232324", text="#383a42", sub="#696c77",
    muted="#a0a1a7", input="#ffffff", inputBorder="#d3d3d4", accent="#4078f2",
    good="#50a14f", warn="#c18401", danger="#e45649", info="#4078f2"))

_add(_theme(
    "github_dark", "GitHub Dark", "dark", "github_light",
    ("#ff7b72", "#ffa657", "#e3b341", "#3fb950", "#39c5bb", "#56d4dd", "#58a6ff", "#bc8cff", "#f778ba"),
    appBg="#010409", surface="#0d1117", surfaceAlt="#161b22", surfaceHover="#1c2128",
    border="#30363d", borderStrong="#484f58", title="#f0f6fc", text="#c9d1d9", sub="#8b949e",
    muted="#6e7681", input="#0d1117", inputBorder="#30363d", accent="#2f81f7",
    good="#3fb950", warn="#d29922", danger="#f85149", info="#58a6ff"))

_add(_theme(
    "github_light", "GitHub Light", "light", "github_dark",
    ("#cf222e", "#bc4c00", "#9a6700", "#1a7f37", "#1b7c83", "#0a7ea4", "#0969da", "#8250df", "#bf3989"),
    appBg="#f6f8fa", surface="#ffffff", surfaceAlt="#f6f8fa", surfaceHover="#eaeef2",
    border="#d0d7de", borderStrong="#afb8c1", title="#1f2328", text="#24292f", sub="#57606a",
    muted="#6e7781", input="#ffffff", inputBorder="#d0d7de", accent="#0969da",
    good="#1a7f37", warn="#9a6700", danger="#cf222e", info="#0969da"))

_add(_theme(
    "solarized_dark", "Solarized Dark", "dark", "solarized_light",
    ("#dc322f", "#cb4b16", "#b58900", "#859900", "#2aa198", "#35b5d6", "#268bd2", "#6c71c4", "#d33682"),
    appBg="#00212b", surface="#002b36", surfaceAlt="#073642", surfaceHover="#0a4050",
    border="#164a57", borderStrong="#2f5f6b", title="#eee8d5", text="#a3b1b1", sub="#839496",
    muted="#657b83", input="#00212b", inputBorder="#164a57", accent="#268bd2",
    good="#859900", warn="#b58900", danger="#dc322f", info="#268bd2"))

_add(_theme(
    "solarized_light", "Solarized Light", "light", "solarized_dark",
    ("#dc322f", "#cb4b16", "#b58900", "#859900", "#2aa198", "#1f8fb8", "#268bd2", "#6c71c4", "#d33682"),
    appBg="#eee8d5", surface="#fdf6e3", surfaceAlt="#f5efdc", surfaceHover="#ece5cf",
    border="#ddd6c1", borderStrong="#c9c2ad", title="#073642", text="#586e75", sub="#657b83",
    muted="#93a1a1", input="#fffbef", inputBorder="#d6cfb9", accent="#268bd2",
    good="#859900", warn="#b58900", danger="#dc322f", info="#268bd2"))

_add(_theme(
    "nord", "Nord", "dark", "light",
    ("#bf616a", "#d08770", "#ebcb8b", "#a3be8c", "#8fbcbb", "#88c0d0", "#81a1c1", "#b48ead", "#c895bf"),
    appBg="#2b303b", surface="#2e3440", surfaceAlt="#3b4252", surfaceHover="#434c5e",
    border="#3b4252", borderStrong="#4c566a", title="#eceff4", text="#d8dee9", sub="#a3adbf",
    muted="#7b88a1", input="#272c36", inputBorder="#434c5e", accent="#88c0d0",
    good="#a3be8c", warn="#ebcb8b", danger="#bf616a", info="#81a1c1"))

_add(_theme(
    "gruvbox_dark", "Gruvbox Dark", "dark", "gruvbox_light",
    ("#fb4934", "#fe8019", "#fabd2f", "#b8bb26", "#8ec07c", "#7fc1b5", "#83a598", "#d3869b", "#e38fb0"),
    appBg="#1d2021", surface="#282828", surfaceAlt="#32302f", surfaceHover="#3c3836",
    border="#3c3836", borderStrong="#504945", title="#fbf1c7", text="#ebdbb2", sub="#bdae93",
    muted="#928374", input="#1d2021", inputBorder="#504945", accent="#fe8019",
    good="#b8bb26", warn="#fabd2f", danger="#fb4934", info="#83a598"))

_add(_theme(
    "gruvbox_light", "Gruvbox Light", "light", "gruvbox_dark",
    ("#9d0006", "#af3a03", "#b57614", "#79740e", "#427b58", "#3b7d77", "#076678", "#8f3f71", "#b0467e"),
    appBg="#f2e5bc", surface="#fbf1c7", surfaceAlt="#f4e8c1", surfaceHover="#ebdbb2",
    border="#d5c4a1", borderStrong="#bdae93", title="#282828", text="#3c3836", sub="#665c54",
    muted="#928374", input="#fdf6d8", inputBorder="#d5c4a1", accent="#af3a03",
    good="#79740e", warn="#b57614", danger="#9d0006", info="#076678"))

_add(_theme(
    "catppuccin_mocha", "Catppuccin Mocha", "dark", "catppuccin_latte",
    ("#f38ba8", "#fab387", "#f9e2af", "#a6e3a1", "#94e2d5", "#89dceb", "#89b4fa", "#cba6f7", "#f5c2e7"),
    appBg="#181825", surface="#1e1e2e", surfaceAlt="#313244", surfaceHover="#45475a",
    border="#313244", borderStrong="#45475a", title="#cdd6f4", text="#bac2de", sub="#a6adc8",
    muted="#7f849c", input="#181825", inputBorder="#45475a", accent="#cba6f7",
    good="#a6e3a1", warn="#f9e2af", danger="#f38ba8", info="#89b4fa"))

_add(_theme(
    "catppuccin_latte", "Catppuccin Latte", "light", "catppuccin_mocha",
    ("#d20f39", "#fe640b", "#df8e1d", "#40a02b", "#179299", "#04a5e5", "#1e66f5", "#8839ef", "#ea76cb"),
    appBg="#e6e9ef", surface="#eff1f5", surfaceAlt="#e9ecf2", surfaceHover="#dce0e8",
    border="#ccd0da", borderStrong="#bcc0cc", title="#4c4f69", text="#4c4f69", sub="#6c6f85",
    muted="#8c8fa1", input="#f7f8fb", inputBorder="#bcc0cc", accent="#8839ef",
    good="#40a02b", warn="#df8e1d", danger="#d20f39", info="#1e66f5"))

_add(_theme(
    "night_owl", "Night Owl", "dark", "light",
    ("#ef5350", "#f78c6c", "#ffcb8b", "#addb67", "#7fdbca", "#21c7a8", "#82aaff", "#c792ea", "#f78ce0"),
    appBg="#010e1a", surface="#011627", surfaceAlt="#0b2942", surfaceHover="#13344f",
    border="#122d42", borderStrong="#1d3b53", title="#e8f1f8", text="#d6deeb", sub="#8badc1",
    muted="#637777", input="#0b253a", inputBorder="#1d3b53", accent="#82aaff",
    good="#addb67", warn="#ecc48d", danger="#ef5350", info="#82aaff"))

_add(_theme(
    "tokyo_night", "Tokyo Night", "dark", "light",
    ("#f7768e", "#ff9e64", "#e0af68", "#9ece6a", "#73daca", "#7dcfff", "#7aa2f7", "#bb9af7", "#ff79c6"),
    appBg="#16161e", surface="#1a1b26", surfaceAlt="#1f2335", surfaceHover="#292e42",
    border="#292e42", borderStrong="#3b4261", title="#c0caf5", text="#a9b1d6", sub="#737aa2",
    muted="#565f89", input="#16161e", inputBorder="#3b4261", accent="#7aa2f7",
    good="#9ece6a", warn="#e0af68", danger="#f7768e", info="#7dcfff"))


# Canvas colours are deliberately separate from chrome: they sit on the dark
# image plane in every theme, so they do not follow the palette.
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


def theme_ids(kind=None):
    """Theme ids in menu order, optionally only 'dark' or 'light' ones."""
    return [tid for tid, t in THEMES.items() if kind is None or t["kind"] == kind]


def theme_for(name: str) -> dict:
    name = str(name or "dark").lower()
    return THEMES.get(name, DARK)


def with_tool(theme: dict, tool) -> dict:
    """The theme with a tool's own hue as its accent."""
    hue = TOOL_HUES.get(tool or "")
    if not hue:
        return theme
    t = {key: value for key, value in theme.items()
         if key not in ("accentHover", "accentPressed", "accentSoft", "onAccent")}
    t["accent"] = theme["hues"][hue]
    t["tool"] = tool
    return _derive(t)


def tool_accent(theme: dict, tool) -> str:
    hue = TOOL_HUES.get(tool or "")
    return theme["hues"][hue] if hue else theme["accent"]


def resolve_theme(setting: str, app=None, tool=None) -> dict:
    """Turn the 'theme' setting into a concrete palette.

    'system' asks Qt what the desktop is using; when Qt cannot tell (older
    platform themes) the app falls back to dark, which is the better default
    for looking at photographs.  An unknown id is treated as dark."""
    setting = str(setting or "dark").lower()
    base = None
    if setting == "system":
        base = DARK
        try:
            if app is not None:
                scheme = app.styleHints().colorScheme()
                if scheme == Qt.ColorScheme.Light:
                    base = LIGHT
                elif scheme == Qt.ColorScheme.Dark:
                    base = DARK
                else:
                    window = app.palette().color(QPalette.ColorRole.Window)
                    base = LIGHT if window.lightness() > 127 else DARK
        except Exception:
            base = DARK
    else:
        base = theme_for(setting)
    return with_tool(base, tool) if tool else base


def toggled_setting(theme: dict) -> str:
    """What Ctrl+T switches to: this theme's light or dark partner."""
    return theme.get("partner") or ("light" if theme.get("name") == "dark" else "dark")


def apply_palette(target, t: dict) -> None:
    """Give Qt's own palette the same colours, so native dialogs, tooltips
    and the window frame match the app instead of fighting it.  `target` is
    the QApplication or a single window."""
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
    target.setPalette(pal)


def install_theme(window, app, theme: dict, hosted: bool) -> None:
    """Style one tool window.

    Inside the suite each tool carries its own stylesheet, so its accent
    stays its own and switching tools costs nothing.  Run on its own, the
    tool styles the whole application as before."""
    if hosted:
        apply_palette(window, theme)
        window.setStyleSheet(stylesheet(theme))
    else:
        apply_palette(app, theme)
        app.setStyleSheet(stylesheet(theme))


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
QFrame#ToolCard, QFrame#FeatureCard {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 16px;
}
QFrame#ToolCard:hover { border-color: %(borderStrong)s; }
QFrame#TileCard, QFrame#ContinueCard {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 14px;
}
QFrame#GhostCard {
    background: transparent; border: 1px dashed %(borderStrong)s;
    border-radius: 16px;
}
QLabel#Hero { font-size: 28px; font-weight: 600; color: %(title)s; }
QLabel#Greeting { font-size: 30px; font-weight: 700; color: %(title)s; }
QLabel#CardTitle { font-size: 17px; font-weight: 600; color: %(title)s; }
QLabel#TileTitle { font-size: 14px; font-weight: 600; color: %(title)s; }
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
