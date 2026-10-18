"""Draws PESI3D toolbar icons (same drawing as the IngeTrazo plugins) into
Contents/icons/{Dark,Light}/PESI3D/<Name>_<size>.png + <Name>.svg.

    D:\\PROJEKTE\\INGETRAZO\\.venv\\Scripts\\python tools\\make_icons.py

Needs PySide6 (any Python with it; the 3ds Max Python works too).
"""

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF

SIZES = (14, 16, 20, 24, 30, 32, 36, 48)
INK = {"Dark": "#D8D8D8", "Light": "#2C2F36"}   # as the Topology icons of 1.0
ACCENT = "#F37329"                               # (243, 115, 41)
OUT = Path(__file__).resolve().parents[1] / "Contents" / "icons"


def _poly(pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _dot(p, acc, x, y, r):
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(acc)
    p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


def topo_plan(p, ink, acc):
    """IngeTrazo Topology 1.2 'topo_survey': a plan sheet with spot heights."""
    p.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(9, 6)
    path.lineTo(31, 6)
    path.lineTo(39, 14)
    path.lineTo(39, 42)
    path.lineTo(9, 42)
    path.closeSubpath()
    p.drawPath(path)
    p.drawPolyline(_poly([(31, 6), (31, 14), (39, 14)]))
    p.save()
    c = QColor(ink)
    c.setAlpha(150)
    pen = QPen(c, 2.2)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    for y in (19, 26, 33):
        p.drawLine(QPointF(19, y), QPointF(33, y))
    p.restore()
    for y in (19, 26, 33):
        _dot(p, acc, 14.5, y, 2.9)


def topo_plan_svg(ink):
    lines = "".join(
        f'<line x1="19" y1="{y}" x2="33" y2="{y}" stroke="{ink}" stroke-opacity="0.59" '
        f'stroke-width="2.2" stroke-linecap="round"/>' for y in (19, 26, 33))
    dots = "".join(f'<circle cx="14.5" cy="{y}" r="2.9" fill="{ACCENT}"/>' for y in (19, 26, 33))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">'
        f'<path d="M9 6 L31 6 L39 14 L39 42 L9 42 Z M31 6 L31 14 L39 14" fill="none" '
        f'stroke="{ink}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>'
        f"{lines}{dots}</svg>")


ICONS = {"Topology_Plan": (topo_plan, topo_plan_svg)}


def render(draw, size, ink):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size / 48.0, size / 48.0)
    pen = QPen(QColor(ink), 3.0)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    draw(p, QColor(ink), QColor(ACCENT))
    p.end()
    return img


def main(names):
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    for name in names or ICONS:
        draw, svg = ICONS[name]
        for theme, ink in INK.items():
            folder = OUT / theme / "PESI3D"
            folder.mkdir(parents=True, exist_ok=True)
            for size in SIZES:
                render(draw, size, ink).save(str(folder / f"{name}_{size}.png"))
            (folder / f"{name}.svg").write_text(svg(ink), encoding="utf-8")
            print("wrote", folder / name)


if __name__ == "__main__":
    main(sys.argv[1:])
