"""The tools that appear on the Home dashboard.

Adding a tool to the suite means adding one ToolSpec here.  The shell builds
its card, its tab and its Ctrl+<n> shortcut from the spec, and creates the
tool's window the first time someone opens it.

A tool window is a QWidget (usually a QMainWindow) that takes the shell as
`host` and offers these methods - every one is optional:

    tool_activated()            it has just been shown
    tool_deactivating() -> bool about to be hidden; save work, False to stay
    tool_close() -> bool        the application is closing; False to cancel
    tool_apply_theme(name)      "dark" | "light" | "system"
    tool_open(folder)           open this folder

and may call back into the host:

    host.request_theme(name)    change the theme for every tool
    host.go_home()              return to the dashboard
    host.quit()                 close the application
    host.theme_setting          the current theme setting
    host.app                    the QApplication
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    tagline: str
    description: str
    mark: str                                   # fluxbox.ui.icons mark name
    version: str
    highlights: tuple = field(default_factory=tuple)
    create: object = None                       # callable(host) -> QWidget
    recent: object = None                       # callable() -> [folder]


# ── ROI Studio ────────────────────────────────────────────────
def _roi_create(host):
    from ..apps.roi.config import Settings
    from ..apps.roi.ui.main_window import MainWindow
    return MainWindow(Settings(), host.app, host=host)


def _roi_recent():
    from ..apps.roi.config import Settings
    return [f for f in (Settings().get("recent_folders") or []) if os.path.isdir(f)]


# ── LabelImg Master ───────────────────────────────────────────
def _labelimg_create(host):
    from ..apps.labelimg.config import Settings
    from ..apps.labelimg.ui.window import LabelImgWindow
    return LabelImgWindow(Settings(), host.app, host=host)


def _labelimg_recent():
    from ..apps.labelimg.config import Settings
    return [f for f in (Settings().get("recent_folders") or []) if os.path.isdir(f)]


def _tools():
    from ..apps.labelimg.config import APP_VERSION as LABELIMG_VERSION
    from ..apps.roi.config import APP_VERSION as ROI_VERSION
    return [
        ToolSpec(
            id="roi", name="ROI Studio", tagline="Polygon ROI annotation",
            description=("Draw regions of interest on fixed-camera batches - polygons, "
                         "rectangles, circles and freehand - and export spreadsheets "
                         "and JSON ready for downstream code."),
            mark="polygon", version=ROI_VERSION,
            highlights=("xlsx + JSON per batch", "COCO / YOLO / VOC / masks",
                        "Apply to many frames"),
            create=_roi_create, recent=_roi_recent),
        ToolSpec(
            id="labelimg", name="LabelImg Master", tagline="Bounding-box labelling and review",
            description=("Label and review detection frames with a class manager, "
                         "number-key class hotkeys and one-key accept - saving Pascal "
                         "VOC, YOLO or CreateML exactly as LabelImg always has."),
            mark="box", version=LABELIMG_VERSION,
            highlights=("Class projects with permanent IDs", "VOC / YOLO / CreateML",
                        "Review mode + report"),
            create=_labelimg_create, recent=_labelimg_recent),
    ]


TOOLS = _tools()


def get(tool_id):
    for spec in TOOLS:
        if spec.id == tool_id:
            return spec
    return None
