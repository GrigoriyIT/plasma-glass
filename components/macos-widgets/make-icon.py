#!/usr/bin/env python3
"""Draw the Glass Widgets app icon: frosted widget cards over the Glass VPN aurora squircle.

  make-icon.py out.png            1024 px master
  make-icon.py out.iconset        all sizes for `iconutil -c icns`
"""
import sys
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath,
                         QPen, QRadialGradient)

S = 1024


def shield_path(cx, top, w, h):
    """Same silhouette as the menu bar icon (glassvpn.draw_icon), scaled."""
    sx, sy = w / 48.0, h / 55.0
    p = QPainterPath()

    def pt(x, y):
        return QPointF(cx + (x - 30) * sx, top + (y - 5) * sy)
    p.moveTo(pt(30, 5))
    p.cubicTo(pt(38, 10), pt(46, 12), pt(54, 12))
    p.lineTo(pt(54, 30))
    p.cubicTo(pt(54, 45), pt(44, 54), pt(30, 60))
    p.cubicTo(pt(16, 54), pt(6, 45), pt(6, 30))
    p.lineTo(pt(6, 12))
    p.cubicTo(pt(14, 12), pt(22, 10), pt(30, 5))
    p.closeSubpath()
    return p


def blob(p, x, y, r, color, alpha):
    g = QRadialGradient(QPointF(x, y), r)
    c = QColor(color)
    c.setAlphaF(alpha)
    g.setColorAt(0, c)
    c.setAlphaF(0)
    g.setColorAt(1, c)
    p.fillRect(QRectF(0, 0, S, S), g)


def draw():
    img = QImage(S, S, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # macOS icon grid: 824 px body, 100 px margin, continuous-corner radius ~185
    body = QPainterPath()
    body.addRoundedRect(QRectF(100, 100, 824, 824), 185, 185)

    # soft drop shadow under the body
    for i in range(14):
        sh = QPainterPath()
        d = i * 2.2
        sh.addRoundedRect(QRectF(100 - d, 112 - d + 6, 824 + 2 * d, 824 + 2 * d), 185 + d, 185 + d)
        p.fillPath(sh, QColor(0, 0, 0, 4))

    p.save()
    p.setClipPath(body)
    bg = QLinearGradient(QPointF(100, 100), QPointF(924, 924))
    bg.setColorAt(0, QColor("#141b3d"))
    bg.setColorAt(0.55, QColor("#0d1f3a"))
    bg.setColorAt(1, QColor("#06121f"))
    p.fillRect(QRectF(0, 0, S, S), bg)
    # aurora: the colours the glass will refract
    blob(p, 300, 300, 420, "#6a5cff", 0.75)
    blob(p, 760, 330, 380, "#18c8e8", 0.65)
    blob(p, 560, 820, 430, "#21e0a0", 0.55)
    blob(p, 230, 760, 300, "#c04cff", 0.35)
    # faint top sheen on the body
    sheen = QLinearGradient(QPointF(0, 100), QPointF(0, 520))
    sheen.setColorAt(0, QColor(255, 255, 255, 40))
    sheen.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillRect(QRectF(0, 0, S, S), sheen)
    p.restore()
    # 1 px-ish light rim on the body, like the glass theme
    p.setPen(QPen(QColor(255, 255, 255, 46), 3))
    p.drawPath(body)

    # three frosted widget cards: a wide one on top, two below — like the desktop
    def card(x, y, w, h):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), 46, 46)
        for i in range(14):   # shadow
            p.save()
            p.translate(0, 12 + i * 1.1)
            p.fillPath(path, QColor(0, 0, 0, 6))
            p.restore()
        g = QLinearGradient(QPointF(x, y), QPointF(x + w, y + h))
        g.setColorAt(0, QColor(255, 255, 255, 120))
        g.setColorAt(1, QColor(255, 255, 255, 34))
        p.fillPath(path, g)
        rim = QLinearGradient(QPointF(x, y), QPointF(x + w, y + h))
        rim.setColorAt(0, QColor(255, 255, 255, 230))
        rim.setColorAt(1, QColor(255, 255, 255, 60))
        p.setPen(QPen(rim, 6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        return path

    card(232, 232, 560, 250)
    card(232, 520, 262, 272)
    card(530, 520, 262, 272)
    # a sun on the top card, a chart line and a dot in the lower ones
    p.setPen(Qt.PenStyle.NoPen)
    sun = QRadialGradient(QPointF(330, 357), 70)
    sun.setColorAt(0, QColor("#ffe58a"))
    sun.setColorAt(1, QColor("#ffb43a"))
    p.setBrush(sun)
    p.drawEllipse(QPointF(330, 357), 58, 58)
    p.setBrush(QColor(255, 255, 255, 220))
    p.drawRoundedRect(QRectF(430, 322, 300, 30), 15, 15)
    p.setBrush(QColor(255, 255, 255, 120))
    p.drawRoundedRect(QRectF(430, 370, 210, 26), 13, 13)
    line = QPainterPath(QPointF(270, 720))
    for x, y in ((320, 680), (360, 700), (410, 630), (455, 655)):
        line.lineTo(QPointF(x, y))
    tg = QLinearGradient(QPointF(270, 720), QPointF(455, 630))
    tg.setColorAt(0, QColor("#5dffc0"))
    tg.setColorAt(1, QColor("#36d6ff"))
    p.setPen(QPen(tg, 22, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(line)
    p.setPen(Qt.PenStyle.NoPen)
    for i, c in enumerate(("#0a84ff", "#30d158", "#ff9f0a")):
        p.setBrush(QColor(c))
        p.drawRoundedRect(QRectF(572, 590 + i * 62, 22, 40), 11, 11)
        p.setBrush(QColor(255, 255, 255, 170 - i * 40))
        p.drawRoundedRect(QRectF(612, 600 + i * 62, 140 - i * 30, 22), 11, 11)
    p.end()
    return img


def main():
    QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QGuiApplication(["make-icon", "-platform", "offscreen"])  # noqa: F841 (needed for painting)
    out = Path(sys.argv[1])
    img = draw()
    if out.suffix == ".iconset":
        out.mkdir(parents=True, exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                img.scaled(px, px, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation).save(str(out / name))
    else:
        img.save(str(out))


if __name__ == "__main__":
    main()
