using System.Text;
using System.Text.Json.Nodes;

namespace GlassVpn.Core;

/// <summary>Xray's local SOCKS ports and their credentials, fresh for each connection:
/// some apps look for open local proxies to detect a VPN.</summary>
public sealed record Ports(int Socks, int Probe, int VpnOnly, string User, string Pass)
{
    public static Ports Fresh()
    {
        int Free()
        {
            var l = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
            l.Start();
            var port = ((System.Net.IPEndPoint)l.LocalEndpoint).Port;
            l.Stop();
            return port;
        }
        string Token() => Convert.ToHexString(System.Security.Cryptography.RandomNumberGenerator.GetBytes(12)).ToLowerInvariant();
        int a = Free(), b, c;
        do b = Free(); while (b == a);
        do c = Free(); while (c == a || c == b);
        return new Ports(a, b, c, Token(), Token());
    }

    /// <summary>Guard mode runs no Xray; the proxy outbounds just have to parse.</summary>
    public static readonly Ports None = new(9, 9, 9, "none", "none");
}

public static class Configs
{
    public const string Tun = "GlassVPN";
    public const string ProbeHost = "connectivitycheck.gstatic.com";   // GET /generate_204 through the server
    static readonly string[] RuSuffixes = ["ru", "su", "xn--p1ai", "xn--p1acf", "xn--d1acj3b"];  // .рф .рус .дети
    static readonly string[] PrivateNets = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
                                            "100.64.0.0/10", "fc00::/7", "fe80::/10"];
    /// <summary>Russian sites and addresses; the service keeps local copies (sing-box then starts
    /// without the network) and refreshes them weekly.</summary>
    public static readonly (string Tag, string Url)[] RuleSets =
    [
        ("geosite-ru", "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-category-ru.srs"),
        ("geoip-ru", "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-ru.srs"),
    ];

    static JsonArray Arr(IEnumerable<string> xs) => [.. xs.Select(x => (JsonNode?)JsonValue.Create(x))];

    /// <summary>Xray client: SOCKS5 on localhost → VLESS to the server.
    /// The probe port and the "only through the VPN" port always go to the server; with
    /// bypass the main port sends everything direct (the server is unreachable and traffic
    /// shouldn't hang on a dead tunnel meanwhile).</summary>
    public static JsonObject Xray(Server s, string? serverIp, Ports p, bool bypass)
    {
        var user = new JsonObject { ["id"] = s.Uuid, ["encryption"] = s.Encryption.Length > 0 ? s.Encryption : "none" };
        if (s.Flow.Length > 0)
            user["flow"] = s.Flow;
        var net = s.Type switch
        {
            "grpc" => "grpc", "ws" => "ws", "httpupgrade" => "httpupgrade",
            "xhttp" or "splithttp" or "http" or "h2" => "xhttp",
            _ => "tcp",
        };
        var security = s.Security is "tls" or "reality" ? s.Security : "none";
        var stream = new JsonObject { ["network"] = net, ["security"] = security };
        if (security == "tls")
        {
            var tls = new JsonObject { ["serverName"] = s.Sni.Length > 0 ? s.Sni : s.Host, ["fingerprint"] = Or(s.Fp, "chrome") };
            if (s.Alpn.Length > 0)
                tls["alpn"] = Arr(s.Alpn.Split(','));
            stream["tlsSettings"] = tls;
        }
        else if (security == "reality")
        {
            stream["realitySettings"] = new JsonObject
            {
                ["serverName"] = s.Sni, ["fingerprint"] = Or(s.Fp, "chrome"),
                ["publicKey"] = s.Pbk, ["shortId"] = s.Sid, ["spiderX"] = s.Spx,
            };
        }
        switch (net)
        {
            case "grpc":
                stream["grpcSettings"] = new JsonObject { ["serviceName"] = s.ServiceName };
                break;
            case "ws":
                var ws = new JsonObject { ["path"] = Or(s.Path, "/") };
                if (s.HostHeader.Length > 0)
                    ws["headers"] = new JsonObject { ["Host"] = s.HostHeader };
                stream["wsSettings"] = ws;
                break;
            case "httpupgrade":
                stream["httpupgradeSettings"] = new JsonObject { ["path"] = Or(s.Path, "/"), ["host"] = s.HostHeader };
                break;
            case "xhttp":
                stream["xhttpSettings"] = new JsonObject { ["path"] = Or(s.Path, "/"), ["host"] = s.HostHeader, ["mode"] = Or(s.Mode, "auto") };
                break;
        }
        JsonObject Socks(string tag, int port, bool udp) => new()
        {
            ["tag"] = tag, ["listen"] = "127.0.0.1", ["port"] = port, ["protocol"] = "socks",
            ["settings"] = new JsonObject
            {
                ["auth"] = "password", ["udp"] = udp,
                ["accounts"] = new JsonArray(new JsonObject { ["user"] = p.User, ["pass"] = p.Pass }),
            },
        };
        var rules = new JsonArray(new JsonObject
        {
            ["type"] = "field", ["inboundTag"] = Arr(["probe", "vpnonly"]), ["outboundTag"] = "proxy",
        });
        if (bypass)
            rules.Add((JsonNode)new JsonObject { ["type"] = "field", ["inboundTag"] = Arr(["socks"]), ["outboundTag"] = "direct" });
        return new JsonObject
        {
            ["log"] = new JsonObject { ["loglevel"] = "warning", ["access"] = "none" },   // to stdout
            ["inbounds"] = new JsonArray(Socks("socks", p.Socks, true), Socks("probe", p.Probe, false), Socks("vpnonly", p.VpnOnly, true)),
            ["outbounds"] = new JsonArray(
                new JsonObject
                {
                    ["protocol"] = "vless", ["tag"] = "proxy",
                    ["settings"] = new JsonObject
                    {
                        ["vnext"] = new JsonArray(new JsonObject
                        {
                            ["address"] = serverIp ?? s.Host, ["port"] = s.Port, ["users"] = new JsonArray(user),
                        }),
                    },
                    ["streamSettings"] = stream,
                },
                // leaves through the TUN, where sing-box sends Xray's traffic out directly
                new JsonObject { ["protocol"] = "freedom", ["tag"] = "direct" }),
            ["routing"] = new JsonObject { ["rules"] = rules },
        };
    }

    static string Or(string v, string def) => v.Length > 0 ? v : def;

    /// <summary>Go's regexp (RE2) rejects escapes of letters and spaces, so .NET's Regex.Escape won't do.</summary>
    static string Re2Escape(string s)
    {
        var b = new StringBuilder(s.Length + 8);
        foreach (var c in s)
        {
            if (@"\.+*?()|[]{}^$".Contains(c))
                b.Append('\\');
            b.Append(c);
        }
        return b.ToString();
    }

    /// <summary>List entries → sing-box matchers. "claude.exe" or "claude" is a program name,
    /// "C:\Program Files\App\" a folder or file prefix, anything else with a dot a domain.
    /// Process matching goes through a case-insensitive regex: Windows names aren't case-sensitive.</summary>
    public static List<JsonObject> MatchRules(IEnumerable<string> entries)
    {
        var procs = new List<string>();
        var domains = new List<string>();
        foreach (var raw in entries)
        {
            var e = raw.Trim();
            if (e.Length == 0)
                continue;
            if (e.Contains('\\') || e.Contains('/') || e.Contains(':'))
                procs.Add("(?i)^" + Re2Escape(e.Replace('/', '\\')));
            else if (e.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
                procs.Add(@"(?i)\\" + Re2Escape(e) + "$");
            else if (e.Contains('.'))
                domains.Add(e.TrimStart('.'));
            else
                procs.Add(@"(?i)\\" + Re2Escape(e) + @"\.exe$");
        }
        var res = new List<JsonObject>();
        if (procs.Count > 0)
            res.Add(new JsonObject { ["process_path_regex"] = Arr(procs.Distinct()) });
        if (domains.Count > 0)
            res.Add(new JsonObject { ["domain_suffix"] = Arr(domains.Distinct()) });
        return res;
    }

    /// <summary>sing-box: the system-wide TUN and the routing. Russian sites and the LAN go
    /// direct, the rest through Xray. guard: the VPN is off — everything direct, except the
    /// "only through the VPN" list, which is blocked rather than let out with the local address.</summary>
    public static JsonObject SingBox(IEnumerable<string> directHosts, string? localDns, Ports p,
        IEnumerable<string> vpnOnly, IEnumerable<string> directApps, bool guard, string cachePath,
        IReadOnlyDictionary<string, string> ruleSets)
    {
        // "local" is the network's own DNS server asked directly: the system resolver
        // points into the tunnel while it is up
        var local = localDns is null
            ? new JsonObject { ["type"] = "local", ["tag"] = "local" }
            : new JsonObject { ["type"] = "udp", ["tag"] = "local", ["server"] = localDns };
        var routeRules = new JsonArray(
            new JsonObject { ["action"] = "sniff" },
            new JsonObject { ["protocol"] = "dns", ["action"] = "hijack-dns" },
            // Xray's own connections — to the server, and its direct traffic while bypassing —
            // never loop back into the tunnel
            new JsonObject { ["process_path_regex"] = Arr([@"(?i)\\xray\.exe$"]), ["outbound"] = "direct" },
            new JsonObject { ["ip_is_private"] = true, ["outbound"] = "direct" });
        // before the Russian zone: these go through the server even to .ru sites
        foreach (var m in MatchRules(vpnOnly))
        {
            if (guard)
                m["action"] = "reject";
            else
                m["outbound"] = "vpn-only";
            routeRules.Add((JsonNode)m);
        }
        foreach (var m in MatchRules(directApps))
        {
            m["outbound"] = "direct";
            routeRules.Add((JsonNode)m);
        }
        routeRules.Add((JsonNode)new JsonObject { ["domain_suffix"] = Arr(RuSuffixes), ["outbound"] = "direct" });
        if (ruleSets.Count > 0)
            routeRules.Add((JsonNode)new JsonObject { ["rule_set"] = Arr(ruleSets.Keys), ["outbound"] = "direct" });
        var dnsRules = new JsonArray(new JsonObject { ["domain_suffix"] = Arr(RuSuffixes), ["server"] = "local" });
        if (ruleSets.ContainsKey("geosite-ru"))
            dnsRules.Add((JsonNode)new JsonObject { ["rule_set"] = Arr(["geosite-ru"]), ["server"] = "local" });

        JsonObject Socks(string tag, int port) => new()
        {
            ["type"] = "socks", ["tag"] = tag, ["server"] = "127.0.0.1", ["server_port"] = port, ["version"] = "5",
            ["username"] = p.User, ["password"] = p.Pass,
        };
        return new JsonObject
        {
            ["log"] = new JsonObject { ["level"] = "warn", ["timestamp"] = false },   // to stdout
            ["dns"] = new JsonObject
            {
                ["servers"] = new JsonArray(
                    new JsonObject { ["type"] = "https", ["tag"] = "remote", ["server"] = "1.1.1.1", ["detour"] = "proxy" },
                    local),
                ["rules"] = dnsRules,
                ["final"] = guard ? "local" : "remote",
                ["strategy"] = "ipv4_only",   // most home networks here have no IPv6
            },
            ["inbounds"] = new JsonArray(new JsonObject
            {
                ["type"] = "tun", ["tag"] = "tun-in", ["interface_name"] = Tun,
                // IPv4 only: with an IPv6 address the tunnel would swallow AAAA traffic
                // that has nowhere to go on networks without IPv6
                ["address"] = Arr(["198.18.0.1/30"]),
                ["mtu"] = 9000, ["auto_route"] = true, ["strict_route"] = true, ["stack"] = "mixed",
                // the LAN and the VPN server stay outside the tunnel
                ["route_exclude_address"] = Arr(PrivateNets.Concat(directHosts.Select(h => h + "/32"))),
            }),
            ["outbounds"] = new JsonArray(Socks("proxy", p.Socks), Socks("vpn-only", p.VpnOnly),
                new JsonObject { ["type"] = "direct", ["tag"] = "direct" }),
            ["route"] = new JsonObject
            {
                ["rules"] = routeRules,
                ["rule_set"] = new JsonArray([.. ruleSets.Select(r => (JsonNode)new JsonObject
                {
                    ["type"] = "local", ["tag"] = r.Key, ["format"] = "binary", ["path"] = r.Value,
                })]),
                ["final"] = guard ? "direct" : "proxy",
                ["auto_detect_interface"] = true,
                ["default_domain_resolver"] = "local",
            },
            ["experimental"] = new JsonObject
            {
                ["cache_file"] = new JsonObject { ["enabled"] = true, ["path"] = cachePath },
            },
        };
    }
}
