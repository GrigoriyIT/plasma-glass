using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;

namespace GlassVpn.App;

static class Program
{
    [STAThread]
    static int Main()
    {
        // one tray icon per user: a second launch just opens the window of the first
        using var single = new Mutex(true, @"Local\GlassVPN.App", out var first);
        if (!first)
        {
            Tray.SignalExisting();
            return 0;
        }
        WinRT.ComWrappersSupport.InitializeComWrappers();
        Application.Start(p =>
        {
            SynchronizationContext.SetSynchronizationContext(
                new DispatcherQueueSynchronizationContext(DispatcherQueue.GetForCurrentThread()));
            _ = new App();
        });
        return 0;
    }
}
