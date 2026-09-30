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
- Monochrome tray icon, click to connect/disconnect; server list with a TCP latency test;
  reconnects if sing-box exits.

Files: settings and servers in `~/.config/glassvpn/` (mode 600), sing-box config and log
in `~/.local/state/glassvpn/`.

```bash
components/vpn/install.sh
```

`install.sh` also installs a polkit rule (`50-glassvpn-resolved.rules`): sing-box sets the
DNS of its TUN link through systemd-resolved on every connect and reverts it on disconnect,
and without the rule each of those calls asks for the password. It allows only resolved's
per-link DNS actions, only for local active sessions of users in the `sudo` group.
