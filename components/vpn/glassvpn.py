#!/usr/bin/env python3
"""Glass VPN — a small tray client for VLESS subscriptions.

Blocked resources go through the VPN; the local network and Russian sites
(.ru/.рф/.su, geosite-category-ru, geoip-ru) go direct.

Two child processes:
- Xray-core speaks VLESS to the server (it supports everything current
  providers use: VLESS Encryption mlkem768x25519, Reality, gRPC, XHTTP) and
  exposes a SOCKS5 proxy on 127.0.0.1 only;
- sing-box owns the system-wide TUN and the routing, sending "proxy" traffic
  to that SOCKS port. Its binary gets cap_net_admin (see install.sh), so
  nothing here runs as root.
"""
import base64
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QIcon
from PyQt6.QtWidgets import (QApplication, QInputDialog, QMenu, QMessageBox,
                             QSystemTrayIcon)

APP = "glassvpn"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / APP
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP
SETTINGS = CONFIG_DIR / "settings.json"
SERVERS = CONFIG_DIR / "servers.json"
SB_CONFIG = STATE_DIR / "sing-box.json"
SB_LOG = STATE_DIR / "sing-box.log"
SING_BOX = os.environ.get("GLASSVPN_SING_BOX", "/usr/local/bin/sing-box")
XRAY = os.environ.get("GLASSVPN_XRAY", "/usr/local/bin/xray")
XRAY_CONFIG = STATE_DIR / "xray.json"
XRAY_LOG = STATE_DIR / "xray.log"
SOCKS_PORT = 10808
AUTOSTART = Path.home() / ".config/autostart/glassvpn.desktop"

RULESET_URL = {
    "geosite-ru": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-category-ru.srs",
    "geoip-ru": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-ru.srs",
}
RU_SUFFIXES = ["ru", "su", "xn--p1ai", "xn--p1acf", "xn--d1acj3b"]  # .рф .рус .дети
PRIVATE_NETS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
                "100.64.0.0/10", "fc00::/7", "fe80::/10"]


# ---------------------------------------------------------------- storage --

def load(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.chmod(tmp, 0o600)  # keys and subscription URLs are secrets
    tmp.replace(path)


# ------------------------------------------------------------ parsing -----

def parse_vless(uri):
    """vless://uuid@host:port?params#name -> dict, or None."""
    u = urllib.parse.urlsplit(uri.strip())
    if u.scheme != "vless" or not u.hostname or not u.username:
        return None
    q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    return {
        "name": urllib.parse.unquote(u.fragment) or f"{u.hostname}:{u.port}",
        "uuid": urllib.parse.unquote(u.username),
        "host": u.hostname,
        "port": u.port or 443,
        "type": q.get("type", "tcp"),
        "security": q.get("security", "none"),
        "sni": q.get("sni") or q.get("host") or "",
        "fp": q.get("fp", ""),
        "pbk": q.get("pbk", ""),
        "sid": q.get("sid", ""),
        "flow": q.get("flow", ""),
        "path": q.get("path", ""),
        "host_header": q.get("host", ""),
        "service_name": q.get("serviceName", ""),
        "alpn": q.get("alpn", ""),
        "encryption": q.get("encryption", "none"),
        "mode": q.get("mode", ""),
        "spx": q.get("spx", ""),
    }


def decode_subscription(body):
    text = body.decode("utf-8", "replace").strip()
    if "://" not in text:
        try:  # most subscriptions are base64 of a newline-separated list
            pad = "=" * (-len(text) % 4)
            text = base64.b64decode(text + pad, altchars=b"-_" if "-" in text or "_" in text else None).decode("utf-8", "replace")
        except ValueError:
            pass
    servers = [s for s in (parse_vless(l) for l in text.splitlines()) if s]
    return servers


def fetch_subscription(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sing-box glassvpn/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return decode_subscription(r.read())


# ------------------------------------------------------- sing-box config --

def xray_config(s, server_ip):
    """Xray client: SOCKS5 on localhost -> VLESS to the server."""
    user = {"id": s["uuid"], "encryption": s.get("encryption") or "none"}
    if s["flow"]:
        user["flow"] = s["flow"]
    net = {"tcp": "tcp", "raw": "tcp", "grpc": "grpc", "ws": "ws", "httpupgrade": "httpupgrade",
           "xhttp": "xhttp", "splithttp": "xhttp", "http": "xhttp", "h2": "xhttp"}.get(s["type"], "tcp")
    stream = {"network": net, "security": s["security"] if s["security"] in ("tls", "reality") else "none"}
    if stream["security"] == "tls":
        stream["tlsSettings"] = {"serverName": s["sni"] or s["host"], "fingerprint": s["fp"] or "chrome",
                                 **({"alpn": s["alpn"].split(",")} if s["alpn"] else {})}
    elif stream["security"] == "reality":
        stream["realitySettings"] = {"serverName": s["sni"], "fingerprint": s["fp"] or "chrome",
                                     "publicKey": s["pbk"], "shortId": s["sid"], "spiderX": s.get("spx", "")}
    if net == "grpc":
        stream["grpcSettings"] = {"serviceName": s["service_name"]}
    elif net == "ws":
        stream["wsSettings"] = {"path": s["path"] or "/", **({"headers": {"Host": s["host_header"]}} if s["host_header"] else {})}
    elif net == "httpupgrade":
        stream["httpupgradeSettings"] = {"path": s["path"] or "/", "host": s["host_header"]}
    elif net == "xhttp":
        stream["xhttpSettings"] = {"path": s["path"] or "/", "host": s["host_header"], "mode": s.get("mode") or "auto"}
    return {
        "log": {"loglevel": "warning", "error": str(XRAY_LOG), "access": "none"},
        "inbounds": [{"listen": "127.0.0.1", "port": SOCKS_PORT, "protocol": "socks",
                      "settings": {"udp": True, "auth": "noauth"}}],
        "outbounds": [{"protocol": "vless", "tag": "proxy",
                       "settings": {"vnext": [{"address": server_ip or s["host"], "port": int(s["port"]),
                                               "users": [user]}]},
                       "streamSettings": stream}],
    }


def build_config(server, direct_hosts):
    ru = {"rule_set": ["geosite-ru"]}
    return {
        "log": {"level": "warn", "output": str(SB_LOG), "timestamp": True},
        "dns": {
            "servers": [
                {"type": "https", "tag": "remote", "server": "1.1.1.1", "detour": "proxy"},
                {"type": "local", "tag": "local"},
            ],
            "rules": [
                {"domain_suffix": RU_SUFFIXES, "server": "local"},
                {**ru, "server": "local"},
            ],
            "final": "remote",
            "strategy": "ipv4_only",  # most home networks here have no IPv6
        },
        "inbounds": [{
            "type": "tun", "tag": "tun-in", "interface_name": "glassvpn0",
            # IPv4 only: with an IPv6 address the tunnel would swallow AAAA traffic
            # that has nowhere to go on networks without IPv6
            "address": ["198.18.0.1/30"],
            "mtu": 9000, "auto_route": True, "strict_route": True, "stack": "mixed",
            # Xray reaches the VPN server over the physical link, not through the tunnel
            # LAN, Docker bridges, the PPTP home gateway and the VPN server stay outside
            "route_exclude_address": PRIVATE_NETS + [f"{h}/32" for h in direct_hosts],
        }],
        "outbounds": [
            {"type": "socks", "tag": "proxy", "server": "127.0.0.1", "server_port": SOCKS_PORT, "version": "5"},
            {"type": "direct", "tag": "direct"},
        ],
        "route": {
            "rules": [
                {"action": "sniff"},
                {"protocol": "dns", "action": "hijack-dns"},
                {"ip_is_private": True, "outbound": "direct"},
                {"domain_suffix": RU_SUFFIXES, "outbound": "direct"},
                {"rule_set": ["geosite-ru", "geoip-ru"], "outbound": "direct"},
            ],
            "rule_set": [
                {"type": "remote", "tag": tag, "format": "binary", "url": url,
                 "download_detour": "direct", "update_interval": "7d"}
                for tag, url in RULESET_URL.items()
            ],
            "final": "proxy",
            "auto_detect_interface": True,
            "default_domain_resolver": "local",
        },
        "experimental": {"cache_file": {"enabled": True, "path": str(CACHE_DIR / "cache.db")}},
    }


def pptp_gateways():
    """Gateways of NetworkManager PPTP/VPN connections, so they bypass the tunnel."""
    out = []
    try:
        names = subprocess.run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
                               capture_output=True, text=True, timeout=5).stdout
        for line in names.splitlines():
            name, _, typ = line.rpartition(":")
            if typ != "vpn":
                continue
            data = subprocess.run(["nmcli", "-g", "vpn.data", "connection", "show", name],
                                  capture_output=True, text=True, timeout=5).stdout
            for kv in data.split(","):
                k, _, v = kv.partition("=")
                if k.strip() in ("gateway", "remote"):
                    out += resolve(v.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def resolve(host):
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(host, None, socket.AF_INET)})
    except OSError:
        return []


def tcp_latency(host, port, timeout=3.0):
    t = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return int((time.monotonic() - t) * 1000)
    except OSError:
        return None


# ------------------------------------------------------------------ tray --

class Signals(QObject):
    servers_changed = pyqtSignal()
    message = pyqtSignal(str, str)
    latency = pyqtSignal(dict)


class Tray:
    def __init__(self, app):
        self.app = app
        self.sig = Signals()
        self.sig.servers_changed.connect(self.rebuild_menu)
        self.sig.message.connect(self.notify)
        self.sig.latency.connect(self.show_latency)
        self.settings = load(SETTINGS, {"subscriptions": [], "selected": None, "autoconnect": True})
        self.servers = load(SERVERS, [])
        self.proc = None
        self.xray = None
        self.want_up = False
        self.latencies = {}
        self.tray = QSystemTrayIcon(self.icon(False))
        self.tray.setToolTip("Glass VPN")
        self.tray.activated.connect(self.on_click)
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self.rebuild_menu()
        self.tray.show()
        self.watchdog = QTimer(interval=3000, timeout=self.check_process)
        self.watchdog.start()
        if self.settings.get("autoconnect") and self.current():
            QTimer.singleShot(1500, self.connect)
        QTimer.singleShot(4000, lambda: self.update_subscriptions(quiet=True))

    # icons: monochrome symbolic icons so the adaptive top bar recolors them
    def icon(self, up):
        name = "network-vpn-symbolic" if up else "network-vpn-disconnected-symbolic"
        return QIcon.fromTheme(name, QIcon.fromTheme("network-vpn"))

    def current(self):
        sel = self.settings.get("selected")
        for s in self.servers:
            if s["name"] == sel:
                return s
        return self.servers[0] if self.servers else None

    # ---- menu
    def rebuild_menu(self):
        m = self.menu
        m.clear()
        up = self.is_up()
        cur = self.current()
        status = QAction(("● Подключено: " if up else "○ Отключено") + (cur["name"] if up and cur else ""), m)
        status.setEnabled(False)
        m.addAction(status)
        m.addSeparator()
        toggle = m.addAction("Отключить" if self.want_up else "Подключить")
        toggle.setEnabled(bool(cur))
        toggle.triggered.connect(self.disconnect if self.want_up else self.connect)

        sm = m.addMenu("Сервер")
        group = QActionGroup(sm)
        for s in self.servers:
            ms = self.latencies.get(s["name"])
            label = s["name"] + (f"   {ms} мс" if ms else ("   —" if s["name"] in self.latencies else ""))
            a = sm.addAction(label)
            a.setCheckable(True)
            a.setChecked(cur is not None and s["name"] == cur["name"])
            a.triggered.connect(lambda _=False, n=s["name"]: self.select(n))
            group.addAction(a)
        if not self.servers:
            sm.addAction("Нет серверов — добавьте подписку").setEnabled(False)
        sm.addSeparator()
        sm.addAction("Проверить задержку").triggered.connect(self.test_latency)

        m.addSeparator()
        m.addAction("Добавить подписку или ключ…").triggered.connect(self.add_subscription)
        m.addAction("Обновить подписки").triggered.connect(lambda: self.update_subscriptions(quiet=False))
        ac = m.addAction("Подключаться при входе")
        ac.setCheckable(True)
        ac.setChecked(AUTOSTART.exists() and self.settings.get("autoconnect", True))
        ac.toggled.connect(self.set_autostart)
        m.addAction("Журнал").triggered.connect(lambda: subprocess.Popen(["xdg-open", str(XRAY_LOG)]))
        m.addSeparator()
        m.addAction("Выход").triggered.connect(self.quit)
        self.tray.setIcon(self.icon(up))
        self.tray.setToolTip("Glass VPN — " + (f"подключено ({cur['name']})" if up and cur else "отключено"))

    def on_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            (self.disconnect if self.want_up else self.connect)()

    def notify(self, title, text):
        self.tray.showMessage(title, text, self.icon(self.is_up()), 4000)

    # ---- subscriptions
    def add_subscription(self):
        text, ok = QInputDialog.getMultiLineText(
            None, "Glass VPN", "Ссылка на подписку (https://…) или ключи vless:// — по одному в строке:")
        if not ok or not text.strip():
            return
        subs = self.settings.setdefault("subscriptions", [])
        manual = [s for s in (parse_vless(l) for l in text.splitlines()) if s]
        urls = [l.strip() for l in text.splitlines() if l.strip().startswith(("http://", "https://"))]
        for u in urls:
            if u not in subs:
                subs.append(u)
        if manual:
            for s in manual:
                s["manual"] = True
            self.servers = [s for s in self.servers if s["name"] not in {m["name"] for m in manual}] + manual
            save(SERVERS, self.servers)
        save(SETTINGS, self.settings)
        if urls:
            self.update_subscriptions(quiet=False)
        else:
            self.sig.servers_changed.emit()

    def update_subscriptions(self, quiet):
        subs = list(self.settings.get("subscriptions", []))
        if not subs:
            if not quiet:
                self.notify("Glass VPN", "Подписок нет — добавьте ссылку.")
            return

        def work():
            fresh, errors = [], []
            for url in subs:
                try:
                    fresh += fetch_subscription(url)
                except Exception as e:  # network, HTTP, decoding
                    errors.append(str(e))
            if fresh:
                manual = [s for s in self.servers if s.get("manual")]
                names = {s["name"] for s in fresh}
                self.servers = fresh + [s for s in manual if s["name"] not in names]
                save(SERVERS, self.servers)
                self.sig.servers_changed.emit()
                if not quiet:
                    self.sig.message.emit("Glass VPN", f"Серверов: {len(fresh)}")
            elif not quiet:
                self.sig.message.emit("Glass VPN", "Не удалось обновить подписки: " + "; ".join(errors)[:200])
        threading.Thread(target=work, daemon=True).start()

    def test_latency(self):
        servers = list(self.servers)

        def work():
            res = {s["name"]: tcp_latency(s["host"], s["port"]) for s in servers}
            self.sig.latency.emit(res)
        threading.Thread(target=work, daemon=True).start()

    def show_latency(self, res):
        self.latencies = res
        self.rebuild_menu()

    def select(self, name):
        self.settings["selected"] = name
        save(SETTINGS, self.settings)
        if self.want_up:
            self.stop_process()
            self.connect()
        else:
            self.rebuild_menu()

    # ---- sing-box process
    def is_up(self):
        return (self.proc is not None and self.proc.poll() is None
                and self.xray is not None and self.xray.poll() is None)

    def connect(self):
        s = self.current()
        if not s:
            self.notify("Glass VPN", "Нет серверов — добавьте подписку.")
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        server_ips = resolve(s["host"])
        direct = pptp_gateways() + server_ips
        save(XRAY_CONFIG, xray_config(s, server_ips[0] if server_ips else None))
        save(SB_CONFIG, build_config(s, direct))
        for cmd in ([XRAY, "run", "-test", "-c", str(XRAY_CONFIG)], [SING_BOX, "check", "-c", str(SB_CONFIG)]):
            check = subprocess.run(cmd, capture_output=True, text=True)
            if check.returncode != 0:
                self.notify("Glass VPN", "Ошибка конфигурации: " + (check.stderr or check.stdout)[-200:])
                return
        self.stop_process()
        self.xray = subprocess.Popen([XRAY, "run", "-c", str(XRAY_CONFIG)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.proc = subprocess.Popen([SING_BOX, "run", "-c", str(SB_CONFIG)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.want_up = True
        self.settings["selected"] = s["name"]
        save(SETTINGS, self.settings)
        QTimer.singleShot(1500, self.rebuild_menu)

    def disconnect(self):
        self.want_up = False
        self.stop_process()
        self.rebuild_menu()

    def stop_process(self):
        for p in (self.proc, self.xray):
            if p and p.poll() is None:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
        self.proc = self.xray = None

    def check_process(self):
        # restart sing-box if it died while the user wants the VPN up
        if self.want_up and not self.is_up():
            self.notify("Glass VPN", "Соединение прервалось, переподключаюсь…")
            self.connect()

    def set_autostart(self, on):
        self.settings["autoconnect"] = on
        save(SETTINGS, self.settings)
        if on:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text("[Desktop Entry]\nType=Application\nName=Glass VPN\n"
                                 "Exec=glassvpn\nIcon=network-vpn\nX-GNOME-Autostart-enabled=true\n")
        elif AUTOSTART.exists():
            AUTOSTART.unlink()

    def quit(self):
        self.stop_process()
        self.app.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Glass VPN")
    app.setDesktopFileName("glassvpn")
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "Glass VPN", "Системный трей недоступен.")
        return 1
    Tray(app)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
