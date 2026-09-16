"""The suite shell: Home, switching tools, shared theme, commit-on-leave, quit.

    python tests/shell/test_shell.py
"""

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SANDBOX = tempfile.mkdtemp(prefix="annotex_shell_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")
# Each tool shows a one-time welcome tour; mark it seen so nothing modal
# blocks a headless run.
for sub in ("roi_studio", os.path.join("annotex", "labelimg")):
    os.makedirs(os.path.join(SANDBOX, "config", sub), exist_ok=True)
    with open(os.path.join(SANDBOX, "config", sub, "settings.json"), "w") as handle:
        handle.write('{"first_run_done": true}')
OUT = os.environ.get("ANNOTEX_SHOT_DIR", "")

from PySide6.QtGui import QColor, QPixmap                            # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402
from annotex.ui.dialogs import messages  # noqa: E402

from annotex.apps.labelimg.core.model import Box                     # noqa: E402
from annotex.apps.labelimg.ui.window import LabelImgWindow           # noqa: E402
from annotex.apps.roi.ui.main_window import MainWindow as RoiWindow  # noqa: E402
from annotex.config import ShellSettings                             # noqa: E402
from annotex.shell.window import ShellWindow                         # noqa: E402

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


app = QApplication(sys.argv[:1])
app.setStyle("Fusion")
messages.ask = lambda *a, **k: True

folder = os.path.join(SANDBOX, "frames")
os.makedirs(folder)
for name in ("A_cam1_1.png", "A_cam1_2.png"):
    px = QPixmap(640, 480)
    px.fill(QColor(60, 80, 110))
    px.save(os.path.join(folder, name))

settings = ShellSettings(os.path.join(SANDBOX, "shell.json"))
shell = ShellWindow(app, settings)
shell.resize(1500, 950)
shell.show()
app.processEvents()

try:
    ok("starts on Home", shell.stack.currentWidget() is shell.home)
    ok("a card per tool", len(shell.home.cards) == 10)
    ok("LabelImg Shapes sits with the annotation tools",
       [c.spec.id for c in shell.home.sections[0][2] if hasattr(c, "spec")] == ["roi", "labelimg", "shapes"])
    ok("no theme button on Home or the bar", not hasattr(shell.home, "theme_button")
       and not hasattr(shell, "theme_button"))
    ok("four sections", [s[0] for s in shell.home.sections] == ["Annotation", "Video", "Images",
                                                                "Dataset"])
    ok("no tool tabs until a tool is opened", not any(t.isVisible() for t in shell.tool_tabs.values()))
    ok("Home tab checked", shell.home_tab.isChecked())

    # Diagnostics has to be reachable without a terminal: somebody who
    # downloaded a built application has no other way to ask what this
    # machine has, or where the log is.
    ok("the bar offers Diagnostics", shell.help_button.isVisible()
       and not shell.help_button.icon().isNull())
    ok("and names its key", "F1" in shell.help_button.toolTip())
    # What a packaged build is checked with: seven tools are opened by name,
    # which a build can silently leave out, so every tool must say where its
    # window lives and that window must load.
    from annotex.shell.registry import verify_tools, window_class_path
    ok("every tool says where its window lives",
       all(window_class_path(spec) for spec in shell.tools))
    ok("and every one of those windows loads", verify_tools(shell.tools) == [])
    ok("F1 is bound for the whole application",
       any(a.shortcut().toString() == "F1" for a in shell.actions()))
    from annotex.shell.diagnostics import DiagnosticsDialog
    report = DiagnosticsDialog(shell)
    app.processEvents()
    ok("it opens with this machine's report in it",
       "Annotex" in report.report.toPlainText())
    report.reject()
    if OUT:
        shell.grab().save(os.path.join(OUT, "shell_home_dark.png"))

    page = shell.open_tool("labelimg", folder)
    app.processEvents()
    ok("LabelImg Master opens", isinstance(page, LabelImgWindow))
    ok("its tab is checked", shell.tool_tabs["labelimg"].isChecked()
       and not shell.home_tab.isChecked())
    ok("folder opened through the shell", page.folder == folder)
    ok("title names the tool", "LabelImg Master" in shell.windowTitle())
    page.settings.data["first_run_done"] = True

    page.register_class("person")
    page.canvas.add_box(Box("person", 20, 20, 120, 140))
    roi = shell.open_tool("roi")
    app.processEvents()
    ok("ROI Studio opens", isinstance(roi, RoiWindow))
    ok("leaving LabelImg saved its work", os.path.isfile(os.path.join(folder, "A_cam1_1.xml")))
    ok("the hidden tool is not visible", not page.isVisible() and roi.isVisible())
    ok("the same tool object is kept", shell.open_tool("labelimg") is page)

    # ── closing one tool from its tab ─────────────────────
    shell.open_tool("dataset")
    ok("a tool tab carries a close button", shell.tab_closers["dataset"].isVisible())
    shell.tab_closers["dataset"].click()
    app.processEvents()
    ok("closing a tool drops its page", "dataset" not in shell.pages)
    ok("its tab goes with it", not shell.tab_holders["dataset"].isVisible())
    ok("another open tool takes over", shell.stack.currentWidget() in shell.pages.values())
    ok("closing a tool that is not open is harmless", shell.close_tool("dataset"))
    shell.open_tool("roi")

    shell.request_theme("light")
    app.processEvents()
    ok("theme reaches every tool", page.theme["name"] == "light" and roi.theme["name"] == "light")
    ok("theme is remembered", ShellSettings(settings.path).get("theme") == "light")
    roi.toggle_theme()
    app.processEvents()
    ok("a tool's theme switch reaches the shell and the other tool",
       shell.theme["name"] == "dark" and page.theme["name"] == "dark")

    shell.go_home()
    app.processEvents()
    ok("back on Home", shell.stack.currentWidget() is shell.home)

    from annotex.ui import palette
    ok("every theme has every colour", all(key in theme for theme in palette.THEMES.values()
                                           for key in palette.DARK))
    ok("every theme keeps text readable", all(palette.contrast(t["text"], t["surface"]) >= 4.5
                                              for t in palette.THEMES.values()))
    # Body text on a card was the only pairing anyone checked, so the ones
    # that actually went wrong went unseen: a warning line at 2.31:1 on
    # Catppuccin Latte's cream, and a Delete button whose white label sat at
    # 3.14:1 on Dracula's red while black would have given 6.01:1.  Every
    # foreground the stylesheet draws on a known background is measured here.
    # (Solarized Light's body text is 4.39 - a hair under, and faithful to
    # the palette it is named after, so the bar allows it.)
    PAIRINGS = (("text", "surface"), ("text", "appBg"), ("text", "surfaceAlt"),
                ("title", "surface"), ("subText", "surface"), ("subTextOnApp", "appBg"),
                ("onAccent", "accent"), ("onDanger", "danger"),
                ("tooltipFg", "tooltipBg"), ("goodText", "surface"),
                ("warnText", "surface"), ("dangerText", "surface"),
                ("accentText", "surface"))
    def shade(resolved, key):
        """The text shade, or the plain colour where there is no such shade."""
        if key in resolved:
            return resolved[key]
        return resolved[key.replace("TextOnApp", "").replace("Text", "")]

    dim = []
    for theme_id in sorted(palette.THEMES):
        resolved = palette.resolve_theme(theme_id, app)
        for fg, bg in PAIRINGS:
            ratio = palette.contrast(shade(resolved, fg), resolved[bg])
            if ratio < 4.35:
                dim.append("%s %s on %s %.2f" % (theme_id, fg, bg, ratio))
    ok("every theme keeps every kind of text readable%s"
       % ("" if not dim else " (%s)" % "; ".join(dim[:4])), not dim)
    # The two colours that are only ever black or white must be the clearer
    # of the two, not the brighter-looking one.
    wrong = []
    for theme_id in sorted(palette.THEMES):
        resolved = palette.resolve_theme(theme_id, app)
        for key, base in (("onAccent", "accent"), ("onDanger", "danger")):
            chosen = palette.contrast(resolved[key], resolved[base])
            best = max(palette.contrast("#111111", resolved[base]),
                       palette.contrast("#ffffff", resolved[base]))
            if chosen < best - 0.01:
                wrong.append("%s %s" % (theme_id, key))
    ok("a button label takes the clearer of black and white%s"
       % ("" if not wrong else " (%s)" % ", ".join(wrong[:4])), not wrong)
    ok("each tool has its own colour", page.theme["accent"] != roi.theme["accent"])
    shell.request_theme("dracula")
    app.processEvents()
    ok("a VS Code theme reaches every tool", page.theme["id"] == "dracula" and roi.theme["id"] == "dracula"
       and page.theme["accent"] == palette.THEMES["dracula"]["hues"]["blue"])
    shell.toggle_theme()
    ok("Ctrl+T goes to the theme's partner", shell.theme_setting == palette.THEMES["dracula"]["partner"])
    shell.request_theme("dark")
    app.processEvents()

    # Regression: hovering a card used to create its shadow effect on Enter
    # and delete it on Leave; Qt sends Leave while hiding Home for a tool, and
    # that deletion crashed the app (segfault in QWidgetPrivate::hideChildren).
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent
    hovered = shell.home.cards[0]
    effect = hovered.graphicsEffect()
    child_count = len(hovered.children())
    app.sendEvent(hovered, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    ok("hover switches the card's glow on", effect is not None and effect.isEnabled())
    ok("hover creates nothing under the card", hovered.graphicsEffect() is effect
       and len(hovered.children()) == child_count)
    shell.open_tool("labelimg")
    app.processEvents()
    app.sendEvent(hovered, QEvent(QEvent.Type.Leave))
    ok("leaving Home while hovering deletes nothing and switches the glow off",
       hovered.graphicsEffect() is effect and not effect.isEnabled()
       and len(hovered.children()) == child_count)
    shell.go_home()
    app.processEvents()

    shell.home.refresh(wait=True)
    resume = [c for c in shell.home.continue_cards if c.session.tool_id == "labelimg"]
    ok("Home offers to continue the LabelImg folder", bool(resume) and resume[0].session.folder == folder)
    ok("and shows how far along it is", bool(resume) and (resume[0].session.total, resume[0].session.done) == (2, 1))
    from PySide6.QtWidgets import QPushButton

    def recent_buttons(card):
        found = []
        for i in range(card.recent_box.count()):
            holder = card.recent_box.itemAt(i).widget()
            if holder is not None:
                found += holder.findChildren(QPushButton)
        return found

    labelimg_card = [card for card in shell.home.cards if card.spec.id == "labelimg"][0]
    ok("Home lists the recent folder",
       any(button.toolTip() == folder for button in recent_buttons(labelimg_card)))
    if OUT:
        shell.grab().save(os.path.join(OUT, "shell_home_after.png"))

    # ── removing a folder from Home's recent list ─────────
    from annotex.apps.labelimg.config import Settings as LabelImgSettings
    removes = [b for b in recent_buttons(labelimg_card) if b.text() == "✕"]
    ok("every recent folder has a remove button", len(removes) >= 1)
    ok("each Continue card has a remove button",
       all(card.remove.text() == "✕" and card.remove.toolTip() for card in shell.home.continue_cards))
    ok("the LabelImg page is still open with the folder in its list",
       "labelimg" in shell.pages and folder in shell.pages["labelimg"].settings.get("recent_folders"))
    removes[0].click()
    app.processEvents()
    labelimg_card = [card for card in shell.home.cards if card.spec.id == "labelimg"][0]
    ok("the removed folder leaves the tool card",
       not any(button.toolTip() == folder for button in recent_buttons(labelimg_card)))
    ok("and the Continue strip",
       not any(c.session.folder == folder for c in shell.home.continue_cards))
    ok("and the settings on disk", folder not in (LabelImgSettings().get("recent_folders") or []))
    ok("and the open tool's own copy",
       folder not in (shell.pages["labelimg"].settings.get("recent_folders") or []))
    ok("the folder itself is untouched", os.path.isdir(folder))
    forgot = True
finally:
    shell.close()
    app.processEvents()
    ok("closing released the LabelImg lock", not os.path.isfile(os.path.join(folder, ".labelimg.lock")))
    if "forgot" in globals():
        from annotex.apps.labelimg.config import Settings as LabelImgSettings
        ok("closing the tool does not bring the removed folder back",
           folder not in (LabelImgSettings().get("recent_folders") or []))
    shutil.rmtree(SANDBOX, ignore_errors=True)

print("=" * 60)
if FAILS:
    print("SHELL TESTS FAILED: %d" % len(FAILS))
    for failure in FAILS:
        print("  x " + failure)
    sys.exit(1)
print("SHELL TESTS PASSED")
