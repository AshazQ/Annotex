"""Helpers over an action registry.

Every tool declares its commands once, as rows of
(id, label, default key, category, icon, description).  The window binds ids
to methods, the settings dialog rebinds keys, the command palette searches
the same list and the shortcut sheet prints it.  These functions are the
parts of that which do not depend on which tool the rows came from.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence


def by_id(actions) -> dict:
    return {row[0]: row for row in actions}


def categories(actions) -> list:
    out = []
    for row in actions:
        if row[3] not in out:
            out.append(row[3])
    return out


def default_key(actions, action_id: str) -> str:
    row = by_id(actions).get(action_id)
    return row[2] if row else ""


def label(actions, action_id: str) -> str:
    row = by_id(actions).get(action_id)
    return row[1] if row else action_id


def resolve(actions, overrides) -> dict:
    """Merge the user's remaps over the defaults, dropping anything unusable."""
    overrides = dict(overrides or {})
    keys = {}
    for action_id, _lbl, default, _cat, _icon, _desc in actions:
        chosen = overrides.get(action_id, default)
        if chosen is None:
            chosen = ""
        chosen = str(chosen).strip()
        if chosen and QKeySequence(chosen).isEmpty():
            chosen = default                      # unparseable - fall back
        keys[action_id] = chosen
    return keys


def conflicts(keys) -> dict:
    """{key: [action ids]} for every key bound more than once."""
    seen = {}
    for action_id, key in (keys or {}).items():
        if not key:
            continue
        canonical = QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText)
        seen.setdefault(canonical, []).append(action_id)
    return {key: ids for key, ids in seen.items() if len(ids) > 1}


def grouped(actions):
    """[(category, [rows])] in declaration order, for the shortcut sheet."""
    return [(category, [row for row in actions if row[3] == category])
            for category in categories(actions)]


def overrides_from(actions, keys) -> dict:
    """Only the bindings that differ from the defaults - what gets saved."""
    out = {}
    for action_id, _label, default, _cat, _icon, _desc in actions:
        key = keys.get(action_id, default)
        if key != default:
            out[action_id] = key
    return out


# ══════════════════════════════════════════════════════════════
# TEXT FIELDS KEEP THEIR OWN EDITING KEYS
# ══════════════════════════════════════════════════════════════
_EDITING_KEYS = None


def _editing_keys():
    """The standard editing sequences, resolved for this platform.

    Built once, and lazily, so importing this module costs nothing."""
    global _EDITING_KEYS
    if _EDITING_KEYS is None:
        from PySide6.QtGui import QKeySequence as _K
        wanted = (_K.StandardKey.Copy, _K.StandardKey.Cut, _K.StandardKey.Paste,
                  _K.StandardKey.SelectAll, _K.StandardKey.Undo, _K.StandardKey.Redo,
                  _K.StandardKey.Delete, _K.StandardKey.DeleteStartOfWord,
                  _K.StandardKey.DeleteEndOfWord)
        keys = set()
        for standard in wanted:
            for sequence in _K.keyBindings(standard):
                keys.add(sequence.toString(_K.SequenceFormat.PortableText))
        _EDITING_KEYS = keys
    return _EDITING_KEYS


def steals_from_text_field(event, focus, text_types) -> bool:
    """True when a window shortcut is about to swallow a key a text field
    needs.

    Ctrl+C in a search box must copy the text, not the annotator's boxes;
    Ctrl+A must select the text, not every shape on the image.  Qt gives
    window shortcuts priority over the focused widget, so the window answers
    the ShortcutOverride event for these keys and lets the field have them.
    """
    if focus is None or not isinstance(focus, tuple(text_types)):
        return False
    try:
        from PySide6.QtGui import QKeySequence as _K
        combination = event.keyCombination()
        pressed = _K(combination).toString(_K.SequenceFormat.PortableText)
    except Exception:
        return False
    return bool(pressed) and pressed in _editing_keys()
