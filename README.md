# FluxBox Suite

Annotation and review tools behind one dashboard. Open the suite, pick a tool
from **Home**, and every tool shares the same look, the same keyboard habits
(Ctrl+K command palette, `?` shortcut sheet, Ctrl+T theme) and the same
safe-saving machinery.

| Tool | What it is for |
|---|---|
| **ROI Studio** | Polygon ROI annotation for fixed-camera batches: polygons, rectangles, circles, freehand; xlsx + JSON outputs; COCO / YOLO-seg / VOC / mask export. |
| **LabelImg Master** | Bounding-box labelling and review of detection frames: class projects with permanent IDs, number-key class hotkeys, one-key accept; Pascal VOC, YOLO or CreateML files written exactly as LabelImg always has. |

Built with PySide6 (Qt 6). Runs on Windows, macOS and Linux from the same
source.

---

## Getting started

```
python bootstrap.py --shortcut --run
```

That creates a private environment in `.venv`, installs everything, runs the
self-tests, writes a desktop shortcut and starts the suite. No administrator
rights, nothing installed system-wide.

Afterwards:

| Command | What it does |
|---|---|
| `python run.py` | the Home dashboard |
| `python run.py --tool labelimg` | straight into LabelImg Master |
| `python run.py --tool roi <folder>` | ROI Studio with a batch open |
| `python run.py --selftest` | verify every tool on this machine, no display needed |
| `python run.py --check` | print the environment report |
| `python bootstrap.py --upgrade` | refresh the environment |
| `python bootstrap.py --offline wheels/` | install from a folder of wheels |
| `python build/build_exe.py` | build a standalone executable for this platform |
| `python tests/run_all.py` | every test suite, headless |

Requirements: Python 3.9+, plus PySide6-Essentials, Pillow, openpyxl and lxml
(the bootstrap installs them).

---

## The shell

A slim bar across the top holds **Home**, a tab per tool and the theme switch.
Tools open the first time you use them and then stay exactly where you left
them while you move between them.

| Key | |
|---|---|
| Ctrl+Shift+H | Home, from any tool |
| Ctrl+1 / Ctrl+2 | ROI Studio / LabelImg Master |
| Ctrl+T | light / dark, for every tool at once |
| Ctrl+Q | quit |

Leaving a tool - for Home, another tool or quitting - saves the image on
screen first. If that write fails, the move is stopped and you are asked;
nothing disappears silently.

---

## LabelImg Master

### Working through a folder

**Ctrl+U** opens a folder; every image in it, sub-folders included, becomes a
frame. Annotations are saved beside the images, or wherever **Ctrl+R** points
them.

| Key | |
|---|---|
| **W** | draw a box (hold **Ctrl** for a square) |
| **V** / **H** | select tool / pan tool |
| **1 … 9, 0** | pick the 1st – 10th class; with a box selected, relabel it |
| **Shift+1 … 0** | the 11th – 20th class |
| **Enter** | accept this frame as it is and go to the next |
| **N** | background: save an empty annotation and go on |
| **Space** | toggle verified |
| **D** / **A** | next / previous image (**Shift+D**: next unannotated) |
| **Ctrl+S** | save (and move on, when auto-advance is on) |
| **Ctrl+V** / **Ctrl+Shift+V** | replace with / add the previous frame's boxes |
| **Ctrl+Z** / **Ctrl+Y** | undo / redo |
| Arrows, Shift+Arrows | nudge the selection 1 / 10 px |
| **Ctrl+E** | change the class of the selection |
| **/** | search classes |
| **Ctrl+M** | Class Manager |
| **F6 / F7 / F8 / F9** | review mode / dashboard / HTML report / change history |
| **Ctrl+K** / **?** | command palette / every shortcut |

With the select tool: drag a box to move it, drag any of its eight handles to
resize, Shift+click to add to the selection, drag on empty space to
rubber-band select, double-click a box to change its class, right-click for
its menu. Overlapping boxes pick the smallest one under the cursor, so a
helmet inside a person box is still easy to grab. Snapping pulls edges onto the
image border and onto other boxes.

New boxes take the **active class** without a dialog (the chip above the class
list shows which). With no active class - or with "skip the label dialog"
turned off - you are asked, and a name that is not in the project yet is
added to it.

### Classes

Classes live in **projects** (one per site or deployment), stored in
`~/.labelImgMaster/class_projects.json` - the same file LabelImg Master has
always used, so existing projects carry over.

- IDs are permanent. YOLO files store the class ID, so a class is never
  renumbered; deleting one leaves a hole that `classes.txt` fills with
  `_reserved_N`.
- Deleting a class that saved annotations still use offers to deprecate it or
  reassign its boxes instead.
- Renaming rewrites the name inside saved VOC and CreateML files (YOLO keeps
  the ID, which did not change).
- Import a legacy `predefined_classes.txt` (IDs follow the file order, which
  is the order YOLO already used) or a class set exported from another machine.

### Files

| Format | One file per image | Notes |
|---|---|---|
| Pascal VOC | `name.xml` | `verified="yes"` and the `difficult` flag live in the file |
| YOLO | `name.txt` + `classes.txt` | class index = the class's permanent ID |
| CreateML | `name.json` | |

The writers are LabelImg's own and produce **the same bytes they always
did** - `python run.py --selftest` checks this against the original modules
whenever the `labelImg-master` folder is next to the suite.

An image that already has an annotation keeps its format when it is opened.
Saving it in another format moves the old file into the backup folder, so a
stale `.xml` can never win over a fresh `.txt` on reload.

### How your work is protected

- Every write goes to a temporary file, is parsed back, and only then replaces
  the old file.
- The previous version of each annotation is kept in `.labelimg_backup/`
  beside it. **Batch → Restore this image from the backup** puts it back on
  the canvas for review.
- An annotation changed on disk since this session read it (another session,
  a sync client, a script) is detected and you are asked before it is
  overwritten.
- Unsaved boxes are drafted every few seconds and offered back after a crash.
- A lock file stops two sessions from saving over each other in one folder.
- A folder that cannot be written to opens read-only.
- Every save and decision is appended to `.labelimg_audit.jsonl` (F9).
- Delete image (Ctrl+Shift+D) moves the image and its annotation into
  `deleted_images/`; copy image puts a copy in `copy_images/`. Neither folder
  is scanned as part of the batch.
- YOLO has nowhere in the file to record "verified", so it is kept in
  `.labelimg_verified.json` beside the images instead of being forgotten.

### Many images at once

- **Apply these boxes to other images** (Ctrl+Shift+A): pick all, the same
  camera, the not-started ones, or everything after this frame. Each box is
  fitted to each image's size.
- **Mark several images as background**: the same picker, empty annotations.
- **Import or merge** (Ctrl+I): another annotator's VOC / YOLO / CreateML
  folder, matched by image name. Choose union (duplicates merged), keep theirs,
  keep the larger set, or keep yours on a conflict - the conflicts are listed
  before anything is written.
- **Export to COCO** (Ctrl+Shift+E): one `export_coco/annotations.json`,
  optionally narrowed to some classes. Category id = class ID + 1 (0 stays free
  for background); the original ID is carried as `labelimg_id`.

### Review and reporting

- **Review mode** (F6): every image at full size with its boxes in their class
  colours; filter to labelled, background, not started or not verified; toggle
  verified; jump to edit.
- **Dashboard** (F7): progress, verified count, throughput and class balance.
- **HTML report** (F8): `labelimg_report.html`, self-contained, with the same
  numbers in `labelimg_summary.json`.
- The status bar keeps LabelImg's **TAI / BAI** counters: images with an
  annotation, and annotated images with no boxes.

### Batch settings

**Batch → Save these settings for this batch** writes `.labelimg.json` beside
the images: save format, class project, annotation folder and the workflow
toggles. Anyone who opens the folder gets them for the session without their
own preferences changing.

### What changed from labelImg-master

Dropped, as agreed: voice readout, auto-focus spotlight, scrolling label
banner, crop preview, beginner/advanced mode, per-box line/fill colour pickers
(the class colour is used) and the upstream tutorial links.

Keys that moved: the class search is **/** (Ctrl+K is the command palette in
every tool), and Settings has no default key. Everything can be rebound in
Settings → Shortcuts.

Fixed along the way: CreateML boxes were loaded as "difficult"; a stale file
in the previous format could win on reload; deleting an image left its
annotation behind; YOLO forgot the verified flag.

---

## ROI Studio

Unchanged in behaviour and outputs, and it still reads its own settings file,
so preferences carry over. See the in-app tour (Window → Show the welcome
tour) and `?` for the full shortcut sheet. Its outputs: `roi_annotations.xlsx`,
`roi_annotations.json`, `roi_map.json`, `printed_roi/`, `no_roi/`, and COCO /
YOLO-seg / VOC / mask exports.

---

## Layout

```
FluxBox-Suite/
├── run.py, bootstrap.py, requirements.txt, pyproject.toml
├── build/build_exe.py
├── fluxbox/
│   ├── app.py              entry point, environment checks, crash handling
│   ├── config.py           suite paths and the shell's settings
│   ├── core/               shared, no Qt: safe I/O, undo history, drafts,
│   │                       audit log, session timer, HTML report kit
│   ├── ui/                 shared Qt kit: theme, icons, image viewport,
│   │                       film strip, side panels, dialogs, shortcut helpers
│   ├── shell/              Home dashboard, the suite window, tool registry
│   ├── resources/
│   └── apps/
│       ├── roi/            ROI Studio
│       └── labelimg/       LabelImg Master
│           ├── core/       classes, boxes, formats, annotations, import,
│           │               export, report - no Qt
│           └── ui/         window, canvas, panels, dialogs
└── tests/                  roi/, labelimg/, shell/, run_all.py
```

### Adding a tool

Add one `ToolSpec` to `fluxbox/shell/registry.py`. The shell builds its card,
tab and Ctrl+<n> shortcut from it and creates the tool's window on first use.
The window takes `host` and may implement `tool_activated`,
`tool_deactivating`, `tool_close`, `tool_apply_theme` and `tool_open`; the
docstring in `registry.py` spells out the contract. Build it from
`fluxbox.ui` and `fluxbox.core` and it will look and behave like the rest.
