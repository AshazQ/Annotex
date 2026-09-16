"""Image side-effects: the burnt-in ROI preview and the no_roi copy.

The preview colour is a user setting and applies ONLY here - the live canvas
keeps its own theme colours, so changing the printed colour never changes
what you are looking at while drawing.
"""

from __future__ import annotations

import os
import shutil

from ..config import PRINTED_DIR
from . import geometry as geo
from .io_safe import WriteReport, atomic_write, ensure_dir, safe_remove

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except Exception:                                    # pragma: no cover
    Image = ImageDraw = ImageFont = None
    HAS_PIL = False


def hex_to_rgb(value, default=(0, 220, 100)):
    """'#00dc64' -> (0, 220, 100).  Bad input falls back rather than raising."""
    try:
        text = str(value).strip().lstrip("#")
        if len(text) == 3:
            text = "".join(ch * 2 for ch in text)
        if len(text) != 6:
            return default
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except Exception:
        return default


def _font(size):
    if not HAS_PIL:
        return None
    for loader in (lambda: ImageFont.truetype("DejaVuSans-Bold.ttf", size),
                   lambda: ImageFont.truetype("arialbd.ttf", size),
                   lambda: ImageFont.truetype("Arial Bold.ttf", size),
                   ImageFont.load_default):
        try:
            return loader()
        except Exception:
            continue
    return None


def image_size(path):
    """(width, height) without decoding the whole file, or (0, 0)."""
    if not HAS_PIL:
        return (0, 0)
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def write_preview(src_path, dest_path, shapes, colour="#00dc64",
                  fill_alpha: int = 70, line_width: int = 3,
                  label_colour="#ffff00", labels=True) -> WriteReport:
    """Save a copy of the image with every ROI burnt in.

    Without Pillow the plain original is copied, so the printed folder always
    lines up one-to-one with the batch either way."""
    report = WriteReport()
    dest_dir = os.path.dirname(dest_path)
    if dest_dir and not ensure_dir(dest_dir):
        report.errors.append("could not create %s" % PRINTED_DIR)
        return report

    if not HAS_PIL:
        try:
            shutil.copy2(src_path, dest_path)
            report.written.append(dest_path)
            report.warnings.append("Pillow missing - preview is a plain copy")
        except Exception as exc:
            report.errors.append("preview: %s" % exc)
        return report

    rgb = hex_to_rgb(colour)
    label_rgb = hex_to_rgb(label_colour, (255, 255, 0))
    alpha = int(max(0, min(255, int(fill_alpha))))
    width = max(1, int(line_width))

    def write(tmp):
        with Image.open(src_path) as raw:
            base = raw.convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        drw = ImageDraw.Draw(overlay)
        font = _font(max(14, base.size[1] // 45))
        for index, shape in enumerate(shapes):
            pts = [(int(p[0]), int(p[1])) for p in shape]
            if len(pts) < 2:
                continue
            if len(pts) >= 3:
                drw.polygon(pts, fill=rgb + (alpha,), outline=rgb + (255,))
                # Pillow's polygon outline ignores width, so trace it again
                drw.line(pts + [pts[0]], fill=rgb + (255,), width=width,
                         joint="curve")
            else:
                drw.line(pts, fill=rgb + (255,), width=width)
            for px, py in pts:
                r = width + 1
                drw.ellipse([px - r, py - r, px + r, py + r],
                            fill=(255, 255, 255, 230), outline=rgb + (255,))
            if labels:
                cx, cy = geo.polygon_centroid(pts)
                text = "ROI %d" % (index + 1)
                try:
                    drw.text((cx + 1, cy + 1), text, fill=(0, 0, 0, 200),
                             font=font, anchor="mm")
                    drw.text((cx, cy), text, fill=label_rgb + (255,),
                             font=font, anchor="mm")
                except TypeError:                    # very old Pillow
                    drw.text((cx, cy), text, fill=label_rgb + (255,), font=font)

        merged = Image.alpha_composite(base, overlay).convert("RGB")
        # Saved in the format its name says: the preview keeps the original's
        # name, and a .webp or .bmp holding PNG bytes confuses what opens it.
        ext = os.path.splitext(dest_path)[1].lower()
        pil_format = Image.registered_extensions().get(ext, "PNG")
        if pil_format == "JPEG":
            merged.save(tmp, format="JPEG", quality=92)
        else:
            try:
                merged.save(tmp, format=pil_format)
            except (OSError, KeyError, ValueError):
                merged.save(tmp, format="PNG")

    def verify(tmp):
        with Image.open(tmp) as im:
            im.verify()

    ok, err = atomic_write(dest_path, write, verify, keep_backup=False)
    if ok:
        report.written.append(dest_path)
    else:
        report.errors.append("preview: %s" % err)
    return report


def copy_into(src_path, dest_dir, name) -> WriteReport:
    """Copy an image into one of the output folders."""
    report = WriteReport()
    if not ensure_dir(dest_dir):
        report.errors.append("could not create %s" % os.path.basename(dest_dir))
        return report
    dest = os.path.join(dest_dir, name)
    try:
        if os.path.isfile(src_path):
            shutil.copy2(src_path, dest)
            report.written.append(dest)
    except Exception as exc:
        report.errors.append("copy: %s" % exc)
    return report


def remove_from(dest_dir, name) -> None:
    safe_remove(os.path.join(dest_dir, name))
