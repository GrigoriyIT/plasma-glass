using System.ComponentModel;
using System.Globalization;
using System.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Storage;
using Windows.Storage.FileProperties;

namespace GlassVpn.App;

/// <summary>An installed program as the Start menu knows it.</summary>
public sealed class AppEntry
{
    public string Name { get; init; } = "";
    public string Exe { get; init; } = "";
    public string ExeName => Path.GetFileName(Exe);
}

/// <summary>A line of a rules list, with the program's own icon once it's loaded.</summary>
public sealed partial class RuleItem : INotifyPropertyChanged
{
    BitmapImage? icon;
    public string Entry { get; init; } = "";
    public string Title { get; init; } = "";
    public string Subtitle { get; init; } = "";
    public string Glyph { get; init; } = "\uECAA";
    public string? IconPath { get; init; }

    public BitmapImage? Icon
    {
        get => icon;
        set
        {
            icon = value;
            PropertyChanged?.Invoke(this, new(nameof(Icon)));
            PropertyChanged?.Invoke(this, new(nameof(GlyphVisibility)));
        }
    }

    public Visibility GlyphVisibility => icon is null ? Visibility.Visible : Visibility.Collapsed;
    public event PropertyChangedEventHandler? PropertyChanged;
}

static class AppCatalog
{
    static List<AppEntry>? cache;

    /// <summary>Programs from the Start menu shortcuts (all users and this user), one per exe.</summary>
    public static List<AppEntry> Installed()
    {
        if (cache is not null)
            return cache;
        var dirs = new[]
        {
            Environment.GetFolderPath(Environment.SpecialFolder.CommonPrograms),
            Environment.GetFolderPath(Environment.SpecialFolder.Programs),
        };
        var seen = new Dictionary<string, AppEntry>(StringComparer.OrdinalIgnoreCase);
        foreach (var dir in dirs.Where(Directory.Exists))
        {
            IEnumerable<string> links;
            try
            {
                links = Directory.EnumerateFiles(dir, "*.lnk", SearchOption.AllDirectories);
            }
            catch (UnauthorizedAccessException)
            {
                continue;
            }
            foreach (var lnk in links)
            {
                var name = Path.GetFileNameWithoutExtension(lnk);
                var exe = LinkTarget(lnk);
                if (exe is null || !exe.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) || !File.Exists(exe)
                    || name.Contains("uninstall", StringComparison.OrdinalIgnoreCase)
                    || name.Contains("удал", StringComparison.OrdinalIgnoreCase)
                    || Path.GetFileName(exe).StartsWith("unins", StringComparison.OrdinalIgnoreCase))
                    continue;
                seen.TryAdd(Path.GetFileName(exe), new AppEntry { Name = name, Exe = exe });
            }
        }
        return cache = [.. seen.Values.OrderBy(a => a.Name, StringComparer.CurrentCultureIgnoreCase)];
    }

    public static AppEntry? ByExeName(string exeName) =>
        Installed().FirstOrDefault(a => string.Equals(a.ExeName, exeName, StringComparison.OrdinalIgnoreCase));

    /// <summary>The target of a shortcut, read straight from the Shell Link format
    /// (no COM): LinkInfo's local base path. Advertised (MSI) shortcuts have none and are skipped.</summary>
    public static string? LinkTarget(string path)
    {
        try
        {
            var b = File.ReadAllBytes(path);
            if (b.Length < 0x4C || BitConverter.ToUInt32(b, 0) != 0x4C)
                return null;
            var flags = BitConverter.ToUInt32(b, 0x14);
            var pos = 0x4C;
            if ((flags & 1) != 0)                                   // HasLinkTargetIDList
                pos += 2 + BitConverter.ToUInt16(b, pos);
            if ((flags & 2) == 0)                                   // HasLinkInfo
                return null;
            var header = BitConverter.ToInt32(b, pos + 4);
            if ((BitConverter.ToInt32(b, pos + 8) & 1) == 0)        // VolumeIDAndLocalBasePath
                return null;
            if (header >= 0x24)
            {
                var start = pos + BitConverter.ToInt32(b, pos + 0x1C);
                var end = start;
                while (end + 1 < b.Length && (b[end] | b[end + 1]) != 0)
                    end += 2;
                return Encoding.Unicode.GetString(b, start, end - start);
            }
            var s = pos + BitConverter.ToInt32(b, pos + 0x10);
            var e = Array.IndexOf(b, (byte)0, s);
            return e > s ? Encoding.Latin1.GetString(b, s, e - s) : null;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException)
        {
            return null;
        }
    }

    public static async Task<BitmapImage?> Icon(string exe)
    {
        try
        {
            var file = await StorageFile.GetFileFromPathAsync(exe);
            using var thumb = await file.GetThumbnailAsync(ThumbnailMode.SingleItem, 32);
            var img = new BitmapImage();
            await img.SetSourceAsync(thumb);
            return img;
        }
        catch (Exception)
        {
            return null;   // no icon is no reason to fail
        }
    }

    /// <summary>"https://Почта.рф/x" → "xn--80a1acny.xn--p1ai"; null when it isn't a site.</summary>
    public static string? NormalizeSite(string text)
    {
        var t = text.Trim().ToLowerInvariant();
        var scheme = t.IndexOf("://", StringComparison.Ordinal);
        if (scheme >= 0)
            t = t[(scheme + 3)..];
        t = t.Split('/', '?', '#')[0].Split(':')[0].TrimStart('*', '.').TrimEnd('.');
        if (t.Length == 0 || !t.Contains('.') || t.Any(char.IsWhiteSpace))
            return null;
        try
        {
            return new IdnMapping().GetAscii(t);
        }
        catch (ArgumentException)
        {
            return null;
        }
    }

    /// <summary>"xn--80a1acny.xn--p1ai" → "почта.рф" for display.</summary>
    public static string ShowSite(string domain)
    {
        try
        {
            return new IdnMapping().GetUnicode(domain);
        }
        catch (ArgumentException)
        {
            return domain;
        }
    }

    /// <summary>A rules entry for display: a program (by exe name), a folder or path prefix, or a site.</summary>
    public static RuleItem Describe(string entry)
    {
        if (entry.Contains('\\') || entry.Contains('/') || entry.Contains(':'))
            return new RuleItem
            {
                Entry = entry, Title = Path.GetFileName(entry.TrimEnd('\\', '/')) is { Length: > 0 } n ? n : entry,
                Subtitle = entry, Glyph = "\uE8B7", IconPath = File.Exists(entry) ? entry : null,
            };
        if (entry.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) || !entry.Contains('.'))
        {
            var exe = entry.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) ? entry : entry + ".exe";
            var app = ByExeName(exe);
            return new RuleItem
            {
                Entry = entry, Title = app?.Name ?? exe, Subtitle = app is null ? "программа" : exe,
                Glyph = "\uECAA", IconPath = app?.Exe,
            };
        }
        return new RuleItem { Entry = entry, Title = ShowSite(entry), Subtitle = "сайт и его поддомены", Glyph = "\uE774" };
    }
}
