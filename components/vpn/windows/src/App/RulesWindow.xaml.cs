using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace GlassVpn.App;

/// <summary>The two app/site lists, as a regular window (Mica): programs with their icons,
/// picked from the Start menu, a file dialog or dropped in, and sites. Applied on close —
/// every apply restarts the tunnel.</summary>
public sealed partial class RulesWindow : Window
{
    static readonly Dictionary<string, string> Hints = new()
    {
        ["vpn_only"] = "Эти программы и сайты ходят только через сервер — даже к российским сайтам. "
                       + "Когда VPN выключен или сервер недоступен, они не выходят в сеть вовсе: "
                       + "так их не увидят с российского адреса.",
        ["direct_apps"] = "Эти программы всегда ходят напрямую, мимо VPN — например, банки и госуслуги, "
                          + "которые не пускают зарубежные адреса.",
    };

    readonly App app;
    readonly Dictionary<string, ObservableCollection<RuleItem>> lists = new()
    {
        ["vpn_only"] = [], ["direct_apps"] = [],
    };
    List<RuleItem> installed = [];
    string tab = "vpn_only";
    bool dirty;

    public RulesWindow(App app)
    {
        this.app = app;
        InitializeComponent();
        SystemBackdrop = new MicaBackdrop();
        App.ApplyTheme(this);
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(TitleBar);
        var ico = Path.Combine(AppContext.BaseDirectory, "Assets", "GlassVPN.ico");
        AppWindow.SetIcon(ico);
        TitleIcon.Source = new BitmapImage(new Uri(ico));
        var scale = (Content.XamlRoot?.RasterizationScale) ?? 1.0;
        AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(660 * scale), (int)(660 * scale)));
        Closed += async (_, _) => await Apply();
        ShowTab();
        _ = Load();
    }

    async Task Load()
    {
        if (await app.Actions.Call("settings") is not { } st)
            return;
        foreach (var key in lists.Keys)
        {
            lists[key].Clear();
            if (st[key] is JsonArray a)
                foreach (var e in a.Select(x => (string?)x).OfType<string>())
                    Add(key, e, markDirty: false);
        }
        ShowTab();
    }

    async Task Apply()
    {
        if (!dirty)
            return;
        dirty = false;
        JsonArray Arr(string key) => [.. lists[key].Select(i => (JsonNode)i.Entry)];
        await app.Actions.Call("set", new JsonObject { ["vpn_only"] = Arr("vpn_only"), ["direct_apps"] = Arr("direct_apps") },
            timeoutSec: 60);
        await app.Poll();
    }

    void ShowTab()
    {
        Hint.Text = Hints[tab];
        List.ItemsSource = lists[tab];
        Empty.Visibility = lists[tab].Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    void Add(string key, string entry, bool markDirty = true)
    {
        var list = lists[key];
        if (list.Any(i => string.Equals(i.Entry, entry, StringComparison.OrdinalIgnoreCase)))
            return;
        // an entry lives in one list only
        var other = key == "vpn_only" ? "direct_apps" : "vpn_only";
        foreach (var dup in lists[other].Where(i => string.Equals(i.Entry, entry, StringComparison.OrdinalIgnoreCase)).ToList())
            lists[other].Remove(dup);
        var item = AppCatalog.Describe(entry);
        list.Add(item);
        if (item.IconPath is { } exe)
            _ = LoadIcon(item, exe);
        dirty |= markDirty;
        if (key == tab)
            Empty.Visibility = Visibility.Collapsed;
    }

    static async Task LoadIcon(RuleItem item, string exe) => item.Icon = await AppCatalog.Icon(exe);

    /// <summary>A program goes in by its exe name: it survives updates that move the folder.</summary>
    void AddProgram(string path)
    {
        if (path.EndsWith(".lnk", StringComparison.OrdinalIgnoreCase))
            path = AppCatalog.LinkTarget(path) ?? "";
        if (path.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
            Add(tab, Path.GetFileName(path));
    }

    void Tabs_SelectionChanged(SelectorBar sender, SelectorBarSelectionChangedEventArgs args)
    {
        tab = (string)sender.SelectedItem.Tag;
        ShowTab();
    }

    void Remove(IEnumerable<RuleItem> items)
    {
        foreach (var it in items.ToList())
            dirty |= lists[tab].Remove(it);
        ShowTab();
    }

    void Remove_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as FrameworkElement)?.DataContext is RuleItem it)
            Remove([it]);
    }

    void List_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Delete && List.SelectedItems.Count > 0)
        {
            Remove(List.SelectedItems.OfType<RuleItem>());
            e.Handled = true;
        }
    }

    void List_DragOver(object sender, DragEventArgs e)
    {
        if (e.DataView.Contains(StandardDataFormats.StorageItems))
            e.AcceptedOperation = DataPackageOperation.Link;
    }

    async void List_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
            return;
        foreach (var f in await e.DataView.GetStorageItemsAsync())
            AddProgram(f.Path);
    }

    async void AddFile_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker { SuggestedStartLocation = PickerLocationId.ComputerFolder };
        picker.FileTypeFilter.Add(".exe");
        picker.FileTypeFilter.Add(".lnk");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
        foreach (var f in await picker.PickMultipleFilesAsync())
            AddProgram(f.Path);
    }

    async void AddApp_Click(object sender, RoutedEventArgs e)
    {
        if (installed.Count == 0)
        {
            var apps = await Task.Run(AppCatalog.Installed);
            installed = [.. apps.Select(a => new RuleItem { Entry = a.ExeName, Title = a.Name, Subtitle = a.ExeName, IconPath = a.Exe })];
            foreach (var it in installed)
                _ = LoadIcon(it, it.IconPath!);
        }
        PickerFilter.Text = "";
        PickerList.ItemsSource = installed;
        Picker.XamlRoot = Content.XamlRoot;
        if (await Picker.ShowAsync() != ContentDialogResult.Primary)
            return;
        foreach (var it in PickerList.SelectedItems.OfType<RuleItem>())
            Add(tab, it.Entry);
    }

    void PickerFilter_TextChanged(object sender, TextChangedEventArgs e)
    {
        var q = PickerFilter.Text.Trim();
        PickerList.ItemsSource = q.Length == 0 ? installed
            : installed.Where(i => i.Title.Contains(q, StringComparison.CurrentCultureIgnoreCase)
                                   || i.Subtitle.Contains(q, StringComparison.OrdinalIgnoreCase)).ToList();
    }

    void AddSite_Click(object sender, RoutedEventArgs e) => AddSite();

    void SiteBox_KeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter)
        {
            AddSite();
            e.Handled = true;
        }
    }

    void AddSite()
    {
        if (AppCatalog.NormalizeSite(SiteBox.Text) is { } d)
        {
            Add(tab, d);
            SiteBox.Text = "";
        }
        else
        {
            Footer.Text = "Это не похоже на адрес сайта: нужен домен вроде claude.ai";
        }
    }
}
