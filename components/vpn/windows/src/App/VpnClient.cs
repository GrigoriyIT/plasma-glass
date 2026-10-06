using System.Text.Json.Nodes;
using GlassVpn.Core;

namespace GlassVpn.App;

/// <summary>A connection to the service's control pipe that reconnects on its own;
/// null means the service didn't answer.</summary>
public sealed class VpnClient : IDisposable
{
    readonly SemaphoreSlim gate = new(1, 1);
    IpcClient? client;

    public async Task<JsonObject?> Call(string cmd, JsonObject? args = null, int timeoutSec = 30)
    {
        var req = new JsonObject { ["cmd"] = cmd };
        if (args is not null)
            foreach (var (k, v) in args)
                req[k] = v?.DeepClone();
        await gate.WaitAsync();
        try
        {
            for (var attempt = 0; attempt < 2; attempt++)
            {
                try
                {
                    client ??= await Task.Run(() => new IpcClient(1000));
                    return await client.CallAsync(req).WaitAsync(TimeSpan.FromSeconds(timeoutSec));
                }
                catch (Exception e) when (e is IOException or TimeoutException or UnauthorizedAccessException
                                               or ObjectDisposedException or System.Text.Json.JsonException)
                {
                    client?.Dispose();
                    client = null;
                }
            }
            return null;
        }
        finally
        {
            gate.Release();
        }
    }

    public void Dispose()
    {
        client?.Dispose();
        gate.Dispose();
    }
}
