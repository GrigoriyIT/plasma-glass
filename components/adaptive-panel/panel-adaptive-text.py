#!/usr/bin/env python3
"""Adaptive top-bar text color, macOS style.

Measures the brightness of the wallpaper strip that sits under the top panel
and sets Panel Colorizer's foreground to dark text on light wallpapers and
white text on dark ones. The panel itself is kept fully transparent, with no
text shadow/outline. Runs from panel-adaptive-text.path whenever the Plasma
desktop config changes; only writes back when something actually changes, so
its own write doesn't cause a loop.
"""
import configparser
import glob
import json
import os
import re
import subprocess
import sys

from PIL import Image

APPLETSRC = os.path.expanduser("~/.config/plasma-org.kde.plasma.desktop-appletsrc")
COLORIZER = "luisbocanegra.panel.colorizer"
DEFAULT_IMAGES = {
    "local.clockwallpaper": "/usr/share/wallpapers/ColdRipple/contents/images/2560x1600.jpg",
}
DARK_TEXT = "#1d1d1f"
LIGHT_TEXT = "#ffffff"
# Mean luminance (0..1) above which the strip counts as "light".
THRESHOLD = 0.55
PANEL_HEIGHT = 32


def load_config():
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read(APPLETSRC, encoding="utf-8")
    return cp


def screen_size():
    for modes in glob.glob("/sys/class/drm/card*-eDP-*/modes") + glob.glob("/sys/class/drm/card*-*/modes"):
        try:
            first = open(modes).readline().strip()
        except OSError:
            continue
        m = re.match(r"(\d+)x(\d+)", first)
        if m:
            return int(m.group(1)), int(m.group(2))
    return 1920, 1080


def resolve_image(path):
    path = re.sub(r"^file://", "", path or "")
    if os.path.isdir(path):  # KPackage wallpaper: pick the largest image
        files = glob.glob(os.path.join(path, "contents/images/*"))
        best, area = None, 0
        for f in files:
            m = re.search(r"(\d+)x(\d+)", os.path.basename(f))
            a = int(m.group(1)) * int(m.group(2)) if m else 0
            if a >= area:
                best, area = f, a
        return best
    return path if os.path.isfile(path) else None


def current_wallpaper(cp):
    """Wallpaper image of the desktop on the primary screen (lastScreen=0)."""
    for sec in cp.sections():
        if not re.fullmatch(r"Containments\]\[\d+", sec):
            continue
        if cp.get(sec, "plugin", fallback="") != "org.kde.plasma.folder":
            continue
        if cp.get(sec, "lastScreen", fallback="") != "0":
            continue
        plugin = cp.get(sec, "wallpaperplugin", fallback="org.kde.image")
        img = cp.get(f"{sec}][Wallpaper][{plugin}][General", "Image",
                     fallback=DEFAULT_IMAGES.get(plugin, ""))
        return resolve_image(img)
    return None


def strip_luminance(image_path, sw, sh):
    """Mean luminance of the image area shown under the top panel
    (the wallpaper is drawn with PreserveAspectCrop)."""
    im = Image.open(image_path).convert("L")
    iw, ih = im.size
    scale = max(sw / iw, sh / ih)
    vis_w, vis_h = sw / scale, sh / scale
    x0, y0 = (iw - vis_w) / 2, (ih - vis_h) / 2
    strip = im.crop((int(x0), int(y0), int(x0 + vis_w), int(y0 + PANEL_HEIGHT / scale) + 1))
    hist = strip.histogram()
    total = sum(hist)
    return sum(i * n for i, n in enumerate(hist)) / total / 255


def colorizer_settings(cp):
    for sec in cp.sections():
        if cp.get(sec, "plugin", fallback="") == COLORIZER:
            general = f"{sec}][Configuration][General"
            return (sec, cp.get(general, "globalSettings", fallback=None),
                    cp.get(general, "panelWidgets", fallback="[]"),
                    cp.get(general, "forceForegroundColor", fallback="{}"))
    return None, None, "[]", "{}"


# Never recolor: layout helpers, and Happ, whose tray icon is an opaque
# black-and-white square that turns into a solid block when masked.
NO_RECOLOR = {COLORIZER, "org.kde.plasma.panelspacer", "org.kde.plasma.marginsseparator", "Happ",
              "Glass VPN"}  # Glass VPN draws its own icon: panel-coloured shield + status dot


def force_recolor(panel_widgets):
    """Monochrome every top-bar icon. KDE widgets only need the icon mask;
    third-party tray icons are pixmaps, so they also get the colorize effect.
    Rebuilt on every run because some tray item names embed a PID."""
    widgets = []
    for w in json.loads(panel_widgets):
        name = w["name"]
        if name in NO_RECOLOR:
            continue
        app_icon = w.get("inTray", False) and not name.startswith("org.kde.")
        # The global menu rebuilds its entries on every window switch, so it
        # has to be recolored periodically too, like tray items that come and go.
        dynamic = w.get("inTray", False) or "globalmenu" in name or "appmenu" in name
        widgets.append({
            "name": name,
            "id": w["id"],
            "method": {"mask": True, "multiEffect": app_icon},
            "reload": dynamic,
        })
    return {"widgets": widgets, "reloadInterval": 150}


def apply(settings, text_color):
    d = json.loads(settings)
    bg = d["panel"]["normal"]["backgroundColor"]
    bg["enabled"] = False
    d["panel"]["normal"]["blurBehind"] = False
    for part in ("widgets", "trayWidgets"):
        n = d[part]["normal"]
        n["enabled"] = True
        n["shadow"]["foreground"]["enabled"] = False
        fg = n["foregroundColor"]
        fg.update({"enabled": True, "sourceType": 0, "custom": text_color, "alpha": 1})
    return d


def main():
    cp = load_config()
    image = current_wallpaper(cp)
    if not image:
        print("wallpaper image not found; leaving panel as is")
        return 0
    sw, sh = screen_size()
    lum = strip_luminance(image, sw, sh)
    text = DARK_TEXT if lum > THRESHOLD else LIGHT_TEXT
    sec, settings, panel_widgets, old_force = colorizer_settings(cp)
    if not settings:
        print("Panel Colorizer not found")
        return 1
    new = apply(settings, text)
    force = force_recolor(panel_widgets)
    print(f"{image}: luminance={lum:.2f} -> text {text}")
    writes = {}
    if new != json.loads(settings) or "--force" in sys.argv:
        writes["globalSettings"] = new
    try:
        old_force = json.loads(old_force)
    except ValueError:
        old_force = {}
    if force != old_force or "--force" in sys.argv:
        writes["forceForegroundColor"] = force
    if not writes:
        return 0
    body = "".join("w.writeConfig(%s, %s);" % (json.dumps(k), json.dumps(json.dumps(v, separators=(",", ":"), ensure_ascii=False)))
                   for k, v in writes.items())
    js = ("panels().forEach(function(p){ p.widgets(%s).forEach(function(w){"
          "w.currentConfigGroup=['General']; %s }); });" % (json.dumps(COLORIZER), body))
    subprocess.run(["qdbus6", "org.kde.plasmashell", "/PlasmaShell",
                    "org.kde.PlasmaShell.evaluateScript", js], check=True)
    print("updated:", ", ".join(writes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
