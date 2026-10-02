#!/usr/bin/env python3
"""Draw the Android TV launcher banner (320x180 dp, xhdpi = 640x360 px).

Needs Pillow and a font file: Inter SemiBold (SIL OFL), not an Apple font.
  pip install pillow
  python3 make-banner.py path/to/Inter-SemiBold.ttf
"""
import sys
from PIL import Image, ImageDraw, ImageFont

W, H, S = 640, 360, 4          # drawn 4x larger, then downscaled for smooth edges
OUT = "app/src/main/res/drawable-xhdpi/banner.png"


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def main(font_path):
    w, h = W * S, H * S
    img = Image.new("RGB", (w, h))
    # same diagonal gradient as the launcher icon: blue -> violet -> teal
    stops = [(0x2E, 0x5B, 0xFF), (0x7A, 0x4D, 0xFF), (0x19, 0xB5, 0xA5)]
    px = img.load()
    for y in range(0, h, S):
        for x in range(0, w, S):
            t = (x / w * 0.7 + y / h * 0.3)
            c = lerp(stops[0], stops[1], t * 2) if t < 0.5 else lerp(stops[1], stops[2], (t - 0.5) * 2)
            for dy in range(S):
                for dx in range(S):
                    px[x + dx, y + dy] = c
    d = ImageDraw.Draw(img, "RGBA")

    # shield: the launcher icon's path (M54,28 L74,35.5 C74,55 67,67 54,77 ...), left third
    cx, top, sh = 150 * S, 82 * S, 196 * S
    sw = sh * 40 / 49
    def pt(fx, fy):
        return (cx + (fx - 0.5) * sw, top + fy * sh)
    def cubic(p0, p1, p2, p3, n=24):
        return [tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * e
                      for a, b, c, e in zip(p0, p1, p2, p3)) for t in (i / n for i in range(1, n + 1))]
    path = [pt(0.5, 0.0), pt(1.0, 0.153)]
    path += cubic(pt(1.0, 0.153), pt(1.0, 0.551), pt(0.825, 0.796), pt(0.5, 1.0))
    path += cubic(pt(0.5, 1.0), pt(0.175, 0.796), pt(0.0, 0.551), pt(0.0, 0.153))
    d.polygon(path, fill=(255, 255, 255, 50))
    d.line(path + [path[0]], fill=(255, 255, 255, 255), width=9 * S, joint="curve")
    r = 18 * S
    dot = pt(0.5, 0.44)
    d.ellipse([dot[0] - r, dot[1] - r, dot[0] + r, dot[1] + r], fill=(0x34, 0xC7, 0x59, 255))

    f1 = ImageFont.truetype(font_path, 88 * S)
    f2 = ImageFont.truetype(font_path, 88 * S)
    d.text((255 * S, 108 * S), "Glass", font=f1, fill="white")
    d.text((255 * S, 196 * S), "VPN", font=f2, fill=(255, 255, 255, 215))

    img.resize((W, H), Image.LANCZOS).save(OUT, optimize=True)
    print(OUT)


if __name__ == "__main__":
    main(sys.argv[1])
