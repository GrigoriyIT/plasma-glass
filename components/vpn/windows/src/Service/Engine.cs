using System.Text.Json.Nodes;
using GlassVpn.Core;

namespace GlassVpn.Service;

enum VpnState { Off, Connecting, On, Bypass, Error }

/// <summary>The tunnel's state machine. Every change happens under one lock; the 2-second
/// tick, the control pipe, power and network events all go through it.</summary>
sealed class Engine : IDisposable
{
    static readonly Dictionary<VpnState, string> StateText = new()
    {
        [VpnState.Off] = "отключено", [VpnState.Connecting] = "подключение…", [VpnState.On] = "подключено",
        [VpnState.Bypass] = "напрямую — сервер недоступен", [VpnState.Error] = "сервер не отвечает",
    };

    readonly Lock gate = new();
    readonly Job job = new();
    readonly HttpClient http = new(new SocketsHttpHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(20) };
    Settings settings = Store.LoadSettings();
    List<Server> servers = Store.LoadServers();
    Child? singBox, xray;
    Ports ports = Ports.None;
    bool wantUp, guard, bypass, probing;
    VpnState state = VpnState.Off;
    int fails, restarts;
    int? probeMs;
    string? message;                       // the last thing worth telling the user
    long lastProbe, lastReconnect, retryAt, resumeAt, resumedAt = long.MinValue / 2;
    int reconnectGap = 30_000;             // between automatic reconnects, doubles up to 5 min
    volatile bool netDirty = true;
    long netCheckedAt;
    string netSig = "";
    string? localDns;
    Timer? timer, daily;
    readonly Dictionary<string, int?> latencies = [];
    (long Rx, long Tx, long At)? lastBytes;
    (double Rx, double Tx) rates;

    static string RunFile(string name) => Path.Combine(Paths.Run, name);
    static string LogFile(string name) => Path.Combine(Paths.Logs, name);

    public void Start()
    {
        Log.Write($"service start, {servers.Count} servers, autoconnect={settings.Autoconnect}");
        lock (gate)
        {
            var phys = Net.Default();
            netSig = phys?.Signature ?? "";
            localDns = phys?.Dns;
            netDirty = false;
            if (settings.Autoconnect && Current() is not null)
                Connect();
            else if (settings.VpnOnly.Count > 0)
                StartGuard();
        }
        timer = new Timer(_ => Tick(), null, 2000, 2000);
        daily = new Timer(_ => _ = Refresh(), null, TimeSpan.FromSeconds(5), TimeSpan.FromHours(12));
    }

    public void Dispose()
    {
        timer?.Dispose();
        daily?.Dispose();
        lock (gate)
        {
            wantUp = false;
            StopAll();
        }
        job.Dispose();
        Log.Write("service stop");
    }

    public void NetworkChanged() => netDirty = true;

    public void Resumed()
    {
        lock (gate)
        {
            var now = Environment.TickCount64;
            // Windows reports a wake twice (automatic, then by the user): one is enough
            if (now - resumedAt < 30_000)
                return;
            resumedAt = now;
            Log.Write("power: resumed");
            // after sleep the network often comes back with another address and Xray's
            // long-lived links hang instead of failing: give it fresh ones. Only Xray —
            // the TUN stays, so nothing slips out directly meanwhile
            resumeAt = now + 5000;
            netDirty = true;
        }
    }

    Server? Current() => servers.FirstOrDefault(s => s.Name == settings.Selected) ?? servers.FirstOrDefault();
    bool IsUp => singBox is { Alive: true } && xray is { Alive: true };

    // ------------------------------------------------------------ the tick --

    void Tick()
    {
        lock (gate)
        {
            try
            {
                TickLocked();
            }
            catch (Exception e)
            {
                Log.Write($"tick: {e}");
            }
        }
    }

    void TickLocked()
    {
        var now = Environment.TickCount64;
        if (resumeAt != 0 && now >= resumeAt)
        {
            resumeAt = 0;
            // the network coming back has usually restarted Xray already; another restart
            // would only cut the connections made since
            if (wantUp && IsUp && xray!.StartedAt < resumedAt)
                RestartXray("after sleep");
        }
        CheckProcesses(now);
        // address-change events are the trigger; a slow poll catches anything they miss
        if (netDirty || now - netCheckedAt > 30_000)
        {
            netDirty = false;
            netCheckedAt = now;
            CheckNetwork();
        }
        if (wantUp && IsUp && !probing && now - lastProbe >= (state == VpnState.On && fails == 0 ? 10_000 : 2_000))
        {
            probing = true;
            lastProbe = now;
            var p = ports;
            _ = Task.Run(async () =>
            {
                var ms = await Net.Probe(p);
                lock (gate)
                {
                    probing = false;
                    if (ReferenceEquals(p, ports))
                        OnProbe(ms);
                }
            });
        }
        else if (!wantUp)
        {
            state = VpnState.Off;
        }
    }

    void CheckNetwork()
    {
        var phys = Net.Default();
        var sig = phys?.Signature ?? "";
        if (sig == netSig)
            return;
        Log.Write($"network: {(netSig.Length > 0 ? netSig : "none")} -> {(sig.Length > 0 ? phys!.Name + " " + sig : "none")}, dns {phys?.Dns}");
        netSig = sig;
        if (sig.Length == 0)
            return;
        var dnsChanged = phys!.Dns is not null && phys.Dns != localDns;
        if (phys.Dns is not null)
            localDns = phys.Dns;
        if (wantUp && IsUp)
        {
            // another network: the direct DNS server lives in sing-box's config, Xray's links hang
            if (dnsChanged)
                Connect();
            else
                RestartXray("network changed");
            lastProbe = 0;
        }
        else if (guard && dnsChanged)
        {
            StartGuard();
        }
    }

    void CheckProcesses(long now)
    {
        if (wantUp && !IsUp)
        {
            if (now < retryAt)
                return;
            retryAt = now + Math.Min(3000L << Math.Min(restarts, 5), 60_000);
            restarts++;
            if (singBox is { Alive: true })
            {
                Log.Write($"xray exited ({xray?.ExitCode}), restarting it");
                RestartXray("xray exited");
                return;
            }
            Log.Write($"sing-box exited ({singBox?.ExitCode}), reconnecting");
            message = "Соединение прервалось, переподключаюсь…";
            Connect();
        }
        else if (guard && singBox is not { Alive: true })
        {
            if (now < retryAt)
                return;
            retryAt = now + Math.Min(3000L << Math.Min(restarts, 5), 60_000);
            restarts++;
            Log.Write($"sing-box (guard) exited ({singBox?.ExitCode}), restarting");
            StartGuard();
        }
        else if (singBox is { } sb && now - sb.StartedAt > 60_000 && (!wantUp || state == VpnState.On))
        {
            restarts = 0;
        }
    }

    void OnProbe(int? ms)
    {
        if (!wantUp)
            return;
        if (ms is not null)
        {
            if (state != VpnState.On)
                Log.Write($"probe ok, {ms} ms");
            fails = 0;
            probeMs = ms;
            reconnectGap = 30_000;
            if (bypass)
                SetBypass(false);
            state = VpnState.On;
            message = null;
            return;
        }
        fails++;
        // give a fresh connection a few seconds before calling it broken; then let traffic
        // go direct until the server answers again (the probe port still asks it)
        if (fails >= 3)
        {
            if (fails == 3)
                Log.Write("probe failed 3 times");
            if (settings.FallbackDirect)
            {
                SetBypass(true);
                state = VpnState.Bypass;
            }
            else
            {
                state = VpnState.Error;
            }
        }
        // still broken: the network may have changed under Xray — restart it, backing off
        // while there is no network at all (not while bypassing: that would put traffic back
        // on the dead tunnel every time)
        var now = Environment.TickCount64;
        if (fails >= 6 && !bypass && now - lastReconnect >= reconnectGap)
        {
            reconnectGap = Math.Min(reconnectGap * 2, 300_000);
            lastReconnect = now;
            RestartXray("server not answering");
        }
    }

    void SetBypass(bool on)
    {
        if (on == bypass)
            return;
        bypass = on;
        RestartXray(on ? "bypass on: server unreachable" : "bypass off: server answers");
    }

    // --------------------------------------------------------- the cores --

    string? WriteXray(Server s)
    {
        var ips = Net.Resolve(s.Host);
        var path = RunFile("xray.json");
        File.WriteAllText(path, Configs.Xray(s, ips.FirstOrDefault(), ports, bypass).ToJsonString());
        return path;
    }

    void StartXray(string config) =>
        xray = Child.Start(job, "xray", Paths.Xray, LogFile("xray.log"), 40, "run", "-c", config);

    void StartSingBox(string config) =>
        singBox = Child.Start(job, "sing-box", Paths.SingBox, LogFile("sing-box.log"), 48,
            "run", "-c", config, "-D", Paths.Run, "--disable-color");

    /// <summary>New Xray (fresh links, current mode) under the running TUN.</summary>
    void RestartXray(string why)
    {
        var s = Current();
        if (s is null || !wantUp)
            return;
        Log.Write($"xray restart: {why}");
        var cfg = WriteXray(s)!;
        xray?.Stop();
        StartXray(cfg);
    }

    bool Connect()
    {
        var s = Current();
        if (s is null)
        {
            message = "Нет серверов — добавьте подписку.";
            return false;
        }
        if (!wantUp)
            bypass = false;      // a fresh start tries the server first
        var ips = Net.Resolve(s.Host);
        ports = Ports.Fresh();
        var xrayCfg = WriteXray(s)!;
        var sbCfg = RunFile("sing-box.json");
        File.WriteAllText(sbCfg, Configs.SingBox(ips, localDns, ports, settings.VpnOnly, settings.DirectApps,
            guard: false, RunFile("cache.db"), RuleSetFiles()).ToJsonString());
        var err = Child.Check(Paths.Xray, "run", "-test", "-c", xrayCfg)
                  ?? Child.Check(Paths.SingBox, "check", "-c", sbCfg, "-D", Paths.Run);
        if (err is not null)
        {
            Log.Write($"config error: {err}");
            message = "Ошибка конфигурации: " + err;
            state = VpnState.Error;
            return false;
        }
        StopAll();
        StartXray(xrayCfg);
        StartSingBox(sbCfg);
        wantUp = true;
        guard = false;
        fails = 0;
        probeMs = null;
        lastBytes = null;
        state = VpnState.Connecting;
        lastProbe = Environment.TickCount64 - 500;   // the first check in ~1.5 s
        if (settings.Selected != s.Name)
        {
            settings.Selected = s.Name;
            Store.Save(settings);
        }
        Log.Write($"connect: {s.Name} ({s.Type}/{s.Security}), server {string.Join(",", ips)}, dns {localDns ?? "system"}");
        return true;
    }

    /// <summary>VPN off, but the "only through the VPN" list stays blocked instead of going direct.</summary>
    void StartGuard()
    {
        var sbCfg = RunFile("sing-box.json");
        File.WriteAllText(sbCfg, Configs.SingBox([], localDns, Ports.None, settings.VpnOnly, settings.DirectApps,
            guard: true, RunFile("cache.db"), RuleSetFiles()).ToJsonString());
        if (Child.Check(Paths.SingBox, "check", "-c", sbCfg, "-D", Paths.Run) is { } err)
        {
            Log.Write($"guard config error: {err}");
            message = "Ошибка конфигурации: " + err;
            return;
        }
        StopAll();
        StartSingBox(sbCfg);
        guard = true;
        Log.Write("guard: VPN off, the VPN-only list is blocked");
    }

    void StopAll()
    {
        xray?.Stop();
        singBox?.Stop();
        xray = singBox = null;
        guard = false;
    }

    void Disconnect()
    {
        wantUp = false;
        bypass = false;
        if (settings.VpnOnly.Count > 0)
            StartGuard();
        else
            StopAll();
        state = VpnState.Off;
        Log.Write("disconnect");
    }

    /// <summary>After a delete: keep the selection valid and move the tunnel if its server is gone.</summary>
    void ServersRemoved()
    {
        Store.Save(servers);
        if (servers.All(s => s.Name != settings.Selected))
        {
            settings.Selected = servers.FirstOrDefault()?.Name;
            Store.Save(settings);
            if (wantUp)
            {
                if (servers.Count > 0)
                    Connect();
                else
                    Disconnect();
            }
        }
    }

    // ------------------------------------------------------ subscriptions --

    async Task Refresh()
    {
        await UpdateRuleSets();
        await UpdateSubscriptions(null);
    }

    static Dictionary<string, string> RuleSetFiles() =>
        Configs.RuleSets.Select(r => (r.Tag, Path: RunFile(r.Tag + ".srs")))
            .Where(r => File.Exists(r.Path)).ToDictionary(r => r.Tag, r => r.Path);

    /// <summary>Fetches the Russian rule sets when missing or older than a week. A first copy
    /// arriving re-applies the config, so the tunnel starts without them and picks them up.</summary>
    async Task UpdateRuleSets()
    {
        var added = false;
        foreach (var (tag, url) in Configs.RuleSets)
        {
            var path = RunFile(tag + ".srs");
            var info = new FileInfo(path);
            if (info.Exists && DateTime.UtcNow - info.LastWriteTimeUtc < TimeSpan.FromDays(7))
                continue;
            try
            {
                var data = await http.GetByteArrayAsync(url);
                if (data.Length < 16 || data[0] != (byte)'S' || data[1] != (byte)'R' || data[2] != (byte)'S')
                    throw new InvalidDataException("not a sing-box rule set");
                await File.WriteAllBytesAsync(path + ".tmp", data);
                File.Move(path + ".tmp", path, overwrite: true);
                added |= !info.Exists;
                Log.Write($"rule set {tag}: {data.Length / 1024} KB");
            }
            catch (Exception e) when (e is HttpRequestException or TaskCanceledException or IOException)
            {
                Log.Write($"rule set {tag}: {e.Message}");
            }
        }
        if (!added)
            return;
        lock (gate)
        {
            if (wantUp)
                Connect();
            else if (guard)
                StartGuard();
        }
    }

    public async Task<JsonObject> UpdateSubscriptions(List<string>? only)
    {
        List<string> subs;
        lock (gate)
            subs = only ?? [.. settings.Subscriptions];
        if (subs.Count == 0)
            return Fail("Подписок нет — добавьте ссылку.");
        var got = new Dictionary<string, List<Server>>();
        var errors = new List<string>();
        foreach (var url in subs)
        {
            try
            {
                using var req = new HttpRequestMessage(HttpMethod.Get, url);
                req.Headers.UserAgent.ParseAdd("sing-box glassvpn/1.0");
                using var resp = await http.SendAsync(req);
                resp.EnsureSuccessStatusCode();
                var list = Vless.Decode(await resp.Content.ReadAsByteArrayAsync());
                foreach (var s in list)
                    s.Sub = url;
                got[url] = list;
            }
            catch (Exception e) when (e is HttpRequestException or TaskCanceledException or IOException)
            {
                errors.Add($"{Vless.SubLabel(url)}: {e.Message}");
            }
        }
        lock (gate)
        {
            if (got.Count > 0)
            {
                // replace only the servers of the subscriptions that answered
                var fresh = got.Values.SelectMany(l => l).ToList();
                var names = fresh.Select(s => s.Name).ToHashSet();
                servers = [.. fresh, .. servers.Where(s => (s.Sub is null || !got.ContainsKey(s.Sub)) && !names.Contains(s.Name))];
                Store.Save(servers);
                Log.Write($"subscriptions: {fresh.Count} servers" + (errors.Count > 0 ? $", errors: {string.Join("; ", errors)}" : ""));
                if (Current() is null)
                    ServersRemoved();
            }
            else
            {
                Log.Write($"subscriptions failed: {string.Join("; ", errors)}");
            }
        }
        if (got.Count == 0)
            return Fail("Не удалось обновить: " + string.Join("; ", errors));
        return new JsonObject
        {
            ["ok"] = true, ["servers"] = got.Values.Sum(l => l.Count),
            ["errors"] = new JsonArray([.. errors.Select(e => (JsonNode)e)]),
        };
    }

    async Task<JsonObject> Add(string text)
    {
        var manual = Vless.Lines(text).Select(Vless.Parse).OfType<Server>().ToList();
        Vless.UniqueNames(manual);
        var urls = Vless.Lines(text).Where(l => l.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
                                                || l.StartsWith("https://", StringComparison.OrdinalIgnoreCase)).ToList();
        if (manual.Count == 0 && urls.Count == 0)
            return Fail("Нет ни ссылки на подписку, ни ключей vless://");
        lock (gate)
        {
            foreach (var u in urls.Where(u => !settings.Subscriptions.Contains(u)))
                settings.Subscriptions.Add(u);
            if (manual.Count > 0)
            {
                foreach (var s in manual)
                    s.Manual = true;
                var names = manual.Select(m => m.Name).ToHashSet();
                servers = [.. servers.Where(s => !names.Contains(s.Name)), .. manual];
                Store.Save(servers);
            }
            Store.Save(settings);
        }
        if (urls.Count > 0)
        {
            var res = await UpdateSubscriptions(urls);
            res["keys"] = manual.Count;
            return res;
        }
        return new JsonObject { ["ok"] = true, ["keys"] = manual.Count };
    }

    // ------------------------------------------------------------ control --

    static JsonObject Ok() => new() { ["ok"] = true };
    static JsonObject Fail(string error) => new() { ["ok"] = false, ["error"] = error };

    public async Task<JsonObject> Handle(JsonObject req)
    {
        var cmd = (string?)req["cmd"] ?? "";
        switch (cmd)
        {
            case "add":
                return await Add((string?)req["text"] ?? "");
            case "update":
                return await UpdateSubscriptions(null);
            case "ping":
                List<Server> list;
                lock (gate)
                    list = [.. servers];
                var res = await Task.WhenAll(list.Select(async s => (s.Name, Ms: await Net.TcpLatency(s.Host, s.Port))));
                lock (gate)
                {
                    foreach (var (name, ms) in res)
                        latencies[name] = ms;
                    return ServersReply();
                }
        }
        lock (gate)
        {
            switch (cmd)
            {
                case "status":
                    return Status();
                case "connect":
                    if ((string?)req["name"] is { } n)
                    {
                        if (servers.All(s => s.Name != n))
                            return Fail("Нет такого сервера");
                        settings.Selected = n;
                    }
                    return Connect() ? Status() : Fail(message ?? "Не удалось подключиться");
                case "disconnect":
                    Disconnect();
                    return Status();
                case "servers":
                    return ServersReply();
                case "subs":
                    return new JsonObject
                    {
                        ["ok"] = true,
                        ["subs"] = new JsonArray([.. settings.Subscriptions.Select((u, i) => (JsonNode)new JsonObject
                        {
                            ["index"] = i, ["label"] = Vless.SubLabel(u), ["servers"] = servers.Count(s => s.Sub == u),
                        })]),
                    };
                case "remove-sub":
                    var idx = (int?)req["index"] ?? -1;
                    if (idx < 0 || idx >= settings.Subscriptions.Count)
                        return Fail("Нет такой подписки");
                    var url = settings.Subscriptions[idx];
                    settings.Subscriptions.RemoveAt(idx);
                    Store.Save(settings);
                    servers = [.. servers.Where(s => s.Sub != url)];
                    ServersRemoved();
                    return Ok();
                case "remove-key":
                    var key = (string?)req["name"];
                    servers = [.. servers.Where(s => !(s.Manual && s.Name == key))];
                    ServersRemoved();
                    return Ok();
                case "settings":
                    return SettingsReply();
                case "set":
                    return Set(req);
                case "logs":
                    var file = (string?)req["name"] switch
                    {
                        "sing-box" => "sing-box.log", "xray" => "xray.log", _ => "service.log",
                    };
                    var lines = Math.Clamp((int?)req["lines"] ?? 40, 1, 500);
                    try
                    {
                        using var fs = new FileStream(LogFile(file), FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                        var all = new StreamReader(fs).ReadToEnd().Split('\n');
                        return new JsonObject { ["ok"] = true, ["text"] = string.Join('\n', all.TakeLast(lines + 1)).TrimEnd() };
                    }
                    catch (IOException e)
                    {
                        return Fail(e.Message);
                    }
                default:
                    return Fail($"unknown command '{cmd}'");
            }
        }
    }

    JsonObject Set(JsonObject req)
    {
        static List<string>? List(JsonNode? n) => n is JsonArray a ? [.. a.Select(x => ((string?)x ?? "").Trim()).Where(x => x.Length > 0).Distinct()] : null;
        var rulesChanged = false;
        if (req["autoconnect"] is { } ac)
            settings.Autoconnect = (bool)ac;
        if (req["fallback_direct"] is { } fd)
        {
            settings.FallbackDirect = (bool)fd;
            if (!settings.FallbackDirect && bypass)
            {
                SetBypass(false);
                state = VpnState.Error;
            }
        }
        if (List(req["vpn_only"]) is { } vo)
        {
            settings.VpnOnly = vo;
            rulesChanged = true;
        }
        if (List(req["direct_apps"]) is { } da)
        {
            settings.DirectApps = da;
            rulesChanged = true;
        }
        Store.Save(settings);
        if (rulesChanged)
        {
            if (wantUp)
                Connect();
            else if (settings.VpnOnly.Count > 0)
                StartGuard();
            else
                StopAll();
        }
        return SettingsReply();
    }

    JsonObject SettingsReply() => new()
    {
        ["ok"] = true,
        ["autoconnect"] = settings.Autoconnect,
        ["fallback_direct"] = settings.FallbackDirect,
        ["vpn_only"] = new JsonArray([.. settings.VpnOnly.Select(x => (JsonNode)x)]),
        ["direct_apps"] = new JsonArray([.. settings.DirectApps.Select(x => (JsonNode)x)]),
    };

    JsonObject ServersReply()
    {
        var cur = Current()?.Name;
        return new JsonObject
        {
            ["ok"] = true,
            ["servers"] = new JsonArray([.. servers.Select(s => (JsonNode)new JsonObject
            {
                ["name"] = s.Name,
                ["selected"] = s.Name == cur,
                ["source"] = s.Sub is null ? "key" : Vless.SubLabel(s.Sub),
                ["sub_index"] = s.Sub is null ? null : settings.Subscriptions.IndexOf(s.Sub),
                ["transport"] = $"{s.Type}/{s.Security}",
                // null: not measured yet; -1: measured, no answer
                ["latency_ms"] = latencies.TryGetValue(s.Name, out var ms) ? ms ?? -1 : null,
            })]),
        };
    }

    JsonObject Status()
    {
        var now = Environment.TickCount64;
        if (wantUp && Net.TunBytes() is { } b)
        {
            if (lastBytes is { } l && now > l.At)
            {
                var dt = (now - l.At) / 1000.0;
                rates = ((b.Rx - l.Rx) / dt, (b.Tx - l.Tx) / dt);
            }
            lastBytes = (b.Rx, b.Tx, now);
        }
        else
        {
            rates = (0, 0);
            lastBytes = null;
        }
        return new JsonObject
        {
            ["ok"] = true,
            ["state"] = state.ToString().ToLowerInvariant(),
            ["text"] = StateText[state],
            ["server"] = Current()?.Name,
            ["probe_ms"] = probeMs,
            ["guard"] = guard,
            ["rx_bps"] = (long)rates.Rx,
            ["tx_bps"] = (long)rates.Tx,
            ["message"] = message,
            ["servers"] = servers.Count,
        };
    }
}
