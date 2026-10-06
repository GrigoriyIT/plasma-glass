using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Graphics;

namespace GlassVpn.App;

public sealed class ServerItem
{
    public string Name { get; init; } = "";
    public string Detail { get; init; } = "";
    public string Latency { get; init; } = "";
    public string Source { get; init; } = "";
    /// <summary>The subscription it came from; null for a key added by hand.</summary>
    public int? SubIndex { get; init; }
    public string DeleteText => SubIndex is null ? "Удалить ключ" : "Удалить подписку";
}

/// <summary>The flyout over the tray: a frosted (Desktop Acrylic) panel, no title bar,
/// hidden as soon as it loses focus — like the system's own flyouts.</summary>
public sealed partial class MainWindow : Window
{
    const int W = 384, H = 590;
    static readonly Dictionary<string, Windows.UI.Color> StateColors = new()
    {
        ["on"] = Windows.UI.Color.FromArgb(255, 0x34, 0xC7, 0x59),
        ["connecting"] = Windows.UI.Color.FromArgb(255, 0xF5, 0xB8, 0x3D),
        ["bypass"] = Windows.UI.Color.FromArgb(255, 0xFF, 0x9F, 0x0A),
        ["error"] = Windows.UI.Color.FromArgb(255, 0xFF, 0x45, 0x3A),
        ["down"] = Windows.UI.Color.FromArgb(255, 0xFF, 0x45, 0x3A),
    };

    readonly App app;
    readonly nint hwnd;
    bool loading;
    public bool Releasing { get; set; }

    public MainWindow(App app)
    {
        this.app = app;
        InitializeComponent();
        hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        SystemBackdrop = new DesktopAcrylicBackdrop();
        AppWindow.Title = "Glass VPN";
        AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets", "GlassVPN.ico"));
        AppWindow.IsShownInSwitchers = false;
        if (AppWindow.Presenter is OverlappedPresenter p)
        {
            p.IsResizable = false;
            p.IsMaximizable = false;
            p.IsMinimizable = false;
            p.IsAlwaysOnTop = true;
            p.SetBorderAndTitleBar(true, false);
        }
        // --stay (screenshots, debugging): the flyout doesn't hide when it loses focus
        var stay = Environment.GetCommandLineArgs().Contains("--stay");
        Activated += (_, e) =>
        {
            if (e.WindowActivationState == WindowActivationState.Deactivated && !stay)
                app.HideFlyout();
        };
        AppWindow.Closing += (_, e) =>
        {
            if (Releasing)
                return;
            e.Cancel = true;   // Alt+F4 hides it; the app lives in the tray
            app.HideFlyout();
        };
    }

    public bool IsShown => AppWindow.IsVisible;

    /// <summary>Above the tray: the bottom-right corner of the work area of the cursor's display.</summary>
    public void Place()
    {
        var area = DisplayArea.GetFromPoint(App.Cursor(), DisplayAreaFallback.Primary).WorkArea;
        var scale = GetDpiForWindow(hwnd) / 96.0;
        int w = (int)(W * scale), h = (int)(H * scale), m = (int)(12 * scale);
        AppWindow.MoveAndResize(new RectInt32(area.X + area.Width - w - m, area.Y + area.Height - h - m, w, h));
    }

    public void ShowStatus(JsonObject? s)
    {
        var state = s is null ? "down" : (string?)s["state"] ?? "off";
        var text = (string?)s?["text"] ?? "";
        StateText.Text = s is null ? "Служба не отвечает" : text.Length > 0 ? char.ToUpper(text[0]) + text[1..] : "";
        var server = (string?)s?["server"];
        var ms = (int?)s?["probe_ms"];
        DetailText.Text = s is null ? "Служба Glass VPN не запущена"
            : server is null ? "Нет серверов — добавьте подписку"
            : state == "off" && (bool?)s["guard"] == true ? "Сайты «только через VPN» закрыты"
            : state is "on" && ms is not null ? $"{server} · {ms} мс"
            : server;
        var up = state is "on" or "bypass" or "connecting";
        RxText.Text = up ? App.Rate((long?)s?["rx_bps"] ?? 0) : "—";
        TxText.Text = up ? App.Rate((long?)s?["tx_bps"] ?? 0) : "—";
        if (StateColors.TryGetValue(state, out var c))
        {
            PowerButton.Background = new SolidColorBrush(c);
            PowerIcon.Foreground = new SolidColorBrush(Colors.White);
            StateText.Foreground = new SolidColorBrush(c);
        }
        else
        {
            PowerButton.ClearValue(Control.BackgroundProperty);
            PowerIcon.ClearValue(FontIcon.ForegroundProperty);
            StateText.ClearValue(TextBlock.ForegroundProperty);
        }
    }

    /// <summary>Servers and settings, read when the window opens.</summary>
    public async Task Reload()
    {
        FillServers(await app.Actions.Call("servers"));
        if (await app.Actions.Call("settings") is { } st)
        {
            loading = true;
            AutoSwitch.IsOn = (bool?)st["autoconnect"] ?? true;
            FallbackSwitch.IsOn = (bool?)st["fallback_direct"] ?? true;
            VpnOnlyBox.Text = Lines(st["vpn_only"]);
            DirectBox.Text = Lines(st["direct_apps"]);
            loading = false;
        }
    }

    static string Lines(JsonNode? n) => n is JsonArray a ? string.Join("\r", a.Select(x => (string?)x)) : "";

    void FillServers(JsonObject? sv)
    {
        if (sv?["servers"] is not JsonArray arr)
            return;
        loading = true;
        var list = arr.OfType<JsonObject>().ToList();
        ServerList.ItemsSource = list.Select(o => new ServerItem
        {
            Name = (string?)o["name"] ?? "",
            Detail = ((string?)o["source"] is "key" or null ? "ключ" : (string?)o["source"]) + " · " + (string?)o["transport"],
            Latency = (int?)o["latency_ms"] switch { null => "", < 0 => "нет ответа", var ms => $"{ms} мс" },
            Source = (string?)o["source"] ?? "",
            SubIndex = (int?)o["sub_index"],
        }).ToList();
        ServerList.SelectedIndex = list.FindIndex(o => (bool?)o["selected"] == true);
        EmptyText.Visibility = list.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        loading = false;
    }

    void ShowPanel(FrameworkElement panel)
    {
        foreach (var p in new FrameworkElement[] { ServersPanel, AddPanel, RulesPanel })
            p.Visibility = p == panel ? Visibility.Visible : Visibility.Collapsed;
    }

    void ShowInfo(InfoBarSeverity severity, string text)
    {
        Info.Severity = severity;
        Info.Message = text;
        Info.IsOpen = true;
    }

    static string? Error(JsonObject? r) => r is null ? "Служба не отвечает" : (bool?)r["ok"] == true ? null : (string?)r["error"] ?? "Ошибка";

    async void Power_Click(object sender, RoutedEventArgs e)
    {
        var state = (string?)app.Status?["state"];
        PowerButton.IsEnabled = false;
        var r = await app.Actions.Call(state is null or "off" or "error" ? "connect" : "disconnect");
        if (Error(r) is { } err)
            ShowInfo(InfoBarSeverity.Error, err);
        await app.Poll();
        PowerButton.IsEnabled = true;
    }

    async void ServerList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (loading || ServerList.SelectedItem is not ServerItem it)
            return;
        var r = await app.Actions.Call("connect", new JsonObject { ["name"] = it.Name });
        if (Error(r) is { } err)
            ShowInfo(InfoBarSeverity.Error, err);
        await app.Poll();
    }

    async void Delete_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as FrameworkElement)?.DataContext is ServerItem it)
            await Delete(it);
    }

    async void ServerList_KeyDown(object sender, Microsoft.UI.Xaml.Input.KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Delete && ServerList.SelectedItem is ServerItem it)
        {
            e.Handled = true;
            await Delete(it);
        }
    }

    async Task Delete(ServerItem it)
    {
        var all = ServerList.ItemsSource as List<ServerItem> ?? [];
        var question = it.SubIndex is null
            ? $"Удалить ключ «{it.Name}»?"
            : $"Удалить подписку {it.Source} и её серверы ({all.Count(x => x.SubIndex == it.SubIndex)})?";
        var dialog = new ContentDialog
        {
            XamlRoot = Content.XamlRoot, Title = "Glass VPN", Content = question,
            PrimaryButtonText = "Удалить", CloseButtonText = "Отмена", DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
            return;
        var r = it.SubIndex is { } i
            ? await app.Actions.Call("remove-sub", new JsonObject { ["index"] = i })
            : await app.Actions.Call("remove-key", new JsonObject { ["name"] = it.Name });
        if (Error(r) is { } err)
            ShowInfo(InfoBarSeverity.Error, err);
        await Reload();
        await app.Poll();
    }

    async void Ping_Click(object sender, RoutedEventArgs e)
    {
        PingButton.IsEnabled = false;
        FillServers(await app.Actions.Call("ping"));
        PingButton.IsEnabled = true;
    }

    void Add_Click(object sender, RoutedEventArgs e)
    {
        ShowPanel(AddPanel);
        AddBox.Focus(FocusState.Programmatic);
    }

    void Rules_Click(object sender, RoutedEventArgs e) => ShowPanel(RulesPanel);

    void Back_Click(object sender, RoutedEventArgs e) => ShowPanel(ServersPanel);

    async void AddConfirm_Click(object sender, RoutedEventArgs e)
    {
        AddConfirm.IsEnabled = false;
        var r = await app.Actions.Call("add", new JsonObject { ["text"] = AddBox.Text }, timeoutSec: 90);
        AddConfirm.IsEnabled = true;
        if (Error(r) is { } err)
        {
            ShowInfo(InfoBarSeverity.Error, err);
            return;
        }
        AddBox.Text = "";
        var n = (int?)r!["servers"] ?? 0;
        var keys = (int?)r["keys"] ?? 0;
        var errors = r["errors"] is JsonArray a && a.Count > 0 ? " Ошибки: " + string.Join("; ", a.Select(x => (string?)x)) : "";
        ShowInfo(errors.Length > 0 ? InfoBarSeverity.Warning : InfoBarSeverity.Success,
            $"Добавлено: серверов {n + keys}.{errors}");
        ShowPanel(ServersPanel);
        await Reload();
    }

    async void Update_Click(object sender, RoutedEventArgs e)
    {
        UpdateButton.IsEnabled = false;
        var r = await app.Actions.Call("update", timeoutSec: 90);
        UpdateButton.IsEnabled = true;
        if (Error(r) is { } err)
            ShowInfo(InfoBarSeverity.Error, err);
        else
            ShowInfo(InfoBarSeverity.Success, $"Подписки обновлены, серверов: {(int?)r!["servers"]}");
        await Reload();
    }

    async void RulesSave_Click(object sender, RoutedEventArgs e)
    {
        static JsonArray List(string text) =>
            [.. text.Split('\r', '\n').Select(x => x.Trim()).Where(x => x.Length > 0).Select(x => (JsonNode)x)];
        var r = await app.Actions.Call("set", new JsonObject
        {
            ["vpn_only"] = List(VpnOnlyBox.Text), ["direct_apps"] = List(DirectBox.Text),
        }, timeoutSec: 60);
        if (Error(r) is { } err)
        {
            ShowInfo(InfoBarSeverity.Error, err);
            return;
        }
        ShowInfo(InfoBarSeverity.Success, "Правила сохранены");
        ShowPanel(ServersPanel);
        await app.Poll();
    }

    async void Auto_Toggled(object sender, RoutedEventArgs e)
    {
        if (!loading)
            await app.Actions.Call("set", new JsonObject { ["autoconnect"] = AutoSwitch.IsOn });
    }

    async void Fallback_Toggled(object sender, RoutedEventArgs e)
    {
        if (!loading)
            await app.Actions.Call("set", new JsonObject { ["fallback_direct"] = FallbackSwitch.IsOn });
    }

    [LibraryImport("user32.dll")]
    private static partial uint GetDpiForWindow(nint hwnd);
}
