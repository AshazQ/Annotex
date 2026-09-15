"""The workspace layout and the display setting: the image gets the room,
nothing is out of reach on a small screen, and the icons are vectors.

    python tests/workspace/test_layout.py
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="annotex_workspace_")
os.environ["HOME"] = os.path.join(SANDBOX, "home")
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "home", "config")
os.environ["APPDATA"] = os.path.join(SANDBOX, "home", "appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.makedirs(os.environ["HOME"], exist_ok=True)

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


def main():
    # ── display maths, before any Qt exists ───────────────
    from annotex import app as app_module
    from annotex.config import auto_factor, interface_factor
    ok("a roomy screen stays at 100 %", auto_factor(1920, 1040) == 1.0)
    ok("a 1366x768 laptop at 125 % scaling fits at 80 %", auto_factor(1093, 614) == 0.8)
    ok("automatic never goes below 70 %", auto_factor(640, 400) == 0.7)
    ok("a nonsense screen size means 100 %", auto_factor(0, 0) == 1.0 and auto_factor("x", 5) == 1.0)
    ok("Automatic uses what was measured", interface_factor({"ui_scale": "auto", "auto_scale": 0.85}) == 0.85)
    ok("a chosen size is used", interface_factor({"ui_scale": 1.25}) == 1.25)
    ok("a broken setting means 100 %", interface_factor({"ui_scale": "huge"}) == 1.0)
    ok("sizes are kept within reason", interface_factor({"ui_scale": 9}) == 2.0)
    saved = os.environ.pop("QT_SCALE_FACTOR", None)
    app_module.apply_interface_size({"ui_scale": 0.9})
    ok("the size is handed to Qt before it starts", os.environ.get("QT_SCALE_FACTOR") == "0.90")
    os.environ["QT_SCALE_FACTOR"] = "1.3"
    app_module.apply_interface_size({"ui_scale": 0.8})
    ok("a QT_SCALE_FACTOR set by hand wins", os.environ["QT_SCALE_FACTOR"] == "1.3")
    os.environ.pop("QT_SCALE_FACTOR", None)
    app_module.apply_interface_size({"ui_scale": 1.0})
    ok("100 % sets nothing", "QT_SCALE_FACTOR" not in os.environ)
    if saved is not None:
        os.environ["QT_SCALE_FACTOR"] = saved
    from annotex.shell.display import restart_command
    argv = sys.argv[:]
    sys.argv = [os.path.join(ROOT, "run.py"), "--tool", "roi"]
    program, arguments, _folder = restart_command()
    ok("restart runs the same script with the same options",
       program == sys.executable and arguments == [os.path.join(ROOT, "run.py"), "--tool", "roi"])
    sys.argv = [os.path.join(ROOT, "annotex", "__main__.py")]
    program, arguments, folder = restart_command()
    ok("restart from python -m annotex uses -m again", arguments[:2] == ["-m", "annotex"]
       and os.path.isdir(os.path.join(folder, "annotex")))
    sys.argv = argv

    # ── a real window ─────────────────────────────────────
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QIcon, QImage
    from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLabel
    from annotex.ui.dialogs import messages
    app = QApplication(sys.argv[:1])
    messages.ask = lambda *a, **k: False
    messages.inform = messages.warn = messages.error = lambda *a, **k: None
    original_exec = QDialog.exec
    QDialog.exec = lambda self: 0

    images = os.path.join(SANDBOX, "images")
    os.makedirs(images)
    for index in range(3):
        picture = QImage(1600, 900, QImage.Format.Format_RGB32)
        picture.fill(QColor(40 + index * 30, 80, 120))
        picture.save(os.path.join(images, "frame_%d.png" % index))

    from annotex.config import ShellSettings
    from annotex.shell.window import ShellWindow
    from annotex.ui.workspace import RAIL_WIDTH, ElidedLabel
    shell = ShellWindow(app, ShellSettings(os.path.join(SANDBOX, "shell.json")))
    ok("the window can be as small as a laptop at 150 %", shell.minimumSize().width() <= 800
       and shell.minimumSize().height() <= 500)
    ok("no \"More tools\" card on Home", not [f for f in shell.home.findChildren(QFrame)
                                              if f.objectName() == "GhostCard"])
    shell.resize(1366, 768)
    shell.show()
    app.processEvents()
    for tool in ("labelimg", "shapes", "roi"):
        page = shell.open_tool(tool, images)
        for _ in range(30):
            app.processEvents()
        page = shell.pages[tool]
        canvas = page.canvas
        share = canvas.width() * canvas.height() / float(shell.width() * shell.height())
        ok("%s: with everything open the image has %.0f %% of a 1366x768 window" % (tool, share * 100),
           share > 0.42)
        ok("%s: the tool fits a narrow screen (needs %d px)" % (tool, page.minimumSizeHint().width()),
           page.minimumSizeHint().width() <= 1000)
        rail = page.workspace.rail
        ok("%s: every header button is in the rail" % tool,
           len(rail.buttons) == len(page.tool_buttons) + len(getattr(page, "quick_buttons", {}))
           + len(getattr(page, "edit_buttons", {})) + len(page.window_buttons))
        ok("%s: the folder path cannot widen the window" % tool, isinstance(page.folder_label, ElidedLabel)
           and page.folder_label.minimumSizeHint().width() < 60)

        side = page.workspace.side
        wide = canvas.width()
        side.toggle()
        for _ in range(10):
            app.processEvents()
        ok("%s: the side panel folds to a strip" % tool, side.is_collapsed()
           and side.width() <= RAIL_WIDTH + 2 and not side.panel.isVisible())
        ok("%s: and the image gets the room" % tool, canvas.width() > wide + 200)
        folded_share = canvas.width() * canvas.height() / float(shell.width() * shell.height())
        ok("%s: panel folded, the image has %.0f %%" % (tool, folded_share * 100), folded_share > 0.52)
        ok("%s: the strip keeps saving within reach" % tool,
           len(side.strip.buttons) >= 3 and all(b.isVisible() for b in side.strip.buttons))
        # Stepping through images belongs to the round arrows over the image;
        # the strip does not repeat it.
        ok("%s: the strip does not repeat previous and next" % tool,
           not {"prev_image", "next_image"} & set(getattr(page, "strip_buttons", {}))
           and page.workspace.nav is not None)
        ok("%s: folding is remembered" % tool, page.settings.get("side_collapsed") is True)
        side.toggle()
        for _ in range(10):
            app.processEvents()
        ok("%s: and it opens again" % tool, not side.is_collapsed() and side.panel.isVisible()
           and page.settings.get("side_collapsed") is False)
        fold = page.workspace.fold
        tall = canvas.height()
        fold.toggle()
        for _ in range(10):
            app.processEvents()
        ok("%s: the filmstrip folds away for a taller image" % tool,
           not page.filmstrip.isVisible() and canvas.height() > tall + 60
           and page.settings.get("filmstrip_folded") is True)
        fold.toggle()
        app.processEvents()
        ok("%s: and comes back" % tool, page.filmstrip.isVisible())

    # a short screen: the rail scrolls rather than clipping
    shell.resize(1093, 614)
    for _ in range(10):
        app.processEvents()
    page = shell.pages["labelimg"]
    ok("on a short window the rail stays inside it",
       page.workspace.rail.geometry().bottom() <= page.height())
    from annotex.ui.design import RAIL_BUTTON
    rail = page.workspace.rail
    ok("a rail too short for every tool shows whole buttons, not half of one",
       rail.scroll.viewport().height() % RAIL_BUTTON[1] == 0
       or rail.scroll.viewport().height() >= rail.scroll.widget().sizeHint().height())
    ok("every rail button is a circle", all(b.width() == b.height() == RAIL_BUTTON[1]
                                            for b in rail.buttons))

    # the Display setting
    from annotex.shell.display import DisplayDialog
    dialog = DisplayDialog(shell, shell.settings)
    ok("Display offers Automatic and fixed sizes", dialog.size_box.count() == 8
       and dialog.chosen() == "auto")
    dialog.size_box.setCurrentIndex(dialog.size_box.findData(0.9))
    DisplayDialog.exec = lambda self: 1
    DisplayDialog.chosen = lambda self: 0.9
    shell.show_display()
    ok("choosing a size saves it for the next start", shell.settings.get("ui_scale") == 0.9)
    shell._measure_screen()
    ok("Automatic is measured on the screen in use", 0.6 <= float(shell.settings.get("auto_scale")) <= 1.0)

    # a dialog taller than the screen scrolls instead of hiding its buttons
    from annotex.ui.dialogs.common import Dialog
    QDialog.exec = original_exec
    tall_dialog = Dialog(shell, "Tall", "A lot of settings")
    filler = QLabel("\n".join("setting %d" % i for i in range(300)))
    tall_dialog.body.addWidget(filler)
    save = tall_dialog.add_button("Save", primary=True)
    tall_dialog.show()
    app.processEvents()
    screen = tall_dialog.screen().availableGeometry()
    ok("a tall dialog is kept inside the screen", tall_dialog.frameGeometry().height() <= screen.height()
       and tall_dialog.height() <= screen.height() * 0.91)
    ok("its buttons stay visible", save.isVisible() and save.mapTo(tall_dialog, save.rect().bottomLeft()).y()
       <= tall_dialog.height())
    ok("its body scrolls instead", tall_dialog.body_scroll.verticalScrollBar().maximum() > 0)
    tall_dialog.close()

    # icons are drawn as vectors at whatever scale is asked
    from annotex.ui import icons
    icon = icons.icon("settings", "#ffffff", 19)
    sharp = icon.pixmap(QSize(19, 19), 2.0)
    ok("an icon asked for at 200 % is drawn at 200 %", sharp.devicePixelRatio() == 2.0
       and sharp.width() == 38)
    odd = icon.pixmap(QSize(19, 19), 1.5)
    ok("and at 150 % (every device pixel drawn, not stretched)", odd.width() in (28, 29)
       and abs(odd.devicePixelRatio() - 1.5) < 0.1)
    two = icons.dual_icon("tag", "#000000", "#ff0000", 16)
    on = two.pixmap(QSize(16, 16), QIcon.Mode.Normal, QIcon.State.On).toImage()
    ok("a checked icon takes its active colour", any(on.pixelColor(x, y).red() > 200 and on.pixelColor(x, y).alpha() > 0
                                                     for x in range(on.width()) for y in range(on.height())))

    shell.close()
    print("=" * 60)
    if FAILS:
        print("WORKSPACE TESTS FAILED: %s" % ", ".join(FAILS))
        return 1
    print("WORKSPACE TESTS PASSED")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    sys.exit(code)
