#!/usr/bin/env python3
"""Tray and app icons for the Windows client, drawn by the same code as the other clients.

  make-icons.py <out dir>     tray-<state>-<light|dark>.ico, tray-connecting-<theme>-<0..7>.ico
                              (the pulse) and GlassVPN.ico

Needs PyQt6 (the macOS client's venv has it). Each .ico holds PNG frames 16…256 px.
"""
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "macos")]

from PyQt6.QtCore import QBuffer, QIODevice, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
import glassvpn  # noqa: E402
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("make_icon", HERE.parent / "macos" / "make-icon.py")
make_icon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_icon)


def png(img, size):
    img = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path, img, sizes):
    frames = [png(img, s) for s in sizes]
    out = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    for s, data in zip(sizes, frames):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(out + b"".join(frames))


FRAMES = 8
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
# a light taskbar wants a dark shield and the other way round
for theme, fg in (("light", QColor("#1c1c1e")), ("dark", QColor("#ffffff"))):
    for state in (glassvpn.OFF, glassvpn.CONNECTING, glassvpn.ON, glassvpn.BYPASS, glassvpn.ERROR):
        img = glassvpn.draw_icon(state, fg, 1.0).pixmap(64, 64).toImage()
        write_ico(out / f"tray-{state}-{theme}.ico", img, [16, 20, 24, 32, 40, 48, 64])
    # "connecting" pulses: the dot fades in and out over these frames
    for i in range(FRAMES):
        phase = abs(1 - 2 * i / FRAMES)          # 1 → 0 → 1
        img = glassvpn.draw_icon(glassvpn.CONNECTING, fg, phase).pixmap(64, 64).toImage()
        write_ico(out / f"tray-connecting-{theme}-{i}.ico", img, [16, 20, 24, 32, 40, 48, 64])
write_ico(out / "GlassVPN.ico", make_icon.draw(), [16, 24, 32, 48, 64, 128, 256])
print("icons in", out)
