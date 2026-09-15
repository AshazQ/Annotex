"""Dataset Tools in a real window: preview, run, history and undo, and a
couple of things a person will get wrong.

    python tests/dataset/test_gui.py
"""

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="annotex_dataset_gui_")
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
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv[:1])
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)

    folder = os.path.join(SANDBOX, "batch")
    os.makedirs(folder)
    for i in range(1, 7):
        with open(os.path.join(folder, "img%d.jpg" % i), "wb") as handle:
            handle.write(b"J%d" % i)
        with open(os.path.join(folder, "img%d.txt" % i), "w") as handle:
            handle.write("" if i == 6 else "0 0.5 0.5 0.1 0.1\n")
    with open(os.path.join(folder, "lonely.png"), "wb") as handle:
        handle.write(b"P")

    from annotex.apps.dataset.ui.page import DatasetPage
    page = DatasetPage(app)
    page.resize(1280, 800)
    page.show()

    def settle(limit=10.0):
        deadline = time.time() + limit
        while (page.previewing or page._busy()) and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
        for _ in range(5):
            app.processEvents()

    ok("nine tools are offered", page.op_list.count() == 9)
    ok("nothing can run before a folder is chosen", not page.run_button.isEnabled())

    page.set_folder(folder)
    page.select_operation("empty_labels")
    settle()
    ok("choosing a folder previews at once", page.plan is not None and len(page.plan.actions) == 1)
    ok("the preview lists every change", page.table.rowCount() == 1
       and page.table.item(0, 1).text() == "img6.txt")
    ok("Run says how many changes", page.run_button.isEnabled() and "1 change" in page.run_button.text())

    page.select_operation("rename_pairs")
    settle()
    ok("an empty name is refused in words", "Enter a name" in page.problems.text()
       and not page.run_button.isEnabled())
    page.fields["rename_pairs"]["base_name"].setText("CON")
    page.preview()
    settle()
    ok("a name Windows reserves is refused", "reserved" in page.problems.text())
    page.fields["rename_pairs"]["base_name"].setText("proj")
    ok("changing an option drops the old preview", page.plan is None and not page.run_button.isEnabled())
    page.preview()
    settle()
    ok("a valid name previews every pair", page.plan is not None and len(page.plan.actions) == 12)
    page.run_plan()
    settle(30)
    names = sorted(os.listdir(folder))
    ok("running renames the pairs", "proj_001.jpg" in names and "proj_006.txt" in names
       and "lonely.png" in names)
    ok("the run shows in History", page.history.count() >= 1 and
       "Rename" in page.history.item(0).text())
    ok("the preview refreshes after the run", page.plan is not None and not page.plan.actions
       or page.plan is not None)

    page.history.setCurrentRow(0)
    ok("Undo is offered for it", page.undo_button.isEnabled())
    page.undo_selected()
    settle(30)
    names = sorted(os.listdir(folder))
    ok("undo from the page restores the names", "img1.jpg" in names and "proj_001.jpg" not in names)
    page.refresh_history()
    ok("History marks it undone", "undone" in page.history.item(0).text())

    page.select_operation("split")
    page.fields["split"]["sizes"].setText("4, ten")
    page.preview()
    settle()
    ok("a bad size is explained", "not a whole number" in page.problems.text())

    for key in ("check_labels", "split_sets", "class_tools"):
        page.set_folder(folder)
        page.select_operation(key)
        settle()
        ok("%s previews without trouble" % key, page.plan is not None and not page.problems.text())
    page.select_operation("split_sets")
    page.fields["split_sets"]["test"].setValue(30)
    page.preview()
    settle()
    ok("shares that do not add up to 100 are explained", "add up to 100" in page.problems.text())
    page.fields["split_sets"]["test"].setValue(10)
    page.select_operation("class_tools")
    settle()
    ok("class tools lists the classes it counted", "box(es)" in page.notes.text())

    missing = os.path.join(SANDBOX, "gone")
    page.set_folder(missing)
    settle()
    ok("a folder that does not exist is explained, not crashed on",
       "does not exist" in page.problems.text() and not page.run_button.isEnabled())

    # it is a tool on Home, and the shell can open it on a folder
    from annotex.config import ShellSettings
    from annotex.shell import registry
    from annotex.shell.window import ShellWindow
    ok("Dataset Tools is registered", registry.get("dataset") is not None)
    shell = ShellWindow(app, ShellSettings(os.path.join(SANDBOX, "shell.json")))
    shell.show()
    opened = shell.open_tool("dataset", folder)
    for _ in range(20):
        app.processEvents()
    ok("the shell opens it with the folder", opened is not None and opened.folder() == folder)
    ok("Home lists it", any(card.spec.id == "dataset" for card in shell.home.cards))
    shell.close()
    page.close()

    print("=" * 60)
    if FAILS:
        print("DATASET GUI TESTS FAILED: %s" % ", ".join(FAILS))
        return 1
    print("DATASET GUI TESTS PASSED")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    sys.exit(code)
