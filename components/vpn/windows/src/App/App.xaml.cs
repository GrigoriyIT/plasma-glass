using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Windows.Graphics;

namespace GlassVpn.App;

/// <summary>The tray app: an icon that mirrors the service's state and a flyout created on
/// demand. Closing the flyout frees it after a while; the VPN itself is the service's job.</summary>
public partial class App : Application
{
    public static readonly string LogFile = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GlassVPN", "app.log");
    static readonly string Assets = Path.Combine(AppContext.BaseDirectory, "Assets");

    Tray tray = null!;
    DispatcherQueue queue = null!;
    DispatcherQueueTimer timer = null!, release = null!;
    MainWindow? window;
    string? lastState, lastMessage;
    long hiddenAt;
    bool polling;

    public VpnClient Poller { get; } = new();     // status, every few seconds
    public VpnClient Actions { get; } = new();    // commands, some of them slow
    public JsonObject? Status { get; private set; }

    public App()
    {
        InitializeComponent();
        UnhandledException += (_, e) =>
        {
            Core.Log.Append(LogFile, $"unhandled: {e.Exception}");
            e.Handled = true;
        };
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(LogFile)!);
        DispatcherShutdownMode = DispatcherShutdownMode.OnExplicitShutdown;
        queue = DispatcherQueue.GetForCurrentThread();
        tray = new Tray();
        // the tray calls back from inside a window procedure: do the work on the next turn
        tray.Clicked += () => queue.TryEnqueue(Toggle);
        tray.ShowRequested += () => queue.TryEnqueue(ShowFlyout);
        tray.MenuRequested += () => queue.TryEnqueue(Menu);
        tray.ThemeChanged += () => queue.TryEnqueue(RefreshTray);
        RefreshTray();
        timer = queue.CreateTimer();
        timer.Interval = TimeSpan.FromSeconds(5);
        timer.Tick += (_, _) => _ = Poll();
        timer.Start();
        release = queue.CreateTimer();
        release.Interval = TimeSpan.FromSeconds(30);
        release.IsRepeating = false;
        release.Tick += (_, _) => ReleaseWindow();
        _ = Poll();
        if (Environment.GetCommandLineArgs().Contains("--show"))
            ShowFlyout();
    }

    public async Task Poll()
    {
        if (polling)
            return;
        polling = true;
        try
        {
            var s = await Poller.Call("status", timeoutSec: 5);
            Status = s;
            var state = s is null ? "down" : (string?)s["state"] ?? "off";
            if (state != lastState)
            {
                Announce(lastState, state);
                lastState = state;
            }
            var msg = (string?)s?["message"];
            if (msg != lastMessage)
            {
                if (msg is not null)
                    tray.Notify("Glass VPN", msg);
                lastMessage = msg;
            }
            RefreshTray();
            window?.ShowStatus(s);
        }
        finally
        {
            polling = false;
        }
    }

    void Announce(string? from, string to)
    {
        if (from is null)
            return;   // the first look after start: nothing has changed
        if (to == "bypass")
            tray.Notify("Glass VPN", "Сервер недоступен — трафик идёт напрямую");
        else if (from == "bypass" && to == "on")
            tray.Notify("Glass VPN", "Сервер снова доступен");
        else if (to == "down")
            tray.Notify("Glass VPN", "Служба Glass VPN не отвечает");
    }

    void RefreshTray()
    {
        var icon = lastState switch { null => "off", "down" => "error", var s => s };
        var theme = Tray.LightTaskbar ? "light" : "dark";
        tray.Set(Path.Combine(Assets, $"tray-{icon}-{theme}.ico"), Tooltip());
    }

    string Tooltip()
    {
        var s = Status;
        if (s is null)
            return lastState is null ? "Glass VPN" : "Glass VPN — служба не отвечает";
        var tip = $"Glass VPN — {(string?)s["text"]}";
        if ((string?)s["server"] is { } server && lastState is "on" or "bypass" or "connecting")
        {
            tip += $"\n{server}" + ((int?)s["probe_ms"] is { } ms ? $" · {ms} мс" : "");
            tip += $"\n↓ {Rate((long?)s["rx_bps"] ?? 0)}  ↑ {Rate((long?)s["tx_bps"] ?? 0)}";
        }
        return tip;
    }

    public static string Rate(long bps) => bps switch
    {
        < 1024 => $"{bps} Б/с",
        < 1024 * 1024 => $"{bps / 1024} КБ/с",
        _ => $"{bps / 1048576.0:0.0} МБ/с",
    };

    void Toggle()
    {
        if (window is { IsShown: true })
        {
            HideFlyout();
            return;
        }
        // the click on the icon has just deactivated (and hidden) the window: don't reopen it
        if (Environment.TickCount64 - hiddenAt < 400)
            return;
        ShowFlyout();
    }

    public void ShowFlyout()
    {
        release.Stop();
        window ??= new MainWindow(this);
        window.Place();
        window.ShowStatus(Status);
        window.Activate();
        timer.Interval = TimeSpan.FromSeconds(1);
        _ = window.Reload();
        _ = Poll();
    }

    public void HideFlyout()
    {
        if (window is not { IsShown: true })
            return;
        window.AppWindow.Hide();
        hiddenAt = Environment.TickCount64;
        timer.Interval = TimeSpan.FromSeconds(5);
        release.Start();   // a closed window gives its memory back; a quick reopen reuses it
    }

    void ReleaseWindow()
    {
        if (window is not { IsShown: false } w)
            return;
        w.Releasing = true;
        w.Close();
        window = null;
        GC.Collect();
    }

    async void Menu()
    {
        var up = lastState is "on" or "connecting" or "bypass";
        List<(string, int)> items = [(up ? "Отключить" : "Подключить", 1), ("Открыть Glass VPN", 2), ("", 0), ("Выход", 3)];
        switch (tray.PopupMenu(items))
        {
            case 1:
                await Actions.Call(up ? "disconnect" : "connect");
                await Poll();
                break;
            case 2:
                ShowFlyout();
                break;
            case 3:
                Quit();
                break;
        }
    }

    void Quit()
    {
        timer.Stop();
        if (window is not null)
        {
            window.Releasing = true;
            window.Close();
        }
        tray.Dispose();
        Poller.Dispose();
        Actions.Dispose();
        Exit();
    }

    public static PointInt32 Cursor()
    {
        GetCursorPos(out var p);
        return new PointInt32(p.X, p.Y);
    }

    [StructLayout(LayoutKind.Sequential)]
    struct POINT
    {
        public int X, Y;
    }

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool GetCursorPos(out POINT pt);
}
