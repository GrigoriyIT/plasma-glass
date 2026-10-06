using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using GlassVpn.Core;

// glassvpnctl: talks to the Glass VPN service over its control pipe.
Console.OutputEncoding = new UTF8Encoding(false);

const string Usage = """
    glassvpnctl status | connect [name] | disconnect | servers | ping
                subs | add <url-or-vless> (- reads stdin) | update | remove-sub <index> | remove-key <name>
                settings | set autoconnect|fallback_direct <true|false> | set vpn_only|direct_apps <a,b,c>
                logs [service|sing-box|xray] [lines]
    """;

if (args.Length == 0 || args[0] is "-h" or "--help" or "help")
{
    Console.WriteLine(Usage);
    return 0;
}

var req = new JsonObject { ["cmd"] = args[0] };
switch (args)
{
    case ["connect", var name]:
        req["name"] = name;
        break;
    case ["add", "-"]:
        req["text"] = Console.In.ReadToEnd();
        break;
    case ["add", .. var rest]:
        req["text"] = string.Join('\n', rest);
        break;
    case ["remove-sub", var i]:
        req["index"] = int.Parse(i);
        break;
    case ["remove-key", var key]:
        req["name"] = key;
        break;
    case ["set", "autoconnect" or "fallback_direct", var v]:
        req[args[1]] = bool.Parse(v);
        break;
    case ["set", "vpn_only" or "direct_apps", var v]:
        req[args[1]] = new JsonArray([.. v.Split(',').Select(x => (JsonNode)x.Trim())]);
        break;
    case ["set", ..]:
        Console.Error.WriteLine(Usage);
        return 2;
    case ["logs", .. var l]:
        if (l.Length > 0)
            req["name"] = l[0];
        if (l.Length > 1)
            req["lines"] = int.Parse(l[1]);
        break;
}

try
{
    using var c = new IpcClient();
    var reply = await c.CallAsync(req);
    if (reply["text"] is JsonValue t && args[0] == "logs")
        Console.WriteLine((string?)t);
    else
        Console.WriteLine(reply.ToJsonString(new JsonSerializerOptions
        {
            WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        }));
    return (bool?)reply["ok"] == true ? 0 : 1;
}
catch (Exception e) when (e is TimeoutException or IOException or UnauthorizedAccessException)
{
    Console.Error.WriteLine($"Glass VPN service: {e.Message}");
    return 3;
}
