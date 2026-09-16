"""Sessions: starting again is not starting over.

The store on its own first - records, ordering, the crash marker, other
machines, a corrupt or unwritable file - and then the real window: work in a
folder, quit, start again, and check that each Startup choice, the offer to
pick up after a crash and the Sessions window all do what they say.

    python tests/shell/test_sessions.py
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
SANDBOX = tempfile.mkdtemp(prefix="annotex_sessions_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")
os.environ["APPDATA"] = os.path.join(SANDBOX, "appdata")

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


def make_batch(name, count=4):
    from PySide6.QtGui import QColor, QPixmap
    folder = os.path.join(SANDBOX, name)
    os.makedirs(folder, exist_ok=True)
    for index in range(count):
        picture = QPixmap(160, 120)
        picture.fill(QColor(40 + index * 30, 80, 120))
        picture.save(os.path.join(folder, "frame_%d.png" % index))
    return folder


def main():
    from annotex.core.sessions import SessionStore, WorkSession, machine_id

    # ══ the store ═════════════════════════════════════════
    store = SessionStore(os.path.join(SANDBOX, "alone.json"))
    a = os.path.join(SANDBOX, "alone_a")
    b = os.path.join(SANDBOX, "alone_b")
    os.makedirs(a)
    os.makedirs(b)
    ok("a new store has nothing in it", store.sessions() == [])
    ok("this machine has an id, and keeps it", machine_id() and machine_id() == machine_id())

    store.update("labelimg", a, last_image="frame_9.png", images_total=40, images_done=9)
    record = store.find("labelimg", a)
    ok("working in a folder makes a record", record is not None
       and record.last_image == "frame_9.png")
    ok("a record still being worked in looks unfinished", record.crashed)
    store.end("labelimg", a, active_seconds=3725)
    record = store.find("labelimg", a)
    ok("closing it properly marks it finished", not record.crashed)
    ok("and keeps the time worked", record.worked_text() == "1h 02m")
    store.note("labelimg", a, images_total=41)
    ok("counting a folder does not make it look unfinished",
       not store.find("labelimg", a).crashed)
    store.note("shapes", b, images_total=3)
    ok("a folder only ever counted is not a crash", not store.find("shapes", b).crashed)

    store.update("shapes", b, last_image="x.png")
    store.update("labelimg", a, last_image="frame_11.png")
    ok("the folder worked in last comes first, even within one instant",
       [r.tool_id for r in store.recent(limit=5)] == ["labelimg", "shapes"])
    ok("unfinished lists what was never closed",
       {r.tool_id for r in store.unfinished()} == {"labelimg", "shapes"})

    other = WorkSession("roi", a, machine="someone-elses-laptop", opened_at="2026-01-01T00:00:00",
                        order=10 ** 6)
    store._write(store.sessions() + [other])
    ok("another machine's session is kept", any(r.machine != machine_id()
                                                 for r in store.sessions()))
    ok("but never offered here", all(r.here for r in store.recent(limit=0)))
    ok("and never offered as a crash to pick up",
       all(r.here for r in store.unfinished()))

    gone = os.path.join(SANDBOX, "alone_gone")
    os.makedirs(gone)
    store.update("roi", gone)
    shutil.rmtree(gone)
    ok("a folder that has gone is not offered",
       all(r.folder != gone for r in store.recent(limit=0)))
    ok("forgetting removes it", store.forget("roi", gone) and store.find("roi", gone) is None)

    small = SessionStore(os.path.join(SANDBOX, "small.json"), limit=4)
    for index in range(9):
        folder = os.path.join(SANDBOX, "many_%d" % index)
        os.makedirs(folder, exist_ok=True)
        small.update("roi", folder)
    ok("the store keeps a bounded number", len(small.sessions()) == 4)
    ok("and keeps the newest", small.sessions()[0].folder.endswith("many_8"))

    broken = os.path.join(SANDBOX, "broken.json")
    for junk in ("{not json", '{"sessions": 7}', '{"sessions": [null, {}, {"tool_id": 3}]}',
                 '{"sessions": [{"tool_id": "roi", "folder": "/x", "schema": 99}]}'):
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write(junk)
        ok("a damaged store is empty, not an error (%s)" % junk[:18],
           SessionStore(broken).sessions() == [])

    # Windows ignores these permission bits, and root ignores them anywhere.
    if os.name != "nt" and not (hasattr(os, "geteuid") and os.geteuid() == 0):
        locked = os.path.join(SANDBOX, "locked")
        os.makedirs(locked)
        os.chmod(locked, 0o500)
        try:
            dead = SessionStore(os.path.join(locked, "sessions.json"))
            dead.update("roi", a)
            ok("a store that cannot be written does not raise", dead.sessions() == [])
        finally:
            os.chmod(locked, 0o700)

    # ══ the real window ═══════════════════════════════════
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    from annotex.ui.dialogs import messages
    # Nothing modal may wait for a person here: a welcome sheet or a chooser
    # opened on the way into a tool would otherwise hold the test for ever.
    from PySide6.QtWidgets import QDialog
    QDialog.exec = lambda self: 0
    for sub in ("roi_studio", os.path.join("annotex", "labelimg"),
                os.path.join("annotex", "shapes")):
        os.makedirs(os.path.join(SANDBOX, "config", sub), exist_ok=True)
        with open(os.path.join(SANDBOX, "config", sub, "settings.json"), "w") as handle:
            handle.write('{"first_run_done": true}')
    answers = []
    messages.inform = lambda *a, **k: None
    messages.warn = lambda *a, **k: None
    messages.ask = lambda *a, **k: answers.pop(0) if answers else False

    from annotex.config import STARTUP_ALL, STARTUP_HOME, STARTUP_LAST, ShellSettings
    from annotex.shell import activity
    from annotex.shell.window import ShellWindow

    boxes = make_batch("boxes", 5)
    outlines = make_batch("outlines", 4)
    settings_path = os.path.join(SANDBOX, "shell.json")

    def start(startup=STARTUP_HOME):
        settings = ShellSettings(settings_path)
        settings.set("startup", startup)
        window = ShellWindow(app, settings)
        window.resize(1280, 800)
        window.show()
        app.processEvents()
        return window

    def settle(rounds=40):
        for _ in range(rounds):
            app.processEvents()

    window = start()
    page = window.open_tool("labelimg", boxes)
    settle()
    page.go_to_index(3)
    settle()
    state = page.session_state()
    ok("LabelImg Master says where it has got to",
       state["folder"] == boxes and state["last_image"] == "frame_3.png")
    shapes = window.open_tool("shapes", outlines)
    settle()
    shapes.go_to_index(2)
    settle()
    ok("so does LabelImg Shapes", shapes.session_state()["last_image"] == "frame_2.png")

    window._checkpoint_sessions()
    live = window.sessions.find("labelimg", boxes)
    ok("a checkpoint writes it down", live is not None and live.last_image == "frame_3.png")
    ok("and says the run is still going", live.crashed)
    ok("Home's Continue strip now comes from real sessions",
       [s.tool_id for s in activity.recent_sessions(window.tools)][:2] == ["shapes", "labelimg"])

    window.close()
    settle()
    ended = window.sessions.find("labelimg", boxes)
    ok("quitting closes every session properly", ended is not None and not ended.crashed)
    ok("and remembers which tools were open, the front one last",
       window.sessions.open_tools() == ["labelimg", "shapes"])
    window.deleteLater()
    settle()

    # ── Startup: Home ─────────────────────────────────────
    window = start(STARTUP_HOME)
    ok("Home, when that is the choice", window.restore_startup() == STARTUP_HOME
       and not window.pages)
    window.close()
    settle()
    window.deleteLater()

    # ── Startup: the last tool ────────────────────────────
    ShellSettings(settings_path).set("last_tool", "labelimg")
    window = start(STARTUP_LAST)
    ok("the last tool, when that is the choice",
       window.restore_startup() == STARTUP_LAST and list(window.pages) == ["labelimg"])
    settle()
    back = window.pages["labelimg"]
    ok("with its folder open", back.folder == boxes)
    ok("on the image it was left on", back.current_name() == "frame_3.png")
    window.close()
    settle()
    window.deleteLater()

    # ── Startup: everything ───────────────────────────────
    window = start(STARTUP_ALL)
    window.sessions.set_open_tools(["labelimg", "shapes"])
    ok("everything, when that is the choice",
       window.restore_startup() == STARTUP_ALL
       and set(window.pages) == {"labelimg", "shapes"})
    settle()
    ok("each tool back on its own image",
       window.pages["shapes"].current_rel() == "frame_2.png")
    ok("and the one in front last time is in front again",
       window.current_tool_id() == "shapes")
    window.close()
    settle()
    window.deleteLater()

    # ── a folder that has gone ────────────────────────────
    ShellSettings(settings_path).set("last_tool", "labelimg")
    moved = boxes + "_moved"
    os.rename(boxes, moved)
    window = start(STARTUP_LAST)
    try:
        result = window.restore_startup()
        ok("a folder that has gone does not stop the start", True)
        ok("the tool still opens, so another folder can be chosen",
           result == STARTUP_LAST and "labelimg" in window.pages)
    except Exception as exc:                                    # noqa: BLE001
        ok("a folder that has gone does not stop the start (%s)" % exc, False)
    window.close()
    settle()
    window.deleteLater()
    os.rename(moved, boxes)

    # ── after a crash ─────────────────────────────────────
    window = start()
    page = window.open_tool("labelimg", boxes)
    settle()
    page.go_to_index(4)
    settle()
    window._checkpoint_sessions()
    # Nothing closes it: as far as the store knows, the window just vanished.
    window.hide()
    window.deleteLater()
    settle()

    window = start()
    ok("a run that did not finish is noticed",
       any(r.tool_id == "labelimg" for r in window.sessions.unfinished()))
    answers[:] = [True]
    ok("saying yes opens it again", window.offer_recovery() and "labelimg" in window.pages)
    settle()
    ok("on the image it was on when it went", window.pages["labelimg"].current_name()
       == "frame_4.png")
    window.close()
    settle()
    window.deleteLater()

    window = start()
    page = window.open_tool("shapes", outlines)
    settle()
    window._checkpoint_sessions()
    window.hide()
    window.deleteLater()
    settle()
    window = start()
    answers[:] = [False]
    ok("saying no opens nothing", not window.offer_recovery() and not window.pages)
    ok("and it is not asked again next time", not window.sessions.unfinished())
    window.settings.set("offer_recovery", False)
    window.sessions.update("shapes", outlines)
    ok("and it can be switched off altogether", not window.offer_recovery())
    window.settings.set("offer_recovery", True)

    # ── the Sessions window ───────────────────────────────
    from annotex.shell.sessions_dialog import SessionsDialog
    # A record synced in from somebody else's laptop, naming a folder that
    # happens to exist here too - the case that must list but not resume.
    foreign = WorkSession("roi", boxes, machine="someone-elses-laptop",
                          opened_at="2026-01-01T00:00:00", order=10 ** 6)
    window.sessions._write(window.sessions.sessions() + [foreign])
    dialog = SessionsDialog(window, window.sessions, window.tools, window.settings)
    ok("the Sessions window lists what was worked in", dialog.table.rowCount() >= 2)
    ok("another machine's session is listed", any(
        "another machine" in (dialog.table.item(r, 1).text() or "")
        for r in range(dialog.table.rowCount())))
    for row_index, record in enumerate(dialog.records):
        if not record.here:
            dialog.table.selectRow(row_index)
            break
    app.processEvents()
    ok("but cannot be resumed from here", not dialog.resume_button.isEnabled())
    resumed = []
    dialog.resumeRequested.connect(lambda t, f: resumed.append((t, f)))
    for row_index, record in enumerate(dialog.records):
        if record.here and record.exists:
            dialog.table.selectRow(row_index)
            break
    app.processEvents()
    dialog.resume()
    ok("one of ours resumes", len(resumed) == 1)

    dialog = SessionsDialog(window, window.sessions, window.tools, window.settings)
    index = dialog.startup.findData(STARTUP_ALL)
    dialog.startup.setCurrentIndex(index)
    ok("choosing what a start looks like is saved",
       ShellSettings(settings_path).get("startup") == STARTUP_ALL)
    dialog.recover.setChecked(False)
    ok("so is switching the offer off",
       ShellSettings(settings_path).get("offer_recovery") is False)
    before = dialog.table.rowCount()
    for row_index, record in enumerate(dialog.records):
        if record.tool_id == "shapes":
            dialog.table.selectRow(row_index)
            break
    app.processEvents()
    answers[:] = [True]
    dialog.forget()
    ok("forgetting takes it off the list", dialog.table.rowCount() == before - 1)
    ok("and leaves the folder itself alone", os.path.isdir(outlines)
       and len(os.listdir(outlines)) >= 4)
    dialog.reject()
    ok("Home offers every session, not just three", hasattr(window.home, "sessions_link"))
    window.close()
    settle()

    print("=" * 60)
    shutil.rmtree(SANDBOX, ignore_errors=True)
    if FAILS:
        print("SESSION TESTS FAILED: %s" % ", ".join(FAILS))
        return 1
    print("SESSION TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
