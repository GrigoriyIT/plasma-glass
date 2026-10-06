using System.Diagnostics;
using System.Runtime.InteropServices;
using GlassVpn.Core;
using Microsoft.Win32.SafeHandles;

namespace GlassVpn.Service;

/// <summary>A Job Object that kills its processes when the service goes away — even when it
/// crashes: no orphaned sing-box keeps the tunnel up with nobody watching it.</summary>
sealed partial class Job : IDisposable
{
    readonly SafeFileHandle handle;

    public Job()
    {
        handle = CreateJobObjectW(0, null);
        if (handle.IsInvalid)
            throw new System.ComponentModel.Win32Exception();
        var info = new ExtendedLimits
        {
            // KILL_ON_JOB_CLOSE | DIE_ON_UNHANDLED_EXCEPTION (no error dialog to hang on)
            Basic = new BasicLimits { LimitFlags = 0x2000 | 0x400 },
        };
        if (!SetInformationJobObject(handle, 9, ref info, Marshal.SizeOf<ExtendedLimits>()))
            throw new System.ComponentModel.Win32Exception();
    }

    public void Add(Process p)
    {
        if (!AssignProcessToJobObject(handle, p.Handle))
            Log.Write($"job: cannot adopt {p.ProcessName}: {Marshal.GetLastPInvokeError()}");
    }

    public void Dispose() => handle.Dispose();

    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public nuint MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public nuint Affinity;
        public uint PriorityClass, SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimits
    {
        public BasicLimits Basic;
        public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;   // IO_COUNTERS
        public nuint ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [LibraryImport("kernel32.dll", SetLastError = true, StringMarshalling = StringMarshalling.Utf16)]
    private static partial SafeFileHandle CreateJobObjectW(nint attributes, string? name);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool SetInformationJobObject(SafeFileHandle job, int infoClass, ref ExtendedLimits info, int size);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool AssignProcessToJobObject(SafeFileHandle job, nint process);
}

/// <summary>A core (sing-box or Xray) running under the job; its console output goes to the service log.</summary>
sealed class Child
{
    readonly Process p;
    public string Name { get; }
    public long StartedAt { get; } = Environment.TickCount64;

    Child(string name, Process p)
    {
        Name = name;
        this.p = p;
    }

    /// <summary>memLimitMb: Go's soft heap limit; with GOGC=50 the cores stay small while idle
    /// and spend a little more CPU on collection under load.</summary>
    public static Child Start(Job job, string name, string exe, string logFile, int memLimitMb, params string[] args)
    {
        var psi = new ProcessStartInfo(exe)
        {
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Paths.Run,
            RedirectStandardOutput = true, RedirectStandardError = true,
        };
        foreach (var a in args)
            psi.ArgumentList.Add(a);
        psi.Environment["GOGC"] = "50";
        psi.Environment["GOMEMLIMIT"] = $"{memLimitMb}MiB";
        var p = new Process { StartInfo = psi };
        p.OutputDataReceived += (_, e) => Echo(logFile, e.Data);
        p.ErrorDataReceived += (_, e) => Echo(logFile, e.Data);
        p.Start();
        job.Add(p);
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();
        return new Child(name, p);
    }

    static void Echo(string logFile, string? line)
    {
        if (!string.IsNullOrWhiteSpace(line))
            Log.Append(logFile, line);
    }

    public bool Alive => !p.HasExited;
    public int ExitCode => p.HasExited ? p.ExitCode : 0;

    public void Stop()
    {
        try
        {
            if (!p.HasExited)
            {
                p.Kill();
                p.WaitForExit(5000);
            }
        }
        catch (InvalidOperationException) { }
        catch (System.ComponentModel.Win32Exception e) { Log.Write($"{Name}: stop failed: {e.Message}"); }
        p.Dispose();
    }

    /// <summary>Runs a core's config check; null when the config is fine, else its complaint.</summary>
    public static string? Check(string exe, params string[] args)
    {
        var psi = new ProcessStartInfo(exe)
        {
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Paths.Run,
            RedirectStandardOutput = true, RedirectStandardError = true,
        };
        foreach (var a in args)
            psi.ArgumentList.Add(a);
        using var p = Process.Start(psi)!;
        var err = p.StandardError.ReadToEndAsync();
        var outp = p.StandardOutput.ReadToEndAsync();
        if (!p.WaitForExit(20000))
        {
            p.Kill();
            return $"{Path.GetFileName(exe)}: config check timed out";
        }
        if (p.ExitCode == 0)
            return null;
        var text = (err.Result + outp.Result).Trim();
        return text.Length > 300 ? text[^300..] : text;
    }
}
