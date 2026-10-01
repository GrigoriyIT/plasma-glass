# Glass VPN

A small tray client for VLESS subscriptions: [Xray-core](https://github.com/XTLS/Xray-core) talks VLESS
(including VLESS Encryption `mlkem768x25519plus`, Reality, gRPC, XHTTP) and exposes SOCKS5 on
127.0.0.1; [sing-box](https://github.com/SagerNet/sing-box) owns the system-wide TUN and the routing.

- Blocked resources go through the VPN; the local network and Russian sites
  (`.ru`, `.рф`, `.su`, sing-geosite `category-ru`, sing-geoip `ru`) go direct.
- System-wide TUN mode (IPv4; networks here usually have no IPv6). sing-box gets `cap_net_admin` via `setcap`, so nothing runs as root.
- Gateways of NetworkManager VPN connections (e.g. a PPTP link home) bypass the tunnel.
- Subscriptions: plain or base64 lists of `vless://` links; transports tcp, grpc, ws,
  httpupgrade, xhttp; security none, tls, reality; VLESS Encryption.
- Tray icon drawn at runtime: a shield in the adaptive top bar's text colour plus a status dot —
  no dot = off, pulsing amber = connecting, green = the tunnel works (a site is opened through
  Xray every 2 s), red = the server doesn't answer. Tooltip: server, latency, ↓/↑ speed.
  Click to connect/disconnect; server list with a TCP latency test; reconnects if a core exits.

  ![Icon states on a light and a dark bar](../../docs/images/glassvpn-states.png)

Files: settings and servers in `~/.config/glassvpn/` (mode 600), sing-box config and log
in `~/.local/state/glassvpn/`.

```bash
components/vpn/install.sh
```

`install.sh` also installs a polkit rule (`50-glassvpn-resolved.rules`): sing-box sets the
DNS of its TUN link through systemd-resolved on every connect and reverts it on disconnect,
and without the rule each of those calls asks for the password. It allows only resolved's
per-link DNS actions, only for local active sessions of users in the `sudo` group.

## macOS

```bash
components/vpn/macos/install.sh
```

Same client, menu bar icon instead of the tray. macOS has no file capabilities, so sing-box runs as
root through `macos/glassvpn-helper` (in `/opt/glassvpn`, root-owned; a sudoers rule allows only
`start <config>` and `stop`). The helper accepts only the config shape the client generates, forces
log/cache paths, and points the system DNS at the tunnel while it is up, restoring it on stop (and at
boot via `local.glassvpn.cleanup`). Settings in `~/Library/Application Support/GlassVPN`, logs in
`~/Library/Logs/GlassVPN`. `macos/switch-test.sh` moves a Mac from another VPN to Glass VPN with an
automatic rollback; `macos/make-icon.py` draws the app icon.

The app bundle's executable is a copy of the Python launcher (script passed via `LSEnvironment` and
`sitecustomize.py`): macOS 26 silently drops the menu bar item of an app whose executable is a shell
script that execs Python.
