#!/bin/bash
# (-k: reachability only — some Russian sites use a CA macOS does not trust)
# One-shot test of Glass VPN on a Mac that currently depends on another VPN (Happ):
# stop the other VPN, bring Glass VPN up, check the routing, and if anything
# fails bring the other VPN back. Usage: switch-test.sh ["Other VPN service name"]
OTHER=${1:-Happ Plus}
APPDIR="$HOME/Library/Application Support/GlassVPN"
LOGDIR="$HOME/Library/Logs/GlassVPN"
PY="$APPDIR/venv/bin/python"

rollback() {
    echo "FAIL: $1 — rolling back"
    pkill -f "^/opt/glassvpn/xray run" 2>/dev/null
    sudo -n /opt/glassvpn/glassvpn-helper stop
    [ -n "$OTHER" ] && scutil --nc start "$OTHER"
    sleep 5
    curl -s -o /dev/null -w "after rollback: anthropic HTTP %{http_code}\n" -m 10 https://api.anthropic.com
    exit 1
}

# configs from the saved server list (no secrets printed)
"$PY" - <<'E' || exit 1
import os, sys; sys.path.insert(0, os.path.expanduser("~/Library/Application Support/GlassVPN"))
import glassvpn as g
s = g.load(g.SETTINGS, {}); servers = g.load(g.SERVERS, [])
cur = next((x for x in servers if x["name"] == s.get("selected")), servers[0] if servers else None)
if not cur: sys.exit("no servers saved")
ips = g.resolve(cur["host"])
g.STATE_DIR.mkdir(parents=True, exist_ok=True)
g.save(g.XRAY_CONFIG, g.xray_config(cur, ips[0] if ips else None))
g.save(g.SB_CONFIG, g.build_config(cur, ips, g.mac_system_dns()))
print("server:", cur["name"], cur["type"], cur["security"], "enc:", cur["encryption"][:24])
E

[ -n "$OTHER" ] && { scutil --nc stop "$OTHER"; sleep 3; }
/opt/glassvpn/xray run -c "$LOGDIR/xray.json" >/dev/null 2>&1 &
sudo -n /opt/glassvpn/glassvpn-helper start "$LOGDIR/sing-box.json" || rollback "helper start"
sleep 3
fails=0
for u in https://api.anthropic.com https://www.google.com https://www.youtube.com https://ya.ru https://www.nalog.gov.ru; do
    code=$(curl -sk -o /dev/null -w "%{http_code}" -m 15 "$u")
    echo "$u -> HTTP $code"
    [ "$code" = 000 ] && fails=$((fails+1))
done
echo "exit country via tunnel: $(curl -s -m 10 https://ipinfo.io/country)"
echo "system DNS now: $(networksetup -getdnsservers Wi-Fi | tr '\n' ' ')"
[ $fails -eq 0 ] || rollback "$fails site(s) unreachable"
echo "OK: Glass VPN is carrying the traffic (xray and sing-box left running)"
