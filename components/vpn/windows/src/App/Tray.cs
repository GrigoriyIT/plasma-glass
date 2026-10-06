using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using Microsoft.Win32;

namespace GlassVpn.App;

/// <summary>The notification-area icon: a hidden Win32 window receives its clicks.
/// WinUI has no tray API, and this is all it takes — no extra library.</summary>
sealed unsafe partial class Tray : IDisposable
{
    const string ClassName = "GlassVPN.Tray";
    const uint WM_TRAY = 0x8000 + 1, WM_SHOW = 0x8000 + 2;
    const uint WM_SETTINGCHANGE = 0x001A, WM_CONTEXTMENU = 0x007B, NIN_SELECT = 0x0400, NIN_KEYSELECT = 0x0401;
    const uint NIM_ADD = 0, NIM_MODIFY = 1, NIM_DELETE = 2, NIM_SETVERSION = 4;
    const uint NIF_MESSAGE = 1, NIF_ICON = 2, NIF_TIP = 4, NIF_INFO = 0x10, NIF_SHOWTIP = 0x80;

    static Tray? instance;
    readonly nint hwnd;
    readonly uint taskbarCreated;
    readonly Dictionary<string, nint> icons = [];
    string iconPath = "";
    string tip = "Glass VPN";

    public event Action? Clicked;
    public event Action? MenuRequested;
    public event Action? ShowRequested;
    public event Action? ThemeChanged;

    public Tray()
    {
        instance = this;
        var hinst = GetModuleHandleW(null);
        fixed (char* cls = ClassName)
        {
            var wc = new WNDCLASSEXW
            {
                cbSize = (uint)sizeof(WNDCLASSEXW), lpfnWndProc = &WndProc, hInstance = hinst, lpszClassName = cls,
            };
            RegisterClassExW(&wc);
            // a real (never shown) top-level window: message-only ones miss the TaskbarCreated broadcast
            hwnd = CreateWindowExW(0, cls, cls, 0, 0, 0, 0, 0, 0, 0, hinst, 0);
        }
        taskbarCreated = RegisterWindowMessageW("TaskbarCreated");
    }

    public static bool LightTaskbar =>
        Registry.GetValue(@"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            "SystemUsesLightTheme", 0) is int v && v == 1;

    /// <summary>Asks the running instance to open its window (a second launch).</summary>
    public static void SignalExisting()
    {
        var h = FindWindowW(ClassName, null);
        if (h != 0)
        {
            AllowSetForegroundWindow(-1);
            PostMessageW(h, WM_SHOW, 0, 0);
        }
    }

    public void Set(string iconFile, string tooltip)
    {
        var first = iconPath.Length == 0;
        if (iconFile == iconPath && tooltip == tip)
            return;
        iconPath = iconFile;
        tip = tooltip;
        Apply(first ? NIM_ADD : NIM_MODIFY);
    }

    void Apply(uint op)
    {
        var d = Data(NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP);
        d.hIcon = Icon(iconPath);
        Copy(d.szTip, 128, tip);
        if (!Shell_NotifyIconW(op, &d) && op == NIM_MODIFY)
            Shell_NotifyIconW(NIM_ADD, &d);       // explorer lost it
        if (op == NIM_ADD)
        {
            d.uVersion = 4;
            Shell_NotifyIconW(NIM_SETVERSION, &d);
        }
    }

    /// <summary>A Windows notification from the tray icon (a toast on Windows 11).</summary>
    public void Notify(string title, string text)
    {
        var d = Data(NIF_INFO);
        Copy(d.szInfoTitle, 64, title);
        Copy(d.szInfo, 256, text);
        d.dwInfoFlags = 0x80;   // NIIF_RESPECT_QUIET_TIME
        Shell_NotifyIconW(NIM_MODIFY, &d);
    }

    /// <summary>A native context menu at the cursor; returns the chosen id or 0.</summary>
    public int PopupMenu(IReadOnlyList<(string Text, int Id)> items)
    {
        var menu = CreatePopupMenu();
        foreach (var (text, id) in items)
            AppendMenuW(menu, id == 0 ? 0x800u : 0u, (nuint)id, id == 0 ? null : text);   // MF_SEPARATOR
        GetCursorPos(out var pt);
        SetForegroundWindow(hwnd);   // else the menu doesn't close when clicking elsewhere
        var cmd = TrackPopupMenuEx(menu, 0x0100 | 0x0020 | 0x0002, pt.X, pt.Y, hwnd, 0);   // RETURNCMD|BOTTOMALIGN|RIGHTBUTTON
        DestroyMenu(menu);
        return cmd;
    }

    NOTIFYICONDATAW Data(uint flags) => new()
    {
        cbSize = (uint)sizeof(NOTIFYICONDATAW), hWnd = hwnd, uID = 1, uFlags = flags, uCallbackMessage = WM_TRAY,
    };

    nint Icon(string path)
    {
        if (!icons.TryGetValue(path, out var h))
        {
            var size = GetSystemMetrics(49);   // SM_CXSMICON, already scaled for the DPI
            h = LoadImageW(0, path, 1, size, size, 0x10);   // IMAGE_ICON, LR_LOADFROMFILE
            icons[path] = h;
        }
        return h;
    }

    static void Copy(char* dst, int cap, string s)
    {
        var n = Math.Min(s.Length, cap - 1);
        s.AsSpan(0, n).CopyTo(new Span<char>(dst, cap));
        dst[n] = '\0';
    }

    [UnmanagedCallersOnly(CallConvs = [typeof(CallConvStdcall)])]
    static nint WndProc(nint hwnd, uint msg, nint w, nint l)
    {
        var t = instance;
        if (t is null)
            return DefWindowProcW(hwnd, msg, w, l);
        try
        {
            if (msg == WM_TRAY)
            {
                switch ((uint)(l & 0xFFFF))
                {
                    // version 4 sends WM_LBUTTONUP and then NIN_SELECT for one click: answering
                    // both opened the flyout and closed it again at once
                    case NIN_SELECT or NIN_KEYSELECT:
                        t.Clicked?.Invoke();
                        break;
                    case WM_CONTEXTMENU:
                        t.MenuRequested?.Invoke();
                        break;
                }
                return 0;
            }
            if (msg == WM_SHOW)
            {
                t.ShowRequested?.Invoke();
                return 0;
            }
            if (msg == t.taskbarCreated && t.iconPath.Length > 0)
            {
                t.Apply(NIM_ADD);   // explorer restarted
                return 0;
            }
            if (msg == WM_SETTINGCHANGE && l != 0 && new string((char*)l) == "ImmersiveColorSet")
                t.ThemeChanged?.Invoke();
        }
        catch (Exception e)
        {
            Core.Log.Append(App.LogFile, $"tray: {e}");
        }
        return DefWindowProcW(hwnd, msg, w, l);
    }

    public void Dispose()
    {
        var d = Data(0);
        Shell_NotifyIconW(NIM_DELETE, &d);
        foreach (var h in icons.Values)
            DestroyIcon(h);
        icons.Clear();
        DestroyWindow(hwnd);
        instance = null;
    }

    // ---------------------------------------------------------------- Win32 --

    [StructLayout(LayoutKind.Sequential)]
    struct WNDCLASSEXW
    {
        public uint cbSize, style;
        public delegate* unmanaged[Stdcall]<nint, uint, nint, nint, nint> lpfnWndProc;
        public int cbClsExtra, cbWndExtra;
        public nint hInstance, hIcon, hCursor, hbrBackground;
        public char* lpszMenuName, lpszClassName;
        public nint hIconSm;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct NOTIFYICONDATAW
    {
        public uint cbSize;
        public nint hWnd;
        public uint uID, uFlags, uCallbackMessage;
        public nint hIcon;
        public fixed char szTip[128];
        public uint dwState, dwStateMask;
        public fixed char szInfo[256];
        public uint uVersion;
        public fixed char szInfoTitle[64];
        public uint dwInfoFlags;
        public Guid guidItem;
        public nint hBalloonIcon;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct POINT
    {
        public int X, Y;
    }

    [LibraryImport("kernel32.dll", StringMarshalling = StringMarshalling.Utf16)]
    private static partial nint GetModuleHandleW(string? name);

    [LibraryImport("user32.dll")]
    private static partial ushort RegisterClassExW(WNDCLASSEXW* wc);

    [LibraryImport("user32.dll")]
    private static partial nint CreateWindowExW(uint exStyle, char* cls, char* name, uint style, int x, int y, int w, int h,
        nint parent, nint menu, nint inst, nint param);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool DestroyWindow(nint hwnd);

    [LibraryImport("user32.dll")]
    private static partial nint DefWindowProcW(nint hwnd, uint msg, nint w, nint l);

    [LibraryImport("user32.dll", StringMarshalling = StringMarshalling.Utf16)]
    private static partial uint RegisterWindowMessageW(string name);

    [LibraryImport("user32.dll", StringMarshalling = StringMarshalling.Utf16)]
    private static partial nint FindWindowW(string cls, string? name);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool PostMessageW(nint hwnd, uint msg, nint w, nint l);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool AllowSetForegroundWindow(int pid);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool SetForegroundWindow(nint hwnd);

    [LibraryImport("shell32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool Shell_NotifyIconW(uint msg, NOTIFYICONDATAW* data);

    [LibraryImport("user32.dll", StringMarshalling = StringMarshalling.Utf16)]
    private static partial nint LoadImageW(nint inst, string name, uint type, int cx, int cy, uint flags);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool DestroyIcon(nint icon);

    [LibraryImport("user32.dll")]
    private static partial int GetSystemMetrics(int index);

    [LibraryImport("user32.dll")]
    private static partial nint CreatePopupMenu();

    [LibraryImport("user32.dll", StringMarshalling = StringMarshalling.Utf16)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool AppendMenuW(nint menu, uint flags, nuint id, string? text);

    [LibraryImport("user32.dll")]
    private static partial int TrackPopupMenuEx(nint menu, uint flags, int x, int y, nint hwnd, nint tpm);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool DestroyMenu(nint menu);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool GetCursorPos(out POINT pt);
}
