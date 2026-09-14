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
