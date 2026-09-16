"""The design system holds.

Two parts:

* The stylesheet and the design values themselves: the stylesheet contains
  no raw pixel numbers (only named design values), every name it uses
  exists, and it builds in every theme.
* The rest of the code, held to the design system by counting what is still
  decided one screen at a time - raw pixel sizes in styles, spacing off the
  scale, icon sizes off the set, fonts built by hand, inline styles, plain
  system message boxes and raw colours.  design_baseline.json records the
  counts; they may only go down.  When a file gets better:

      python tests/workspace/test_design.py --update

  and the goal is an empty baseline.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASELINE = os.path.join(HERE, "design_baseline.json")

FAILS = []

# Files whose job is to hold these values, or whose colours are data rather
# than interface (report pages, image overlays burnt into exported files).
EXEMPT = {
    "raw_colour": {"annotex/ui/palette.py", "annotex/ui/design.py", "annotex/ui/style.py",
                   "annotex/ui/icons.py", "annotex/core/htmlreport.py",
                   "annotex/apps/roi/core/report.py", "annotex/apps/roi/core/imaging.py",
                   "annotex/apps/roi/config.py"},
    "raw_px": {"annotex/ui/design.py", "annotex/core/htmlreport.py", "annotex/apps/roi/core/report.py"},
    "font_in_code": {"annotex/ui/design.py"},
    "inline_style": {"annotex/ui/palette.py", "annotex/ui/style.py"},
    "message_box": {"annotex/ui/dialogs/messages.py"},
}


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


def scan():
    """{rule: {file: count}} for the code under annotex/."""
    from annotex.ui import design
    rules = {
        "raw_px": re.compile(r"(?<![%\w])\d+px\b"),
        "font_in_code": re.compile(r"\bQFont\(|setPointSizeF?\(|setPixelSize\(|setBold\("),
        "inline_style": re.compile(r"\.setStyleSheet\("),
        "message_box": re.compile(r"\bQMessageBox\b"),
        "raw_colour": re.compile(r"#[0-9a-fA-F]{6}\b"),
    }
    margins = re.compile(r"setContentsMargins\(([^)]*)\)")
    spacing = re.compile(r"set(?:Horizontal|Vertical)?Spacing\(\s*(\d+)\s*\)")
    icon_size = re.compile(r"setIconSize\(QSize\(\s*(\d+)\s*,\s*(\d+)\s*\)\)")
    found = {}

    def count(rule, rel, amount=1):
        if rel in EXEMPT.get(rule, ()):
            return
        found.setdefault(rule, {})
        found[rule][rel] = found[rule].get(rel, 0) + amount

    for folder, _subfolders, files in os.walk(os.path.join(ROOT, "annotex")):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            for rule, pattern in rules.items():
                hits = len(pattern.findall(text))
                if hits:
                    count(rule, rel, hits)
            for match in margins.finditer(text):
                numbers = [int(n) for n in re.findall(r"-?\d+", match.group(1))]
                if numbers and any(n not in design.SCALE for n in numbers):
                    count("spacing_off_scale", rel)
            for match in spacing.finditer(text):
                if int(match.group(1)) not in design.SCALE:
                    count("spacing_off_scale", rel)
            for match in icon_size.finditer(text):
                if int(match.group(1)) not in design.ICON_SIZES or int(match.group(2)) not in design.ICON_SIZES:
                    count("icon_size_off_set", rel)
    return found


def main():
    from annotex.ui import design, style
    from annotex.ui.palette import THEMES

    # ── the design values and the stylesheet ──────────────
    raw = re.findall(r"(?<![%\w-])\d+px", style.TEMPLATE)
    ok("the stylesheet uses no raw pixel sizes", not raw)
    if raw:
        print("      %s" % ", ".join(sorted(set(raw))))
    names = set(re.findall(r"%\((\w+)\)s", style.TEMPLATE))
    values = design.stylesheet_values()
    theme_keys = set(next(iter(THEMES.values())))
    unknown = names - set(values) - theme_keys - {"checkIcon", "radioIcon"}
    ok("every name the stylesheet uses is a design value or a theme colour", not unknown)
    if unknown:
        print("      unknown: %s" % ", ".join(sorted(unknown)))
    built = []
    for theme_id, theme in THEMES.items():
        try:
            built.append(len(style.build(dict(theme, dangerSoft=theme.get("dangerSoft", "#000000")))) > 0)
        except Exception as exc:
            print("      %s: %s" % (theme_id, exc))
            built.append(False)
    ok("the stylesheet builds in all %d themes" % len(THEMES), all(built))
    ok("spacing is one scale", list(design.SCALE) == sorted(set(design.SCALE)) and 0 in design.SCALE)
    ok("a few type styles, not a dozen", len({size for size, _w in design.TYPE.values()}) <= 6)
    ok("a few corner sizes, not twenty", len(design.RADIUS) <= 4)
    ok("a few icon sizes, all even", len(design.ICON_SIZES) <= 3
       and all(size % 4 == 0 for size in design.ICON_SIZES))
    ok("the rail's buttons are square, so their highlight is a circle",
       design.RAIL_BUTTON[0] == design.RAIL_BUTTON[1]
       and values["round_rail_button"] == "%dpx" % (design.RAIL_BUTTON[1] // 2))
    ok("every control is the same height", design.stylesheet_values()["control_inner"]
       == "%dpx" % (design.CONTROL_HEIGHT - 2 * design.HAIRLINE))

    from PySide6.QtWidgets import QApplication, QHBoxLayout
    app = QApplication(sys.argv[:1])
    layout = QHBoxLayout()
    design.margins(layout, "s", "l")
    margins = layout.contentsMargins()
    ok("margins read like CSS: vertical then horizontal",
       (margins.top(), margins.right(), margins.bottom(), margins.left()) == (8, 16, 8, 16))
    ok("a type style is a real font", design.font("headline").pixelSize() == 15)

    from annotex.shell.style_guide import StyleGuideDialog
    from annotex.ui.palette import resolve_theme
    guide = StyleGuideDialog(None, resolve_theme("dark", app))
    guide.show()
    app.processEvents()
    ok("the style guide opens", guide.isVisible())
    guide.close()

    from PySide6.QtWidgets import QWidget
    from annotex.ui import toast
    host = QWidget()
    host.resize(640, 400)
    host.show()
    pressed = []
    first = toast.show(host, "3 boxes cleared", action="Undo", on_action=lambda: pressed.append(1))
    app.processEvents()
    ok("a toast shows over its window", first is not None and first.isVisible())
    ok("a toast sits inside the window, above the bottom edge",
       host.rect().contains(first.geometry()) and first.geometry().bottom() < host.height())
    second = toast.show(host, "Saved", tone="good")
    app.processEvents()
    ok("a new toast replaces the old one", host._annotex_toast is second and not first.isVisible())
    second.button is None and ok("a toast without an action has no button", True)
    third = toast.show(host, "Removed", action="Undo", on_action=lambda: pressed.append(1))
    third.button.click()
    app.processEvents()
    ok("a toast's action runs and closes it", pressed == [1] and not third.isVisible())
    host.close()

    # ── the rest of the code only gets more consistent ────
    found = scan()
    if "--update" in sys.argv:
        with open(BASELINE, "w", encoding="utf-8") as handle:
            json.dump(found, handle, indent=1, sort_keys=True)
        total = sum(sum(files.values()) for files in found.values())
        print("  ..  baseline written: %d one-off(s) left to convert" % total)
    if not os.path.isfile(BASELINE):
        ok("a baseline exists (run with --update once)", False)
    else:
        with open(BASELINE, encoding="utf-8") as handle:
            baseline = json.load(handle)
        grew = []
        for rule, files in found.items():
            for rel, amount in files.items():
                allowed = baseline.get(rule, {}).get(rel, 0)
                if amount > allowed:
                    grew.append("%s: %s %d (was %d)" % (rule, rel, amount, allowed))
        ok("no screen has gained a one-off size, colour, font, style or message box", not grew)
        for line in grew[:30]:
            print("      " + line)
        left = sum(sum(files.values()) for files in found.values())
        before = sum(sum(files.values()) for files in baseline.values())
        print("  ..  %d one-off(s) left to convert (baseline %d)" % (left, before))
        if left < before and "--update" not in sys.argv:
            print("  ..  fewer than the baseline - run with --update to lock the progress in")

    # ── no two buttons in a rail may be the same drawing ──
    # Duplicate, Copy and Cut were all drawn as the same two overlapping
    # squares, so Duplicate and Copy sat side by side in the rail looking
    # identical.  Checking the action tables was not enough: LabelImg Shapes
    # names its icons where it builds its actions, not in its table, so a
    # table-only check passed while the rail still showed two of the same.
    # These are the pixels the rail actually draws.
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication
    import tempfile
    picture_app = QApplication.instance() or QApplication(sys.argv[:1])
    from annotex.ui.dialogs import messages as _messages
    _messages.ask = lambda *a, **k: False
    _messages.inform = _messages.warn = _messages.error = lambda *a, **k: None
    from annotex.config import ShellSettings
    from annotex.shell.window import ShellWindow
    from annotex.ui import icons as icon_set

    sandbox = tempfile.mkdtemp(prefix="annotex_rail_")
    for index in range(2):
        picture = QImage(400, 300, QImage.Format.Format_RGB32)
        picture.fill(QColor(50, 90, 130))
        picture.save(os.path.join(sandbox, "f%d.png" % index))
    rail_shell = ShellWindow(picture_app, ShellSettings(os.path.join(sandbox, "s.json")))
    rail_shell.resize(1400, 900)
    rail_shell.show()
    for tool_id, name in (("labelimg", "LabelImg Master"), ("shapes", "LabelImg Shapes"),
                          ("roi", "ROI Studio")):
        page = rail_shell.open_tool(tool_id, sandbox)
        for _ in range(25):
            picture_app.processEvents()
        drawn, clashes = {}, []
        for group in ("tool_buttons", "quick_buttons", "edit_buttons", "window_buttons"):
            for key, button in (getattr(page, group, {}) or {}).items():
                image = button.icon().pixmap(QSize(19, 19)).toImage()
                if image.isNull():
                    continue
                pixels = tuple(image.pixelColor(x, y).rgba()
                               for x in range(image.width()) for y in range(image.height()))
                if pixels in drawn:
                    clashes.append("%s == %s" % (key, drawn[pixels]))
                else:
                    drawn[pixels] = key
        ok("%s: every button in the rail is a different drawing%s"
           % (name, "" if not clashes else " (%s)" % "; ".join(clashes[:3])), not clashes)

        # ...and with room to spare the rail shows all of them, without
        # scrolling.  Its size hint left out the pill's own hairline border, so
        # it asked for two pixels less than it needed and scrolled on every
        # screen - and the rounding to whole buttons turned those two pixels
        # into a whole button nobody could see.
        rail = page.workspace.rail
        viewport = rail.scroll.viewport()
        hidden = [b for b in rail.buttons
                  if b.mapTo(viewport, b.rect().topLeft()).y() < 0
                  or b.mapTo(viewport, b.rect().topLeft()).y() + b.height() > viewport.height()]
        ok("%s: on a roomy window the rail shows every button%s"
           % (name, "" if not hidden else " (%d of %d hidden)" % (len(hidden), len(rail.buttons))),
           not hidden)
    rail_shell.close()

    # ── a thumbnail is clipped to the frame that holds it ──
    # The picture was clipped square while its frame was drawn rounded, so the
    # corners of every thumbnail stood outside the frame.
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication
    import tempfile
    picture_app = QApplication.instance() or QApplication(sys.argv[:1])
    from annotex.ui.filmstrip import FilmStrip, PADDING
    from annotex.ui import palette as palette_module
    folder = tempfile.mkdtemp(prefix="annotex_strip_")
    for index in range(2):
        picture = QImage(200, 150, QImage.Format.Format_RGB32)
        picture.fill(QColor(255, 0, 0))            # loud, so a stray corner shows
        picture.save(os.path.join(folder, "p%d.png" % index))
    strip = FilmStrip()
    strip.set_theme(palette_module.resolve_theme("dark", picture_app))
    strip.resize(320, 104)
    strip.set_batch(folder, ["p0.png", "p1.png"], {})
    strip.show()
    import time as _time
    limit = _time.time() + 15
    while _time.time() < limit and len(strip._thumbs) < 2:
        picture_app.processEvents()
        _time.sleep(0.05)
    for _ in range(10):
        picture_app.processEvents()
    shot = strip.grab().toImage()
    corner = shot.pixelColor(PADDING + 1, PADDING + 1)
    middle = shot.pixelColor(PADDING + 40, PADDING + 30)
    ok("a thumbnail's picture reaches the middle of its frame", middle.red() > 180)
    ok("and its corner is cut to the frame's curve, not left square",
       corner.red() < 150)
    strip.close()

    print("=" * 60)
    if FAILS:
        print("DESIGN TESTS FAILED: %s" % ", ".join(FAILS))
        return 1
    print("DESIGN TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
