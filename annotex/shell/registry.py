"""The tools that appear on the Home dashboard.

Adding a tool to Annotex means adding one ToolSpec here.  The shell builds its
card, its tab and its Ctrl+<n> shortcut from the spec, and creates the tool's
window the first time someone opens it.

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
    host.jobs                   the shared background JobManager
    host.app                    the QApplication

Media tools build on annotex.ui.media_page.MediaToolPage, which implements
all of this already.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field

SECTIONS = (("annotation", "Annotation"), ("video", "Video"), ("images", "Images"),
            ("dataset", "Dataset"))


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    tagline: str
    description: str
    section: str
    icon: str                                   # annotex.ui.icons name (tab + card)
    version: str
    highlights: tuple = field(default_factory=tuple)
    create: object = None                       # callable(host) -> QWidget
    recent: object = None                       # callable() -> [folder], or None
    forget: object = None                       # callable(folder) drops it from recent


def forget_in(settings, folder) -> None:
    """Drop one folder from a settings store's recent list.  The folder itself
    is never touched."""
    target = os.path.normcase(os.path.abspath(str(folder)))
    recent = [f for f in (settings.get("recent_folders") or [])
              if os.path.normcase(os.path.abspath(str(f))) != target]
    settings.set("recent_folders", recent)


def _roi_create(host):
    from ..apps.roi.config import Settings
    from ..apps.roi.ui.main_window import MainWindow
    return MainWindow(Settings(), host.app, host=host)


def _roi_recent():
    from ..apps.roi.config import Settings
    return [f for f in (Settings().get("recent_folders") or []) if os.path.isdir(f)]


def _roi_forget(folder):
    from ..apps.roi.config import Settings
    forget_in(Settings(), folder)


def _labelimg_create(host):
    from ..apps.labelimg.config import Settings
    from ..apps.labelimg.ui.window import LabelImgWindow
    return LabelImgWindow(Settings(), host.app, host=host)


def _labelimg_recent():
    from ..apps.labelimg.config import Settings
    return [f for f in (Settings().get("recent_folders") or []) if os.path.isdir(f)]


def _labelimg_forget(folder):
    from ..apps.labelimg.config import Settings
    forget_in(Settings(), folder)


def _shapes_create(host):
    from ..apps.shapes.config import Settings
    from ..apps.shapes.ui.window import ShapesWindow
    return ShapesWindow(Settings(), host.app, host=host)


def _shapes_recent():
    from ..apps.shapes.config import Settings
    return [f for f in (Settings().get("recent_folders") or []) if os.path.isdir(f)]


def _shapes_forget(folder):
    from ..apps.shapes.config import Settings
    forget_in(Settings(), folder)


def _page(module, name):
    def create(host):
        return getattr(importlib.import_module(module), name)(host.app, host=host)
    return create


def _tools():
    from ..apps.labelimg.config import APP_VERSION as LABELIMG_VERSION
    from ..apps.roi.config import APP_VERSION as ROI_VERSION
    from ..apps.shapes.config import APP_VERSION as SHAPES_VERSION
    media = "1.0.0"
    return [
        ToolSpec("roi", "ROI Studio", "Polygon ROI annotation",
                 "Draw regions of interest on fixed-camera batches - polygons, rectangles, "
                 "circles and freehand - and export spreadsheets and JSON for downstream code.",
                 "annotation", "polygon", ROI_VERSION,
                 ("xlsx + JSON per batch", "COCO / YOLO / VOC / masks"),
                 _roi_create, _roi_recent, _roi_forget),
        ToolSpec("labelimg", "LabelImg Master", "Bounding-box labelling and review",
                 "Label and review detection frames with a class manager, number-key class "
                 "hotkeys and one-key accept - Pascal VOC, YOLO or CreateML, exactly as LabelImg "
                 "always wrote them.",
                 "annotation", "rect", LABELIMG_VERSION,
                 ("Permanent class IDs", "VOC / YOLO / CreateML"),
                 _labelimg_create, _labelimg_recent, _labelimg_forget),
        ToolSpec("shapes", "LabelImg Shapes", "Polygons, oriented boxes, circles and more",
                 "Label objects with polygons, oriented boxes, circles, ellipses and freehand "
                 "outlines. Shapes stay editable, and export to YOLO segmentation, YOLO OBB "
                 "or COCO.",
                 "annotation", "shapes", SHAPES_VERSION,
                 ("Editable shapes", "YOLO seg / OBB / COCO"),
                 _shapes_create, _shapes_recent, _shapes_forget),
        ToolSpec("frames", "Video to Images", "Turn footage into frames",
                 "Save a frame every few seconds, every Nth frame or whenever the scene changes "
                 "- or scrub through and grab exactly the frames you want.",
                 "video", "frames", media, ("Scene-change detection", "Manual grab"),
                 _page("annotex.apps.video.ui.frames_page", "FramesPage")),
        ToolSpec("trim", "Video Trimmer", "Cut pieces out of videos",
                 "Mark pieces with I and O and export them - instantly without quality loss, or "
                 "frame-accurate - as separate files or joined into one.",
                 "video", "scissors", media, ("Fast lossless or exact", "Several pieces per video"),
                 _page("annotex.apps.video.ui.trim_page", "TrimPage")),
        ToolSpec("vconvert", "Video Converter", "Change format, size or frame rate",
                 "Convert to MP4, WebM, MKV or AVI, scale down, change the frame rate, and "
                 "shrink files by quality or to a target size.",
                 "video", "film", media, ("H.264 / H.265 / VP9", "Target file size"),
                 _page("annotex.apps.video.ui.convert_page", "ConvertPage")),
        ToolSpec("merge", "Video Merger", "Join clips into one video",
                 "Put clips in order and join them - losslessly when they match, or converted "
                 "to one resolution, frame rate and format when they don't.",
                 "video", "merge", media, ("Lossless when possible", "Mixed clips welcome"),
                 _page("annotex.apps.video.ui.merge_page", "MergePage")),
        ToolSpec("iconvert", "Image Converter", "Format, size, quality and names",
                 "Convert many images at once between JPEG, PNG, WebP, BMP and TIFF - resize, "
                 "set quality, strip EXIF and rename with a pattern.",
                 "images", "convert", media, ("Keeps sub-folders", "Rename patterns"),
                 _page("annotex.apps.images.ui.convert_page", "ImageConvertPage")),
        ToolSpec("sorter", "Image Sorter", "Sort images into folders",
                 "Copy images into folders by pressing number keys, by rules (name, date, size, "
                 "annotation status) or with an ONNX model - every run can be undone.",
                 "images", "sort", media, ("Keys 1-9", "Rules", "ONNX models"),
                 _page("annotex.apps.images.ui.sorter_page", "SorterPage")),
        ToolSpec("dataset", "Dataset Tools", "Clean up, rename, split and zip",
                 "Six independent tools for image + .txt label folders: delete empty labels, "
                 "move unpaired images, rename pairs, split into parts, rename parts and zip - "
                 "each previewed first, and every run can be undone.",
                 "dataset", "dataset", media, ("Preview first", "Undo any run"),
                 _page("annotex.apps.dataset.ui.page", "DatasetPage")),
    ]


TOOLS = _tools()


def get(tool_id):
    for spec in TOOLS:
        if spec.id == tool_id:
            return spec
    return None
