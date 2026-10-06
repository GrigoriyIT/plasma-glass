using System.IO.Pipes;
using System.Text;
using System.Text.Json.Nodes;

namespace GlassVpn.Core;

/// <summary>The service's control channel: a local named pipe carrying one JSON object per line.
/// Request {"cmd": "...", ...}; reply {"ok": true, ...} or {"ok": false, "error": "..."}.</summary>
public sealed class IpcClient : IDisposable
{
    readonly NamedPipeClientStream pipe;
    readonly StreamReader reader;
    readonly StreamWriter writer;

    public IpcClient(int timeoutMs = 2000)
    {
        pipe = new NamedPipeClientStream(".", Paths.Pipe, PipeDirection.InOut, PipeOptions.Asynchronous);
        pipe.Connect(timeoutMs);
        reader = new StreamReader(pipe, new UTF8Encoding(false), false, 4096, leaveOpen: true);
        writer = new StreamWriter(pipe, new UTF8Encoding(false), 4096, leaveOpen: true) { AutoFlush = true, NewLine = "\n" };
    }

    public async Task<JsonObject> CallAsync(JsonObject request, CancellationToken ct = default)
    {
        await writer.WriteLineAsync(request.ToJsonString().AsMemory(), ct);
        var line = await reader.ReadLineAsync(ct) ?? throw new IOException("the service closed the connection");
        return JsonNode.Parse(line)?.AsObject() ?? throw new IOException("empty reply");
    }

    public void Dispose()
    {
        try
        {
            writer.Dispose();
        }
        catch (IOException) { }
        catch (ObjectDisposedException) { }
        reader.Dispose();
        pipe.Dispose();
    }
}
