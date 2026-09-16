"""One keymap across the annotation tools: a command the tools share has the
same default key in each, no tool binds one key to two commands, and every
tool can change its keys.

    python tests/workspace/test_keymap.py
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="annotex_keymap_")
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
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    from annotex.apps.labelimg.ui import shortcuts as labelimg_keys
    from annotex.apps.roi.ui import shortcuts as roi_keys
    from annotex.apps.shapes.ui import shortcuts as shape_keys
    from annotex.ui import keymap
    from annotex.ui import shortcuts as shared

    tables = {"labelimg": labelimg_keys, "roi": roi_keys, "shapes": shape_keys}
    for tool, module in tables.items():
        defaults = {row[0]: row[2] for row in module.ACTIONS}
        wrong = ["%s is %r, not %r" % (action_id, defaults.get(action_id), keymap.STANDARD[command])
                 for action_id, command in keymap.TOOL_COMMANDS[tool].items()
                 if defaults.get(action_id) != keymap.STANDARD[command]]
        ok("%s: every shared command has the standard key" % tool, not wrong)
        for line in wrong:
            print("      " + line)
        missing = [a for a in keymap.TOOL_COMMANDS[tool] if a not in defaults]
        ok("%s: every mapped action exists" % tool, not missing)
        clashes = shared.conflicts(dict((row[0], row[2]) for row in module.ACTIONS))
        ok("%s: no key is bound to two commands" % tool, not clashes)
        if clashes:
            print("      %s" % clashes)
        extra = []
        for action_id in defaults:
            for key in keymap.sequences(tool, action_id, defaults[action_id])[1:]:
                owners = [a for a, k in defaults.items() if k == key]
                if owners:
                    extra.append("%s's second key %s belongs to %s" % (action_id, key, owners))
        ok("%s: second keys never steal another command's key" % tool, not extra)
        reserved = getattr(module, "RESERVED", set())
        bad = [a for a, k in defaults.items() if k in reserved and not (tool == "roi" and k == "Space")]
        ok("%s: no default uses a key the canvas owns" % tool, not bad)

    ok("the same command, the same key: next image", {
        m.BY_ID["next_image"][2] for m in tables.values()} == {"D"})
    ok("the same command, the same key: save", {
        labelimg_keys.BY_ID["save"][2], roi_keys.BY_ID["save_roi"][2], shape_keys.BY_ID["save"][2]}
       == {"Ctrl+S"})
    ok("the same command, the same key: zoom to fit", {
        m.BY_ID["zoom_fit"][2] for m in tables.values()} == {"Ctrl+0"})
    ok("the same command, the same key: move image out", {
        m.BY_ID["delete_image"][2] for m in tables.values() if "delete_image" in m.BY_ID}
       == {"Ctrl+Shift+D"})
    ok("every tool can move the image out of its folder",
       all("delete_image" in m.BY_ID for m in tables.values()))
    ok("moving an image out has its own icon, not the trash can",
       all(m.BY_ID["delete_image"][4] == "image_remove" for m in tables.values()))

    # LabelImg Shapes: the keys come from its table and can be changed
    from annotex.apps.shapes.config import Settings
    from annotex.apps.shapes.ui.dialogs import ShapesSettingsDialog
    from annotex.apps.shapes.ui.window import ShapesWindow
    from PySide6.QtGui import QKeySequence
    settings = Settings(os.path.join(SANDBOX, "shapes.json"))
    window = ShapesWindow(settings, app)

    def keys_of(action_id):
        return [k.toString(QKeySequence.SequenceFormat.PortableText)
                for k in window.act(action_id).shortcuts()]

    ok("Shapes: next image answers D and PgDown", keys_of("next_image") == ["D", "PgDown"])
    ok("Shapes: redo answers Ctrl+Y and Ctrl+Shift+Z", keys_of("redo") == ["Ctrl+Y", "Ctrl+Shift+Z"])
    ok("Shapes: Space is not a window shortcut (holding it pans)", "Space" not in keys_of("verify"))
    dialog = ShapesSettingsDialog(window, settings)
    ok("Shapes: Settings has a shortcut editor", hasattr(dialog, "keys")
       and dialog.keys.table.rowCount() == len(shape_keys.ACTIONS))
    ok("Shapes: a class number key cannot be taken", not dialog.keys.assign("zoom_fit", "1"))
    dialog.keys.assign("next_image", "Right")
    ok("Shapes: arrows are refused too (they nudge)", dialog.keys.keys["next_image"] == "D")
    dialog.keys.assign("next_image", "K")
    settings.update(dialog.result_values())
    window._rebind_shortcuts()
    ok("Shapes: a changed key takes effect", keys_of("next_image") == ["K", "PgDown"])
    ok("Shapes: and is kept in its settings", settings.get("shortcuts") == {"next_image": "K"})
    # Stepping through images lives on the arrows over the image, so the key
    # shows up on the action itself; the rail's own buttons carry their keys.
    ok("Shapes: the rail's tooltips show the keys", "[K]" not in window.tool_buttons["select"].toolTip()
       and ("[%s]" % keys_of("save")[0]) in window.strip_buttons["save"].toolTip())

    # tapping Space marks verified; holding it to pan does not
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QColor, QImage, QKeyEvent
    folder = os.path.join(SANDBOX, "images")
    os.makedirs(folder)
    picture = QImage(200, 150, QImage.Format.Format_RGB32)
    picture.fill(QColor("#335577"))
    picture.save(os.path.join(folder, "a.png"))
    picture.save(os.path.join(folder, "b.png"))
    window.show()
    window.open_folder(folder)
    app.processEvents()
    canvas = window.canvas
    before = window.verified
    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
    canvas.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
    ok("Shapes: a tap of Space marks the image verified", window.verified != before)
    state = window.verified
    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
    canvas._space_dragged = True                         # the mouse panned while it was held
    canvas.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
    ok("Shapes: holding Space to pan does not", window.verified == state)

    # the round arrows step through the images
    nav = window.workspace.nav
    ok("round previous / next buttons sit on the image", nav is not None
       and nav.next_button.isVisible() and nav.prev_button.isVisible()
       and nav.next_button.x() > canvas.width() - 80)
    window.set_tool("select")
    nav.next_button.click()
    app.processEvents()
    ok("the next arrow moves to the next image", window.index == 1)
    nav.prev_button.click()
    app.processEvents()
    ok("the previous arrow moves back", window.index == 0)

    # moving an image out of the folder
    from annotex.ui.dialogs import messages
    messages.ask = lambda *a, **k: True
    ok("the rail has a button for it", "delete_image" in window.edit_buttons)
    window.delete_image()
    app.processEvents()
    ok("Shapes: the image moves into deleted_images",
       os.path.isfile(os.path.join(folder, "deleted_images", "a.png"))
       and not os.path.exists(os.path.join(folder, "a.png")))
    ok("Shapes: the folder list drops it", window.images == ["b.png"] and window.current_rel() == "b.png")
    window.tool_close()

    # ROI Studio and LabelImg Master: the same rail button, arrows and keys
    from PySide6.QtWidgets import QDialog
    from annotex.apps.labelimg.config import Settings as BoxSettings
    from annotex.apps.labelimg.ui.window import LabelImgWindow
    from annotex.apps.roi.config import Settings as RoiSettings
    from annotex.apps.roi.ui.main_window import MainWindow as RoiWindow
    QDialog.exec = lambda self: 0
    messages.inform = lambda *a, **k: None
    messages.warn = lambda *a, **k: None
    tools = (("ROI Studio", lambda: RoiWindow(RoiSettings(os.path.join(SANDBOX, "roi.json")), app)),
             ("LabelImg Master", lambda: LabelImgWindow(BoxSettings(os.path.join(SANDBOX, "box.json")), app)))
    for name, build in tools:
        batch = os.path.join(SANDBOX, name.replace(" ", "_"))
        os.makedirs(batch)
        for file_name in ("a.png", "b.png", "c.png"):
            picture.save(os.path.join(batch, file_name))
        tool = build()
        tool.show()
        tool.open_folder(batch)
        for _ in range(10):
            app.processEvents()
        ok("%s: the rail has a move-image-out button" % name, "delete_image" in tool.quick_buttons)
        next_keys = [k.toString(QKeySequence.SequenceFormat.PortableText)
                     for k in tool.act("next_image").shortcuts()]
        ok("%s: next image answers D and PgDown" % name, next_keys == ["D", "PgDown"])
        ok("%s: round arrows sit on the image" % name, tool.workspace.nav is not None
           and tool.workspace.nav.next_button.isVisible())
        tool.workspace.nav.next_button.click()
        for _ in range(10):
            app.processEvents()
        ok("%s: the round arrow moves to the next image" % name, tool.index == 1)
        current = tool.image_files[tool.index]
        tool.delete_image()
        for _ in range(10):
            app.processEvents()
        ok("%s: the image moves into deleted_images" % name,
           os.path.isfile(os.path.join(batch, "deleted_images", current))
           and not os.path.exists(os.path.join(batch, current)))
        ok("%s: and leaves the list, with the next one on screen" % name,
           current not in tool.image_files and len(tool.image_files) == 2)
        closer = getattr(tool, "tool_close", None)
        if closer is not None:
            closer()
        else:
            tool.close()

    # ── ROI Studio: taking points back while drawing ──
    # Ctrl+Z did nothing mid-polygon: the window's Undo is switched off until
    # there is a finished shape to undo, so its shortcut never fired and only
    # Backspace worked - while LabelImg Shapes took the point back.  And
    # thinning a traced outline meant Ctrl+right-clicking every point.
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtTest import QTest
    from annotex.config import ShellSettings
    from annotex.shell.window import ShellWindow
    from annotex.apps.roi.core.model import Shape as RoiShape

    strokes = os.path.join(SANDBOX, "roi_keys")
    os.makedirs(strokes, exist_ok=True)
    for index in range(2):
        picture = QImage(600, 400, QImage.Format.Format_RGB32)
        picture.fill(QColor(50, 80, 110))
        picture.save(os.path.join(strokes, "frame_%d.png" % index))

    roi_shell = ShellWindow(app, ShellSettings(os.path.join(SANDBOX, "roi_keys.json")))
    roi_shell.show()
    roi_page = roi_shell.open_tool("roi", strokes)
    for _ in range(15):
        app.processEvents()
    roi_canvas = roi_page.canvas

    roi_canvas._draft = [QPointF(20, 20), QPointF(120, 30), QPointF(140, 110)]
    ok("ROI: Undo is still switched off mid-polygon",
       not roi_page.act("undo").isEnabled())
    QTest.keyClick(roi_canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    ok("ROI: Ctrl+Z takes back the last point while drawing",
       len(roi_canvas._draft) == 2)
    QTest.keyClick(roi_canvas, Qt.Key.Key_Backspace)
    app.processEvents()
    ok("ROI: Backspace still does the same", len(roi_canvas._draft) == 1)

    roi_canvas._draft = []
    roi_canvas.set_shapes([RoiShape.polygon(
        [(80, 80), (280, 80), (280, 240), (180, 280), (80, 240)])])
    app.processEvents()
    roi_canvas._hover_vertex = (0, 3)
    QTest.keyClick(roi_canvas, Qt.Key.Key_R)
    app.processEvents()
    ok("ROI: R removes the point under the pointer",
       len(roi_canvas.shapes[0].points) == 4)
    roi_canvas._hover_vertex = (0, 2)
    QTest.keyClick(roi_canvas, Qt.Key.Key_R)
    app.processEvents()
    ok("ROI: and again, so the key can be held down",
       len(roi_canvas.shapes[0].points) == 3)
    roi_canvas._hover_vertex = (0, 1)
    QTest.keyClick(roi_canvas, Qt.Key.Key_R)
    app.processEvents()
    ok("ROI: but never below the three a polygon needs",
       len(roi_canvas.shapes[0].points) == 3)
    roi_shell.close()
    app.processEvents()

    # ── the shell must not eat a key the tool on show binds ──
    # The shell's own keys are application shortcuts, which outrank a tool's
    # window shortcuts: Ctrl+1 jumped to a tool instead of zooming, and Ctrl+W
    # closed the whole tool instead of the batch, with nothing logged.  Press
    # the keys for real and see which action answers.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction, QColor, QImage
    from PySide6.QtTest import QTest
    from annotex.config import ShellSettings
    from annotex.shell.window import ShellWindow

    pictures = os.path.join(SANDBOX, "keys_batch")
    os.makedirs(pictures, exist_ok=True)
    for index in range(2):
        picture = QImage(400, 300, QImage.Format.Format_RGB32)
        picture.fill(QColor(60, 90, 120))
        picture.save(os.path.join(pictures, "shot_%d.png" % index))

    shell = ShellWindow(app, ShellSettings(os.path.join(SANDBOX, "keys_shell.json")))
    shell.show()
    app.processEvents()
    for tool_id in ("roi", "labelimg"):
        page = shell.open_tool(tool_id, pictures)
        for _ in range(10):
            app.processEvents()
        answered = []
        for action in page.findChildren(QAction):
            for sequence in action.shortcuts():
                if sequence.toString() in ("Ctrl+1", "Ctrl+W"):
                    action.triggered.connect(
                        lambda *_a, name=action.text(): answered.append(name))
        for key, name, wanted in ((Qt.Key.Key_1, "Ctrl+1", "Zoom to 100%"),
                                  (Qt.Key.Key_W, "Ctrl+W", "Close batch")):
            answered.clear()
            QTest.keyClick(page, key, Qt.KeyboardModifier.ControlModifier)
            app.processEvents()
            ok("%s: %s reaches the tool, not the shell" % (tool_id, name),
               answered == [wanted])
            if name == "Ctrl+W":
                page = shell.open_tool(tool_id, pictures)
                for _ in range(10):
                    app.processEvents()

    # and the shell takes its keys back where no tool claims them
    shell.open_tool("frames")
    for _ in range(5):
        app.processEvents()
    shell_keys = {a.shortcut().toString(): a for a in shell.findChildren(
        QAction, options=Qt.FindChildOption.FindDirectChildrenOnly)}
    ok("a media tool leaves Ctrl+1 and Ctrl+W to the shell",
       all(shell_keys[key].isEnabled() for key in ("Ctrl+1", "Ctrl+W") if key in shell_keys))
    shell.close()

    print("=" * 60)
    if FAILS:
        print("KEYMAP TESTS FAILED: %s" % ", ".join(FAILS))
        return 1
    print("KEYMAP TESTS PASSED")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    sys.exit(code)
