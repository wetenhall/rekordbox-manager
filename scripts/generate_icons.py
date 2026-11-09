"""Render the original SVG into desktop icons. Requires the app's Qt dependencies.

Run on macOS to also regenerate the ICNS file with Apple's iconutil.
"""
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "rekordbox_manager" / "assets"


def render(size):
    renderer = QSvgRenderer(str(ASSETS / "icon.svg"))
    if not renderer.isValid():
        raise RuntimeError("Invalid icon SVG")
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Cannot encode icon PNG")
    return bytes(data)


def main():
    app = QGuiApplication([])
    sizes = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
    pngs = {size: render(size) for size in sizes}
    (ASSETS / "icon.png").write_bytes(pngs[1024])
    # Modern Windows ICO files support PNG-compressed entries.
    windows_sizes = (16, 24, 32, 48, 64, 128, 256)
    offset = 6 + 16 * len(windows_sizes)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(windows_sizes)))
    for size in windows_sizes:
        png = pngs[size]
        directory.extend(struct.pack("<BBBBHHII", size % 256, size % 256,
                                     0, 0, 1, 32, len(png), offset))
        offset += len(png)
    (ASSETS / "icon.ico").write_bytes(directory + b"".join(pngs[s] for s in windows_sizes))
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as temp:
            iconset = Path(temp) / "RekordboxManager.iconset"
            iconset.mkdir()
            for size in (16, 32, 128, 256, 512):
                (iconset / f"icon_{size}x{size}.png").write_bytes(pngs[size])
                (iconset / f"icon_{size}x{size}@2x.png").write_bytes(pngs[size * 2])
            subprocess.run(["iconutil", "-c", "icns", str(iconset),
                            "-o", str(ASSETS / "icon.icns")], check=True)
    print(f"Generated desktop icons in {ASSETS}")


if __name__ == "__main__":
    main()
