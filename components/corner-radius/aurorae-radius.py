#!/usr/bin/env python3
"""Shrink the rounded top corners of an Aurorae decoration.svg.

Every quarter-circle arc (a cubic whose endpoints are ~R apart on both axes,
R within RANGE) inside the top corner groups is scaled about its corner
point, so it stays tangent to both window edges. Radius R becomes R - DELTA,
which keeps concentric outline arcs (R and R+1) concentric.

usage: aurorae-radius.py decoration.svg NEW_RADIUS
       aurorae-radius.py panel-background.svgz NEW_RADIUS --panel
       (--panel: Plasma theme dock background, south-* corners, radius 16)
       aurorae-radius.py dialogs/background.svgz NEW_RADIUS --dialog
       (--dialog: Plasma popup background incl. mask/shadow corners, radius 11)
"""
import gzip
import re
import sys
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
for p, u in {"inkscape": "http://www.inkscape.org/namespaces/inkscape",
             "sodipodi": "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
             "xlink": "http://www.w3.org/1999/xlink"}.items():
    ET.register_namespace(p, u)

BASE_R = 24.0          # radius of the main fill arc in this theme
RANGE = (20.0, 30.0)
TOKEN = re.compile(r"[MmLlHhVvCcZz]|-?\d*\.?\d+(?:e-?\d+)?")


def parse(d):
    """Path data -> list of (cmd, [points]) in absolute coordinates."""
    toks = TOKEN.findall(d)
    out, i, cmd = [], 0, None
    cur = start = (0.0, 0.0)
    while i < len(toks):
        if re.match(r"[A-Za-z]", toks[i]):
            cmd = toks[i]; i += 1
            if cmd in "Zz":
                out.append(("Z", [])); cur = start
                continue
        rel = cmd.islower()
        c = cmd.upper()
        n = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6}[c]
        v = [float(x) for x in toks[i:i + n]]; i += n
        if c in "ML":
            pt = (v[0] + cur[0], v[1] + cur[1]) if rel else (v[0], v[1])
            out.append((c, [pt])); cur = pt
            if c == "M":
                start = pt
                cmd = "l" if rel else "L"  # implicit lineto after moveto
        elif c == "H":
            pt = (v[0] + (cur[0] if rel else 0), cur[1]); out.append(("L", [pt])); cur = pt
        elif c == "V":
            pt = (cur[0], v[0] + (cur[1] if rel else 0)); out.append(("L", [pt])); cur = pt
        elif c == "C":
            pts = [(v[k] + cur[0], v[k + 1] + cur[1]) if rel else (v[k], v[k + 1]) for k in (0, 2, 4)]
            out.append(("C", pts)); cur = pts[2]
    return out


def fmt(x):
    return ("%.4f" % x).rstrip("0").rstrip(".")


def shrink(segs, delta):
    changed = 0
    moved = {}  # old endpoint -> new endpoint
    prev = None
    for idx, (c, pts) in enumerate(segs):
        if c == "C" and prev is not None:
            p0, c1, c2, p3 = prev, pts[0], pts[1], pts[2]
            dx, dy = p3[0] - p0[0], p3[1] - p0[1]
            R = abs(dx)
            if RANGE[0] <= R <= RANGE[1] and abs(abs(dx) - abs(dy)) < 0.6:
                # corner point: where the tangents at p0 and p3 intersect
                if abs(c1[1] - p0[1]) < 1e-3:      # leaves p0 horizontally
                    k = (p3[0], p0[1])
                else:                               # leaves p0 vertically
                    k = (p0[0], p3[1])
                s = (R - delta) / R
                sc = lambda p: (k[0] + (p[0] - k[0]) * s, k[1] + (p[1] - k[1]) * s)
                np0, npts = sc(p0), [sc(p) for p in pts]
                moved[p0] = np0
                moved[p3] = npts[2]
                segs[idx] = ("C", npts)
                changed += 1
        if pts:
            prev = pts[-1]
    if not changed:
        return 0
    # endpoints shared with neighbouring M/L segments follow the arc
    for idx, (c, pts) in enumerate(segs):
        if c in "ML":
            p = pts[0]
            for old, new in moved.items():
                if abs(p[0] - old[0]) < 1e-3 and abs(p[1] - old[1]) < 1e-3:
                    segs[idx] = (c, [new])
    return changed


def serialize(segs):
    parts = []
    for c, pts in segs:
        parts.append(c + (" " + " ".join(fmt(x) + " " + fmt(y) for x, y in pts) if pts else ""))
    return " ".join(parts)


def main():
    global BASE_R, RANGE
    path, new_r = sys.argv[1], float(sys.argv[2])
    panel = "--panel" in sys.argv
    groups = r"decoration(-inactive)?-(topleft|topright)"
    if panel:
        BASE_R, RANGE = 16.0, (12.0, 20.0)
        groups = r"south(-mask)?-(topleft|topright|bottomleft|bottomright)"
    if "--dialog" in sys.argv:
        BASE_R, RANGE = 11.0, (9.0, 13.0)
        groups = r"(mask-|shadow-)?(topleft|topright|bottomleft|bottomright)"
    delta = BASE_R - new_r
    gz = path.endswith(".svgz")
    tree = ET.parse(gzip.open(path) if gz else path)
    root = tree.getroot()
    total = 0
    for g in root.iter():
        gid = g.get("id") or ""
        if not re.fullmatch(groups, gid):
            continue
        for el in g.iter():
            if el.tag.endswith("path") and el.get("d"):
                segs = parse(el.get("d"))
                n = shrink(segs, delta)
                if n:
                    el.set("d", serialize(segs))
                    total += n
    if gz:
        with gzip.open(path, "wb") as f:
            tree.write(f, xml_declaration=True, encoding="UTF-8")
    else:
        tree.write(path, xml_declaration=True, encoding="UTF-8")
    print(f"rewrote {total} corner arcs -> radius {new_r:g}")


if __name__ == "__main__":
    main()
