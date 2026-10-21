#!/usr/bin/env python3
"""Render a contact sheet of the panorama in several states (no Plasma needed).

    QT_QPA_PLATFORM=offscreen python3 tools/preview.py out.png
"""
import os
import sys
from PyQt6.QtCore import QUrl, QSize
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QColor, QFont
from PyQt6.QtQuick import QQuickView

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, "..", "contents", "ui", "Scene.qml")
W, H = 1920, 360   # the whole 5760x1080 panorama at 1/3
SINGLE = "--single" in sys.argv   # the one-screen composition instead
if SINGLE:
    W, H = 960, 540
# --slice=X: one screen of the panorama at full size, from scene x = X
SLICE = next((float(a.split("=")[1]) for a in sys.argv if a.startswith("--slice=")), None)
if SLICE is not None:
    W, H = 1920, 1080
# --states=1,3: only these rows
PICK = next(([int(i) for i in a.split("=")[1].split(",")] for a in sys.argv if a.startswith("--states=")), None)

STATES = [
    ("Осень, утро, ясно", dict(elevation=6, sun=(1150, 491), season="autumn")),
    ("Осень, день, малооблачно", dict(elevation=24, sun=(2700, 239), season="autumn", clouds=0.3)),
    ("Осень, закат", dict(elevation=1, sun=(4950, 561), season="autumn", clouds=0.2)),
    ("Ночь, ясно, луна", dict(elevation=-22, moon=(3300, 210), moonUp=True, moonPhase=0.62, season="autumn")),
    ("День, дождь", dict(elevation=16, sun=(2900, 351), season="autumn", clouds=0.9, precip="rain", intensity=0.7)),
    ("Зима, день, снегопад", dict(elevation=10, sun=(2600, 435), season="winter", snowGround=True, clouds=0.8, precip="snow", intensity=0.6)),
    ("Зима, ночь, ясно", dict(elevation=-16, moon=(1800, 260), moonUp=True, moonPhase=0.45, season="winter", snowGround=True)),
    ("Лето, утро, туман", dict(elevation=3, sun=(1000, 533), season="summer", clouds=0.35, fog=0.7)),
]

if PICK:
    STATES = [STATES[i] for i in PICK]
app = QGuiApplication(sys.argv)
frames = []
for title, st in STATES:
    v = QQuickView()
    v.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    v.setSource(QUrl.fromLocalFile(SCENE))
    if v.status() != QQuickView.Status.Ready:
        for e in v.errors():
            print(e.toString())
        sys.exit(1)
    v.resize(QSize(W, H))
    r = v.rootObject()
    r.setProperty("animate", False)
    r.setProperty("single", SINGLE)
    if SLICE is not None:
        r.setProperty("sceneX", SLICE)
    for key, val in st.items():
        if key in ("sun", "moon"):
            from PyQt6.QtCore import QPointF
            val = QPointF(val[0] / 3, val[1]) if SINGLE else QPointF(*val)
        r.setProperty(key, val)
    v.show()
    for _ in range(30):
        app.processEvents()
    img = v.grabWindow()
    frames.append((title, img))
    v.close()

pad = 36
sheet = QImage(W, len(frames) * (H + pad), QImage.Format.Format_RGB32)
sheet.fill(QColor("#1b1b1b"))
p = QPainter(sheet)
f = QFont("DejaVu Sans"); f.setPixelSize(20); p.setFont(f)
for i, (title, img) in enumerate(frames):
    y = i * (H + pad)
    p.setPen(QColor("#e8e8e8")); p.drawText(10, y + 25, title)
    p.drawImage(0, y + pad, img)
    p.setPen(QColor(255, 255, 255, 60))
    for sx in (() if SINGLE or SLICE is not None else (640, 1280)):
        p.drawLine(sx, y + pad, sx, y + pad + H)
p.end()
args = [a for a in sys.argv[1:] if not a.startswith("--")]
out = args[0] if args else "/tmp/bashkir-preview.png"
sheet.save(out)
print("saved", out)
