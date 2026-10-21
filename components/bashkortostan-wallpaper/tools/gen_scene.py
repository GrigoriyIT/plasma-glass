#!/usr/bin/env python3
"""Generate the vector layers of the Bashkortostan landscape.

Two compositions from the same motifs, both 1080 high:
  contents/ui/scene3.js  5760 wide: a panorama over three 1920x1080 screens
  contents/ui/scene1.js  1920 wide: the same landscape packed into one screen

Each file holds SVG path strings. The wallpaper colours every layer at run time
from the sun position, the season and the weather, so the shapes are generated
once and never change. Deterministic: the same seeds give the same landscape.

    python3 tools/gen_scene.py
"""
import math
import os
import random

H = 1080
HERE = os.path.dirname(os.path.abspath(__file__))

# Where the motifs stand in each composition (x in scene units).
LAYOUTS = {
    "scene3": dict(
        width=5760,
        yamantau=1950, iremel=4380, iremel2=4700, ridge2=(3000, 5200),
        shikhan=1120, shikhan_w=205, yurt=640, horses=(860, 960), pines=(180, 300, 1180, 1290, 1420),
        birches=(4120, 4260, 4470, 4610, 4820, 5010, 5160, 5390, 5560, 5700),
        river=[(3900, 704), (3620, 712), (3260, 726), (3020, 742), (3180, 770), (3520, 806),
               (3560, 850), (3250, 905), (2860, 970), (2620, 1030), (2520, 1090)],
        river_w=330,
        near_left=(0, 2200, 520, 1500, 700), near_right=(3500, 5760, 5100, 4200, 700),
        grass_left=(0, 1700), grass_right=(4050, 5760),
        clouds=(6, 7, 9), stars=420),
    "scene1": dict(
        width=1920,
        yamantau=820, iremel=1560, iremel2=1700, ridge2=(1100, 1800),
        shikhan=300, shikhan_w=150, yurt=250, horses=(420, 500), pines=(40, 110, 560, 640),
        birches=(1440, 1530, 1640, 1730, 1840),
        river=[(1330, 704), (1210, 712), (1060, 724), (980, 742), (1060, 768), (1180, 806),
               (1190, 850), (1080, 905), (960, 970), (900, 1030), (880, 1090)],
        river_w=250,
        near_left=(0, 820, 230, 560, 300), near_right=(1180, 1920, 1700, 1440, 300),
        grass_left=(0, 640), grass_right=(1380, 1920),
        clouds=(2, 3, 4), stars=150),
}


def noise1d(seed, wavelength, width):
    """Smooth 1D value noise in -1..1 with cosine interpolation."""
    r = random.Random(seed)
    knots = [r.uniform(-1, 1) for _ in range(int(width / wavelength) + 3)]

    def f(x):
        t = x / wavelength
        i = int(math.floor(t))
        u = (1 - math.cos((t - i) * math.pi)) / 2
        return knots[i] * (1 - u) + knots[i + 1] * u
    return f


def fmt(v):
    return ("%.1f" % v).rstrip("0").rstrip(".")


def closed(pts, bottom=H):
    d = "M%s %s" % (fmt(pts[0][0]), fmt(bottom))
    d += "".join(" L%s %s" % (fmt(x), fmt(y)) for x, y in pts)
    d += " L%s %s Z" % (fmt(pts[-1][0]), fmt(bottom))
    return d


def poly(pts):
    return "M" + " L".join("%s %s" % (fmt(x), fmt(y)) for x, y in pts) + " Z"


def ellipse(cx, cy, rx, ry):
    return ("M%s %s a%s %s 0 1 0 %s 0 a%s %s 0 1 0 %s 0 Z"
            % (fmt(cx - rx), fmt(cy), fmt(rx), fmt(ry), fmt(2 * rx), fmt(rx), fmt(ry), fmt(-2 * rx)))


def y_at(pts, x):
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
        if xa <= x <= xb:
            return ya + (yb - ya) * (x - xa) / (xb - xa)
    return pts[-1][1] if x > pts[-1][0] else pts[0][1]


def smooth(points, n=12):
    """Catmull-Rom spline through the points."""
    out = []
    p = [points[0]] + points + [points[-1]]
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        for k in range(n):
            t = k / n
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in (0, 1)))
    out.append(points[-1])
    return out


def horse(x, base, s, grazing, flip):
    """A small horse silhouette standing on (x, base), s = scale, facing right
    (left when flip)."""
    sx = -s if flip else s
    P = lambda pts: poly([(x + px * sx, base + py * s) for px, py in pts])
    parts = [ellipse(x, base - 30 * s, 23 * s, 9.5 * s)]
    if grazing:
        parts.append(P([(14, -36), (25, -18), (31, -6), (27, -3), (19, -16), (11, -28)]))
        parts.append(P([(27, -8), (35, -3), (34, 0), (26, -2)]))
    else:
        parts.append(P([(13, -36), (21, -55), (27, -54), (24, -36), (18, -27)]))
        parts.append(P([(21, -55), (35, -49), (35, -45), (25, -46)]))
        parts.append(P([(19, -52), (17, -42), (14, -36), (17, -48)]))   # mane
    for lx in (-17, -12, 12, 17):
        parts.append(P([(lx - 1.6, -24), (lx + 1.6, -24), (lx + 1.3, 0), (lx - 1.3, 0)]))
    parts.append(P([(-21, -35), (-31, -19), (-27, -18), (-19, -31)]))   # tail
    return " ".join(parts)


def build(L):
    W = L["width"]
    rnd = random.Random(1919)  # the year Bashkortostan became an autonomous republic
    layers = {}

    def profile(base, octaves, bumps=(), step=6, x0=0, x1=W):
        fs = [(noise1d(s, wl, W), a) for wl, a, s in octaves]
        pts, x = [], x0
        while x <= x1:
            y = base - sum(f(x) * a for f, a in fs)
            for bx, bh, bw, flat in bumps:
                y -= bh * math.exp(-abs((x - bx) / bw) ** (2 * flat))
            pts.append((x, y))
            x += step
        return pts

    kx = W / 5760   # horizontal scale of features relative to the panorama
    sx = max(kx, 0.6)

    # Far Southern Ural: Yamantau (massive) and Iremel (bald, flat-topped).
    far = profile(560, [(900 * sx, 38, 1), (330 * sx, 18, 2), (110 * sx, 6, 3)],
                  bumps=[(L["yamantau"], 120, 520 * sx, 1), (L["iremel"], 150, 300 * sx, 1.8), (L["iremel2"], 60, 220 * sx, 1)])
    layers["far"] = closed(far)
    mid = profile(612, [(620 * sx, 30, 4), (210 * sx, 14, 5), (70 * sx, 4, 6)],
                  bumps=[(L["ridge2"][0], 40, 600 * sx, 1), (L["ridge2"][1], 35, 400 * sx, 1)])
    layers["mid"] = closed(mid)

    # Shikhan: an isolated steep limestone dome, with bare rock streaks.
    cx, sw = L["shikhan"], L["shikhan_w"]
    shikhan = []
    for i in range(121):
        x = cx - 1.8 * sw + i / 120 * 3.6 * sw
        dx = (x - cx) / sw
        y = 668 - 245 * math.exp(-abs(dx) ** 2.4) - 8 * math.sin(x / 23) * math.exp(-dx * dx)
        shikhan.append((x, y))
    layers["shikhan"] = closed(shikhan, 700)
    rock = []
    for k in range(9):
        x = cx - 0.4 * sw + k * sw * 0.093 + rnd.uniform(-6, 6)
        top = y_at(shikhan, x) + rnd.uniform(4, 18)
        rock.append(poly([(x, top), (x + 5, top), (x + 2 + rnd.uniform(-3, 3), top + rnd.uniform(40, 90))]))
    layers["shikhanRock"] = " ".join(rock)

    # Forested hills: conifers (always dark) and deciduous crowns (seasonal).
    hills = profile(668, [(520 * sx, 22, 7), (170 * sx, 10, 8)])
    layers["hills"] = closed(hills)
    conifers, crowns = [], []
    x = 0
    while x < W:
        if abs(x - cx) < 1.3 * sw:          # leave the shikhan's foot clear
            x += 14
            continue
        y = y_at(hills, x) + 3
        if rnd.random() < 0.62:
            h = rnd.uniform(10, 24)
            w = h * rnd.uniform(0.32, 0.42)
            conifers.append(poly([(x - w, y), (x, y - h), (x + w, y)]))
        else:
            r = rnd.uniform(4, 8)
            crowns.append(ellipse(x, y - r * 0.8, r, r * 0.85))
        x += rnd.uniform(5, 11)
    layers["hillConifers"] = " ".join(conifers)
    layers["hillCrowns"] = " ".join(crowns)

    plain = profile(700, [(800 * sx, 8, 9), (260 * sx, 4, 10)])
    layers["plain"] = closed(plain)

    # River Belaya with shimmer lines.
    line = smooth(L["river"])
    rw = L["river_w"]
    left, right = [], []
    for i, (x, y) in enumerate(line):
        nx, ny = line[min(i + 1, len(line) - 1)]
        px, py = line[max(i - 1, 0)]
        dx, dy = nx - px, ny - py
        ln = math.hypot(dx, dy) or 1
        half = 2 + ((y - 704) / (1090 - 704)) ** 1.7 * rw
        ox, oy = -dy / ln * half, dx / ln * half * 0.35
        left.append((x + ox, y + oy))
        right.append((x - ox, y - oy))
    layers["river"] = poly(left + right[::-1])
    shimmer = []
    for i in range(10, len(line) - 2, 3):
        x, y = line[i]
        half = 2 + ((y - 704) / (1090 - 704)) ** 1.7 * rw
        ln = half * rnd.uniform(0.25, 0.6)
        off = rnd.uniform(-half * 0.4, half * 0.4)
        shimmer.append(poly([(x + off - ln, y), (x + off + ln, y), (x + off + ln * 0.9, y + 1.6), (x + off - ln * 0.9, y + 1.6)]))
    layers["shimmer"] = " ".join(shimmer)

    # Near ground: a rise on the left (yurt, horses) and a slope on the right (birches).
    a, b, bump, fall, fw = L["near_left"]
    nearL = profile(930, [(500 * sx, 22, 11), (150 * sx, 6, 12)], bumps=[(bump, 80, 520 * sx, 1)], x0=a, x1=b)
    nearL = [(x, y + max(0, (x - fall) / fw) ** 2 * 260) for x, y in nearL]
    layers["nearLeft"] = closed(nearL)
    a, b, bump, fall, fw = L["near_right"]
    nearR = profile(960, [(500 * sx, 20, 13), (140 * sx, 6, 14)], bumps=[(bump, 90, 700 * sx, 1)], x0=a, x1=b)
    nearR = [(x, y + max(0, (fall - x) / fw) ** 2 * 260) for x, y in nearR]
    layers["nearRight"] = closed(nearR)

    grass = []
    for pts, (xa, xb) in ((nearL, L["grass_left"]), (nearR, L["grass_right"])):
        for _ in range(int(260 * (xb - xa) / 1700)):
            x = rnd.uniform(xa, xb)
            y = y_at(pts, x) + rnd.uniform(2, 60)
            h = rnd.uniform(6, 16)
            lean = rnd.uniform(-4, 4)
            grass.append(poly([(x - 1.4, y), (x + lean, y - h), (x + 1.4, y)]))
    layers["grass"] = " ".join(grass)

    # Bashkir yurt (tirmä): felt walls, dome, red ornament band, door, smoke.
    yx = L["yurt"]
    yb = y_at(nearL, yx) + 6
    ww, wh, dh = 150, 64, 58
    # Dome: two quadratic curves, sampled into points (the GPU curve renderer
    # in Plasma skipped Q segments mixed into a multi-part path).
    def quad(p0, p1, p2, n=16):
        return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                 (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (k / n for k in range(n + 1))]
    dome = (quad((yx - ww / 2 - 6, yb - wh), (yx - ww / 2 + 10, yb - wh - dh * 0.9), (yx, yb - wh - dh))
            + quad((yx, yb - wh - dh), (yx + ww / 2 - 10, yb - wh - dh * 0.9), (yx + ww / 2 + 6, yb - wh))[1:])
    layers["yurt"] = (poly([(yx - ww / 2, yb), (yx - ww / 2, yb - wh + 1), (yx + ww / 2, yb - wh + 1), (yx + ww / 2, yb)])
                      + " " + poly(dome))
    layers["yurtBand"] = poly([(yx - ww / 2, yb - wh + 4), (yx + ww / 2, yb - wh + 4),
                               (yx + ww / 2, yb - wh + 13), (yx - ww / 2, yb - wh + 13)])
    layers["yurtDoor"] = poly([(yx - 16, yb), (yx - 16, yb - 46), (yx + 16, yb - 46), (yx + 16, yb)])
    layers["yurtShade"] = poly([(yx + ww / 6, yb), (yx + ww / 6, yb - wh), (yx + ww / 2, yb - wh), (yx + ww / 2, yb)])
    smoke = []
    top = yb - wh - dh
    for k in range(7):
        t = k / 6
        smoke.append(ellipse(yx + 4 + t * 70 + math.sin(t * 5) * 10, top - 14 - t * 120, 9 + t * 22, 6 + t * 12))
    layers["smoke"] = " ".join(smoke)
    layers["yurtX"] = fmt(yx)
    layers["yurtTop"] = fmt(top)

    # Two horses near the yurt: one grazing, one looking up.
    h1, h2 = L["horses"]
    layers["horses"] = (horse(h1, y_at(nearL, h1) + 14, 1.15, True, False) + " "
                        + horse(h2, y_at(nearL, h2) + 20, 1.25, False, True))

    # Birch grove: weeping birches. A curved white trunk with dark marks; limbs
    # that rise and arch over; thin twigs hanging from them; small leaves along
    # the twigs in three tones (shadow, base, sunlit), loose enough for the sky
    # to show through; fallen leaves under the trees. Own random generator, so
    # the rest of the landscape stays where it is.
    br = random.Random(77)
    trunks, marks, limbs, twigs, fallen = [], [], [], [], []
    leaves = {"Dark": [], "Mid": [], "Light": []}

    def stroke(pts, w0, w1):
        """Tapered band along a polyline."""
        left, right, n = [], [], len(pts)
        for i, (x, y) in enumerate(pts):
            nx, ny = pts[min(i + 1, n - 1)]
            px, py = pts[max(i - 1, 0)]
            dx, dy = nx - px, ny - py
            ln = math.hypot(dx, dy) or 1
            hw = (w0 + (w1 - w0) * i / (n - 1)) / 2
            left.append((x - dy / ln * hw, y + dx / ln * hw))
            right.append((x + dy / ln * hw, y - dx / ln * hw))
        return poly(left + right[::-1])

    def leaf(x, y, size, ang):
        """A small pointed leaf (a slim diamond) pointing along ang."""
        ca, sa = math.cos(ang), math.sin(ang)
        wd = size * 0.5
        pts = [(x + ca * size, y + sa * size), (x - sa * wd, y + ca * wd),
               (x - ca * size * 0.55, y - sa * size * 0.55), (x + sa * wd, y - ca * wd)]
        d = "M%s %s" % (fmt(pts[0][0]), fmt(pts[0][1]))
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            d += "l%s %s" % (fmt(xb - xa), fmt(yb - ya))
        return d + "z"

    def curve(p0, p1, p2, n):
        return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                 (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (k / n for k in range(n + 1))]

    for bx in L["birches"]:
        bx += br.uniform(-30, 30) * sx
        base = y_at(nearR, bx) + br.uniform(8, 30)
        h = br.uniform(320, 520)
        w = br.uniform(9, 14)
        lean = br.uniform(-18, 18)
        bend = br.uniform(-6, 6)

        def trunk_at(t):
            return (bx + lean * t + math.sin(t * 3.1) * bend, base - h * t)
        trunks.append(stroke([trunk_at(k / 24 * 0.9) for k in range(25)], w, w * 0.3))
        for k in range(int(h / 22)):
            t = br.uniform(0.04, 0.8)
            mx, my = trunk_at(t)
            wd = w * (1 - t * 0.75)
            ml = wd * br.uniform(0.3, 0.85)
            side = br.choice((-1, 1))
            x0 = mx + side * wd / 2
            marks.append(poly([(x0, my), (x0 - side * ml, my - 1), (x0 - side * ml, my + 2.4), (x0, my + 3.2)]))

        nlimbs = br.randint(7, 10)
        for k in range(nlimbs):
            t = 0.36 + 0.56 * (k + br.random()) / nlimbs
            ax, ay = trunk_at(t)
            side = -1 if (k + (bx > 0)) % 2 else 1
            ln = br.uniform(60, 140) * (1.3 - t * 0.6)
            ang = math.radians(br.uniform(24, 50))      # from the vertical: birch limbs rise steeply
            p1 = (ax + side * math.sin(ang) * ln * 0.5, ay - math.cos(ang) * ln * 0.9)
            p2 = (ax + side * math.sin(ang) * ln * 0.95, ay - math.cos(ang) * ln * 0.75)
            lp = curve((ax, ay), p1, p2, 14)
            limbs.append(stroke(lp, 2.3 * (1.1 - t * 0.6), 0.5))
            # the crown mass: leaf clusters around the limb
            for j in range(2, len(lp)):
                cxl, cyl = lp[j]
                for _ in range(br.randint(4, 8)):
                    lx, ly = cxl + br.gauss(0, 9), cyl + br.gauss(0, 7)
                    r = br.random()
                    tone = "Light" if r < 0.3 + 0.25 * (ly < cyl) else ("Dark" if r > 0.82 else "Mid")
                    leaves[tone].append(leaf(lx, ly, br.uniform(3.2, 5.4), br.uniform(0, math.pi * 2)))
            for j in range(3, len(lp)):
                if br.random() < 0.38:
                    continue
                tx, ty = lp[j]
                tl = br.uniform(35, 120) * (0.55 + j / len(lp) * 0.6)
                sway = br.uniform(-9, 9)
                path = [(tx + sway * q ** 1.6 + side * 7 * q, ty + tl * q) for q in (i / 8 for i in range(9))]
                twigs.append(stroke(path, 1.0, 0.45))
                q = br.uniform(0.04, 0.18)
                while q <= 1.0:
                    lx = tx + sway * q ** 1.6 + side * 7 * q + br.gauss(0, 3.2)
                    ly = ty + tl * q + br.gauss(0, 2.2)
                    r = br.random()
                    # sunlit near the top of the hanging strands, shadow low and inside
                    if r < 0.16 or (q < 0.35 and r < 0.5):
                        tone = "Light"
                    elif r > 0.86 or (q > 0.68 and r > 0.45):
                        tone = "Dark"
                    else:
                        tone = "Mid"
                    leaves[tone].append(leaf(lx, ly, br.uniform(3.0, 5.0), math.pi / 2 + br.uniform(-1.0, 1.0)))
                    q += br.uniform(0.045, 0.1)
        topx, topy = trunk_at(0.95)
        for _ in range(br.randint(90, 140)):
            lx, ly = topx + br.gauss(0, 16), topy + abs(br.gauss(0, 30))
            r = br.random()
            tone = "Light" if r < 0.45 else ("Dark" if r > 0.88 else "Mid")
            leaves[tone].append(leaf(lx, ly, br.uniform(3.2, 5.4), br.uniform(0, math.pi * 2)))
        for k in range(br.randint(45, 85)):
            fx = bx + br.gauss(0, 70)
            fy = y_at(nearR, fx) + br.uniform(4, 64)
            fallen.append(leaf(fx, fy, br.uniform(2.2, 3.8), br.uniform(-0.5, 0.5) + (0 if br.random() < 0.5 else math.pi)))
    layers["birchTrunks"] = " ".join(trunks)
    layers["birchMarks"] = " ".join(marks)
    layers["birchBranches"] = " ".join(limbs)
    layers["birchTwigs"] = " ".join(twigs)
    for tone, items in leaves.items():
        layers["birchLeaves" + tone] = " ".join(items)
    layers["birchFallen"] = " ".join(fallen)

    pines = []
    for px in L["pines"]:
        base = y_at(nearL, px) + 4
        h = rnd.uniform(150, 230)
        for k in range(6):
            ty = base - h * (0.25 + k * 0.13)
            tw = (h * 0.28) * (1 - k * 0.13)
            pines.append(poly([(px - tw, ty + h * 0.16), (px, ty - h * 0.07), (px + tw, ty + h * 0.16)]))
        pines.append(poly([(px - 3, base), (px - 2, base - h * 0.3), (px + 2, base - h * 0.3), (px + 3, base)]))
    layers["pines"] = " ".join(pines)

    stars = []
    for _ in range(L["stars"]):
        x, y = rnd.uniform(0, W), rnd.uniform(0, 470)
        r = rnd.choice((0.7, 0.8, 0.9, 1.0, 1.1, 1.3, 1.6))
        stars.append(ellipse(x, y, r, r))
    layers["stars"] = " ".join(stars)

    # Clouds: flat two-tone puffs in three sets that appear one after another as
    # the sky gets cloudier (few -> half -> overcast).
    cr = random.Random(23)

    def cloud(ccx, ccy, size):
        body, shade = [], []
        n = cr.randint(5, 8)
        for k in range(n):
            t = (k + 0.5) / n
            x = ccx + (t - 0.5) * size * 2.2 + cr.gauss(0, size * 0.08)
            r = size * (0.35 + 0.55 * math.sin(t * math.pi)) * cr.uniform(0.8, 1.1)
            y = ccy - r * 0.45
            body.append(ellipse(x, y, r * 1.1, r * 0.82))
            shade.append(ellipse(x, y + size * 0.16, r * 1.1, r * 0.78))
        body.append(ellipse(ccx, ccy + size * 0.05, size * 1.25, size * 0.28))
        shade.append(ellipse(ccx, ccy + size * 0.2, size * 1.2, size * 0.26))
        return body, shade

    for name, count, ylo, yhi, slo, shi in (("cloudsA", L["clouds"][0], 140, 300, 55, 85),
                                             ("cloudsB", L["clouds"][1], 90, 340, 45, 80),
                                             ("cloudsC", L["clouds"][2], 60, 380, 60, 110)):
        body, shade = [], []
        for i in range(count):
            ccx = (i + cr.uniform(0.1, 0.9)) * W / count
            bd, sh = cloud(ccx, cr.uniform(ylo, yhi), cr.uniform(slo, shi))
            body += bd
            shade += sh
        layers[name] = " ".join(body)
        layers[name + "Shade"] = " ".join(shade)

    layers["glow"] = ellipse(0, 0, 230, 230)

    # Rain streaks and snow flakes on a 1920x1080 tile (repeated and scrolled).
    rain, snow = [], []
    tr = random.Random(7)
    for _ in range(520):
        x, y = tr.uniform(0, 1920), tr.uniform(0, 1080)
        ln = tr.uniform(14, 30)
        rain.append(poly([(x, y), (x + 0.9, y), (x - ln * 0.18 + 0.9, y + ln), (x - ln * 0.18, y + ln)]))
    for _ in range(420):
        x, y = tr.uniform(0, 1920), tr.uniform(0, 1080)
        r = tr.choice((1.2, 1.5, 1.8, 2.2, 2.6))
        snow.append(ellipse(x, y, r, r))
    layers["rain"] = " ".join(rain)
    layers["snow"] = " ".join(snow)
    return layers


for name, L in LAYOUTS.items():
    layers = build(L)
    out = os.path.join(HERE, "..", "contents", "ui", name + ".js")
    with open(out, "w") as f:
        f.write("// Generated by tools/gen_scene.py, do not edit.\n.pragma library\n\n")
        f.write("var width = %d;\nvar height = %d;\n\n" % (L["width"], H))
        for k, v in layers.items():
            f.write("var %s = %r;\n" % (k, v))
    print("wrote", os.path.normpath(out), sum(len(v) for v in layers.values()) // 1024, "KiB")
