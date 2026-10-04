#!/usr/bin/env python3
"""Glass Widgets — the Plasma Glass desktop widgets (weather, markets, agenda) on macOS.

The widgets are the very same QML packages as on Plasma (components/*-widget). This
host gives them what Plasma would: small stand-ins for the Plasma/Kirigami modules
(shim/), the widget settings, an SQLite cache behind Qt's LocalStorage API,
notifications and, for the agenda, the system Calendar through EventKit. Each widget
is a borderless window on the desktop layer — under the app windows, on every Space —
blurred by the system (NSVisualEffectView) instead of Plasma's wallpaper trick.

Right click a widget for its menu; drag it with ⌥ (Option) held to move it.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from PyQt6.QtCore import QEvent, QEventLoop, QObject, QSize, Qt, QTimer, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtQml import QJSValue, QQmlPropertyMap
from PyQt6.QtQuick import QQuickImageProvider, QQuickView, QQuickWindow
from PyQt6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox

HERE = Path(__file__).resolve().parent
SHIM = HERE / "shim"
ICONS = HERE / "icons"
SUPPORT = Path.home() / "Library/Application Support/GlassWidgets"
CONFIG = SUPPORT / "config.json"
CACHE = Path.home() / "Library/Caches/GlassWidgets"
AUTOSTART = Path.home() / "Library/LaunchAgents/local.glasswidgets.plist"
APP_BUNDLE = Path.home() / "Applications/Glass Widgets.app"
USER_AGENT = "GlassWidgets/1.0 (+https://github.com/plasma-glass)"   # Nominatim asks for one

# key -> QML package, size, default corner and settings that differ from the package defaults
WIDGETS = {
    "weather": {"pkg": "org.plasmaglass.weather", "title": "Погода", "size": (464, 256), "corner": "left",
                "config": {"city": "Уфа", "latitude": 54.7558, "longitude": 56.0050}},
    "agenda": {"pkg": "org.plasmaglass.agenda", "title": "Календарь", "size": (464, 304), "corner": "left",
               "config": {}},
    "markets": {"pkg": "org.plasmaglass.markets", "title": "Котировки", "size": (608, 480), "corner": "right",
                "config": {}},
}
REGIONS = [("", "только федеральные выходные"), ("02", "Башкортостан")]
MARGIN, GAP, RADIUS = 24, 16, 16


# ---------------------------------------------------------------- settings --

def load_config():
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    SUPPORT.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
    tmp.replace(CONFIG)


def package_dir(pkg):
    """Installed copy next to this file, or the repo's components/*-widget/<pkg>."""
    for p in [HERE / "widgets" / pkg, *HERE.parent.glob(f"*-widget/{pkg}")]:
        if (p / "contents/ui/main.qml").exists():
            return p
    raise FileNotFoundError(pkg)


def kcfg_defaults(pkg_dir):
    """Defaults from the package's contents/config/main.xml (KConfigXT)."""
    out = {}
    try:
        root = ET.parse(pkg_dir / "contents/config/main.xml").getroot()
    except (OSError, ET.ParseError):
        return out
    for e in root.iter():
        if not e.tag.endswith("entry"):
            continue
        typ = e.get("type", "String")
        d = next((c.text or "" for c in e if c.tag.endswith("default")), "")
        out[e.get("name")] = (int(d or 0) if typ == "Int" else float(d or 0) if typ == "Double"
                              else d.strip().lower() == "true" if typ == "Bool" else d)
    return out


def prepared_qml(pkg):
    """A copy of the package for this host: Plasma's attached Plasmoid.backgroundHints
    can't be expressed with the stand-in singleton, and the macOS card has no background
    of its own anyway, so that line is dropped. Everything else is loaded as is."""
    src = package_dir(pkg)
    dst = CACHE / "qml" / pkg
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    for f in dst.rglob("*.qml"):
        text = f.read_text()
        fixed = re.sub(r"(?m)^\s*Plasmoid\.backgroundHints:.*\n", "", text)
        if fixed != text:
            f.write_text(fixed)
    return dst / "contents/ui/main.qml"


# ------------------------------------------------------------- the host API --

class IconProvider(QQuickImageProvider):
    """image://icon/<freedesktop name> from the bundled Breeze weather icons."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Pixmap)

    def requestPixmap(self, name, requested):
        path = ICONS / f"{name}.svg"
        if not path.exists():
            path = ICONS / "weather-none-available.svg"
        size = requested if requested.isValid() and requested.width() > 0 else QSize(128, 128)
        pm = QIcon(str(path)).pixmap(size)
        return pm, pm.size()


class TileProvider(QQuickImageProvider):
    """image://tile/z/x/y — OpenStreetMap tiles with an identifying User-Agent (their
    tile policy requires one), cached on disk. Runs off the GUI thread (async Image)."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, zxy, requested):
        path = CACHE / "tiles" / (zxy.replace("/", "-") + ".png")
        if not path.exists():
            try:
                req = urllib.request.Request(f"https://tile.openstreetmap.org/{zxy}.png",
                                             headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = r.read()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            except Exception as e:
                print(f"tile {zxy}: {e}", file=sys.stderr)
                img = QImage(256, 256, QImage.Format.Format_RGB32)
                img.fill(0x3a3a3c)
                return img, img.size()
        img = QImage(str(path))
        return img, img.size()


class Picker(QObject):
    """`picker` in MapPicker.qml."""

    def __init__(self, lat, lon):
        super().__init__()
        self._lat, self._lon = lat, lon
        self.result = None
        self.loop = QEventLoop()

    @pyqtProperty(float, constant=True)
    def lat(self):
        return self._lat

    @pyqtProperty(float, constant=True)
    def lon(self):
        return self._lon

    @pyqtSlot(float, float)
    def accept(self, lat, lon):
        self.result = (lat, lon)
        self.loop.quit()

    @pyqtSlot()
    def cancel(self):
        self.loop.quit()


def pick_on_map(lat, lon):
    """Show the map; (lat, lon) of the chosen point, or None."""
    picker = Picker(lat, lon)
    v = QQuickView()
    v.setTitle("Погода — выберите точку")
    tiles = TileProvider()
    v.engine().addImageProvider("tile", tiles)
    v.rootContext().setContextProperty("picker", picker)
    v.setSource(QUrl.fromLocalFile(str(HERE / "MapPicker.qml")))
    v.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    for e in v.errors():
        print(f"map: {e.toString()}", file=sys.stderr)

    class Closer(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.Close:
                picker.loop.quit()
            return False
    closer = Closer()
    v.installEventFilter(closer)
    bring_to_front()
    v.show()
    v.requestActivate()
    picker.loop.exec()
    v.hide()
    v.deleteLater()
    return picker.result


def place_name(lat, lon):
    """"Уфа, проспект Октября" for a point (Nominatim reverse), or ""."""
    try:
        url = "https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
            {"lat": lat, "lon": lon, "format": "json", "zoom": 17, "accept-language": "ru"})
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
                                    timeout=15) as r:
            a = json.loads(r.read()).get("address", {})
    except Exception:
        return ""
    city = a.get("city") or a.get("town") or a.get("village") or a.get("county") or ""
    street = a.get("road") or a.get("suburb") or ""
    return ", ".join(x for x in (city, street) if x)


def parse_coords(text):
    """"54.7559, 56.0048" / "54,7559 56,0048" / "54.7559N 56.0048E" -> (lat, lon) or None."""
    for pattern, fix in ((r"-?\d+\.\d+", str), (r"-?\d+,\d+", lambda x: x.replace(",", ".")),
                         (r"-?\d+(?:\.\d+)?", str)):
        nums = re.findall(pattern, text)
        if len(nums) == 2:
            lat, lon = (float(fix(n)) for n in nums)
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
    return None


class MacCalendar(QObject):
    """The system Calendar (every account added in macOS) for the agenda widget."""
    changed = pyqtSignal()
    accessChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        import EventKit
        self.ek = EventKit
        self.store = EventKit.EKEventStore.alloc().init()
        self._access = "pending"
        self.debounce = QTimer(singleShot=True, interval=1500, timeout=self.changed.emit)
        self.refresh_access()
        from Foundation import NSNotificationCenter, NSOperationQueue
        self.observer = NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            "EKEventStoreChangedNotification", self.store, NSOperationQueue.mainQueue(),
            lambda _n: self.debounce.start())

    def refresh_access(self):
        # 3 = full access (macOS 14+) / authorized; 0 = not asked yet; others = no
        status = self.ek.EKEventStore.authorizationStatusForEntityType_(self.ek.EKEntityTypeEvent)
        if status == 0:
            self.set_access("pending")
            done = lambda granted, _err: QTimer.singleShot(0, self.after_request)
            if hasattr(self.store, "requestFullAccessToEventsWithCompletion_"):
                self.store.requestFullAccessToEventsWithCompletion_(done)
            else:
                self.store.requestAccessToEntityType_completion_(self.ek.EKEntityTypeEvent, done)
        else:
            self.set_access("granted" if status == 3 else "denied")
        cals = self.store.calendarsForEntityType_(self.ek.EKEntityTypeEvent) or []
        print(f"calendar: access status {status}, {len(cals)} calendars", file=sys.stderr)

    def after_request(self):
        self.store.reset()
        self.refresh_access()
        self.changed.emit()

    def set_access(self, a):
        if a != self._access:
            self._access = a
            self.accessChanged.emit()

    @pyqtProperty(str, notify=accessChanged)
    def access(self):
        return self._access

    def events(self, start_ms, end_ms):
        """Same shape as ics.js occurrences: {t, end, allDay, calendar, color, summary, location}."""
        if self._access != "granted":
            return []
        from AppKit import NSColorSpace
        from Foundation import NSDate
        pred = self.store.predicateForEventsWithStartDate_endDate_calendars_(
            NSDate.dateWithTimeIntervalSince1970_(start_ms / 1000),
            NSDate.dateWithTimeIntervalSince1970_(end_ms / 1000), None)
        out, order = [], {}
        for e in self.store.eventsMatchingPredicate_(pred) or []:
            cal = e.calendar()
            color = ""
            c = cal.color().colorUsingColorSpace_(NSColorSpace.sRGBColorSpace()) if cal and cal.color() else None
            if c is not None:
                color = "#%02x%02x%02x" % tuple(round(255 * v) for v in
                                                 (c.redComponent(), c.greenComponent(), c.blueComponent()))
            out.append({
                "t": e.startDate().timeIntervalSince1970() * 1000,
                "end": e.endDate().timeIntervalSince1970() * 1000,
                "allDay": bool(e.isAllDay()),
                "calendar": order.setdefault(str(cal.calendarIdentifier()) if cal else "", len(order)),
                "color": color,
                "summary": str(e.title() or "(без названия)"),
                "location": str(e.location() or ""),
            })
        return out


class WidgetHost(QObject):
    """What the widget's QML sees as `host`."""

    def __init__(self, key, config, on_action, calendar=None):
        super().__init__()
        self.key = key
        self._config = config
        self._calendar = calendar
        self.on_action = on_action
        self.dbs = {}

    @pyqtProperty(QObject, constant=True)
    def config(self):
        return self._config

    @pyqtProperty(QObject, constant=True)
    def calendar(self):
        return self._calendar

    @pyqtSlot(str, str, "QVariantList", result="QVariantList")
    def sql(self, name, statement, args):
        db = self.dbs.get(name)
        if db is None:
            CACHE.mkdir(parents=True, exist_ok=True)
            db = self.dbs[name] = sqlite3.connect(CACHE / f"{name}.sqlite")
            db.row_factory = sqlite3.Row
        cur = db.execute(statement, list(args))
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        db.commit()
        return rows

    # PyQt6: slots of a class that has signals return nothing to QML, so the calendar's
    # events are served from here (this class has no signals)
    @pyqtSlot(float, float, result="QVariantList")
    def calendarEvents(self, start_ms, end_ms):
        return self._calendar.events(start_ms, end_ms) if self._calendar else []

    @pyqtSlot(QJSValue, QJSValue)
    def invoke(self, fn, arg):
        r = fn.call([arg])
        if r.isError():
            print(f"{self.key}: {r.toString()}", file=sys.stderr)

    @pyqtSlot(str, str)
    def notify(self, title, text):
        script = f"display notification {json.dumps(text)} with title {json.dumps(title)} sound name \"Glass\""
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @pyqtSlot(str)
    def action(self, name):
        self.on_action(self.key, name)


# ------------------------------------------------------------ macOS window --

def make_desktop_glass(view):
    """Desktop layer, every Space, not in ⌘Tab, and a system blur behind the card."""
    try:
        import objc
        from AppKit import (NSColor, NSViewHeightSizable, NSViewWidthSizable, NSVisualEffectView,
                            NSWindowBelow)
        from Quartz import CGWindowLevelForKey, kCGDesktopIconWindowLevelKey
    except ImportError:
        return
    nsview = objc.objc_object(c_void_p=int(view.winId()))
    win = nsview.window()
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setHasShadow_(False)
    win.setLevel_(CGWindowLevelForKey(kCGDesktopIconWindowLevelKey) + 1)
    # CanJoinAllSpaces | Stationary (stays put in Mission Control) | IgnoresCycle
    win.setCollectionBehavior_((1 << 0) | (1 << 4) | (1 << 6))
    fx = NSVisualEffectView.alloc().initWithFrame_(nsview.frame())
    fx.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
    fx.setBlendingMode_(0)        # behind the window: the desktop shows through, blurred
    fx.setMaterial_(13)           # HUD window: dark, like the Plasma card's tint
    fx.setState_(1)               # always active, even though the app never is
    fx.setWantsLayer_(True)
    fx.layer().setCornerRadius_(RADIUS)
    fx.layer().setMasksToBounds_(True)
    nsview.superview().addSubview_positioned_relativeTo_(fx, NSWindowBelow, nsview)
    view._glass = fx


class Widget(QObject):
    def __init__(self, app, key):
        super().__init__()
        self.app, self.key, self.spec = app, key, WIDGETS[key]
        st = app.cfg.setdefault("widgets", {}).setdefault(key, {})
        pkg = package_dir(self.spec["pkg"])
        values = {**kcfg_defaults(pkg), **self.spec["config"], **st.get("config", {})}
        self.config = QQmlPropertyMap(self)
        for k, v in values.items():
            self.config.insert(k, v)
        self.config.valueChanged.connect(self.config_changed)
        cal = app.calendar() if key == "agenda" else None
        self.host = WidgetHost(key, self.config, app.widget_action, cal)

        v = self.view = QQuickView()
        v.setColor(Qt.GlobalColor.transparent)
        v.setFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        v.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        v.setTitle(self.spec["title"])
        v.engine().addImportPath(str(SHIM))
        self.icons = IconProvider()     # keep it: the engine doesn't own the Python object
        v.engine().addImageProvider("icon", self.icons)
        v.rootContext().setContextProperty("host", self.host)
        v.rootContext().setContextProperty("hostCalendar", cal)
        v.setSource(QUrl.fromLocalFile(str(prepared_qml(self.spec["pkg"]))))
        for e in v.errors():
            print(f"{key}: {e.toString()}", file=sys.stderr)
        w, h = st.get("size") or self.spec["size"]
        v.resize(w, h)
        x, y = st.get("pos") or app.default_pos(key)
        v.setPosition(x, y)
        v.installEventFilter(self)
        self.save_pos = QTimer(singleShot=True, interval=800, timeout=self.remember_pos)
        v.xChanged.connect(lambda _: self.save_pos.start())
        v.yChanged.connect(lambda _: self.save_pos.start())

    def show(self):
        self.view.show()
        make_desktop_glass(self.view)

    def config_changed(self, k, v):
        st = self.app.cfg["widgets"][self.key].setdefault("config", {})
        st[k] = v
        save_config(self.app.cfg)

    def remember_pos(self):
        self.app.cfg["widgets"][self.key]["pos"] = [self.view.x(), self.view.y()]
        save_config(self.app.cfg)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonPress:
            if ev.button() == Qt.MouseButton.RightButton:
                self.app.menu_for(self, ev.globalPosition().toPoint())
                return True
            if ev.button() == Qt.MouseButton.LeftButton and ev.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.view.startSystemMove()
                return True
        return False

    def reload(self):
        self.view.engine().clearComponentCache()
        self.view.setSource(QUrl.fromLocalFile(str(prepared_qml(self.spec["pkg"]))))


# --------------------------------------------------------------------- app --

class App:
    def __init__(self, qapp):
        self.qapp = qapp
        self.cfg = load_config()
        self._calendar = None
        self.widgets = {}
        for key in WIDGETS:
            if self.cfg.get("widgets", {}).get(key, {}).get("hidden"):
                continue
            self.add(key)
        save_config(self.cfg)

    def add(self, key):
        try:
            w = self.widgets[key] = Widget(self, key)
            w.show()
        except Exception as e:     # one broken widget must not take the others down
            print(f"{key}: {e}", file=sys.stderr)

    def calendar(self):
        if self._calendar is None:
            try:
                self._calendar = MacCalendar()
            except ImportError:
                return None
        return self._calendar

    def default_pos(self, key):
        geo = self.qapp.primaryScreen().availableGeometry()
        y = geo.top() + MARGIN
        for k in WIDGETS:                 # stack the cards of the same side
            if k == key:
                break
            if WIDGETS[k]["corner"] == WIDGETS[key]["corner"]:
                y += WIDGETS[k]["size"][1] + GAP
        w = WIDGETS[key]["size"][0]
        x = geo.left() + MARGIN if WIDGETS[key]["corner"] == "left" else geo.right() - MARGIN - w
        return x, y

    # ---- menu
    def menu_for(self, widget, pos):
        m = QMenu()
        m.addAction(f"Настройки «{widget.spec['title']}»…").triggered.connect(
            lambda: self.widget_action(widget.key, "configure"))
        m.addAction("Обновить").triggered.connect(widget.reload)
        m.addAction(f"Скрыть «{widget.spec['title']}»").triggered.connect(lambda: self.set_hidden(widget.key, True))
        hidden = [k for k in WIDGETS if k not in self.widgets]
        if hidden:
            sm = m.addMenu("Показать")
            for k in hidden:
                sm.addAction(WIDGETS[k]["title"]).triggered.connect(lambda _=False, k=k: self.set_hidden(k, False))
        m.addAction("Вернуть на места по умолчанию").triggered.connect(self.reset_positions)
        m.addSeparator()
        hint = m.addAction("Переместить: перетащите с зажатой ⌥")
        hint.setEnabled(False)
        auto = m.addAction("Запускать при входе")
        auto.setCheckable(True)
        auto.setChecked(AUTOSTART.exists())
        auto.toggled.connect(set_autostart)
        m.addAction("Выход").triggered.connect(self.qapp.quit)
        bring_to_front()
        m.exec(pos)

    def set_hidden(self, key, hide):
        st = self.cfg.setdefault("widgets", {}).setdefault(key, {})
        st["hidden"] = hide
        save_config(self.cfg)
        if hide and key in self.widgets:
            self.widgets.pop(key).view.close()
        elif not hide and key not in self.widgets:
            self.add(key)

    def reset_positions(self):
        for key, w in self.widgets.items():
            self.cfg["widgets"][key].pop("pos", None)
            w.view.setPosition(*self.default_pos(key))
        save_config(self.cfg)

    # ---- settings per widget
    def widget_action(self, key, name):
        if name != "configure":
            return
        bring_to_front()
        c = self.widgets[key].config
        if key == "weather":
            self.configure_weather(c)
        elif key == "agenda":
            self.configure_agenda(c)
        elif key == "markets":
            self.configure_markets(c)

    def configure_weather(self, c):
        ways = ["Выбрать точку на карте", "Найти по адресу или названию", "Ввести координаты"]
        way, ok = QInputDialog.getItem(None, "Погода", f"Сейчас: {c.value('city')} "
                                       f"({float(c.value('latitude')):.4f}, {float(c.value('longitude')):.4f})",
                                       ways, 0, False)
        if not ok:
            return
        point = None
        if way == ways[0]:
            point = pick_on_map(float(c.value("latitude")), float(c.value("longitude")))
        elif way == ways[1]:
            point = self.search_place()
        else:
            text, ok = QInputDialog.getText(None, "Погода", "Широта и долгота, например 54.7559, 56.0048\n"
                                            "(можно вставить из Яндекс или Google Карт):")
            if ok:
                point = parse_coords(text)
                if not point:
                    QMessageBox.warning(None, "Погода", f"Не понял координаты: «{text}»")
        if not point:
            return
        lat, lon = point
        name, ok = QInputDialog.getText(None, "Погода", "Подпись на карточке:",
                                        text=place_name(lat, lon) or c.value("city"))
        if not ok:
            return
        for k, v in (("latitude", round(lat, 4)), ("longitude", round(lon, 4)), ("city", name.strip() or "—")):
            c.insert(k, v)                      # insert() doesn't emit valueChanged
            self.widgets["weather"].config_changed(k, v)
        self.widgets["weather"].reload()

    def search_place(self):
        q, ok = QInputDialog.getText(None, "Погода", "Адрес или место (например, «Уфа, остановка Спортивная»):")
        if not ok or not q.strip():
            return None
        try:
            url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
                {"q": q.strip(), "format": "json", "limit": 8, "accept-language": "ru"})
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
                                        timeout=15) as r:
                found = json.loads(r.read())
        except Exception as e:
            QMessageBox.warning(None, "Погода", f"Не удалось найти место: {e}")
            return None
        if not found:
            QMessageBox.information(None, "Погода", "Ничего не нашлось.")
            return None
        names = [f["display_name"] for f in found]
        pick, ok = QInputDialog.getItem(None, "Погода", "Какое место?", names, 0, False)
        if not ok:
            return None
        f = found[names.index(pick)]
        return float(f["lat"]), float(f["lon"])

    def configure_agenda(self, c):
        cal = self.calendar()
        if cal is not None and cal.access != "granted":
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars"])
            return
        days, ok = QInputDialog.getInt(None, "Календарь", "На сколько дней вперёд показывать события:",
                                       int(c.value("days")), 1, 31)
        if not ok:
            return
        labels = [f"{name}" for _, name in REGIONS]
        cur = next((i for i, (code, _) in enumerate(REGIONS) if code == c.value("region")), 0)
        pick, ok = QInputDialog.getItem(None, "Календарь", "Региональные выходные:", labels, cur, False)
        if not ok:
            return
        for k, v in (("days", days), ("region", REGIONS[labels.index(pick)][0])):
            c.insert(k, v)
            self.widgets["agenda"].config_changed(k, v)
        self.widgets["agenda"].reload()

    def configure_markets(self, c):
        on = QMessageBox.question(None, "Котировки", "Присылать уведомление при резком движении курса?")
        sens, ok = QInputDialog.getDouble(
            None, "Котировки", "Чувствительность сигналов (1 — обычная, 0,5 — вдвое чувствительнее):",
            float(c.value("alertSensitivity")), 0.2, 5.0, 1)
        if not ok:
            return
        for k, v in (("notify", on == QMessageBox.StandardButton.Yes), ("alertSensitivity", sens)):
            c.insert(k, v)
            self.widgets["markets"].config_changed(k, v)
        self.widgets["markets"].reload()


def bring_to_front():
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except ImportError:
        pass


LAUNCH_AGENT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.glasswidgets</string>
  <key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-a</string><string>{app}</string></array>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
"""


def set_autostart(on):
    if on:
        AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART.write_text(LAUNCH_AGENT.format(app=APP_BUNDLE))
    elif AUTOSTART.exists():
        AUTOSTART.unlink()


def main():
    import fcntl
    if not sys.stderr.isatty():    # started from Finder/launchd: keep QML errors somewhere
        log = Path.home() / "Library/Logs/GlassWidgets.log"
        sys.stderr = open(log, "a", buffering=1)
        os.dup2(sys.stderr.fileno(), 2)
    CACHE.mkdir(parents=True, exist_ok=True)
    lock = open(CACHE / "instance.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0       # already running
    QQuickWindow.setDefaultAlphaBuffer(True)
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setApplicationName("Glass Widgets")
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(1)   # accessory: no Dock icon
    except ImportError:
        pass
    app = App(qapp)  # noqa: F841 (keeps the windows alive)
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
