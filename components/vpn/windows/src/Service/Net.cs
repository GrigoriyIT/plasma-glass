using System.Diagnostics;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Text;
using GlassVpn.Core;

namespace GlassVpn.Service;

static class Net
{
    /// <summary>The physical network the machine is on: when it changes (Wi-Fi ↔ Ethernet,
    /// another network, LTE) Xray's long-lived links hang on the old one.</summary>
    public sealed record Physical(string Id, string Name, string Gateway, string Address, string? Dns)
    {
        public string Signature => $"{Id}|{Gateway}|{Address}";
    }

    public static Physical? Default()
    {
        NetworkInterface[] all;
        try
        {
            all = NetworkInterface.GetAllNetworkInterfaces();
        }
        catch (NetworkInformationException)
        {
            return null;
        }
        Physical? best = null;
        var bestRank = int.MaxValue;
        foreach (var nic in all)
        {
            if (nic.OperationalStatus != OperationalStatus.Up
                || nic.NetworkInterfaceType is NetworkInterfaceType.Loopback or NetworkInterfaceType.Tunnel
                || nic.Name == Configs.Tun || nic.Description.Contains("Wintun", StringComparison.OrdinalIgnoreCase))
                continue;
            var ip = nic.GetIPProperties();
            var gw = ip.GatewayAddresses.Select(g => g.Address)
                .FirstOrDefault(a => a.AddressFamily == AddressFamily.InterNetwork && !a.Equals(IPAddress.Any));
            var addr = ip.UnicastAddresses.Select(u => u.Address).FirstOrDefault(a => a.AddressFamily == AddressFamily.InterNetwork);
            if (gw is null || addr is null)
                continue;
            var dns = ip.DnsAddresses.FirstOrDefault(a => a.AddressFamily == AddressFamily.InterNetwork
                                                          && !a.ToString().StartsWith("198.18.", StringComparison.Ordinal));
            var rank = nic.NetworkInterfaceType switch
            {
                NetworkInterfaceType.Ethernet or NetworkInterfaceType.GigabitEthernet => 0,
                NetworkInterfaceType.Wireless80211 => 1,
                _ => 2,
            };
            if (rank < bestRank)
            {
                bestRank = rank;
                best = new Physical(nic.Id, nic.Name, gw.ToString(), addr.ToString(), dns?.ToString());
            }
        }
        return best;
    }

    /// <summary>Byte counters of the tunnel adapter, or null while it is down.</summary>
    public static (long Rx, long Tx)? TunBytes()
    {
        try
        {
            var nic = NetworkInterface.GetAllNetworkInterfaces().FirstOrDefault(n => n.Name == Configs.Tun);
            if (nic is null)
                return null;
            var st = nic.GetIPStatistics();
            return (st.BytesReceived, st.BytesSent);
        }
        catch (NetworkInformationException)
        {
            return null;
        }
    }

    public static List<string> Resolve(string host)
    {
        if (IPAddress.TryParse(host, out var ip))
            return ip.AddressFamily == AddressFamily.InterNetwork ? [ip.ToString()] : [];
        try
        {
            using var cts = new CancellationTokenSource(4000);
            var addrs = Dns.GetHostAddressesAsync(host, AddressFamily.InterNetwork, cts.Token).GetAwaiter().GetResult();
            return [.. addrs.Select(a => a.ToString()).Distinct().Order()];
        }
        catch (Exception e) when (e is SocketException or OperationCanceledException or ArgumentException)
        {
            return [];
        }
    }

    public static async Task<int?> TcpLatency(string host, int port, int timeoutMs = 3000)
    {
        var sw = Stopwatch.StartNew();
        try
        {
            using var cts = new CancellationTokenSource(timeoutMs);
            using var c = new TcpClient();
            await c.ConnectAsync(host, port, cts.Token);
            return (int)sw.ElapsedMilliseconds;
        }
        catch (Exception e) when (e is SocketException or OperationCanceledException)
        {
            return null;
        }
    }

    /// <summary>GET http://ProbeHost/generate_204 through Xray's probe port (always the server);
    /// milliseconds or null. A real request: Xray answers the SOCKS CONNECT before it has
    /// reached the server, so a bare CONNECT proves nothing.</summary>
    public static async Task<int?> Probe(Ports p, int timeoutMs = 4000)
    {
        var sw = Stopwatch.StartNew();
        try
        {
            using var cts = new CancellationTokenSource(timeoutMs);
            var ct = cts.Token;
            using var c = new TcpClient();
            await c.ConnectAsync(IPAddress.Loopback, p.Probe, ct);
            var s = c.GetStream();
            await s.WriteAsync(new byte[] { 5, 1, 2 }, ct);                    // username/password only
            if (!(await Read(s, 2, ct)).AsSpan().SequenceEqual(new byte[] { 5, 2 }))
                return null;
            var u = Encoding.ASCII.GetBytes(p.User);
            var pw = Encoding.ASCII.GetBytes(p.Pass);
            await s.WriteAsync((byte[])[1, (byte)u.Length, .. u, (byte)pw.Length, .. pw], ct);
            if ((await Read(s, 2, ct))[1] != 0)
                return null;
            var h = Encoding.ASCII.GetBytes(Configs.ProbeHost);
            await s.WriteAsync((byte[])[5, 1, 0, 3, (byte)h.Length, .. h, 0, 80], ct);
            var head = await Read(s, 4, ct);
            if (head[1] != 0)
                return null;
            var rest = head[3] switch
            {
                1 => 4 + 2,
                4 => 16 + 2,
                _ => (await Read(s, 1, ct))[0] + 2,
            };
            await Read(s, rest, ct);
            await s.WriteAsync(Encoding.ASCII.GetBytes(
                $"GET /generate_204 HTTP/1.1\r\nHost: {Configs.ProbeHost}\r\nConnection: close\r\n\r\n"), ct);
            var status = await Read(s, 12, ct);
            return status.AsSpan().StartsWith("HTTP/"u8) ? (int)sw.ElapsedMilliseconds : null;
        }
        catch (Exception e) when (e is IOException or SocketException or OperationCanceledException)
        {
            return null;
        }
    }

    static async Task<byte[]> Read(NetworkStream s, int n, CancellationToken ct)
    {
        var b = new byte[n];
        await s.ReadExactlyAsync(b, ct);
        return b;
    }
}
