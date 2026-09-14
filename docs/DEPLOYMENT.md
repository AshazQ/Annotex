# Deploying Annotex to annotators

Three ways, from least to most effort for you.

## 1. Copy the folder and run the bootstrap

Best when annotators have Python and can run one command.

1. Copy the whole `Annotex` folder to the machine (or clone it).
2. On that machine:
   ```
   python bootstrap.py --shortcut
   ```
3. They start it from the desktop shortcut, or with `python run.py`.

The bootstrap builds `.venv` inside the folder, so nothing is installed
system-wide and no administrator rights are needed. It runs every tool's
self-test before it finishes. `run.py` finds that environment by itself
afterwards.

A shortcut straight into one tool is just the launcher with a flag:

```
python run.py --tool labelimg
python run.py --tool roi
```

### Machines with no internet

Download the wheels once on a connected machine **of the same OS and Python
version**:

```
python -m pip download -d wheels PySide6-Essentials pillow openpyxl lxml
```

Copy `wheels/` alongside the project, then on the target machine:

```
python bootstrap.py --offline wheels
```

## 2. Ship a standalone executable

Best when annotators should not have to think about Python at all.

```
python build/build_exe.py            one file
python build/build_exe.py --onedir   a folder (starts faster)
```

PyInstaller cannot cross-compile: build the Windows executable on Windows,
the macOS app on macOS, the Linux binary on Linux. The result lands in
`dist/`.

## 3. Install it as a package

For a shared Python environment or a managed image:

```
python -m pip install .
annotex                      # the Home dashboard
annotex --tool labelimg
```

---

## What lives where

| What | Where |
|---|---|
| The suite's theme and window size | `~/.config/annotex/shell.json` (Windows: `%APPDATA%\Annotex`, macOS: `~/Library/Application Support/Annotex`) |
| LabelImg Master settings | `…/annotex/labelimg/settings.json` |
| LabelImg Master class projects | `~/.labelImgMaster/class_projects.json` (unchanged, so existing projects carry over) |
| ROI Studio settings | its original location (`~/.config/roi_studio/settings.json`) |
| Crash reports | `…/annotex/recovery/` |

Beside each batch of images LabelImg Master writes its annotations plus a few
hidden housekeeping files: `.labelimg.lock`, `.labelimg_draft.json`,
`.labelimg_audit.jsonl`, `.labelimg_verified.json` (YOLO only),
`.labelimg_backup/` and, if saved, `.labelimg.json` batch settings. ROI Studio
keeps its own `.roi_studio*` files. None of them are needed by downstream
tools and all are safe to exclude when copying annotations onward.

## Sharing a class project with a team

In LabelImg Master open the Class Manager (Ctrl+M), pick the project and use
**Export…** to save it as a class set. On each annotator's machine,
**Import set…** brings it in with the same IDs. Saving the batch settings
(Batch → Save these settings for this batch) then makes anyone who opens that
folder use that project automatically.

## Verifying a machine

```
python run.py --check       versions of Python, Qt, Pillow, openpyxl, lxml
python run.py --selftest    persistence, formats, import/export, reports
```

Both work without a display, so they can run over SSH before anyone sits down
to annotate.
