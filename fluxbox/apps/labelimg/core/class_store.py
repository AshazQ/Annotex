#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Structured, per-project class store for LabelImgMaster.

Replaces the old flat ``data/*.txt`` predefined-class files with a small
JSON-backed store of ``{id, name, color, active, description}`` records.

Design notes
------------
* **Stable numeric IDs.** ``id`` is what the YOLO exporter writes as the class
  index.  Once a class has been used in an exported annotation its ID must
  never change, so IDs are only ever assigned (auto-incremented, or set
  manually at creation) and never renumbered.  Deleting a class leaves a hole
  in the ID space on purpose -- see :func:`ClassProject.ordered_names_for_yolo`.
* **Per project.** A store holds any number of named projects (one per site /
  deployment) and remembers which one is active.
* **Portable.** The store lives under the user's home directory by default and
  contains no absolute paths.  Nothing here imports Qt, so it is unit-testable
  without a display.
"""

import codecs
import hashlib
import json
import os
import re
import shutil
import tempfile

STORE_VERSION = 1

MAX_NAME_LENGTH = 64
MAX_PROJECT_NAME_LENGTH = 48

# Deliberately conservative: these characters are safe inside a filename, an
# XML text node, and a whitespace-delimited YOLO classes.txt line.
CLASS_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _.\-]*$')
PROJECT_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _.\-]*$')

# Names Windows refuses to use for a file, which would break crop export.
_RESERVED_NAMES = {
    'con', 'prn', 'aux', 'nul',
    *('com%d' % i for i in range(1, 10)),
    *('lpt%d' % i for i in range(1, 10)),
}

DEFAULT_PROJECT_NAME = 'default'

ANNOTATION_EXTENSIONS = ('.xml', '.txt', '.json')


class ClassStoreError(Exception):
    """Raised for validation failures. The message is user-facing."""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def default_store_dir():
    """Per-user config directory. No hardcoded drive letters or dev paths."""
    return os.path.join(os.path.expanduser('~'), '.labelImgMaster')


def default_store_path():
    return os.path.join(default_store_dir(), 'class_projects.json')


def color_for_name(name):
    """Deterministic fallback colour, as a ``#rrggbb`` string.

    Mirrors the hash-based scheme the app already used for box colours so
    imported classes keep the colours reviewers are used to.
    """
    hash_code = int(hashlib.sha256(name.encode('utf-8')).hexdigest(), 16)
    r = int((hash_code / 255) % 255)
    g = int((hash_code / 65025) % 255)
    b = int((hash_code / 16581375) % 255)
    return '#%02x%02x%02x' % (r, g, b)


def normalise_name(name):
    return (name or '').strip()


def validate_class_name(name):
    """Return the cleaned name, or raise :class:`ClassStoreError`."""
    cleaned = normalise_name(name)
    if not cleaned:
        return _fail('Class name cannot be empty.')
    if len(cleaned) > MAX_NAME_LENGTH:
        return _fail('Class name is too long (max %d characters).' % MAX_NAME_LENGTH)
    if not CLASS_NAME_RE.match(cleaned):
        return _fail(
            'Class name must start with a letter or digit and may only '
            'contain letters, digits, spaces and _ . -')
    if cleaned.lower() in _RESERVED_NAMES:
        return _fail('"%s" is a reserved system name and cannot be used.' % cleaned)
    return cleaned


def validate_project_name(name):
    cleaned = normalise_name(name)
    if not cleaned:
        return _fail('Project name cannot be empty.')
    if len(cleaned) > MAX_PROJECT_NAME_LENGTH:
        return _fail('Project name is too long (max %d characters).' % MAX_PROJECT_NAME_LENGTH)
    if not PROJECT_NAME_RE.match(cleaned):
        return _fail(
            'Project name must start with a letter or digit and may only '
            'contain letters, digits, spaces and _ . -')
    return cleaned


def validate_class_id(value):
    try:
        as_int = int(value)
    except (TypeError, ValueError):
        return _fail('Class ID must be a whole number.')
    if as_int < 0:
        return _fail('Class ID cannot be negative.')
    return as_int


def _fail(message):
    raise ClassStoreError(message)


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------

class ClassEntry(object):
    """One predefined class."""

    __slots__ = ('id', 'name', 'color', 'active', 'description')

    def __init__(self, id, name, color=None, active=True, description=''):
        self.id = int(id)
        self.name = name
        self.color = color or color_for_name(name)
        self.active = bool(active)
        self.description = description or ''

    @property
    def deprecated(self):
        return not self.active

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'active': self.active,
            'description': self.description,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data['id'],
            name=data['name'],
            color=data.get('color'),
            active=data.get('active', True),
            description=data.get('description', ''),
        )

    def __repr__(self):
        return '<ClassEntry %d %r%s>' % (self.id, self.name, '' if self.active else ' deprecated')


class ClassProject(object):
    """A named set of classes -- one per site / deployment."""

    def __init__(self, name, classes=None, next_id=0):
        self.name = name
        self.classes = list(classes or [])
        self._next_id = int(next_id)

    # -- lookups ---------------------------------------------------------
    def __len__(self):
        return len(self.classes)

    def __iter__(self):
        return iter(self.classes)

    def active_classes(self):
        """Classes offered for new labelling, in ID order."""
        return [c for c in self.sorted_classes() if c.active]

    def sorted_classes(self):
        return sorted(self.classes, key=lambda c: c.id)

    def by_id(self, class_id):
        for c in self.classes:
            if c.id == int(class_id):
                return c
        return None

    def by_name(self, name, case_sensitive=False):
        target = normalise_name(name)
        if not case_sensitive:
            target = target.lower()
        for c in self.classes:
            candidate = c.name if case_sensitive else c.name.lower()
            if candidate == target:
                return c
        return None

    def names(self, include_deprecated=True):
        return [c.name for c in self.sorted_classes()
                if include_deprecated or c.active]

    def id_map(self):
        """``{class name: stable id}`` -- what the YOLO writer indexes by."""
        return {c.name: c.id for c in self.classes}

    def ordered_names_for_yolo(self):
        """A ``classes.txt`` body where line N is the class with ID N.

        IDs can have holes (a deleted class), so the holes are filled with
        reserved placeholders. That keeps every already-exported ``.txt``
        readable: the reader still resolves index -> name correctly.
        """
        if not self.classes:
            return []
        highest = max(c.id for c in self.classes)
        by_id = {c.id: c.name for c in self.classes}
        return [by_id.get(i, '_reserved_%d' % i) for i in range(highest + 1)]

    # -- mutation --------------------------------------------------------
    def peek_next_id(self):
        used = {c.id for c in self.classes}
        candidate = self._next_id
        while candidate in used:
            candidate += 1
        return candidate

    def add_class(self, name, class_id=None, color=None, description='', active=True):
        cleaned = validate_class_name(name)
        if self.by_name(cleaned) is not None:
            _fail('A class named "%s" already exists (names are case-insensitive).' % cleaned)

        if class_id is None:
            new_id = self.peek_next_id()
        else:
            new_id = validate_class_id(class_id)
            if self.by_id(new_id) is not None:
                _fail('Class ID %d is already used by "%s".' % (new_id, self.by_id(new_id).name))

        entry = ClassEntry(new_id, cleaned, color=color,
                           active=active, description=description)
        self.classes.append(entry)
        self._next_id = max(self._next_id, new_id + 1)
        return entry

    def rename_class(self, class_id, new_name):
        entry = self.by_id(class_id)
        if entry is None:
            _fail('No class with ID %s.' % class_id)
        cleaned = validate_class_name(new_name)
        clash = self.by_name(cleaned)
        if clash is not None and clash.id != entry.id:
            _fail('A class named "%s" already exists (names are case-insensitive).' % cleaned)
        old_name = entry.name
        entry.name = cleaned
        return old_name, cleaned

    def set_color(self, class_id, color):
        entry = self.by_id(class_id)
        if entry is None:
            _fail('No class with ID %s.' % class_id)
        entry.color = color
        return entry

    def set_active(self, class_id, active):
        entry = self.by_id(class_id)
        if entry is None:
            _fail('No class with ID %s.' % class_id)
        entry.active = bool(active)
        return entry

    def set_description(self, class_id, description):
        entry = self.by_id(class_id)
        if entry is None:
            _fail('No class with ID %s.' % class_id)
        entry.description = description or ''
        return entry

    def remove_class(self, class_id):
        entry = self.by_id(class_id)
        if entry is None:
            _fail('No class with ID %s.' % class_id)
        self.classes.remove(entry)
        return entry

    def merge_name(self, name):
        """Ensure ``name`` exists, adding it if it doesn't. Returns the entry.

        Used when loading annotations that reference a class the current
        project doesn't know about yet -- better to adopt it than to silently
        drop the box.
        """
        existing = self.by_name(name)
        if existing is not None:
            return existing
        try:
            return self.add_class(name)
        except ClassStoreError:
            # Name the user could never have typed (odd characters from an old
            # file). Keep it verbatim so annotations round-trip unchanged.
            new_id = self.peek_next_id()
            entry = ClassEntry(new_id, normalise_name(name) or 'unnamed')
            self.classes.append(entry)
            self._next_id = new_id + 1
            return entry

    # -- serialisation ---------------------------------------------------
    def to_dict(self):
        return {
            'name': self.name,
            'next_id': self._next_id,
            'classes': [c.to_dict() for c in self.sorted_classes()],
        }

    @classmethod
    def from_dict(cls, data):
        classes = [ClassEntry.from_dict(d) for d in data.get('classes', [])]
        next_id = data.get('next_id')
        if next_id is None:
            next_id = (max((c.id for c in classes), default=-1) + 1)
        return cls(data['name'], classes, next_id)


class ClassStore(object):
    """All projects plus the notion of an active one, persisted as JSON."""

    def __init__(self, path=None):
        self.path = path or default_store_path()
        self.projects = {}
        self._active_project_name = DEFAULT_PROJECT_NAME
        self.ensure_project(DEFAULT_PROJECT_NAME)

    # -- projects --------------------------------------------------------
    @property
    def active_project_name(self):
        return self._active_project_name

    def active_project(self):
        return self.ensure_project(self._active_project_name)

    def project_names(self):
        return sorted(self.projects.keys(), key=lambda s: s.lower())

    def ensure_project(self, name):
        if name not in self.projects:
            self.projects[name] = ClassProject(name)
        return self.projects[name]

    def create_project(self, name):
        cleaned = validate_project_name(name)
        for existing in self.projects:
            if existing.lower() == cleaned.lower():
                _fail('A project named "%s" already exists.' % existing)
        self.projects[cleaned] = ClassProject(cleaned)
        return self.projects[cleaned]

    def rename_project(self, old_name, new_name):
        if old_name not in self.projects:
            _fail('No project named "%s".' % old_name)
        cleaned = validate_project_name(new_name)
        for existing in self.projects:
            if existing.lower() == cleaned.lower() and existing != old_name:
                _fail('A project named "%s" already exists.' % existing)
        project = self.projects.pop(old_name)
        project.name = cleaned
        self.projects[cleaned] = project
        if self._active_project_name == old_name:
            self._active_project_name = cleaned
        return project

    def delete_project(self, name):
        if name not in self.projects:
            _fail('No project named "%s".' % name)
        if len(self.projects) == 1:
            _fail('Cannot delete the only project.')
        del self.projects[name]
        if self._active_project_name == name:
            self._active_project_name = self.project_names()[0]

    def set_active_project(self, name):
        if name not in self.projects:
            _fail('No project named "%s".' % name)
        self._active_project_name = name
        return self.projects[name]

    # -- convenience passthroughs to the active project ------------------
    def names(self, include_deprecated=True):
        return self.active_project().names(include_deprecated)

    def active_names(self):
        return [c.name for c in self.active_project().active_classes()]

    def id_map(self):
        return self.active_project().id_map()

    # -- import / export -------------------------------------------------
    def import_txt(self, txt_path, project_name=None, replace=False):
        """Import a legacy ``data/*.txt`` list.

        IDs are assigned in **file order** starting at 0, which is exactly the
        index order the YOLO exporter previously used for that file -- so
        annotations exported before the migration stay valid.
        """
        if not os.path.isfile(txt_path):
            _fail('File not found: %s' % txt_path)

        if project_name is None:
            project_name = os.path.splitext(os.path.basename(txt_path))[0]
            if project_name.endswith('_classes'):
                project_name = project_name[:-len('_classes')]
        project_name = validate_project_name(project_name)

        with codecs.open(txt_path, 'r', 'utf8') as handle:
            raw_names = [line.strip() for line in handle]
        names = [n for n in raw_names if n]
        if not names:
            _fail('%s contains no class names.' % os.path.basename(txt_path))

        seen = set()
        ordered = []
        for name in names:
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            ordered.append(name)

        if project_name in self.projects and not replace:
            project = self.projects[project_name]
        else:
            project = ClassProject(project_name)
            self.projects[project_name] = project

        for index, name in enumerate(ordered):
            if project.by_name(name) is not None:
                continue
            if project.by_id(index) is None:
                project.add_class(name, class_id=index)
            else:
                project.add_class(name)
        return project

    def export_txt(self, txt_path, project_name=None):
        """Write a ``classes.txt`` whose line N is the class with ID N."""
        project = self.projects[project_name] if project_name else self.active_project()
        lines = project.ordered_names_for_yolo()
        with codecs.open(txt_path, 'w', 'utf8') as handle:
            handle.write('\n'.join(lines))
            if lines:
                handle.write('\n')
        return txt_path

    def export_project(self, json_path, project_name=None):
        project = self.projects[project_name] if project_name else self.active_project()
        payload = {'version': STORE_VERSION, 'project': project.to_dict()}
        _atomic_write_json(json_path, payload)
        return json_path

    def import_project(self, json_path, replace=False):
        with codecs.open(json_path, 'r', 'utf8') as handle:
            payload = json.load(handle)
        data = payload.get('project') or payload
        if 'name' not in data or 'classes' not in data:
            _fail('%s is not a LabelImgMaster class set.' % os.path.basename(json_path))
        project = ClassProject.from_dict(data)
        name = validate_project_name(project.name)
        if name in self.projects and not replace:
            suffix = 2
            while '%s %d' % (name, suffix) in self.projects:
                suffix += 1
            name = '%s %d' % (name, suffix)
        project.name = name
        self.projects[name] = project
        return project

    # -- persistence -----------------------------------------------------
    def to_dict(self):
        return {
            'version': STORE_VERSION,
            'active_project': self._active_project_name,
            'projects': {name: p.to_dict() for name, p in self.projects.items()},
        }

    def save(self):
        if not self.path:
            return False
        _atomic_write_json(self.path, self.to_dict())
        return True

    def load(self):
        if not self.path or not os.path.isfile(self.path):
            return False
        try:
            with codecs.open(self.path, 'r', 'utf8') as handle:
                payload = json.load(handle)
        except Exception as error:      # corrupt store must not block launch
            print('Could not read class store (%s); starting fresh.' % error)
            return False

        projects = payload.get('projects') or {}
        if not projects:
            return False
        self.projects = {}
        for name, data in projects.items():
            data.setdefault('name', name)
            self.projects[name] = ClassProject.from_dict(data)
        active = payload.get('active_project')
        if active not in self.projects:
            active = self.project_names()[0]
        self._active_project_name = active
        return True

    @classmethod
    def load_or_create(cls, path=None):
        store = cls(path)
        store.load()
        return store


def _atomic_write_json(path, payload):
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        'w', encoding='utf-8', dir=directory or None,
        prefix='.tmp_', suffix='.json', delete=False)
    try:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    shutil.move(handle.name, path)


# --------------------------------------------------------------------------
# usage scanning -- "is this class still referenced by saved annotations?"
# --------------------------------------------------------------------------

def find_class_usage(class_name, search_dirs, class_id=None, limit=None):
    """Return the annotation files that reference ``class_name``.

    Reads Pascal VOC ``.xml``, YOLO ``.txt`` and CreateML ``.json`` without
    importing Qt, so it can run before a UI warning is shown.
    """
    matches = []
    seen_dirs = set()
    for directory in search_dirs:
        if not directory:
            continue
        directory = os.path.abspath(directory)
        if directory in seen_dirs or not os.path.isdir(directory):
            continue
        seen_dirs.add(directory)
        for entry in sorted(os.listdir(directory)):
            if not entry.lower().endswith(ANNOTATION_EXTENSIONS):
                continue
            if entry.lower() == 'classes.txt':
                continue
            full = os.path.join(directory, entry)
            if not os.path.isfile(full):
                continue
            if _file_references_class(full, class_name, class_id):
                matches.append(full)
                if limit and len(matches) >= limit:
                    return matches
    return matches


def _file_references_class(path, class_name, class_id):
    extension = os.path.splitext(path)[1].lower()
    try:
        if extension == '.xml':
            with codecs.open(path, 'r', 'utf8', errors='ignore') as handle:
                body = handle.read()
            return '<name>%s</name>' % class_name in body
        if extension == '.json':
            with codecs.open(path, 'r', 'utf8', errors='ignore') as handle:
                body = handle.read()
            return '"%s"' % class_name in body
        if extension == '.txt':
            if class_id is None:
                return False
            with codecs.open(path, 'r', 'utf8', errors='ignore') as handle:
                for line in handle:
                    parts = line.split()
                    if len(parts) == 5 and parts[0].isdigit() and int(parts[0]) == class_id:
                        return True
            return False
    except Exception:
        return False
    return False


def rename_class_in_annotations(search_dirs, old_name, new_name):
    """Rewrite a class name inside already-saved annotations.

    Only Pascal VOC (``.xml``) and CreateML (``.json``) store the class *name*;
    YOLO ``.txt`` stores the numeric ID, which never changes on a rename, so
    those files are intentionally left alone (only ``classes.txt`` is
    regenerated, by the caller).

    Returns the list of files that were modified.
    """
    changed = []
    seen_dirs = set()
    for directory in search_dirs:
        if not directory:
            continue
        directory = os.path.abspath(directory)
        if directory in seen_dirs or not os.path.isdir(directory):
            continue
        seen_dirs.add(directory)
        for entry in sorted(os.listdir(directory)):
            extension = os.path.splitext(entry)[1].lower()
            if extension not in ('.xml', '.json'):
                continue
            full = os.path.join(directory, entry)
            if not os.path.isfile(full):
                continue
            try:
                with codecs.open(full, 'r', 'utf8') as handle:
                    body = handle.read()
            except Exception:
                continue
            if extension == '.xml':
                needle = '<name>%s</name>' % old_name
                replacement = '<name>%s</name>' % new_name
            else:
                needle = '"%s"' % old_name
                replacement = '"%s"' % new_name
            if needle not in body:
                continue
            try:
                with codecs.open(full, 'w', 'utf8') as handle:
                    handle.write(body.replace(needle, replacement))
                changed.append(full)
            except Exception:
                continue
    return changed
