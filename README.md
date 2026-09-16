# Annotex

Annotation, video and image tools behind one dashboard. Open Annotex, pick a
tool from **Home**, and every tool shares the same look, the same keyboard
habits (Ctrl+T theme, Ctrl+Shift+H Home, Ctrl+1…9 to jump to a tool), one
background job queue and the same safe-saving rules.

| Section | Tool | What it is for |
|---|---|---|
| Annotation | **ROI Studio** | Polygon ROI annotation for fixed-camera batches; xlsx + JSON outputs; COCO / YOLO-seg / VOC / mask export. |
| Annotation | **LabelImg Master** | Bounding-box labelling and review; AI select with SAM; class projects with permanent IDs; Pascal VOC, YOLO, CreateML written byte for byte as LabelImg always has. |
| Annotation | **LabelImg Shapes** | Polygons, oriented boxes, circles, ellipses and freehand outlines; AI select with SAM; editable shape files; YOLO segmentation, YOLO OBB and COCO export. |
| Video | **Video to Images** | Frames every N seconds, N per second, every Nth frame, on scene change - or scrub and grab. |
| Video | **Video Trimmer** | Mark pieces with I / O; fast lossless or frame-accurate cuts; separate files or joined. |
| Video | **Video Converter** | MP4 H.264 / H.265, WebM VP9, MKV, AVI; resolution, frame rate, quality or target size. |
| Video | **Video Merger** | Join clips in order; lossless when they match, converted to a common format when they don't. |
| Images | **Image Converter** | JPEG / PNG / WebP / BMP / TIFF; resize, quality, strip EXIF, rename patterns. |
| Images | **Image Sorter** | Copy images into folders with keys 1–9, by rule, with an ONNX model, or by example; every run can be undone. |

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
rights, nothing installed system-wide. Add `--ai` to install onnxruntime and
numpy, for AI select in the labelling tools and AI sorting in the Image
Sorter.

| Command | What it does |
|---|---|
| `python run.py` | the Home dashboard |
| `python run.py --tool <id>` | straight into a tool: `roi`, `labelimg`, `shapes`, `frames`, `trim`, `vconvert`, `merge`, `iconvert`, `sorter` |
| `python run.py --tool roi <folder>` | a tool with a folder open |
| `python run.py --selftest` | verify every tool on this machine, no display needed |
| `python run.py --check` | versions of Python, Qt, Pillow, lxml, ffmpeg, onnxruntime |
| `python bootstrap.py --upgrade` | refresh the environment |
| `python bootstrap.py --offline wheels/` | install from a folder of wheels |
| `python build/build_exe.py` | build a standalone executable for this platform (ffmpeg included) |
| `python tests/run_all.py` | every test suite, headless - including a batch built to break the labelling tools and a thousand random operations against each |

---

## The shell

A slim bar across the top holds **Home**, a tab for each tool you have opened,
the jobs indicator, **Display** and **Diagnostics**. Tools stay exactly where
you left them while you move between them.

**Diagnostics** (the `?` in the bar, or **F1**) shows what Annotex found on
this machine - Python, Qt, ffmpeg, whether AI select has a model - alongside
the recent log, with buttons to copy the lot into a bug report, open the log
and crash folders, and run every tool's checks again. It is the same report
as `--check` and the same checks as `--selftest`, for when there is no
terminal to ask from.

**The image comes first.** In ROI Studio, LabelImg Master and LabelImg Shapes
the tools sit in a pill-shaped rail down the left, so the image starts at the
top of the window. The side panel folds into a slim strip (its button, or
**Ctrl+Shift+L**) that keeps Save, Next and Previous within reach, and the
filmstrip folds away under the one-line bar that shows the folder and image.
Each tool remembers what you folded. Nothing is taken away - every button is
still one click away.

**Display** sets the **Interface size** for the whole of Annotex: Automatic
(the largest size that fits the screen without scrolling), or 75 % to 150 %.
Smaller fits more on a laptop running Windows at 125 % or 150 % scaling. The
size is used from the next start; *Save and restart now* does that straight
away, saving open work first. Every dialog scrolls when the screen is too
short for it, so no button is ever out of reach.

**Home** greets you, offers to **continue where you left off** (the last
folders you worked in, with a thumbnail, how many images are annotated and a
Resume button), and shows the annotation tools as large cards and the video
and image tools as compact tiles. The **✕** on a Continue card, or beside a
folder under a tool card's recent folders, takes that folder off the list; the
folder itself is never touched.

**Every tool has its own colour** - ROI Studio orange, LabelImg Master blue,
LabelImg Shapes violet, Video to Images cyan, Trimmer red, Converter yellow,
Merger pink, Image Converter green, Image Sorter teal - on its card, its tab,
its buttons and its selection, so you always know where you are.

**Themes.** Pick one in any tool's **Settings** (the gear) or its
**View → Theme** menu; it applies to every tool, each still in its own colour.

| Dark | Light |
|---|---|
| Annotex Dark, True Black (OLED), Dark Modern, Monokai, Dracula, One Dark, GitHub Dark, Solarized Dark, Nord, Gruvbox Dark, Catppuccin Mocha, Night Owl, Tokyo Night | Annotex Light, Light Modern, One Light, GitHub Light, Solarized Light, Gruvbox Light, Catppuccin Latte |

**Ctrl+T** switches to the theme's partner (Dracula → Annotex Light,
GitHub Dark ↔ GitHub Light, …). "Follow the system" is there too.

| Key | |
|---|---|
| Ctrl+Shift+H | Home, from any tool |
| Ctrl+1 … Ctrl+9 | open a tool (numbers follow the order on Home) |
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
- **By example** - no training and no class list: make a folder with one
  sub-folder per category and a few example pictures in each, then
  **Compare**. Every image is scored against the examples (its closest one, or
  their average), and the two sliders decide where it goes - below **Alike at
  least** it goes to `_unmatched`, and too close to a second category to
  `_unsure`. The sliders start where the examples themselves suggest, the
  table lists the weakest matches first with a preview of each, and moving a
  slider re-decides every image instantly without comparing again. Compare by
  **how they look** (layout and colour; nothing to download - right for the
  same scene, the same camera, near-duplicates) or by **what is in them**,
  with any ONNX image model such as a CLIP or DINOv2 image encoder. Results
  are cached, so comparing again after adding an example costs only that
  example. Examples kept inside the folder being sorted are never sorted
  themselves. Needs `numpy` (`python bootstrap.py --ai`).

---

## Dataset Tools

Six independent tools for folders of images with YOLO-style `.txt` labels
beside them (`a.jpg` + `a.txt`). Use any of them, in any order - none needs
another to have run first.

| Tool | What it does |
|---|---|
| Delete empty .txt files | removes label files with nothing but spaces or blank lines in them (sub-folders optional); images are never touched |
| Move unpaired images | moves images with no `.txt` of the same name into `unpaired images/` |
| Rename image + label pairs | renames every pair to `name_001.jpg` + `name_001.txt`, … in natural order |
| Split into parts | moves pairs into `part_1`, `part_2`, … with the counts you give (`500, 500, rest`) |
| Rename part folders | renames `part_1`, `part_2`, … to `name_1`, `name_2`, …, keeping the numbers |
| Zip each folder | compresses each sub-folder into `zipped/<folder>.zip`, leaving the folders as they are |
| Check & fix labels | finds lines that break training - class ids that are not whole numbers or not in `classes.txt` / `data.yaml`, the wrong number of values, coordinates outside the image, boxes with no size (or under a minimum), repeated boxes - and fixes what you tick; the rest is reported |
| Train / val / test split | copies (or moves) pairs into `images/train`, `labels/train`, … by your percentages, repeatable with a seed, keeping rare classes in every set, and writes `data.yaml` |
| Class tools | counts the boxes of each class, and renumbers, merges or deletes classes across every label (`3>1, 4>1, 7>delete`) |

**Nothing happens without a preview.** Choose a folder and a tool, and the
table lists every file that would be removed, moved, renamed or zipped - and
anything that stops it, in plain words - before **Run** is enabled.

**Every run can be undone**, even after closing Annotex: History lists the runs
for the folder, and *Undo selected run* puts things back as they were. A
"deleted" file is only moved into a hidden `.annotex_removed` folder inside the
dataset until then.

Built for folders on Windows as much as Linux and macOS: names are checked
against Windows' rules (no `CON`, `?`, trailing dots, …), images and labels are
matched without regard to case, a pair's image and label always move and rename
together, renames go through temporary names so an interruption never leaves
two files wanting one name, a file that is locked or refused is reported and
skipped, and an existing file is never overwritten. The work runs in the
background and can be cancelled.

---

## LabelImg Master

### Working through a folder

**Ctrl+O** opens a folder; every image in it, sub-folders included, becomes a
frame. Annotations are saved beside the images, or wherever **Ctrl+R** points
them.

| Key | |
|---|---|
| **W** | draw a box (hold **Ctrl** for a square) |
| **S** | AI select - click the object and the box is proposed |
| **Y** | auto-label with your own YOLO model - every object is proposed at once |
| **V** / **H** | select tool / pan tool |
| **1 … 9, 0** | pick the 1st – 10th class; with a box selected, relabel it |
| **Shift+1 … 0** | the 11th – 20th class |
| **Enter** | accept this frame as it is and go to the next |
| **N** | background: save an empty annotation and go on |
| **Space** | toggle verified |
| **D** / **A** (or PgDown / PgUp, or the round arrows on the image) | next / previous image (**Shift+D**: next unannotated) |
| **Ctrl+S** | save (and move on, when auto-advance is on) |
| **Ctrl+Shift+D** | move the image (and its annotation) into `deleted_images` |
| **Ctrl+C** / **Ctrl+X** / **Ctrl+V** | copy / cut / paste the selected boxes - onto any other image |
| **Ctrl+Shift+V** / **Ctrl+Alt+V** | replace with / add the previous frame's boxes |
| **Ctrl+Z** / **Ctrl+Y** | undo / redo |
| Arrows, Shift+Arrows | nudge the selection 1 / 10 px |
| **Ctrl+E** / **Del** / **Ctrl+Shift+Del** | change class / delete / clear every box |
| **Ctrl+0** / **Ctrl+1** / **Z** | fit / 100 % / zoom to the selection |
| **L** | show or hide class names |
| **/** | search classes (**Ctrl+[** / **Ctrl+]** previous / next class) |
| **Ctrl+M** / **Ctrl+,** | Class Manager / Settings |
| **F6 / F7 / F8** | review mode / dashboard / HTML report |
| **Ctrl+K** / **?** | command palette / every shortcut |

**The same keys in every annotation tool.** ROI Studio, LabelImg Master and
LabelImg Shapes share one keymap - D / A for images, Ctrl+S to save, Ctrl+0 to
fit, V / H / W / P for the tools, Ctrl+Shift+D to move an image out - and any
key can be changed in that tool's **Settings → Shortcuts**.

With the select tool: drag a box to move it, drag any of its eight handles to
resize, Shift+click to add to the selection, drag on empty space to
rubber-band select, double-click a box to change its class, right-click for its
menu. Overlapping boxes pick the smallest one under the cursor. Snapping pulls
edges onto the image border and onto other boxes.

**Copying boxes onto another image.** Select the boxes you want (Shift+click
adds to the selection, or rubber-band them), **Ctrl+C**, move to any other
image, **Ctrl+V**. Nothing selected means the whole image. **Ctrl+X** cuts.
The clipboard survives moving between images, switching to LabelImg Shapes -
where the boxes arrive as oriented boxes - and closing the tool, because the
copy also goes onto the system clipboard as JSON. Pasting onto an image of a
different size scales the boxes to it instead of dropping them in the corner.
To take a whole frame's annotation across instead, **Ctrl+Shift+V** replaces
this image's boxes with the previous image's and **Ctrl+Alt+V** adds them.

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
external changes are detected, unsaved work is drafted, and a lock file
prevents two sessions colliding. Nothing else is written beside your images:
no log of what was annotated when, and no count-and-time record of the work.

Also: apply boxes to many images, mark many as background, import and merge
another annotator's folder, COCO export, review mode, dashboard and HTML
report, per-batch settings (`.labelimg.json`).

---

## LabelImg Shapes

A separate tool for everything that is not an upright box. LabelImg Master is
untouched, and the two keep separate class lists.

| Key | |
|---|---|
| **P** | polygon - click points; click the first point, Enter or right-click to close |
| **O** | oriented box - drag it out, then turn it with the round handle |
| **C** | circle - drag out from the centre |
| **E** | ellipse - drag its box (Shift for a circle), then turn it |
| **F** | freehand - hold the button and trace the outline |
| **S** | AI select - click the object and the outline is proposed |
| **Y** | auto-label with your own YOLO model - a rectangle for every object |
| **V** / **H** (or hold Space and drag) | select / pan |
| **Space** (a tap) | mark the image verified |
| **1 … 9, 0** | pick a class; with a shape selected, relabel it |
| **[** / **]** | rotate the selection 15° (Shift while dragging snaps to 15°) |
| **D** / **A** (or PgDown / PgUp, or the round arrows on the image) | next / previous image - leaving an image saves it |
| **Ctrl+S** | save (an image saved with no shapes counts as background) |
| **Ctrl+Shift+D** | move the image (and its shapes file) into `deleted_images` |
| **Ctrl+0** / **Z** / **L** | fit / zoom to the selection / show class names |
| **Ctrl+C** / **Ctrl+X** / **Ctrl+V** | copy / cut / paste the selected shapes - onto any other image |
| **Ctrl+Shift+V** | add every shape from the previous image |
| **Ctrl+Z** / **Ctrl+Y** | undo / redo - while a polygon is being drawn, Ctrl+Z (or Backspace) takes back just the last point |
| **Ctrl+E** / **Ctrl+D** / **Del** | change class / duplicate / delete |
| **Ctrl+M** / **Ctrl+Shift+E** / **Ctrl+,** | Class Manager / export / Settings |

Every key above can be changed in **Settings → Keyboard shortcuts**.

With the select tool: drag a shape to move it; oriented boxes and ellipses have
eight handles that resize along their own axes, circles have four that change
the radius; polygons and freehand outlines show their points - drag one,
Ctrl+click to delete it, double-click an edge to add one.

**Files.** Each image gets `name.shapes.json` beside it, holding the shapes
exactly as drawn (a circle keeps its centre and radius, an oriented box its
angle), so everything stays editable. Writes are atomic, the previous version
is kept in `.labelimg_shapes_backup/`, and a lock file stops two sessions
colliding.

**Export** (Ctrl+Shift+E) never changes the shape files:

| Export | Folder | What you get |
|---|---|---|
| YOLO segmentation | `export_yolo_seg/` | every shape as a polygon (circles and ellipses sampled); `labels/`, `classes.txt`, `data.yaml` |
| YOLO oriented boxes | `export_yolo_obb/` | oriented boxes as drawn, other shapes as their tightest rotated box |
| COCO | `export_coco_shapes/annotations.json` | segmentation, bbox and area, plus the exact shape of each annotation |

YOLO class numbers are the Class Manager's permanent IDs, counted from 0.

---

## AI select (SAM)

Both labelling tools have a **Segment Anything** tool, the way LabelMe does
it: press **S**, click the object, and the tool proposes the shape - a box in
LabelImg Master, a polygon in LabelImg Shapes.

| | |
|---|---|
| click | include this - the model looks for the object under the cursor |
| right-click, or Shift+click | exclude this - trim the proposal back |
| drag | a rough box to look inside |
| **Enter** (or double-click) | keep the proposal, with the active class |
| **Backspace** or **Ctrl+Z** | take back the last click |
| **Esc** | drop the proposal and start again |

Each extra click starts from the proposal already on screen, so it refines
that proposal instead of starting over. Enter, Esc, Backspace and Ctrl+Z work
even after a click on the class list or the filmstrip has moved the focus.

Nothing is added to the image until you accept it, and what is added is an
ordinary box or polygon: drag it, resize it, relabel it, undo it like any
other.

**Setting it up.** Once:

```
python bootstrap.py --ai          # installs onnxruntime and numpy
```

then press **S**, say yes to *Download or choose a model now?*, pick a model
and press **Download** - the LabelMe way. The dialog fetches the two ONNX
files, checks them, switches the AI tool on and closes. The choices are the
quantized Segment Anything models LabelMe itself uses, from LabelMe's GitHub
releases:

| Model | Download | |
|---|---|---|
| SAM ViT-B | 104 MB | fastest - the one to start with |
| SAM ViT-L | 316 MB | more accurate, slower |
| SAM ViT-H | 634 MB | most accurate, slowest |

A download that stops - Stop, closing the dialog, a dropped connection -
resumes from where it was the next time, and a file that arrives cut short or
damaged is refused rather than used. Downloading is the only time Annotex
touches the network for this; no image ever leaves your machine.

**Your own model.** The model is two ONNX files - an *encoder* and a
*decoder*. Put them in the model folder and pick them in
**Settings → AI** (or **Window → AI model**). The folder is shown in that
dialog - `%APPDATA%\Annotex\models` on Windows,
`~/Library/Application Support/Annotex/models` on macOS,
`~/.config/annotex/models` on Linux - and a `models/` folder beside Annotex
itself is searched too, for a shared or portable copy. Files whose names
contain *encoder* and *decoder* are paired up automatically; anything else can
be pointed at by hand. The dialog opens the model before accepting it, so a
file that cannot be used is refused there rather than on your first click.

Exports from Segment Anything, MobileSAM, EdgeSAM and samexporter all work:
the graph is inspected rather than assumed. MobileSAM (about 40 MB) is the
quickest on a laptop; a ViT-B export is more accurate and slower. The slow
half of the model runs once per image, in the background, so only the first
click on a new image waits; every click after that is immediate.

Without onnxruntime and numpy the tool simply says what to install, and
everything else in Annotex works exactly as before.

### Auto-label with your own YOLO model

Bring the detector you trained - an `.onnx` export, e.g. from Ultralytics with
`yolo export model=best.pt format=onnx` - and let it propose the boxes.
Choose it once in **Tools → YOLO model…** (LabelImg Master and LabelImg
Shapes); YOLOv5, v8 / v11 and exports with NMS built in are all understood.

* **On the image - Y.** Every object the model finds is proposed, dashed, with
  its confidence. Click a proposal to drop it (click again to bring it back),
  **Enter** keeps the rest, **Esc** drops them all. LabelImg Master gets
  boxes, LabelImg Shapes rectangles. **Ctrl+Z** takes them back like anything
  else.
* **The whole folder - Tools → Pre-label the folder with YOLO….** The model runs
  in the background over every image that has no annotation yet. Images that
  already have one are never touched, and nothing is written where the model
  finds nothing - then you review the folder as usual.

The model's classes are matched to your project's by name. For any that do
not match you choose once - map it to an existing class, add it as a new one,
or ignore it - and the choice is remembered for that model (*Forget class
choices* asks again). The confidence is set in the same dialog. The model runs
on this machine; nothing is uploaded. Detection models only: segmentation,
oriented-box, classification and pose exports are refused with a message.

---

## ROI Studio

Unchanged in behaviour and outputs, and it still reads its own settings file.
See its welcome tour (Window → Show the welcome tour) and `?` for every
shortcut. Its keys follow the shared keymap: **D** / **A** next / previous
image, **Ctrl+S** save, **N** no_roi, **V** / **H** / **W** / **P** / **C** /
**F** select / pan / rectangle / polygon / circle / freehand, **Ctrl+D**
duplicate, **Ctrl+Shift+V** the previous image's ROIs, **Ctrl+0** / **Ctrl+1**
fit / 100 %, **Ctrl+Shift+D** move the image into `deleted_images` (its rows
leave the outputs), **Ctrl+Shift+S** export now - all changeable in Settings. Outputs: `roi_annotations.xlsx`, `roi_annotations.json`,
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
│   ├── core/               no Qt: safe I/O, undo, drafts, the annotation
│   │                       clipboard, SAM + mask maths, HTML report kit,
│   │                       background job model, media/ffmpeg
│   ├── ui/                 shared Qt kit: theme, icons, viewport, film strip,
│   │                       panels, dialogs, job queue, media widgets, media page
│   ├── shell/              Home dashboard, the window, the tool registry
│   ├── resources/
│   └── apps/
│       ├── roi/            ROI Studio
│       ├── labelimg/       LabelImg Master
│       ├── shapes/         LabelImg Shapes
│       ├── video/          Video to Images, Trimmer, Converter, Merger
│       └── images/         Image Converter, Image Sorter
└── tests/                  roi/, labelimg/, shapes/, media/, shell/, ai/,
                         robust/ (hostile folders, random operations),
                         run_all.py
```

### Adding a tool

Add one `ToolSpec` to `annotex/shell/registry.py` (name, section, icon, a
`create(host)` function). The shell builds its card, tab and Ctrl+<n> shortcut
and creates the tool on first use. A tool that processes files should subclass
`annotex.ui.media_page.MediaToolPage` - it gets the header, menus, theme, job
queue and the suite contract for free and only fills in `build()`.

---

## Credits

Annotex is written by **Ashaz Qureshi**.

**LabelImg Master** is built on [LabelImg](https://github.com/HumanSignal/labelImg)
by Tzutalin. Its Pascal VOC, YOLO and CreateML readers and writers come from
LabelImg's code (MIT licence), which is why those files come out byte for byte
the same as LabelImg's. The full LabelImg copyright notice is in
[`NOTICE`](NOTICE).

## Licence

Annotex is released under the **GNU General Public License v3.0** - see
[`LICENSE`](LICENSE). The LabelImg-derived parts keep their MIT notice, as
listed in [`NOTICE`](NOTICE).
