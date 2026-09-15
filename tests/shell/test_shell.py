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
from PySide6.QtWidgets import QApplication, QMessageBox              # noqa: E402

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
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)

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
