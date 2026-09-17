"""Draw Annotex's application icon files from the mark on the Home page.

    python build/make_icons.py

Writes annotex/resources/icons/annotex.svg, annotex.png (1024 px),
annotex.ico (Windows, 16-256 px) and annotex.icns (macOS).  build_exe.py
hands the .ico or .icns to PyInstaller.  The mark and its colours come from
annotex.ui - the suite mark in the accent, on the dark theme's tile, as the
Home page draws it - so run this again if either changes.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "annotex", "resources", "icons")
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def icon_svg() -> str:
    from annotex.ui.icons import _MARKS
    from annotex.ui.palette import DARK
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
            'width="1024" height="1024">'
            '<rect width="64" height="64" rx="14" fill="{bg}"/>' + _MARKS["suite"]
            + '</svg>\n').format(bg=DARK["surfaceAlt"], fg=DARK["accent"])


def render(svg: str, size: int):
    """The SVG as a Pillow image, drawn by Qt at exactly this size."""
    from PIL import Image
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    image = QImage(size, size, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return Image.frombytes("RGBA", (size, size), bytes(image.constBits()))


def main() -> int:
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])   # noqa: F841
    svg = icon_svg()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "annotex.svg"), "w", encoding="utf-8") as handle:
        handle.write(svg)
    big = render(svg, 1024)
    big.save(os.path.join(OUT, "annotex.png"))
    # Each size drawn on its own, not shrunk from the big one, so the small
    # ones stay crisp.
    frames = [render(svg, s) for s in ICO_SIZES]
    frames[-1].save(os.path.join(OUT, "annotex.ico"), format="ICO",
                    sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])
    big.save(os.path.join(OUT, "annotex.icns"), format="ICNS")
    for name in ("annotex.svg", "annotex.png", "annotex.ico", "annotex.icns"):
        print("wrote %s (%d KB)" % (os.path.join("annotex", "resources", "icons", name),
                                     os.path.getsize(os.path.join(OUT, name)) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
