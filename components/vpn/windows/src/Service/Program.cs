using System.IO.Pipes;
using System.Net.NetworkInformation;
using System.Security.AccessControl;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using GlassVpn.Core;

namespace GlassVpn.Service;

static class Program
{
    static int Main(string[] args)
    {
        if (args is ["--ctl", .. var ctl])
            return Ctl.Run(ctl);
        if (args is ["--console"])
        {
            // development: run in the foreground of an elevated console
            Log.Console = true;
            using var host = new Host();
            host.Start();
            using var done = new ManualResetEventSlim();
            Console.CancelKeyPress += (_, e) =>
            {
                e.Cancel = true;
                done.Set();
            };
            done.Wait();
            return 0;
        }
        ServiceBase.Run(new VpnService());
        return 0;
    }
}

/// <summary>The engine plus what feeds it: the control pipe and network-change events.</summary>
sealed class Host : IDisposable
{
    public Engine Engine { get; private set; } = null!;
    PipeServer? pipe;

    public void Start()
    {
        Paths.EnsureDataDir();
        Engine = new Engine();
        NetworkChange.NetworkAddressChanged += OnNetwork;
        Engine.Start();
        pipe = new PipeServer(Engine);
        pipe.Start();
    }

    void OnNetwork(object? sender, EventArgs e) => Engine.NetworkChanged();

    public void Dispose()
    {
        NetworkChange.NetworkAddressChanged -= OnNetwork;
        pipe?.Dispose();
        Engine?.Dispose();
    }
}

sealed class VpnService : ServiceBase
{
    readonly Host host = new();
    Task? starting;

    public VpnService()
    {
        ServiceName = "GlassVPN";
        CanStop = true;
        CanShutdown = true;
        CanHandlePowerEvent = true;
        AutoLog = false;
    }

    // connecting checks configs and starts the cores: not on the service manager's clock
    protected override void OnStart(string[] args) => starting = Task.Run(() =>
    {
        try
        {
            host.Start();
        }
        catch (Exception e)
        {
            Log.Write($"start failed: {e}");
            Stop();
        }
    });

    protected override void OnStop()
    {
        starting?.Wait(30_000);
        host.Dispose();
    }

    protected override void OnShutdown() => OnStop();

    protected override bool OnPowerEvent(PowerBroadcastStatus status)
    {
        if (status is PowerBroadcastStatus.ResumeAutomatic or PowerBroadcastStatus.ResumeSuspend && starting is { IsCompleted: true })
            host.Engine.Resumed();
        return true;
    }
}

/// <summary>The control pipe: users of this machine (the tray app). .NET creates every server pipe
/// with PIPE_REJECT_REMOTE_CLIENTS, so nothing reaches it over the network (SMB).</summary>
sealed class PipeServer(Engine engine) : IDisposable
{
    const int MaxLine = 256 * 1024;
    readonly CancellationTokenSource cts = new();

    public void Start() => _ = Task.Run(Loop);

    public void Dispose()
    {
        cts.Cancel();
        cts.Dispose();
    }

    static NamedPipeServerStream Create()
    {
        var sec = new PipeSecurity();
        SecurityIdentifier Sid(WellKnownSidType t) => new(t, null);
        sec.AddAccessRule(new PipeAccessRule(Sid(WellKnownSidType.LocalSystemSid), PipeAccessRights.FullControl, AccessControlType.Allow));
        sec.AddAccessRule(new PipeAccessRule(Sid(WellKnownSidType.BuiltinAdministratorsSid), PipeAccessRights.FullControl, AccessControlType.Allow));
        sec.AddAccessRule(new PipeAccessRule(Sid(WellKnownSidType.InteractiveSid),
            PipeAccessRights.ReadWrite | PipeAccessRights.Synchronize, AccessControlType.Allow));
        return NamedPipeServerStreamAcl.Create(Paths.Pipe, PipeDirection.InOut, NamedPipeServerStream.MaxAllowedServerInstances,
            PipeTransmissionMode.Byte, PipeOptions.Asynchronous, 0, 0, sec);
    }

    async Task Loop()
    {
        while (!cts.IsCancellationRequested)
        {
            NamedPipeServerStream server;
            try
            {
                server = Create();
            }
            catch (Exception e)
            {
                Log.Write($"pipe: {e.Message}");
                await Task.Delay(2000);
                continue;
            }
            try
            {
                await server.WaitForConnectionAsync(cts.Token);
            }
            catch (OperationCanceledException)
            {
                await server.DisposeAsync();
                return;
            }
            _ = Task.Run(() => Serve(server));
        }
    }

    async Task Serve(NamedPipeServerStream server)
    {
        await using var _ = server;
        using var reader = new StreamReader(server, new UTF8Encoding(false), false, 4096, leaveOpen: true);
        var writer = new StreamWriter(server, new UTF8Encoding(false), 4096, leaveOpen: true) { AutoFlush = true, NewLine = "\n" };
        try
        {
            while (!cts.IsCancellationRequested && await reader.ReadLineAsync(cts.Token) is { } line)
            {
                JsonObject reply;
                if (line.Length > MaxLine)
                {
                    reply = new JsonObject { ["ok"] = false, ["error"] = "request too long" };
                }
                else
                {
                    try
                    {
                        reply = JsonNode.Parse(line) is JsonObject req
                            ? await engine.Handle(req)
                            : new JsonObject { ["ok"] = false, ["error"] = "expected a JSON object" };
                    }
                    catch (Exception e) when (e is JsonException or InvalidOperationException or FormatException)
                    {
                        reply = new JsonObject { ["ok"] = false, ["error"] = e.Message };
                    }
                }
                await writer.WriteLineAsync(reply.ToJsonString().AsMemory(), cts.Token);
            }
        }
        catch (Exception e) when (e is IOException or OperationCanceledException or ObjectDisposedException)
        {
        }
        catch (Exception e)
        {
            Log.Write($"pipe client: {e}");
        }
    }
}
