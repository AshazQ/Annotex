# Annotex

Annotation, video and image tools behind one dashboard. Open Annotex, pick a
tool from **Home**, and every tool shares the same look, the same keyboard
habits (Ctrl+T theme, Ctrl+Shift+H Home, Ctrl+1…8 to jump to a tool), one
background job queue and the same safe-saving rules.

| Section | Tool | What it is for |
|---|---|---|
| Annotation | **ROI Studio** | Polygon ROI annotation for fixed-camera batches; xlsx + JSON outputs; COCO / YOLO-seg / VOC / mask export. |
| Annotation | **LabelImg Master** | Bounding-box labelling and review; class projects with permanent IDs; Pascal VOC, YOLO, CreateML written byte for byte as LabelImg always has. |
| Video | **Video to Images** | Frames every N seconds, N per second, every Nth frame, on scene change - or scrub and grab. |
| Video | **Video Trimmer** | Mark pieces with I / O; fast lossless or frame-accurate cuts; separate files or joined. |
| Video | **Video Converter** | MP4 H.264 / H.265, WebM VP9, MKV, AVI; resolution, frame rate, quality or target size. |
| Video | **Video Merger** | Join clips in order; lossless when they match, converted to a common format when they don't. |
| Images | **Image Converter** | JPEG / PNG / WebP / BMP / TIFF; resize, quality, strip EXIF, rename patterns. |
| Images | **Image Sorter** | Copy images into folders with keys 1–9, by rule, or with an ONNX model; every run can be undone. |

Built with PySide6 (Qt 6). Runs on Windows, macOS and Linux from the same
source; ffmpeg is bundled through `imageio-ffmpeg`, so nothing else needs
installing.

---

## Getting started

```
python bootstrap.py --shortcut --run
```

That creates a private environment in `.venv`, installs everything, runs the
self-tests, writes a desktop shortcut and starts Annotex. No administrator
rights, nothing installed system-wide. Add `--ai` to install onnxruntime for
AI sorting.

| Command | What it does |
|---|---|
| `python run.py` | the Home dashboard |
| `python run.py --tool <id>` | straight into a tool: `roi`, `labelimg`, `frames`, `trim`, `vconvert`, `merge`, `iconvert`, `sorter` |
| `python run.py --tool roi <folder>` | a tool with a folder open |
| `python run.py --selftest` | verify every tool on this machine, no display needed |
| `python run.py --check` | versions of Python, Qt, Pillow, lxml, ffmpeg, onnxruntime |
| `python bootstrap.py --upgrade` | refresh the environment |
| `python bootstrap.py --offline wheels/` | install from a folder of wheels |
| `python build/build_exe.py` | build a standalone executable for this platform (ffmpeg included) |
| `python tests/run_all.py` | every test suite, headless |

---

## The shell

A slim bar across the top holds **Home**, a tab for each tool you have opened,
the jobs indicator and the theme switch. Tools stay exactly where you left them
while you move between them.

| Key | |
|---|---|
| Ctrl+Shift+H | Home, from any tool |
| Ctrl+1 … Ctrl+8 | open a tool (numbers follow the order on Home) |
| Ctrl+J | every background job, from every tool |
| Ctrl+T | light / dark, for every tool at once |
| Ctrl+Q | quit - asks first if jobs are still running |

Leaving an annotation tool saves the image on screen first; if that write
fails, the move is stopped and you are asked.

---

## The media tools

All six share the same layout: inputs on the left, a preview in the middle,
options on the right, and the **job queue** underneath.

- **Background jobs.** Add files or whole folders (drag them in, or Ctrl+O /
  Ctrl+Shift+O) and start. Jobs run one at a time in the background with
  progress, Cancel, and Open (shows the result). Switch tools or go Home while
  they run.
- **Output beside the source by default** - `clip_frames/`, `trimmed/`,
  `converted/`, `merged/`, `<folder>_sorted/` - or a folder you choose.
- **Nothing half-written.** Results are written under a hidden `.part` name and
  renamed only when complete; a cancelled or failed job removes its partial
  output. Existing files are never overwritten - a free `name_2` is used.
- **Originals are never modified.**

### Video to Images
Pick frames automatically - **every N seconds**, **N per second**, **every Nth
frame**, or **only when the scene changes** (with a sensitivity slider) -
optionally within a start/end range and up to a maximum count. Or play and
scrub the video (Space, ← → frame, Shift+← → second) and press **G** to grab
the exact frame. Frames are named with their time in the video
(`clip_01m05s250.jpg`) and listed in `frames.csv`.

### Video Trimmer
Press **I** at the start of a piece and **O** at its end; add as many pieces as
you like (they show on the timeline and in an editable table). **Fast** copies
without re-encoding - instant, full quality, but a cut can only start on a
keyframe. **Exact** re-encodes for frame-accurate cuts. Save each piece as its
own file or join them into one.

### Video Converter
Presets: MP4 · H.264 (plays everywhere), MP4 · H.265 (smaller), WebM · VP9,
MKV · H.264, AVI · MPEG-4. Scale down to 2160p … 360p (never up, unless you
allow it), change the frame rate, and choose a quality - or aim for a file
size. Audio is kept.

### Video Merger
Order the clips with ↑ ↓. When they share codec, resolution, frame rate and
audio format they are joined **losslessly**. Otherwise they are converted to
one resolution (the first clip's, the largest, or a standard size), frame rate
and format; clips of a different shape get black bars rather than being
stretched, and clips without sound get silence.

### Image Converter
Convert between JPEG, PNG, WebP, BMP and TIFF (or keep each image's format).
Resize by longest side, percent, or to fit a box; set JPEG/WebP quality, PNG
compression, lossless WebP; fill transparency with a colour when the target
has none; **strip EXIF** (the EXIF rotation is applied first, so photos stay
upright; colour profiles are kept). Rename with a pattern: `{name}`, `{n}` /
`{n:05}`, `{parent}`, `{ext}`. Folders keep their sub-folder structure.

### Image Sorter
Choose a folder of images and where the copies go (`<folder>_sorted` by
default). Sorting **always copies**, and every copy is logged in
`sort_log.csv`, so **Undo a run…** can take any sort back.

- **By hand** - name up to nine folders, then press **1–9** to copy the image
  into that folder and move on; ← → move without sorting; Ctrl+Z undoes.
- **By rule** - filename parts (`SITE_cam3_…` → `SITE_cam3`), a regular
  expression, date taken (EXIF, else file date; year / month / day / hour),
  exact resolution, orientation, LabelImg annotation status (labelled /
  background / unannotated) or ROI Studio status (roi / no_roi / unannotated).
  **Preview** shows the folders and counts before anything is copied.
- **With a model (ONNX)** - load a classifier or a YOLO detector
  (v5 / v8 / v11 / end-to-end outputs). Class names come from the model's
  metadata or a labels file. Set a confidence threshold; below it a classifier's
  image goes to `_unsure` and a detector's to `_empty`. Map classes to folder
  names (or clear one to ignore that class), choose whether a detector image
  with several classes is copied to the best one or to all, and **test on the
  image shown** before sorting. Needs `onnxruntime` (`python bootstrap.py --ai`).

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
rubber-band select, double-click a box to change its class, right-click for its
menu. Overlapping boxes pick the smallest one under the cursor. Snapping pulls
edges onto the image border and onto other boxes.

### Classes

Classes live in **projects**, stored in `~/.labelImgMaster/class_projects.json`
- the same file LabelImg Master has always used. IDs are permanent (YOLO stores
them); deleting a class in use offers deprecate or reassign; renames rewrite
saved VOC and CreateML files; `.txt` class lists and exported sets can be
imported.

### Files and protection

| Format | One file per image | Notes |
|---|---|---|
| Pascal VOC | `name.xml` | `verified="yes"` and `difficult` live in the file |
| YOLO | `name.txt` + `classes.txt` | class index = the class's permanent ID |
| CreateML | `name.json` | |

The writers are LabelImg's own and produce the same bytes they always did -
`python run.py --selftest` checks this against the original modules whenever
the `labelImg-master` folder is next to Annotex. Every write is verified before
it replaces the old file, the previous version is kept in `.labelimg_backup/`,
external changes are detected, unsaved work is drafted, a lock file prevents
two sessions colliding, and every decision is logged in `.labelimg_audit.jsonl`.

Also: apply boxes to many images, mark many as background, import and merge
another annotator's folder, COCO export, review mode, dashboard and HTML
report, per-batch settings (`.labelimg.json`).

---

## ROI Studio

Unchanged in behaviour and outputs, and it still reads its own settings file.
See its welcome tour (Window → Show the welcome tour) and `?` for every
shortcut. Outputs: `roi_annotations.xlsx`, `roi_annotations.json`,
`roi_map.json`, `printed_roi/`, `no_roi/`, and COCO / YOLO-seg / VOC / mask
exports.

---

## Layout

```
Annotex/
├── run.py, bootstrap.py, requirements.txt, pyproject.toml
├── build/build_exe.py
├── annotex/
│   ├── app.py              entry point, environment checks, crash handling
│   ├── config.py           paths and the shell's settings
│   ├── core/               no Qt: safe I/O, undo, drafts, audit log, HTML
│   │                       report kit, background job model, media/ffmpeg
│   ├── ui/                 shared Qt kit: theme, icons, viewport, film strip,
│   │                       panels, dialogs, job queue, media widgets, media page
│   ├── shell/              Home dashboard, the window, the tool registry
│   ├── resources/
│   └── apps/
│       ├── roi/            ROI Studio
│       ├── labelimg/       LabelImg Master
│       ├── video/          Video to Images, Trimmer, Converter, Merger
│       └── images/         Image Converter, Image Sorter
└── tests/                  roi/, labelimg/, media/, shell/, run_all.py
```

### Adding a tool

Add one `ToolSpec` to `annotex/shell/registry.py` (name, section, icon, a
`create(host)` function). The shell builds its card, tab and Ctrl+<n> shortcut
and creates the tool on first use. A tool that processes files should subclass
`annotex.ui.media_page.MediaToolPage` - it gets the header, menus, theme, job
queue and the suite contract for free and only fills in `build()`.
