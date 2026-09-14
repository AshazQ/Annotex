"""Image format conversion.  No Qt.

One output per input, written to a temporary sibling and renamed into place,
never over an existing file.  ICC colour profiles are always kept so colours
do not shift; "strip metadata" removes EXIF (camera, GPS, time) after first
applying the EXIF rotation, so a photo shot sideways stays the right way up.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from PIL import Image, ImageOps

from annotex.core.jobs import JobCancelled

from .common import render_pattern

TARGETS = {
    "keep": ("Keep the original format", None, None),
    "jpg": ("JPEG (.jpg)", "JPEG", ".jpg"),
    "png": ("PNG (.png)", "PNG", ".png"),
    "webp": ("WebP (.webp)", "WEBP", ".webp"),
    "bmp": ("BMP (.bmp)", "BMP", ".bmp"),
    "tiff": ("TIFF (.tif)", "TIFF", ".tif"),
}
FORMAT_BY_EXT = {".jpg": "jpg", ".jpeg": "jpg", ".jfif": "jpg", ".png": "png", ".webp": "webp",
                 ".bmp": "bmp", ".tif": "tiff", ".tiff": "tiff", ".gif": "png"}
OUTPUT_DIR = "converted"


@dataclass
class ImageOptions:
    target: str = "jpg"
    resize: str = "none"              # none | max | percent | exact
    max_side: int = 1920
    percent: int = 50
    width: int = 1280
    height: int = 720
    keep_aspect: bool = True
    never_upscale: bool = True
    quality: int = 90                 # JPEG / WebP
    png_level: int = 6
    webp_lossless: bool = False
    strip_metadata: bool = True
    background: str = "#ffffff"       # used when transparency has to go
    pattern: str = "{name}"
    start_number: int = 1


def target_key(options, source):
    if options.target != "keep":
        return options.target
    return FORMAT_BY_EXT.get(os.path.splitext(source)[1].lower(), "png")


def plan(items, options, output_root=""):
    """[(source, destination)] for [(source, root)] items.

    Without `output_root`, each image goes to a `converted/` folder in the
    folder it was picked from, keeping any sub-folders below it."""
    planned, taken = [], set()
    for number, (source, root) in enumerate(items, start=options.start_number):
        key = target_key(options, source)
        ext = TARGETS[key][2]
        relative = os.path.relpath(os.path.dirname(source), root)
        base = output_root or os.path.join(root, OUTPUT_DIR)
        folder = os.path.normpath(os.path.join(base, relative))
        name = render_pattern(options.pattern, os.path.splitext(os.path.basename(source))[0],
                              number, os.path.basename(os.path.dirname(source)), ext[1:])
        destination = os.path.join(folder, name + ext)
        stem, counter = destination[:-len(ext)], 2
        while destination in taken or os.path.exists(destination) or \
                os.path.abspath(destination) == os.path.abspath(source):
            destination = "%s_%d%s" % (stem, counter, ext)
            counter += 1
        taken.add(destination)
        planned.append((source, destination))
    return planned


def new_size(size, options):
    width, height = size
    if options.resize == "max":
        longest = max(width, height)
        scale = options.max_side / float(longest)
    elif options.resize == "percent":
        scale = options.percent / 100.0
    elif options.resize == "exact":
        if not options.keep_aspect:
            target = (max(1, options.width), max(1, options.height))
            if options.never_upscale and (target[0] > width or target[1] > height):
                return (width, height)
            return target
        scale = min(options.width / float(width), options.height / float(height))
    else:
        return (width, height)
    if options.never_upscale:
        scale = min(scale, 1.0)
    return (max(1, int(round(width * scale))), max(1, int(round(height * scale))))


def _flatten(image, background):
    rgba = image.convert("RGBA")
    base = Image.new("RGB", rgba.size, background)
    base.paste(rgba, mask=rgba.getchannel("A"))
    return base


def _has_alpha(image):
    return image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info)


def convert_one(source, destination, options):
    """Convert one image.  Returns the output (width, height)."""
    key = target_key(options, source)
    pil_format = TARGETS[key][1]
    with Image.open(source) as opened:
        opened.seek(0)
        image = opened.copy()
        exif = opened.info.get("exif")
        icc = opened.info.get("icc_profile")
    if options.strip_metadata:
        image = ImageOps.exif_transpose(image)
        exif = None
    size = new_size(image.size, options)
    if size != image.size:
        if image.mode in ("P", "1"):
            image = image.convert("RGBA" if _has_alpha(image) else "RGB")
        image = image.resize(size, Image.Resampling.LANCZOS)

    save = {}
    if pil_format == "JPEG":
        if _has_alpha(image):
            image = _flatten(image, options.background)
        elif image.mode not in ("RGB", "L", "CMYK"):
            image = image.convert("RGB")
        save.update(quality=max(1, min(100, options.quality)), optimize=True)
    elif pil_format == "BMP":
        image = _flatten(image, options.background) if _has_alpha(image) else (
            image if image.mode in ("RGB", "L", "1") else image.convert("RGB"))
    elif pil_format == "WEBP":
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if _has_alpha(image) else "RGB")
        save.update(quality=max(1, min(100, options.quality)), method=4,
                    lossless=bool(options.webp_lossless))
    elif pil_format == "PNG":
        if image.mode == "CMYK":
            image = image.convert("RGB")
        save.update(compress_level=max(0, min(9, options.png_level)), optimize=False)
    elif pil_format == "TIFF":
        save.update(compression="tiff_lzw")
    if exif and pil_format in ("JPEG", "WEBP", "PNG", "TIFF"):
        save["exif"] = exif
    if icc and pil_format in ("JPEG", "WEBP", "PNG", "TIFF"):
        save["icc_profile"] = icc

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    folder, name = os.path.split(destination)
    part = os.path.join(folder, "." + name + ".part")
    try:
        image.save(part, format=pil_format, **save)
        with Image.open(part) as check:
            check.verify()
        os.replace(part, destination)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return image.size


def run(ctx, planned, options):
    """Convert every (source, destination).  One bad file does not stop the
    rest; failures are reported as warnings.  Returns a summary."""
    done, failed = 0, 0
    total = len(planned) or 1
    for index, (source, destination) in enumerate(planned):
        if ctx is not None:
            if ctx.cancelled:
                raise JobCancelled()
            ctx.progress(index / float(total), "%d of %d  ·  %s"
                         % (index + 1, len(planned), os.path.basename(source)))
        try:
            convert_one(source, destination, options)
            done += 1
            if ctx is not None:
                ctx.output(destination)
        except Exception as exc:                                  # noqa: BLE001
            failed += 1
            if ctx is not None:
                ctx.warn("%s: %s" % (os.path.basename(source), exc))
    if ctx is not None:
        ctx.progress(1.0)
    return "Converted %d image(s)%s" % (done, ", %d failed" % failed if failed else "")
