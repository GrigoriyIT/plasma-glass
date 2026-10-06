using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace GlassVpn.Core;

public sealed class Server
{
    public string Name { get; set; } = "";
    public string Uuid { get; set; } = "";
    public string Host { get; set; } = "";
    public int Port { get; set; } = 443;
    public string Type { get; set; } = "tcp";
    public string Security { get; set; } = "none";
    public string Sni { get; set; } = "";
    public string Fp { get; set; } = "";
    public string Pbk { get; set; } = "";
    public string Sid { get; set; } = "";
    public string Flow { get; set; } = "";
    public string Path { get; set; } = "";
    public string HostHeader { get; set; } = "";
    public string ServiceName { get; set; } = "";
    public string Alpn { get; set; } = "";
    public string Encryption { get; set; } = "none";
    public string Mode { get; set; } = "";
    public string Spx { get; set; } = "";
    /// <summary>Subscription URL the server came from; null for a key added by hand.</summary>
    public string? Sub { get; set; }
    public bool Manual { get; set; }
}

public sealed class Settings
{
    public List<string> Subscriptions { get; set; } = [];
    public string? Selected { get; set; }
    public bool Autoconnect { get; set; } = true;
    /// <summary>Server unreachable: let traffic go direct instead of into a dead tunnel.</summary>
    public bool FallbackDirect { get; set; } = true;
    /// <summary>Apps and sites that must never leave with the local address.</summary>
    public List<string> VpnOnly { get; set; } = [.. Defaults.VpnOnly];
    public List<string> DirectApps { get; set; } = [];
}

public static class Defaults
{
    // Anthropic, OpenAI and the rest refuse Russian IPs (403 unsupported_country),
    // so their apps and sites never fall back to the direct route
    public static readonly string[] VpnOnly =
    [
        "claude.exe", "ChatGPT.exe", "codex.exe",          // matched case-insensitively
        "anthropic.com", "claude.ai", "claude.com", "claudeusercontent.com",
        "openai.com", "chatgpt.com", "oaistatic.com", "oaiusercontent.com",
        "githubcopilot.com", "copilot.microsoft.com", "x.ai", "grok.com",
        "gemini.google.com", "generativelanguage.googleapis.com", "elevenlabs.io",
        "notion.so", "notion.com",
    ];
}

[JsonSourceGenerationOptions(WriteIndented = true, PropertyNamingPolicy = JsonKnownNamingPolicy.SnakeCaseLower,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull)]
[JsonSerializable(typeof(Settings))]
[JsonSerializable(typeof(List<Server>))]
internal partial class ModelJson : JsonSerializerContext;

public static class Paths
{
    public static readonly string InstallDir = AppContext.BaseDirectory;
    public static readonly string Data = Environment.GetEnvironmentVariable("GLASSVPN_DATA")
        ?? System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "GlassVPN");
    public static readonly string Logs = System.IO.Path.Combine(Data, "logs");
    public static readonly string Run = System.IO.Path.Combine(Data, "run");
    public static readonly string Settings = System.IO.Path.Combine(Data, "settings.dat");
    public static readonly string Servers = System.IO.Path.Combine(Data, "servers.dat");
    public static readonly string SingBox = Environment.GetEnvironmentVariable("GLASSVPN_BIN") is { } b
        ? System.IO.Path.Combine(b, "sing-box.exe") : System.IO.Path.Combine(InstallDir, "sing-box.exe");
    public static readonly string Xray = Environment.GetEnvironmentVariable("GLASSVPN_BIN") is { } b2
        ? System.IO.Path.Combine(b2, "xray.exe") : System.IO.Path.Combine(InstallDir, "xray.exe");
    public const string Pipe = "GlassVPN";

    /// <summary>The data folder holds keys and subscription tokens: SYSTEM and Administrators only.</summary>
    public static void EnsureDataDir()
    {
        var dir = new DirectoryInfo(Data);
        if (!dir.Exists)
            dir.Create();
        var acl = new DirectorySecurity();
        acl.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        foreach (var sid in new[] { WellKnownSidType.LocalSystemSid, WellKnownSidType.BuiltinAdministratorsSid })
            acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(sid, null), FileSystemRights.FullControl,
                InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None,
                AccessControlType.Allow));
        dir.SetAccessControl(acl);
        Directory.CreateDirectory(Logs);
        Directory.CreateDirectory(Run);
    }
}

/// <summary>Settings and servers on disk: JSON sealed with DPAPI (machine scope), so a copy
/// of the file — or the disk read from the other OS — doesn't give the keys away.</summary>
public static class Store
{
    static readonly byte[] Entropy = "GlassVPN store v1"u8.ToArray();
    static readonly ModelJson Json = new(new JsonSerializerOptions(ModelJson.Default.Options)
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    });

    public static Settings LoadSettings() => Load(Paths.Settings, Json.Settings) ?? new Settings();
    public static List<Server> LoadServers() => Load(Paths.Servers, Json.ListServer) ?? [];
    public static void Save(Settings s) => Save(Paths.Settings, JsonSerializer.SerializeToUtf8Bytes(s, Json.Settings));
    public static void Save(List<Server> s) => Save(Paths.Servers, JsonSerializer.SerializeToUtf8Bytes(s, Json.ListServer));

    static T? Load<T>(string path, System.Text.Json.Serialization.Metadata.JsonTypeInfo<T> info) where T : class
    {
        try
        {
            var raw = ProtectedData.Unprotect(File.ReadAllBytes(path), Entropy, DataProtectionScope.LocalMachine);
            return JsonSerializer.Deserialize(raw, info);
        }
        catch (Exception e) when (e is IOException or CryptographicException or JsonException or UnauthorizedAccessException)
        {
            if (e is not FileNotFoundException)
                Log.Write($"store: {System.IO.Path.GetFileName(path)} unreadable: {e.Message}");
            return null;
        }
    }

    static void Save(string path, byte[] json)
    {
        var tmp = path + ".tmp";
        File.WriteAllBytes(tmp, ProtectedData.Protect(json, Entropy, DataProtectionScope.LocalMachine));
        File.Move(tmp, path, overwrite: true);
    }

    public static string Dump(object o) => o switch
    {
        Settings s => Encoding.UTF8.GetString(JsonSerializer.SerializeToUtf8Bytes(s, Json.Settings)),
        List<Server> l => Encoding.UTF8.GetString(JsonSerializer.SerializeToUtf8Bytes(l, Json.ListServer)),
        _ => "",
    };
}

/// <summary>One log file per component (the service and each core), rotated at 1 MB with one
/// old copy kept. The cores write to stdout and the service files their lines, so no log can
/// grow without bound behind a handle it can't rotate.</summary>
public static class Log
{
    static readonly Lock Gate = new();
    static readonly Dictionary<string, long> Sizes = [];
    public static string File { get; set; } = System.IO.Path.Combine(Paths.Logs, "service.log");
    public static bool Console { get; set; }
    const long Max = 1 << 20;

    public static void Write(string msg) => Append(File, msg, Console);

    public static void Append(string path, string msg, bool echo = false)
    {
        var line = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} {msg}{Environment.NewLine}";
        lock (Gate)
        {
            if (echo)
                System.Console.Write(line);
            try
            {
                if (!Sizes.TryGetValue(path, out var size))
                    size = new FileInfo(path) is { Exists: true } f ? f.Length : 0;
                if (size > Max)
                {
                    System.IO.File.Move(path, path + ".1", overwrite: true);
                    size = 0;
                }
                System.IO.File.AppendAllText(path, line);
                Sizes[path] = size + line.Length;
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }
}
