using System.Diagnostics;
using System.IO;
using System.Text;

namespace HookshotBuilder;

/// Where nx2/make_game.py and its Python are: a "tools" folder beside the app when packaged, or the source tree it sits in.
sealed record Tools(string Root, string Python)
{
    /// Which release these tools are (tools/version.txt, written when the release is packed); null from the source tree
    public string? Version => File.Exists(Path.Combine(Root, "version.txt")) ? File.ReadAllText(Path.Combine(Root, "version.txt")).Trim() : null;

    public static Tools? Find()
    {
        var at = AppContext.BaseDirectory;
        var bundled = Path.Combine(at, "tools");
        if (File.Exists(Path.Combine(bundled, "nx2", "make_game.py")))
        {
            var py = Path.Combine(bundled, "python", "python.exe");
            return new Tools(bundled, File.Exists(py) ? py : "python");
        }
        for (var d = new DirectoryInfo(at); d != null; d = d.Parent)
            if (File.Exists(Path.Combine(d.FullName, "nx2", "make_game.py")))
                return new Tools(d.FullName, "python");
        return null;
    }
}

/// A build's log file: %LOCALAPPDATA%\HookshotBuilder\logs\build-<date>-<time>.log, every line the build tools print with the time,
/// the last ten kept. Logging never stops a build: a file that cannot be made or written is skipped. The header names the folders in
/// use (and so your user name), so look through a log before posting it. The progress ticks (@@progress) are left out.
sealed class BuildLog : IDisposable
{
    readonly StreamWriter? writer;
    readonly object gate = new();
    public string? FilePath { get; }

    public BuildLog(Tools tools, IEnumerable<string> args)
    {
        try
        {
            var dir = System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HookshotBuilder", "logs");
            Directory.CreateDirectory(dir);
            foreach (var old in new DirectoryInfo(dir).GetFiles("build-*.log").OrderByDescending(f => f.LastWriteTimeUtc).Skip(9))
            {
                try { old.Delete(); } catch (Exception) { }
            }
            FilePath = System.IO.Path.Combine(dir, $"build-{DateTime.Now:yyyyMMdd-HHmmss}.log");
            writer = new StreamWriter(new FileStream(FilePath, FileMode.CreateNew, FileAccess.Write, FileShare.Read), new UTF8Encoding(false)) { AutoFlush = true };
            writer.WriteLine($"Hookshot Builder {typeof(BuildLog).Assembly.GetName().Version}, {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
            writer.WriteLine($"Windows {Environment.OSVersion.Version}, {Environment.ProcessorCount} logical processors");
            writer.WriteLine($"tools: {tools.Root}, python: {tools.Python}, release: {tools.Version ?? "(source tree)"}");
            writer.WriteLine("arguments: " + string.Join(' ', args.Select(a => a.Contains(' ') ? $"\"{a}\"" : a)));
            writer.WriteLine();
        }
        catch (Exception)
        {
            writer?.Dispose();
            writer = null;
            FilePath = null;
        }
    }

    public void Write(string line)
    {
        if (writer == null || line.StartsWith("@@progress")) return;
        try
        {
            lock (gate) writer.WriteLine($"{DateTime.Now:HH:mm:ss} {line}");
        }
        catch (Exception)
        {
            // (a full disk or a file in use: the build goes on without its log)
        }
    }

    public void Dispose()
    {
        lock (gate)
        {
            try { writer?.Dispose(); } catch (Exception) { }
        }
    }
}

/// nx2/make_game.py as a child process: its lines as they come, and how it ended.
sealed class Runner
{
    readonly Tools tools;
    readonly List<string> args;
    Process? process;
    string? error;
    bool cancelled;

    public event Action<string>? Line;
    public event Action<string?>? Finished;

    public Runner(Tools tools, List<string> args)
    {
        this.tools = tools;
        this.args = args;
    }

    static ProcessStartInfo Info(Tools tools, IEnumerable<string> args)
    {
        var si = new ProcessStartInfo(tools.Python)
        {
            WorkingDirectory = tools.Root,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        si.Environment["PYTHONIOENCODING"] = "utf-8";
        // (written into the game folder's hookshot_version.txt: the game starts this app again to update, host/hos_update.c)
        if (Environment.ProcessPath != null) si.Environment["HOOKSHOT_BUILDER_EXE"] = Environment.ProcessPath;
        // (the folder's own compiler, headers and libraries, when it has them: nothing of the PC's but Windows' own)
        var sets = new[] { ("EMSDK", "emsdk"), ("RX_CPM", "cpm"), ("WGPU_NATIVE", "wgpu-native") };
        foreach (var (name, folder) in sets)
        {
            var path = Path.Combine(tools.Root, folder);
            if (Directory.Exists(path)) si.Environment[name] = path;
        }
        si.ArgumentList.Add("-I");
        si.ArgumentList.Add(Path.Combine(tools.Root, "nx2", "make_game.py"));
        foreach (var a in args) si.ArgumentList.Add(a);
        return si;
    }

    public void Start()
    {
        Task.Run(() =>
        {
            // (everything the build tools say goes to a file too: the window's details keep the last few thousand lines only)
            using var log = new BuildLog(tools, args);
            if (log.FilePath != null) Line?.Invoke("log: " + log.FilePath);
            try
            {
                using var p = Process.Start(Info(tools, args))!;
                process = p;
                p.ErrorDataReceived += (_, e) => { if (e.Data != null) { log.Write(e.Data); Line?.Invoke(e.Data); } };
                p.BeginErrorReadLine();
                try { p.PriorityClass = ProcessPriorityClass.BelowNormal; } catch (Exception) { }
                while (p.StandardOutput.ReadLine() is { } line)
                {
                    if (line.StartsWith("@@error ")) error = line[8..];
                    log.Write(line);
                    Line?.Invoke(line);
                }
                p.WaitForExit();
                var failure = cancelled ? "cancelled" : p.ExitCode == 0 ? null : error ?? "The build tools stopped without saying why. See the details.";
                log.Write(failure == null ? "finished: ok" : $"finished: {failure} (exit code {p.ExitCode})");
                Finished?.Invoke(failure);
            }
            catch (Exception e)
            {
                log.Write("could not start: " + e);
                Finished?.Invoke("The build tools could not start: " + e.Message);
            }
        });
    }

    public void Cancel()
    {
        cancelled = true;
        try { process?.Kill(entireProcessTree: true); } catch (Exception) { }
    }

    /// Is this the supported game and version? The answer in plain words.
    public static async Task<(bool Ok, string Text)> Check(Tools tools, IEnumerable<string> args)
    {
        try
        {
            using var p = Process.Start(Info(tools, args))!;
            p.ErrorDataReceived += (_, _) => { };
            p.BeginErrorReadLine();
            var result = (false, "The game files could not be read.");
            while (await p.StandardOutput.ReadLineAsync() is { } line)
            {
                if (line.StartsWith("@@check ok ")) result = (true, line[11..]);
                else if (line.StartsWith("@@check bad ")) result = (false, line[12..]);
                else if (line.StartsWith("@@error ")) result = (false, line[8..]);
            }
            await p.WaitForExitAsync();
            return result;
        }
        catch (Exception)
        {
            // (the package's own Python missing: an antivirus took it, most often, after a false alarm on the download)
            if (tools.Python == "python" && Directory.Exists(Path.Combine(tools.Root, "python")))
                return (false, "The builder's own Python (tools/python/python.exe) is missing. Your antivirus probably removed it: restore it " +
                               "from quarantine, or unpack the zip again into a folder your antivirus allows, then try again.");
            return (false, "Python was not found. Install Python 3 or use the full Hookshot Builder package.");
        }
    }
}
