#!/usr/bin/env python3
"""Glass VPN — a small tray client for VLESS subscriptions.

Blocked resources go through the VPN; the local network and Russian sites
(.ru/.рф/.su, geosite-category-ru, geoip-ru) go direct.

Two child processes:
- Xray-core speaks VLESS to the server (it supports everything current
  providers use: VLESS Encryption mlkem768x25519, Reality, gRPC, XHTTP) and
  exposes a SOCKS5 proxy on 127.0.0.1 only;
- sing-box owns the system-wide TUN and the routing, sending "proxy" traffic
  to that SOCKS port. On Linux its binary gets cap_net_admin (see install.sh),
  so nothing here runs as root. macOS has no capabilities: sing-box is started
  by a small root helper (macos/glassvpn-helper, allowed via sudoers) that also
  points the system DNS at the tunnel while it is up.

Routing, first match wins: LAN direct; the "only through the VPN" list (apps or
domains; Claude and Anthropic by default) through a dedicated Xray port that
always goes to the server — never direct, not even while the server is down and
everything else falls back to direct, and blocked while the VPN is off (sing-box
then keeps running as a guard); the "always direct" list; the Russian zone
direct; the rest through the server. Recovering from sleep or a dead server only
restarts Xray: the TUN stays, so nothing on the VPN-only list slips out meanwhile.
"""
import base64
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QActionGroup, QColor, QIcon, QPainter, QPainterPath,
                         QPen, QPixmap)
from PyQt6.QtWidgets import (QApplication, QInputDialog, QMenu, QMessageBox,
                             QSystemTrayIcon)

APP = "glassvpn"
IS_MAC = sys.platform == "darwin"
if IS_MAC:
    CONFIG_DIR = Path.home() / "Library/Application Support/GlassVPN"
    STATE_DIR = Path.home() / "Library/Logs/GlassVPN"
    CACHE_DIR = Path.home() / "Library/Caches/GlassVPN"
    MAC_BIN = Path("/opt/glassvpn")                   # root-owned: the helper runs sing-box as root
    HELPER = str(MAC_BIN / "glassvpn-helper")
    SING_BOX = str(MAC_BIN / "sing-box")
    XRAY = str(MAC_BIN / "xray")
    SB_LOG = Path("/var/log/glassvpn/sing-box.log")  # written by the helper
    AUTOSTART = Path.home() / "Library/LaunchAgents/local.glassvpn.plist"
    TUN = "utun225"                                  # macOS only accepts utunN names
else:
    CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP
    STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / APP
    CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP
    SING_BOX = os.environ.get("GLASSVPN_SING_BOX", "/usr/local/bin/sing-box")
    XRAY = os.environ.get("GLASSVPN_XRAY", "/usr/local/bin/xray")
    SB_LOG = STATE_DIR / "sing-box.log"
    AUTOSTART = Path.home() / ".config/autostart/glassvpn.desktop"
    TUN = "glassvpn0"
SETTINGS = CONFIG_DIR / "settings.json"
SERVERS = CONFIG_DIR / "servers.json"
SB_CONFIG = STATE_DIR / "sing-box.json"
XRAY_CONFIG = STATE_DIR / "xray.json"
XRAY_LOG = STATE_DIR / "xray.log"
SOCKS_PORT = 10808
PROBE_SOCKS_PORT = 10809        # a second Xray inbound that always goes to the server
VPN_ONLY_PORT = 10810           # and a third, for the "only through the VPN" list: never direct
APPLETSRC = Path.home() / ".config/plasma-org.kde.plasma.desktop-appletsrc"
PROBE_HOST = "connectivitycheck.gstatic.com"      # GET /generate_204 through the server

# tray states
OFF, CONNECTING, ON, BYPASS, ERROR = "off", "connecting", "on", "bypass", "error"
STATE_COLOR = {CONNECTING: "#f5b83d", ON: "#34c759", BYPASS: "#ff9f0a", ERROR: "#ff453a"}
STATE_TEXT = {OFF: "отключено", CONNECTING: "подключение…", ON: "подключено",
              BYPASS: "напрямую — сервер недоступен", ERROR: "сервер не отвечает"}

RULESET_URL = {
    "geosite-ru": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-category-ru.srs",
    "geoip-ru": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-ru.srs",
}
RU_SUFFIXES = ["ru", "su", "xn--p1ai", "xn--p1acf", "xn--d1acj3b"]  # .рф .рус .дети
# "Only through the VPN" by default: Anthropic refuses requests from Russian IPs,
# so Claude must never fall back to the direct route
CLAUDE_DESKTOP = "Claude.app" if sys.platform == "darwin" else "/usr/lib/claude-desktop/"
DEFAULT_VPN_ONLY = ["claude", CLAUDE_DESKTOP, "anthropic.com", "claude.ai", "claude.com"]
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


def sub_label(url):
    """host plus a short tail of the path; the rest of the URL (the token) stays hidden."""
    u = urllib.parse.urlsplit(url)
    tail = u.path.rstrip("/").rsplit("/", 1)[-1]
    return u.hostname + (f"/…{tail[-4:]}" if tail else "")


def fetch_subscription(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sing-box glassvpn/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return decode_subscription(r.read())


# ------------------------------------------------------- sing-box config --

def xray_config(s, server_ip, bypass=False):
    """Xray client: SOCKS5 on localhost -> VLESS to the server.

    A second SOCKS port always goes to the server (the live check), and so does a third
    (the "only through the VPN" list, which must never leave directly). With bypass,
    the main port sends everything direct: the server is unreachable (e.g. mobile
    internet on a whitelist) and traffic shouldn't hang on a dead tunnel meanwhile.
    """
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
        "inbounds": [{"tag": "socks", "listen": "127.0.0.1", "port": SOCKS_PORT, "protocol": "socks",
                      "settings": {"udp": True, "auth": "noauth"}},
                     {"tag": "probe", "listen": "127.0.0.1", "port": PROBE_SOCKS_PORT, "protocol": "socks",
                      "settings": {"auth": "noauth"}},
                     {"tag": "vpnonly", "listen": "127.0.0.1", "port": VPN_ONLY_PORT, "protocol": "socks",
                      "settings": {"udp": True, "auth": "noauth"}}],
        "outbounds": [{"protocol": "vless", "tag": "proxy",
                       "settings": {"vnext": [{"address": server_ip or s["host"], "port": int(s["port"]),
                                               "users": [user]}]},
                       "streamSettings": stream},
                      # leaves through the TUN, where sing-box sends Xray's traffic out directly
                      {"protocol": "freedom", "tag": "direct"}],
        "routing": {"rules": [
            {"type": "field", "inboundTag": ["probe", "vpnonly"], "outboundTag": "proxy"},
            *([{"type": "field", "inboundTag": ["socks"], "outboundTag": "direct"}] if bypass else []),
        ]},
    }


def match_rules(entries):
    """List entries -> sing-box rule matchers: a process name ("claude"), an app
    bundle ("Telegram.app"), a path prefix ("/usr/bin/curl") or a domain ("claude.ai")."""
    names, paths, domains = [], [], []
    for e in (x.strip() for x in entries):
        if not e:
            continue
        if e.endswith(".app"):
            paths.append("/" + re.escape(e) + "/")
        elif "/" in e:
            paths.append("^" + re.escape(e))
        elif "." in e:
            domains.append(e.lstrip("."))
        else:
            names.append(e)
    return ([{"process_name": names}] if names else []) + \
           ([{"process_path_regex": paths}] if paths else []) + \
           ([{"domain_suffix": domains}] if domains else [])


def build_config(server, direct_hosts, local_dns=None, vpn_only=(), direct_apps=(), guard=False):
    """guard: the VPN is off — everything direct, except the "only through the VPN"
    list, which is blocked rather than let out with the local address."""
    ru = {"rule_set": ["geosite-ru"]}
    # on macOS the system resolver points at the tunnel while it is up, so "local"
    # must be the network's own DNS server, asked directly
    local = {"type": "udp", "tag": "local", "server": local_dns} if local_dns else {"type": "local", "tag": "local"}
    # Xray's own connections — to the server, and its direct traffic while bypassing —
    # never loop back into the tunnel
    direct_rules = [{"process_name": ["xray"], "outbound": "direct"}]
    return {
        "log": {"level": "warn", "output": str(SB_LOG), "timestamp": True},
        "dns": {
            "servers": [
                {"type": "https", "tag": "remote", "server": "1.1.1.1", "detour": "proxy"},
                local,
            ],
            "rules": [
                {"domain_suffix": RU_SUFFIXES, "server": "local"},
                {**ru, "server": "local"},
            ],
            "final": "local" if guard else "remote",
            "strategy": "ipv4_only",  # most home networks here have no IPv6
        },
        "inbounds": [{
            "type": "tun", "tag": "tun-in", "interface_name": TUN,
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
            {"type": "socks", "tag": "vpn-only", "server": "127.0.0.1", "server_port": VPN_ONLY_PORT, "version": "5"},
            {"type": "direct", "tag": "direct"},
        ],
        "route": {
            "rules": [
                {"action": "sniff"},
                {"protocol": "dns", "action": "hijack-dns"},
                *direct_rules,
                {"ip_is_private": True, "outbound": "direct"},
                # before the Russian zone: these go through the server even to .ru sites
                *({**m, "action": "reject"} if guard else {**m, "outbound": "vpn-only"} for m in match_rules(vpn_only)),
                *({**m, "outbound": "direct"} for m in match_rules(direct_apps)),
                {"domain_suffix": RU_SUFFIXES, "outbound": "direct"},
                {"rule_set": ["geosite-ru", "geoip-ru"], "outbound": "direct"},
            ],
            "rule_set": [
                {"type": "remote", "tag": tag, "format": "binary", "url": url,
                 "download_detour": "direct", "update_interval": "7d"}
                for tag, url in RULESET_URL.items()
            ],
            "final": "direct" if guard else "proxy",
            "auto_detect_interface": True,
            "default_domain_resolver": "local",
        },
        "experimental": {"cache_file": {"enabled": True, "path": str(CACHE_DIR / "cache.db")}},
    }


def pptp_gateways():
    """Gateways of NetworkManager PPTP/VPN connections, so they bypass the tunnel."""
    out = []
    if IS_MAC:
        return out
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


def recv_exact(c, n):
    b = b""
    while len(b) < n:
        chunk = c.recv(n - len(b))
        if not chunk:
            raise OSError("closed")
        b += chunk
    return b


def server_probe(timeout=4.0):
    """Fetch http://PROBE_HOST/generate_204 through Xray's probe port (always the
    server); returns milliseconds or None. A real request: Xray answers the SOCKS
    CONNECT before it has reached the server."""
    t = time.monotonic()
    try:
        with socket.create_connection(("127.0.0.1", PROBE_SOCKS_PORT), timeout=timeout) as c:
            c.settimeout(timeout)
            c.sendall(b"\x05\x01\x00")
            if recv_exact(c, 2) != b"\x05\x00":
                return None
            h = PROBE_HOST.encode()
            c.sendall(b"\x05\x01\x00\x03" + bytes([len(h)]) + h + (80).to_bytes(2, "big"))
            head = recv_exact(c, 4)
            if head[1] != 0:
                return None
            recv_exact(c, {1: 4, 4: 16}.get(head[3], 0) + 2 if head[3] != 3 else recv_exact(c, 1)[0] + 2)
            c.sendall(f"GET /generate_204 HTTP/1.1\r\nHost: {PROBE_HOST}\r\nConnection: close\r\n\r\n".encode())
            if not recv_exact(c, 12).startswith(b"HTTP/"):
                return None
            return int((time.monotonic() - t) * 1000)
    except OSError:
        return None


def network_signature():
    """Default gateway and interface of the physical network: when it changes
    (Wi-Fi <-> Ethernet, another network, tethering) Xray's links hang on the old one."""
    try:
        if IS_MAC:
            out = subprocess.run(["route", "-n", "get", "default"], capture_output=True, text=True, timeout=3).stdout
            return " ".join(l.split(":", 1)[1].strip() for l in out.splitlines()
                            if l.strip().startswith(("gateway:", "interface:")))
        out = subprocess.run(["ip", "-4", "route", "show", "default", "table", "main"],
                             capture_output=True, text=True, timeout=3).stdout
        return out.split("\n")[0].strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def mac_system_dns():
    """DNS servers the network (DHCP) hands out, read per physical interface so the
    tunnel's own override never shows up here."""
    ifaces = []
    try:
        out = subprocess.run(["scutil"], input="show State:/Network/Global/IPv4\n",
                             capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            if "PrimaryInterface" in line:
                ifaces.append(line.split(":", 1)[1].strip())
    except (OSError, subprocess.SubprocessError):
        pass
    for iface in ifaces + ["en0", "en1", "en2", "en3", "en4", "en5"]:
        if iface.startswith("utun"):
            continue
        try:
            dns = subprocess.run(["ipconfig", "getoption", iface, "domain_name_server"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if dns:
            return dns
    return "77.88.8.8"   # Yandex DNS: works from any Russian network


def tun_bytes():
    if IS_MAC:
        try:
            out = subprocess.run(["netstat", "-I", TUN, "-b", "-n"], capture_output=True,
                                 text=True, timeout=3).stdout.splitlines()
            cols = out[1].split()   # Name Mtu Network Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll
            return int(cols[5]), int(cols[8])
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            return None
    base = Path("/sys/class/net") / TUN / "statistics"
    try:
        return int((base / "rx_bytes").read_text()), int((base / "tx_bytes").read_text())
    except (OSError, ValueError):
        return None


def human_rate(bps):
    for unit in ("Б/с", "КБ/с", "МБ/с"):
        if bps < 1024 or unit == "МБ/с":
            return f"{bps:.0f} {unit}" if unit == "Б/с" else f"{bps:.1f} {unit}"
        bps /= 1024


def panel_text_color():
    """Colour the adaptive top bar currently uses for text, so the shield matches it."""
    if IS_MAC:
        try:
            dark = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True,
                                  text=True, timeout=3).stdout.strip() == "Dark"
        except (OSError, subprocess.SubprocessError):
            dark = True
        return QColor("#ffffff" if dark else "#000000")
    try:
        import configparser
        cp = configparser.RawConfigParser(strict=False, interpolation=None)
        cp.optionxform = str
        cp.read(APPLETSRC, encoding="utf-8")
        for sec in cp.sections():
            if cp.get(sec, "plugin", fallback="") == "luisbocanegra.panel.colorizer":
                g = json.loads(cp.get(f"{sec}][Configuration][General", "globalSettings"))
                fg = g["widgets"]["normal"]["foregroundColor"]
                if fg.get("enabled") and fg.get("custom"):
                    return QColor(fg["custom"])
    except Exception:
        pass
    return QColor("#ffffff")


def draw_icon(state, fg, phase=0.0):
    """Shield in the panel's text colour; a coloured status dot in the corner."""
    size = 64
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    shield = QPainterPath()
    shield.moveTo(30, 5)
    shield.cubicTo(38, 10, 46, 12, 54, 12)
    shield.lineTo(54, 30)
    shield.cubicTo(54, 45, 44, 54, 30, 60)
    shield.cubicTo(16, 54, 6, 45, 6, 30)
    shield.lineTo(6, 12)
    shield.cubicTo(14, 12, 22, 10, 30, 5)
    shield.closeSubpath()
    if state == ON:
        p.fillPath(shield, fg)
        # check mark knocked out of the filled shield
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        pen = QPen(Qt.GlobalColor.black, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        tick = QPainterPath(QPointF(19, 32))
        tick.lineTo(27, 40)
        tick.lineTo(42, 24)
        p.drawPath(tick)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    else:
        c = QColor(fg)
        if state == OFF:
            c.setAlphaF(0.55)
        p.setPen(QPen(c, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(shield)
        if state == ERROR:
            p.drawLine(QPointF(30, 20), QPointF(30, 35))
            p.drawPoint(QPointF(30, 44))
    if state in STATE_COLOR:
        dot = QColor(STATE_COLOR[state])
        if state == CONNECTING:
            dot.setAlphaF(0.45 + 0.55 * abs(phase))
        r = 14
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.setBrush(Qt.GlobalColor.black)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(size - r - 1, size - r - 1), r + 3, r + 3)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setBrush(dot)
        p.drawEllipse(QPointF(size - r - 1, size - r - 1), r, r)
    p.end()
    return QIcon(pm)


class HelperProc:
    """sing-box started as root by the macOS helper, with the Popen methods the tray uses."""
    PIDFILE = Path("/var/run/glassvpn.pid")

    def __init__(self, config):
        r = subprocess.run(["sudo", "-n", HELPER, "start", str(config)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip()[-200:] or "helper failed")
        self.pid = int(self.PIDFILE.read_text())

    def poll(self):
        try:
            os.kill(self.pid, 0)
        except PermissionError:   # alive, but owned by root
            return None
        except OSError:
            return 1
        return None

    def send_signal(self, _sig):
        helper_stop()

    def wait(self, timeout=None):
        return 0

    kill = send_signal


def helper_stop():
    """Stop sing-box and give the system DNS back; safe to call when nothing runs."""
    subprocess.run(["sudo", "-n", HELPER, "stop"], capture_output=True, timeout=30)


def mac_hide_dock_icon():
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        from Foundation import NSActivityUserInitiatedAllowingIdleSystemSleep, NSProcessInfo
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        # no App Nap: a background menu bar app gets its timers throttled, and the
        # watchdog would take a late tick for a sleep
        mac_hide_dock_icon.activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            NSActivityUserInitiatedAllowingIdleSystemSleep, "VPN watchdog")
    except ImportError:
        pass


# ------------------------------------------------------------------ tray --

# ------------------------------------------------------- app rules window --

KNOWN_NAMES = {"claude": "Claude Code"}   # command-line tools without an app bundle or icon
LINUX_APP_DIRS = ["/usr/share/applications", "/usr/local/share/applications",
                  str(Path.home() / ".local/share/applications")]
MAC_APP_DIRS = ["/Applications", "/Applications/Utilities", str(Path.home() / "Applications"),
                "/System/Applications", "/System/Applications/Utilities"]


def normalize_domain(text):
    """"https://www.claude.ai/chat" -> "claude.ai"; None if it isn't a domain."""
    t = text.strip().lower()
    if "://" not in t:
        t = "//" + t
    host = (urllib.parse.urlsplit(t).hostname or "").removeprefix("www.")
    if not re.fullmatch(r"[a-z0-9а-яё-]+(\.[a-z0-9а-яё-]+)+", host):
        return None
    try:
        return host.encode("idna").decode()   # кто-то.рф -> xn--...: what the TLS name looks like
    except UnicodeError:
        return None


def show_domain(d):
    try:
        return d.encode().decode("idna")
    except UnicodeError:
        return d


SHARED_BIN_DIRS = ("/usr/bin", "/bin", "/usr/local/bin", "/usr/sbin", "/sbin", "/usr/games",
                   str(Path.home() / ".local/bin"))
LAUNCHERS = {"pkexec", "xdg-open", "env", "sh", "bash", "python3", "sudo", "gksu"}


def has_elf(d):
    try:
        for f in os.scandir(d):
            if f.is_file() and os.access(f.path, os.X_OK):
                with open(f.path, "rb") as fh:
                    if fh.read(4) == b"\x7fELF":
                        return True
    except OSError:
        pass
    return False


def linux_entry_for_exec(exec_line):
    """Desktop-file Exec -> list entry. An app with its own directory (Chrome, Electron
    apps, LibreOffice) -> that directory, so its helper processes match too; a program
    in a shared bin directory -> its process name; launchers that hide the real
    program (pkexec, xdg-open, scripts in ~/.local/bin) -> None."""
    import shlex
    import shutil
    try:
        args = [a for a in shlex.split(exec_line) if not a.startswith("%")]
    except ValueError:
        return None
    while args and (args[0] == "env" or "=" in args[0]):
        args.pop(0)
    if not args or os.path.basename(args[0]) == "flatpak":
        return None     # sandboxed: its processes aren't visible by host path
    real = os.path.realpath(shutil.which(args[0]) or args[0])
    try:
        with open(real, "rb") as f:
            script = f.read(2) == b"#!"
    except OSError:
        return None
    d = os.path.dirname(real)
    if d not in SHARED_BIN_DIRS:
        return d + "/" if has_elf(d) else None
    name = os.path.basename(real)
    if name in LAUNCHERS or (script and d == SHARED_BIN_DIRS[-1]):
        return None
    return name


def mac_app_name(path):
    """The name Finder shows ("Калькулятор", not "Calculator")."""
    try:
        from Foundation import NSFileManager
        return str(NSFileManager.defaultManager().displayNameAtPath_(str(path))).removesuffix(".app")
    except ImportError:
        return Path(path).stem


def installed_apps():
    """[(entry, name, icon, icon_name)] of the apps a user would pick from, sorted by name."""
    from PyQt6.QtCore import QFileInfo
    from PyQt6.QtWidgets import QFileIconProvider
    apps = {}
    if IS_MAC:
        icons = QFileIconProvider()
        for d in MAC_APP_DIRS:
            for app in sorted(Path(d).glob("*.app")) + sorted(Path(d).glob("*/*.app")):
                if app.name != "Glass VPN.app" and app.name not in apps:
                    apps[app.name] = (mac_app_name(app), icons.icon(QFileInfo(str(app))), "")
    else:
        import configparser
        for d in LINUX_APP_DIRS:
            for f in sorted(Path(d).glob("*.desktop")):
                cp = configparser.RawConfigParser(strict=False, interpolation=None)
                try:
                    cp.read(f, encoding="utf-8")
                    e = cp["Desktop Entry"]
                except (configparser.Error, KeyError, UnicodeDecodeError):
                    continue
                if e.get("Type") != "Application" or e.get("NoDisplay") == "true" or not e.get("Exec"):
                    continue
                entry = linux_entry_for_exec(e["Exec"])
                if entry and entry not in apps and entry != "glassvpn":
                    name = e.get("Name[ru]") or e.get("Name") or entry
                    apps[entry] = (name, QIcon.fromTheme(e.get("Icon", "")), e.get("Icon", ""))
    return sorted(((k, *v) for k, v in apps.items()), key=lambda a: a[1].lower())


def entry_look(entry, labels, known=None):
    """How a list entry is shown: (name, detail, icon). known: entry -> (name, icon)
    of the installed apps, for entries added by hand or by default."""
    from PyQt6.QtCore import QFileInfo
    from PyQt6.QtWidgets import QFileIconProvider
    if entry.endswith(".app"):
        for d in MAC_APP_DIRS:
            for p in [Path(d) / entry, *Path(d).glob(f"*/{entry}")]:
                if p.exists():
                    return mac_app_name(p), "приложение", QFileIconProvider().icon(QFileInfo(str(p)))
        return entry[:-4], "приложение", QIcon.fromTheme("application-x-executable")
    if "/" not in entry and "." in entry:
        return show_domain(entry), "сайт и его поддомены", QIcon.fromTheme("applications-internet", draw_globe())
    detail = "программа в " + entry if entry.endswith("/") else "программа " + entry
    if known and entry in known and entry not in labels:
        return known[entry][0], detail, known[entry][1]
    label = labels.get(entry, {})
    name = label.get("name") or KNOWN_NAMES.get(entry) or os.path.basename(entry.rstrip("/")) or entry
    icon = QIcon.fromTheme(label.get("icon", "")) if label.get("icon") else QIcon.fromTheme("utilities-terminal")
    return name, detail, icon


def draw_globe():
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#4c9cff"), 4))
    p.drawEllipse(QRectF(6, 6, 52, 52))
    p.drawEllipse(QRectF(20, 6, 24, 52))
    p.drawLine(QPointF(6, 32), QPointF(58, 32))
    p.end()
    return QIcon(pm)


def bring_to_front():
    """A menu bar app has no Dock icon; without this its windows open behind others."""
    if IS_MAC:
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except ImportError:
            pass


class AppPicker:
    """Pick installed apps (search, icons, multi-select) or any program file."""

    def __init__(self, parent):
        from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QLabel, QLineEdit,
                                     QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)
        self.dlg = d = QDialog(parent)
        d.setWindowTitle("Выберите приложения")
        d.resize(420, 520)
        lay = QVBoxLayout(d)
        hint = QLabel("Можно выбрать несколько — с " + ("⌘" if IS_MAC else "Ctrl") + " или Shift.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.search = QLineEdit(placeholderText="Поиск")
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setIconSize(QPixmap(28, 28).size())
        for entry, name, icon, icon_name in installed_apps():
            it = QListWidgetItem(icon, name)
            it.setData(Qt.ItemDataRole.UserRole, (entry, {"name": name, "icon": icon_name}))
            self.list.addItem(it)
        self.list.itemDoubleClicked.connect(lambda _: d.accept())
        lay.addWidget(self.list)
        other = QPushButton("Другая программа…")
        other.clicked.connect(self.pick_file)
        lay.addWidget(other)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Добавить")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        self.search.textChanged.connect(self.filter)
        self.picked = []

    def filter(self, text):
        t = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def pick_file(self):
        from PyQt6.QtWidgets import QFileDialog
        start = "/Applications" if IS_MAC else "/usr/bin"
        path, _ = QFileDialog.getOpenFileName(self.dlg, "Программа", start)
        if path:
            self.picked = [(file_entry(path), None)]
            self.dlg.accept()

    def run(self):
        """[(entry, label_or_None)], label = {"name", "icon"}"""
        bring_to_front()
        if self.dlg.exec() != self.dlg.DialogCode.Accepted:
            return []
        if self.picked:
            return self.picked
        return [it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems()]


def file_entry(path):
    """A dropped or chosen file -> list entry (an .app bundle anywhere in its path wins)."""
    m = re.search(r"([^/]+\.app)(/|$)", path)
    return m.group(1) if m else path


class RulesDialog:
    """The two lists side by side in tabs, edited with buttons and drag and drop."""
    TABS = [("vpn_only", "Только через VPN",
             "Эти приложения и сайты всегда идут через VPN — даже к российским сайтам. "
             "Если сервер недоступен или VPN выключен, у них нет интернета, но с вашего "
             "настоящего адреса они не выходят."),
            ("direct_apps", "Всегда мимо VPN",
             "Эти приложения и сайты всегда идут напрямую, даже когда VPN включён.")]

    def __init__(self, settings, tab_key):
        from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListWidget,
                                     QPushButton, QTabWidget, QVBoxLayout, QWidget)
        self.settings = settings
        self.lists = {k: list(settings.get(k, [])) for k, _, _ in self.TABS}
        self.labels = dict(settings.get("app_labels", {}))
        self.known = {e: (n, i) for e, n, i, _ in installed_apps()}
        self.dlg = d = QDialog()
        d.setWindowTitle("Glass VPN — правила для приложений")
        d.resize(520, 560)
        lay = QVBoxLayout(d)
        self.tabs = QTabWidget()
        self.widgets = {}
        for key, title, help_text in self.TABS:
            page = QWidget()
            pl = QVBoxLayout(page)
            hint = QLabel(help_text + "\n\nМожно перетащить сюда приложение из Finder или файлового менеджера.")
            hint.setWordWrap(True)
            pl.addWidget(hint)
            lw = DropList(lambda paths, k=key: self.add([(file_entry(p), None) for p in paths], k))
            lw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            lw.setIconSize(QPixmap(28, 28).size())
            pl.addWidget(lw)
            row = QHBoxLayout()
            for text, fn in (("Добавить приложение…", lambda _=False, k=key: self.add(AppPicker(d).run(), k)),
                             ("Добавить сайт…", lambda _=False, k=key: self.add_site(k)),
                             ("Удалить", lambda _=False, k=key: self.remove(k))):
                b = QPushButton(text)
                b.clicked.connect(fn)
                row.addWidget(b)
            row.addStretch()
            pl.addLayout(row)
            self.widgets[key] = lw
            self.tabs.addTab(page, title)
            self.refresh(key)
        self.tabs.setCurrentIndex([k for k, _, _ in self.TABS].index(tab_key))
        lay.addWidget(self.tabs)
        done = QPushButton("Готово")
        done.setDefault(True)
        done.clicked.connect(d.accept)
        r = QHBoxLayout()
        r.addStretch()
        r.addWidget(done)
        lay.addLayout(r)

    def refresh(self, key):
        from PyQt6.QtWidgets import QListWidgetItem
        lw = self.widgets[key]
        lw.clear()
        for entry in self.lists[key]:
            name, detail, icon = entry_look(entry, self.labels, self.known)
            it = QListWidgetItem(icon, f"{name}\n{detail}")
            it.setData(Qt.ItemDataRole.UserRole, entry)
            it.setToolTip(entry)
            lw.addItem(it)
        title = dict((k, t) for k, t, _ in self.TABS)[key]
        self.tabs.setTabText([k for k, _, _ in self.TABS].index(key),
                             f"{title} ({len(self.lists[key])})" if self.lists[key] else title)

    def add(self, picked, key):
        other = "direct_apps" if key == "vpn_only" else "vpn_only"
        for entry, label in picked:
            if not entry:
                continue
            if label and not entry.endswith(".app"):     # bundles show their own name and icon
                self.labels[entry] = label
            if entry in self.lists[other]:       # an app can only be on one list
                self.lists[other].remove(entry)
                self.refresh(other)
            if entry not in self.lists[key]:
                self.lists[key].append(entry)
        self.refresh(key)

    def add_site(self, key):
        text, ok = QInputDialog.getText(self.dlg, "Добавить сайт",
                                        "Адрес сайта, например claude.ai (поддомены тоже попадут под правило):")
        if not ok or not text.strip():
            return
        dom = normalize_domain(text)
        if not dom:
            QMessageBox.warning(self.dlg, "Glass VPN", f"«{text.strip()}» не похоже на адрес сайта.")
            return
        self.add([(dom, None)], key)

    def remove(self, key):
        lw = self.widgets[key]
        gone = {it.data(Qt.ItemDataRole.UserRole) for it in lw.selectedItems()}
        if not gone and lw.currentItem():
            gone = {lw.currentItem().data(Qt.ItemDataRole.UserRole)}
        self.lists[key] = [e for e in self.lists[key] if e not in gone]
        self.refresh(key)

    def run(self):
        """True if the lists changed (they are written into settings)."""
        bring_to_front()
        self.dlg.exec()
        changed = any(self.lists[k] != self.settings.get(k, []) for k in self.lists)
        used = set(self.lists["vpn_only"]) | set(self.lists["direct_apps"])
        self.settings["app_labels"] = {k: v for k, v in self.labels.items() if k in used}
        for k, v in self.lists.items():
            self.settings[k] = v
        return changed


def DropList(on_drop):
    """A QListWidget that takes files dropped from Finder / a file manager."""
    from PyQt6.QtWidgets import QListWidget

    class _DropList(QListWidget):
        def __init__(self):
            super().__init__()
            self.setAcceptDrops(True)
            self.setDragDropMode(self.DragDropMode.DropOnly)

        def dragEnterEvent(self, e):
            if e.mimeData().hasUrls():
                e.acceptProposedAction()

        dragMoveEvent = dragEnterEvent

        def dropEvent(self, e):
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if paths:
                on_drop(paths)
                e.acceptProposedAction()
    return _DropList()


class Signals(QObject):
    servers_changed = pyqtSignal()
    message = pyqtSignal(str, str)
    latency = pyqtSignal(dict)
    probed = pyqtSignal(object)


class Tray:
    def __init__(self, app):
        self.app = app
        self.sig = Signals()
        self.sig.servers_changed.connect(self.rebuild_menu)
        self.sig.message.connect(self.notify)
        self.sig.latency.connect(self.show_latency)
        self.sig.probed.connect(self.on_probe)
        self.state = OFF
        self.fg = panel_text_color()
        self.phase = 0.0
        self.probe_ms = None
        self.probing = False
        self.fails = 0
        self.bypass = False               # server unreachable: Xray sends traffic direct
        self.net = network_signature()
        self.last_bytes = None
        self.last_tick = time.time()      # wall clock: a jump means the machine slept
        self.last_reconnect = 0.0
        self.reconnect_gap = 30           # seconds between automatic reconnects, doubles up to 5 min
        self.rates = (0.0, 0.0)
        self.settings = load(SETTINGS, {"subscriptions": [], "selected": None, "autoconnect": True})
        self.settings.setdefault("fallback_direct", True)
        self.settings.setdefault("vpn_only", list(DEFAULT_VPN_ONLY))
        if not IS_MAC and "Claude.app" in self.settings["vpn_only"]:   # the macOS default on Linux
            self.settings["vpn_only"] = [CLAUDE_DESKTOP if e == "Claude.app" else e
                                         for e in self.settings["vpn_only"]]
        self.settings.setdefault("direct_apps", [])
        self.guard = False                # sing-box up with the VPN off, blocking the VPN-only list
        self.servers = load(SERVERS, [])
        self.proc = None
        self.xray = None
        self.want_up = False
        self.latencies = {}
        self.tray = QSystemTrayIcon(draw_icon(OFF, self.fg))
        self.tray.setToolTip("Glass VPN")
        self.tray.activated.connect(self.on_click)
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self.rebuild_menu()
        self.tray.show()
        self.watchdog = QTimer(interval=3000, timeout=self.check_process)
        self.watchdog.start()
        self.ticker = QTimer(interval=2000, timeout=self.tick)       # traffic, colour, probe
        self.ticker.start()
        self.pulse = QTimer(interval=120, timeout=self.animate)      # connecting blink
        self.pulse.start()
        if self.settings.get("autoconnect") and self.current():
            QTimer.singleShot(1500, self.connect)
        elif self.settings.get("vpn_only"):
            QTimer.singleShot(1500, self.start_guard)
        QTimer.singleShot(4000, lambda: self.update_subscriptions(quiet=True))
        # repair an autostart entry written with a bare "Exec=glassvpn"
        if not IS_MAC and AUTOSTART.exists() and "Exec=glassvpn\n" in AUTOSTART.read_text():
            AUTOSTART.write_text(LINUX_AUTOSTART)

    # icons: monochrome symbolic icons so the adaptive top bar recolors them
    def icon(self, up=None):
        return draw_icon(self.state, self.fg, self.phase)

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self.refresh_icon()
            self.rebuild_menu()

    def refresh_icon(self):
        self.tray.setIcon(draw_icon(self.state, self.fg, self.phase))
        cur = self.current()
        lines = [f"Glass VPN — {STATE_TEXT[self.state]}"]
        if cur and self.state != OFF:
            lines.append(f"Сервер: {cur['name']}")
        if self.state == BYPASS:
            lines.append("Трафик идёт мимо VPN, пока сервер не ответит")
        if self.settings.get("vpn_only") and self.state in (BYPASS, ERROR):
            lines.append("Приложения «только через VPN» ждут сервер")
        if self.guard:
            lines.append("Приложения «только через VPN» заблокированы")
        if self.state == ON:
            if self.probe_ms:
                lines.append(f"Задержка: {self.probe_ms} мс")
            lines.append(f"↓ {human_rate(self.rates[0])}   ↑ {human_rate(self.rates[1])}")
        self.tray.setToolTip("\n".join(lines))

    def animate(self):
        if self.state == CONNECTING:
            self.phase = ((self.phase + 0.18 + 1) % 2) - 1
            self.tray.setIcon(draw_icon(self.state, self.fg, self.phase))

    def tick(self):
        now = time.time()
        slept, self.last_tick = now - self.last_tick > 20, now
        if slept and self.want_up:
            # after sleep the network often comes back with another address and Xray's
            # long-lived links hang instead of failing: give it fresh ones. Only Xray —
            # the TUN stays, so nothing slips out directly meanwhile
            QTimer.singleShot(5000, self.restart_xray)
        fg = panel_text_color()
        if fg != self.fg:
            self.fg = fg
            self.refresh_icon()
        net = network_signature()
        if net != self.net:
            self.net = net
            if self.want_up and net and self.is_up():
                # another network: restart Xray onto it and check at once
                self.restart_xray()
        b = tun_bytes()
        if b and self.last_bytes:
            self.rates = ((b[0] - self.last_bytes[0]) / 2.0, (b[1] - self.last_bytes[1]) / 2.0)
        self.last_bytes = b
        if self.want_up and self.is_up() and not self.probing:
            self.probing = True
            threading.Thread(target=lambda: self.sig.probed.emit(server_probe()), daemon=True).start()
        elif not self.want_up:
            self.set_state(OFF)
        if self.state == ON:
            self.refresh_icon()

    def on_probe(self, ms):
        self.probing = False
        if not self.want_up:
            return
        if ms is not None:
            self.fails, self.probe_ms = 0, ms
            self.reconnect_gap = 30
            if self.bypass:
                self.set_bypass(False)
            self.set_state(ON)
        else:
            self.fails += 1
            # give a fresh connection a few seconds before calling it broken; then let
            # traffic go direct until the server answers again (the probe port still asks it)
            if self.fails >= 3:
                if self.settings.get("fallback_direct", True):
                    self.set_bypass(True)
                    self.set_state(BYPASS)
                else:
                    self.set_state(ERROR)
            # still broken: the network may have changed under Xray — restart it,
            # backing off while there is no network at all
            # (not while bypassing: that would put traffic back on the dead tunnel every time)
            if self.fails >= 6 and not self.bypass and time.time() - self.last_reconnect >= self.reconnect_gap:
                self.reconnect_gap = min(self.reconnect_gap * 2, 300)
                self.reconnect()

    def set_bypass(self, on):
        if on != self.bypass:
            self.bypass = on
            self.restart_xray()

    def restart_xray(self):
        """New Xray (fresh links, current mode) under the running TUN."""
        s = self.current()
        if not s or not self.want_up:
            return
        ips = resolve(s["host"])
        save(XRAY_CONFIG, xray_config(s, ips[0] if ips else None, self.bypass))
        self.stop_xray()
        self.xray = subprocess.Popen([XRAY, "run", "-c", str(XRAY_CONFIG)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def reconnect(self):
        if self.want_up:
            self.last_reconnect = time.time()
            self.restart_xray()

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
        mark = {OFF: "○", CONNECTING: "◌", ON: "●", BYPASS: "◐", ERROR: "⚠"}[self.state]
        status = QAction(f"{mark} {STATE_TEXT[self.state].capitalize()}" + (f": {cur['name']}" if cur and self.state != OFF else "")
                         + (f" · {self.probe_ms} мс" if self.state == ON and self.probe_ms else ""), m)
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
        self.build_sources_menu(m.addMenu("Подписки и ключи"))
        m.addAction("Правила для приложений…").triggered.connect(lambda: self.edit_rules("vpn_only"))
        fd = m.addAction("Напрямую, если сервер недоступен")
        fd.setCheckable(True)
        fd.setChecked(self.settings.get("fallback_direct", True))
        fd.toggled.connect(self.set_fallback_direct)
        ac = m.addAction("Подключаться при входе")
        ac.setCheckable(True)
        ac.setChecked(AUTOSTART.exists() and self.settings.get("autoconnect", True))
        ac.toggled.connect(self.set_autostart)
        m.addAction("Журнал").triggered.connect(
            lambda: subprocess.Popen(["open", "-a", "Console", str(XRAY_LOG), str(SB_LOG)] if IS_MAC
                                     else ["xdg-open", str(XRAY_LOG)]))
        m.addSeparator()
        m.addAction("Выход").triggered.connect(self.quit)
        self.refresh_icon()

    def edit_rules(self, tab):
        if RulesDialog(self.settings, tab).run():
            save(SETTINGS, self.settings)
            self.apply_rules()
        else:
            save(SETTINGS, self.settings)    # labels only

    def apply_rules(self):
        """New lists take effect: rebuild sing-box in whatever mode it is in."""
        if self.want_up:
            self.connect()
        elif self.settings.get("vpn_only"):
            self.start_guard()
        elif self.guard:
            self.stop_process()
            self.guard = False
        self.rebuild_menu()

    def build_sources_menu(self, sm):
        subs = self.settings.get("subscriptions", [])
        if subs:
            sm.addSection("Подписки")
        for url in subs:
            n = sum(1 for s in self.servers if s.get("sub") == url)
            sub = sm.addMenu(f"{sub_label(url)}  ·  {n} серв.")
            sub.addAction("Обновить").triggered.connect(lambda _=False, u=url: self.update_subscriptions(False, [u]))
            sub.addAction("Удалить…").triggered.connect(lambda _=False, u=url: self.remove_subscription(u))
        keys = [s for s in self.servers if s.get("manual")]
        if keys:
            sm.addSection("Ключи")
        for s in keys:
            k = sm.addMenu(s["name"])
            k.addAction("Удалить…").triggered.connect(lambda _=False, n=s["name"]: self.remove_key(n))
        if subs or keys:
            sm.addSeparator()
        sm.addAction("Добавить подписку или ключ…").triggered.connect(self.add_subscription)
        upd = sm.addAction("Обновить все подписки")
        upd.setEnabled(bool(subs))
        upd.triggered.connect(lambda: self.update_subscriptions(quiet=False))

    def confirm(self, text):
        return QMessageBox.question(None, "Glass VPN", text) == QMessageBox.StandardButton.Yes

    def servers_removed(self):
        """After a delete: keep the selection valid and move the tunnel if its server is gone."""
        save(SERVERS, self.servers)
        names = {s["name"] for s in self.servers}
        if self.settings.get("selected") not in names:
            self.settings["selected"] = self.servers[0]["name"] if self.servers else None
            save(SETTINGS, self.settings)
            if self.want_up:
                if self.servers:
                    self.connect()
                else:
                    self.disconnect()
        self.sig.servers_changed.emit()

    def remove_subscription(self, url):
        n = sum(1 for s in self.servers if s.get("sub") == url)
        if not self.confirm(f"Удалить подписку {sub_label(url)} и её серверы ({n})?"):
            return
        self.settings["subscriptions"] = [u for u in self.settings.get("subscriptions", []) if u != url]
        save(SETTINGS, self.settings)
        self.servers = [s for s in self.servers if s.get("sub") != url]
        self.servers_removed()

    def remove_key(self, name):
        if not self.confirm(f"Удалить ключ «{name}»?"):
            return
        self.servers = [s for s in self.servers if not (s.get("manual") and s["name"] == name)]
        self.servers_removed()

    def on_click(self, reason):
        # on macOS a click opens the menu, as with every menu bar item
        if reason == QSystemTrayIcon.ActivationReason.Trigger and not IS_MAC:
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

    def update_subscriptions(self, quiet, only=None):
        subs = list(only or self.settings.get("subscriptions", []))
        if not subs:
            if not quiet:
                self.notify("Glass VPN", "Подписок нет — добавьте ссылку.")
            return

        def work():
            got, errors = {}, []
            for url in subs:
                try:
                    servers = fetch_subscription(url)
                    for sv in servers:
                        sv["sub"] = url
                    got[url] = servers
                except Exception as e:  # network, HTTP, decoding
                    errors.append(f"{sub_label(url)}: {e}")
            if got:
                # replace only the servers of the subscriptions that answered
                keep = [sv for sv in self.servers if sv.get("sub") not in got]
                fresh = [sv for url in got for sv in got[url]]
                names = {sv["name"] for sv in fresh}
                self.servers = fresh + [sv for sv in keep if sv["name"] not in names]
                save(SERVERS, self.servers)
                self.sig.servers_changed.emit()
                if not quiet:
                    self.sig.message.emit("Glass VPN", f"Обновлено, серверов: {len(fresh)}"
                                          + (f". Ошибки: {'; '.join(errors)[:150]}" if errors else ""))
            elif not quiet:
                self.sig.message.emit("Glass VPN", "Не удалось обновить: " + "; ".join(errors)[:200])
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
            self.connect()
        else:
            self.rebuild_menu()

    # ---- sing-box process
    def is_up(self):
        return (self.proc is not None and self.proc.poll() is None
                and self.xray is not None and self.xray.poll() is None)

    def sb_config(self, s, direct, guard=False):
        return build_config(s, direct, mac_system_dns() if IS_MAC else None,
                            self.settings.get("vpn_only", []), self.settings.get("direct_apps", []), guard)

    def run_sing_box(self):
        """Start sing-box with SB_CONFIG, replacing the running one. On macOS the helper
        swaps it in place, keeping the DNS on the tunnel; True on success."""
        if IS_MAC:
            try:
                self.proc = HelperProc(SB_CONFIG)
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
                self.proc = None
                self.notify("Glass VPN", f"Не удалось поднять туннель: {e}")
                return False
        else:
            self.stop_sing_box()
            self.proc = subprocess.Popen([SING_BOX, "run", "-c", str(SB_CONFIG)],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def check_configs(self, *cmds):
        for cmd in cmds:
            check = subprocess.run(cmd, capture_output=True, text=True)
            if check.returncode != 0:
                self.notify("Glass VPN", "Ошибка конфигурации: " + (check.stderr or check.stdout)[-200:])
                return False
        return True

    def connect(self):
        s = self.current()
        if not s:
            self.notify("Glass VPN", "Нет серверов — добавьте подписку.")
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if not self.want_up:
            self.bypass = False      # a fresh start tries the server first
        server_ips = resolve(s["host"])
        direct = pptp_gateways() + server_ips
        save(XRAY_CONFIG, xray_config(s, server_ips[0] if server_ips else None, self.bypass))
        save(SB_CONFIG, self.sb_config(s, direct))
        if not self.check_configs([XRAY, "run", "-test", "-c", str(XRAY_CONFIG)],
                                  [SING_BOX, "check", "-c", str(SB_CONFIG)]):
            return
        # the TUN is replaced, never taken down first: the VPN-only list has no gap to slip through
        self.stop_xray()
        self.xray = subprocess.Popen([XRAY, "run", "-c", str(XRAY_CONFIG)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not self.run_sing_box():
            self.stop_process()
            self.want_up = self.guard = False
            self.set_state(ERROR)
            return
        self.want_up, self.guard = True, False
        self.fails, self.probe_ms, self.last_bytes = 0, None, None
        self.set_state(CONNECTING)
        self.settings["selected"] = s["name"]
        save(SETTINGS, self.settings)
        QTimer.singleShot(1500, self.rebuild_menu)

    def start_guard(self):
        """VPN off, but the "only through the VPN" list stays blocked instead of going direct."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        save(SB_CONFIG, self.sb_config(self.current(), pptp_gateways(), guard=True))
        if not self.check_configs([SING_BOX, "check", "-c", str(SB_CONFIG)]):
            return
        self.stop_xray()
        self.guard = self.run_sing_box()
        self.rebuild_menu()

    def disconnect(self):
        self.want_up = False
        if self.settings.get("vpn_only"):
            self.start_guard()
        else:
            self.stop_process()
        self.set_state(OFF)
        self.rebuild_menu()

    @staticmethod
    def stop_child(p):
        if p and p.poll() is None:
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

    def stop_xray(self):
        self.stop_child(self.xray)
        self.xray = None

    def stop_sing_box(self):
        self.stop_child(self.proc)
        if IS_MAC and isinstance(self.proc, HelperProc) and self.proc.poll() is not None:
            helper_stop()   # sing-box died on its own: still give the DNS back
        self.proc = None

    def stop_process(self):
        self.stop_sing_box()
        self.stop_xray()
        self.guard = False

    def check_process(self):
        if self.want_up and not self.is_up():
            if self.proc is not None and self.proc.poll() is None:
                self.restart_xray()      # only Xray died: the TUN is fine
                return
            # restart sing-box if it died while the user wants the VPN up
            self.notify("Glass VPN", "Соединение прервалось, переподключаюсь…")
            self.connect()
        elif self.guard and (self.proc is None or self.proc.poll() is not None):
            self.start_guard()

    def set_fallback_direct(self, on):
        self.settings["fallback_direct"] = on
        save(SETTINGS, self.settings)
        if not on and self.bypass:
            self.set_bypass(False)
            self.set_state(ERROR)

    def set_autostart(self, on):
        self.settings["autoconnect"] = on
        save(SETTINGS, self.settings)
        if on and IS_MAC:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text(MAC_LAUNCH_AGENT.format(app=Path.home() / "Applications/Glass VPN.app"))
        elif on:
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text(LINUX_AUTOSTART)
        elif AUTOSTART.exists():
            AUTOSTART.unlink()

    def quit(self):
        self.stop_process()
        self.app.quit()


# Absolute Exec: the XDG autostart generator runs before ~/.local/bin is on PATH
# and silently skips entries whose binary it can't find.
LINUX_AUTOSTART = (f"[Desktop Entry]\nType=Application\nName=Glass VPN\n"
                   f"Exec={Path(os.path.abspath(sys.argv[0]))}\nIcon=network-vpn\n"
                   f"StartupNotify=false\nX-GNOME-Autostart-enabled=true\n")

MAC_LAUNCH_AGENT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.glassvpn</string>
  <key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-a</string><string>{app}</string></array>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
"""


def main():
    if IS_MAC:
        import fcntl
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        lock = open(CACHE_DIR / "instance.lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)   # held until exit
        except OSError:
            return 0   # already running
        main.lock = lock
        helper_stop()   # a crash last time may have left sing-box or the DNS override behind
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Glass VPN")
    app.setDesktopFileName("glassvpn")
    if IS_MAC:
        mac_hide_dock_icon()
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "Glass VPN", "Системный трей недоступен.")
        return 1
    tray = Tray(app)
    app.aboutToQuit.connect(tray.stop_process)   # never leave sing-box/Xray behind
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
