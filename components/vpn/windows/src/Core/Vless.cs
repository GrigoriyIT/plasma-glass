using System.Text;

namespace GlassVpn.Core;

public static class Vless
{
    /// <summary>vless://uuid@host:port?params#name → Server, or null.</summary>
    public static Server? Parse(string uri)
    {
        uri = uri.Trim();
        if (!uri.StartsWith("vless://", StringComparison.OrdinalIgnoreCase)
            || !Uri.TryCreate(uri, UriKind.Absolute, out var u) || string.IsNullOrEmpty(u.UserInfo) || u.Host.Length == 0)
            return null;
        var q = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var kv in u.Query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var i = kv.IndexOf('=');
            var k = UnescapeQuery(i < 0 ? kv : kv[..i]);
            q.TryAdd(k, i < 0 ? "" : UnescapeQuery(kv[(i + 1)..]));
        }
        string Q(string k, string def = "") => q.TryGetValue(k, out var v) && v.Length > 0 ? v : def;
        var port = u.Port > 0 ? u.Port : 443;
        var name = Unescape(u.Fragment.TrimStart('#'));
        return new Server
        {
            Name = name.Length > 0 ? name : $"{u.DnsSafeHost}:{port}",
            Uuid = Unescape(u.UserInfo),
            Host = u.DnsSafeHost,
            Port = port,
            Type = Q("type", "tcp"),
            Security = Q("security", "none"),
            Sni = Q("sni", Q("host")),
            Fp = Q("fp"),
            Pbk = Q("pbk"),
            Sid = Q("sid"),
            Flow = Q("flow"),
            Path = Q("path"),
            HostHeader = Q("host"),
            ServiceName = Q("serviceName"),
            Alpn = Q("alpn"),
            Encryption = Q("encryption", "none"),
            Mode = Q("mode"),
            Spx = Q("spx"),
        };
    }

    static string Unescape(string s) => Uri.UnescapeDataString(s);
    static string UnescapeQuery(string s) => Uri.UnescapeDataString(s.Replace('+', ' '));

    /// <summary>A subscription body: a plain or base64 list of links, one per line.</summary>
    public static List<Server> Decode(byte[] body)
    {
        var text = Encoding.UTF8.GetString(body).Trim();
        if (!text.Contains("://"))
        {
            try
            {
                var b64 = text.Replace('-', '+').Replace('_', '/').Replace("\r", "").Replace("\n", "");
                b64 += new string('=', (4 - b64.Length % 4) % 4);
                text = Encoding.UTF8.GetString(Convert.FromBase64String(b64));
            }
            catch (FormatException) { }
        }
        var list = Lines(text).Select(Parse).OfType<Server>().ToList();
        UniqueNames(list);
        return list;
    }

    /// <summary>Links in pasted text: one per line, several on a line, or glued together — no link
    /// contains whitespace. Any line break counts (WinUI text boxes use a bare \r).</summary>
    public static IEnumerable<string> Lines(string text) =>
        // links copied in a row sometimes come glued together: every vless:// starts a new one
        System.Text.RegularExpressions.Regex.Replace(text, "(?<=\\S)(?=vless://)", "\n",
                System.Text.RegularExpressions.RegexOptions.IgnoreCase)
            .Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    /// <summary>Servers are told apart by name: "Germany", "Germany 2", …</summary>
    public static void UniqueNames(IEnumerable<Server> servers, IEnumerable<string>? taken = null)
    {
        var seen = new HashSet<string>(taken ?? [], StringComparer.Ordinal);
        foreach (var s in servers)
        {
            var name = s.Name;
            for (var i = 2; !seen.Add(name); i++)
                name = $"{s.Name} {i}";
            s.Name = name;
        }
    }

    /// <summary>Host plus a short tail of the path; the token in the URL stays hidden.</summary>
    public static string SubLabel(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var u))
            return "?";
        var tail = u.AbsolutePath.TrimEnd('/');
        tail = tail[(tail.LastIndexOf('/') + 1)..];
        return u.Host + (tail.Length > 0 ? "/…" + tail[^Math.Min(4, tail.Length)..] : "");
    }
}
