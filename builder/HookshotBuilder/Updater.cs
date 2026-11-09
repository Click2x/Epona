using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net.Http;
using System.Text.Json;
using System.Windows;

namespace HookshotBuilder;

/// The game's update offer (host/hos_update.c) starts this app with --update <game folder> --tag <release>. When these tools are
/// not that release, the release's HookshotBuilder.zip is downloaded and unpacked beside this app, and the new app is started with
/// --fetched to build the folder; when they are, the folder is built again here (nx2/make_game.py --update: from the game files the
/// folder keeps).
static class Updater
{
    const string Asset = "HookshotBuilder.zip";
    const string SetupAsset = "HookshotBuilder.exe";            // (the setup, builder/setup/setup.c: a release holds it and its list)
    const string SetupList = "hookshot-setup.txt";              // (scripts/make_setup_parts.py)
    // (Epona) The update source is the repository YOU name, never a built-in one: HOOKSHOT_UPDATE_REPO, else the first line of
    // update_repo.txt in the tools folder. None set (or not "owner/name") means nothing is downloaded. Every download must be from GitHub
    // for that repository, and GitHub must list its SHA-256: a file with no digest to check it against, or one that does not match, is
    // deleted and never run. Upstream's version of this file asked NotRexed/Hookshot and ran what it got, with retries; the retries stay
    static string? Repo(Tools? tools)
    {
        var repo = Environment.GetEnvironmentVariable("HOOKSHOT_UPDATE_REPO");
        var file = tools == null ? null : Path.Combine(tools.Root, "update_repo.txt");
        if (string.IsNullOrWhiteSpace(repo) && file != null && File.Exists(file)) repo = File.ReadLines(file).FirstOrDefault();
        repo = repo?.Trim();
        return repo != null && System.Text.RegularExpressions.Regex.IsMatch(repo, @"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$") ? repo : null;
    }

    const string NoSource = "No update source is set for this build (set HOOKSHOT_UPDATE_REPO, or put owner/name in update_repo.txt in the tools folder), " +
                            "so nothing was downloaded. Your game folder is unchanged.";

    static string LatestUrl(string repo) => $"https://api.github.com/repos/{repo}/releases/latest";

    static string? Digest(JsonElement asset) =>
        asset.TryGetProperty("digest", out var d) && d.ValueKind == JsonValueKind.String ? d.GetString() : null;

    /// The link must be GitHub's, for this repository (the browser link, or the API's asset link), and a SHA-256 must be listed
    static string RequireListed(string what, string? url, string? apiUrl, string? digest, string repo)
    {
        var uri = url == null ? null : new Uri(url);
        var onGitHub = uri != null && uri.Scheme == Uri.UriSchemeHttps &&
                       ((uri.Host == "github.com" && uri.AbsolutePath.StartsWith($"/{repo}/releases/download/", StringComparison.OrdinalIgnoreCase)) ||
                        uri.Host.EndsWith(".githubusercontent.com", StringComparison.OrdinalIgnoreCase));
        if (!onGitHub) throw new InvalidOperationException($"The release's download link for {what} is not on GitHub for {repo}, so it was not used.");
        if (apiUrl != null)
        {
            var api = new Uri(apiUrl);
            if (api.Scheme != Uri.UriSchemeHttps || api.Host != "api.github.com" ||
                !api.AbsolutePath.StartsWith($"/repos/{repo}/releases/assets/", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException($"The release's API link for {what} is not GitHub's for {repo}, so it was not used.");
        }
        if (digest == null || !digest.StartsWith("sha256:", StringComparison.OrdinalIgnoreCase) || digest.Length != 7 + 64)
            throw new InvalidOperationException($"GitHub lists no SHA-256 for {what} in this release, so it was not downloaded.");
        return digest[7..];
    }

    static void VerifyDownload(string path, string expected, string what)
    {
        string actual;
        using (var f = File.OpenRead(path)) actual = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(f));
        if (!string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
        {
            try { File.Delete(path); } catch (Exception) { }
            throw new InvalidOperationException($"The download of {what} does not match the SHA-256 GitHub lists for it, so it was deleted and not used.");
        }
    }

    static readonly TimeSpan[] RetryDelays = { TimeSpan.FromSeconds(3), TimeSpan.FromSeconds(6), TimeSpan.FromSeconds(12), TimeSpan.FromSeconds(20) };

    public static void FromCommandLine(MainWindow w)
    {
        var a = Environment.GetCommandLineArgs();
        string? folder = null, tag = null;
        var fetched = false;
        for (var i = 1; i < a.Length; i++)
        {
            if (a[i] == "--update" && i + 1 < a.Length) folder = a[++i];
            else if (a[i] == "--tag" && i + 1 < a.Length) tag = a[++i];
            else if (a[i] == "--fetched") fetched = true;
        }
        if (folder == null) return;
        UpdateFolder(w, folder, tag, fetched);
    }

    /// The latest release's tag, quietly (null: GitHub did not answer); a few tries, 20 s at most
    public static async Task<string?> LatestTag()
    {
        var repo = Repo(Tools.Find());
        if (repo == null) return null;   // (Epona: no update source set: nothing is asked)
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
        http.DefaultRequestHeaders.UserAgent.ParseAdd("HookshotBuilder");
        for (var attempt = 0; attempt < 3; attempt++)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, LatestUrl(repo));
                request.Headers.Accept.ParseAdd("application/vnd.github+json");
                using var response = await http.SendAsync(request);
                if (response.IsSuccessStatusCode)
                {
                    using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
                    return doc.RootElement.GetProperty("tag_name").GetString();
                }
                if ((int)response.StatusCode < 500) break;   // (the API's limit, 60 an hour a PC: the list below instead)
            }
            catch (Exception) { }
            await Task.Delay(TimeSpan.FromSeconds(2 << attempt));
        }
        // (v2.0.0: when the API did not answer, the builder said a game was up to date. The release's setup list names its tag in
        // its first line, from GitHub's download service, not the API)
        for (var attempt = 0; attempt < 2; attempt++)
        {
            try
            {
                var list = await http.GetStringAsync($"https://github.com/{repo}/releases/latest/download/" + SetupList);
                foreach (var line in list.Split('\n'))
                    if (line.StartsWith("tag ")) return line[4..].Trim();
            }
            catch (Exception) { }
            await Task.Delay(TimeSpan.FromSeconds(2));
        }
        return null;
    }

    /// The latest release's setup (HookshotBuilder.exe) downloaded and started with args: it installs the new builder (only the
    /// parts that changed) and starts it with the same args; this one closes. (no args: the new builder opens as it does)
    public static async Task RunLatestSetup(MainWindow w, IEnumerable<string> args)
    {
        var repo = Repo(Tools.Find());
        if (repo == null) throw new InvalidOperationException(NoSource);
        var token = w.DownloadToken;
        using var http = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
        http.DefaultRequestHeaders.UserAgent.ParseAdd("HookshotBuilder");
        w.Note($"Asking GitHub for the latest release of {repo}");
        string? setupUrl = null, setupApiUrl = null, setupDigest = null;
        long setupSize = 0;
        using (var response = await GetWithRetries(w, http, LatestUrl(repo), token, "application/vnd.github+json", TimeSpan.FromSeconds(30)))
        using (var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync(token)))
            foreach (var asset in doc.RootElement.GetProperty("assets").EnumerateArray())
                if (asset.GetProperty("name").GetString() == SetupAsset)
                {
                    setupUrl = asset.GetProperty("browser_download_url").GetString();
                    setupApiUrl = asset.GetProperty("url").GetString();
                    setupSize = asset.GetProperty("size").GetInt64();
                    setupDigest = Digest(asset);
                }
        if (setupUrl == null) throw new InvalidOperationException("The latest release has no " + SetupAsset + ".");
        var setupExpected = RequireListed(SetupAsset, setupUrl, setupApiUrl, setupDigest, repo);
        var cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HookshotBuilder", "update");
        Directory.CreateDirectory(cache);
        var setup = Path.Combine(cache, SetupAsset);
        w.Note("Downloading the new Hookshot Builder");
        await DownloadWithRetries(w, http, setupUrl, setupApiUrl, setup, setupSize, token);
        VerifyDownload(setup, setupExpected, SetupAsset);
        w.Note("Checked: SHA-256 matches");
        var si = new ProcessStartInfo(setup) { UseShellExecute = false, WorkingDirectory = cache };
        foreach (var arg in args) si.ArgumentList.Add(arg);
        Process.Start(si);
        Application.Current.Shutdown();
    }

    /// The game in folder built again with the latest release: here when these tools are it (or fetched), else after the setup
    /// installed it (it starts the new builder with --update folder --tag t --fetched)
    public static async void UpdateFolder(MainWindow w, string folder, string? tag, bool fetched)
    {
        w.BeginUpdate(folder, tag);
        var tools = Tools.Find();
        if (tools == null)
        {
            w.DownloadFailed("The Hookshot tools were not found next to this app.");
            return;
        }
        // (just downloaded, but another release than asked for: the setup installed the release before it (GitHub's latest link lags
        // right after a publish), and building here kept players on the old version while the builder said it updated)
        if (fetched && tag != null && tools.Version != null && tools.Version != tag)
        {
            w.DownloadFailed($"The update installed {tools.Version}, not {tag}: GitHub's download links can lag right after a release. Try Update again in a few minutes.");
            return;
        }
        // (already the new release, or just downloaded: no second download)
        if (fetched || (tag != null && tools.Version == tag))
        {
            w.UpdateBuild(tools, folder);
            return;
        }
        var repo = Repo(tools);
        if (repo == null)
        {
            w.DownloadFailed(NoSource);
            return;
        }
        try
        {
            var token = w.DownloadToken;
            using var http = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
            http.DefaultRequestHeaders.UserAgent.ParseAdd("HookshotBuilder");
            w.Note($"Asking GitHub for the latest release of {repo}");
            string? newTag = null, url = null, setupUrl = null, digest = null, setupDigest = null;
            string? apiUrl = null, setupApiUrl = null;
            long size = 0, setupSize = 0;
            var hasList = false;
            using (var response = await GetWithRetries(w, http, LatestUrl(repo), token, "application/vnd.github+json", TimeSpan.FromSeconds(30)))
            using (var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync(token)))
            {
                newTag = doc.RootElement.GetProperty("tag_name").GetString();
                foreach (var asset in doc.RootElement.GetProperty("assets").EnumerateArray())
                {
                    var assetName = asset.GetProperty("name").GetString();
                    if (assetName == Asset)
                    {
                        url = asset.GetProperty("browser_download_url").GetString();
                        apiUrl = asset.GetProperty("url").GetString();
                        size = asset.GetProperty("size").GetInt64();
                        digest = Digest(asset);
                    }
                    else if (assetName == SetupAsset)
                    {
                        setupUrl = asset.GetProperty("browser_download_url").GetString();
                        setupApiUrl = asset.GetProperty("url").GetString();
                        setupSize = asset.GetProperty("size").GetInt64();
                        setupDigest = Digest(asset);
                    }
                    else if (assetName == SetupList) hasList = true;
                }
            }
            if (newTag == null || (url == null && setupUrl == null)) throw new InvalidOperationException("The latest release has no " + Asset + ".");
            if (newTag == tools.Version)
            {
                w.UpdateBuild(tools, folder);
                return;
            }
            var name = string.Concat(newTag.Where(c => char.IsLetterOrDigit(c) || c == '-' || c == '_' || c == '.'));
            var cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HookshotBuilder", "update");
            Directory.CreateDirectory(cache);
            // (a release with the setup and its list: the setup downloads only the parts that changed since the version installed (a few MB
            // when only the builder's code did), checks them and starts the new builder with these arguments. The whole zip is the fallback)
            if (setupUrl != null && hasList)
            {
                w.Note($"Downloading the update for {newTag}");
                var setup = Path.Combine(cache, SetupAsset);
                var setupExpected = RequireListed(SetupAsset, setupUrl, setupApiUrl, setupDigest, repo);
                await DownloadWithRetries(w, http, setupUrl, setupApiUrl, setup, setupSize, token);
                VerifyDownload(setup, setupExpected, SetupAsset);
                w.Note("Checked: SHA-256 matches");
                var ssi = new ProcessStartInfo(setup) { UseShellExecute = false, WorkingDirectory = cache };
                foreach (var arg in new[] { "--update", folder, "--tag", newTag, "--fetched" }) ssi.ArgumentList.Add(arg);
                Process.Start(ssi);
                Application.Current.Shutdown();
                return;
            }
            if (url == null) throw new InvalidOperationException("The latest release has no " + Asset + ".");
            var zip = Path.Combine(cache, "HookshotBuilder-" + name + ".zip");
            var expected = RequireListed(Asset, url, apiUrl, digest, repo);
            w.Note($"Downloading {Asset} of {newTag} ({size >> 20} MB)");
            await DownloadWithRetries(w, http, url, apiUrl, zip, size, token, w.DownloadProgress);
            VerifyDownload(zip, expected, Asset);
            w.Note("Checked: SHA-256 matches. Unpacking the new version");
            // (beside this app when that folder takes writing, else in the app data folder)
            var parent = Directory.GetParent(AppContext.BaseDirectory.TrimEnd('\\', '/'))!.FullName;
            string target;
            try
            {
                target = await Unpack(zip, Path.Combine(parent, "HookshotBuilder " + name));
            }
            catch (Exception e) when (e is UnauthorizedAccessException or IOException)
            {
                target = await Unpack(zip, Path.Combine(Path.GetDirectoryName(cache)!, "builders", name));
            }
            try { File.Delete(zip); } catch (Exception) { }
            var exe = Path.Combine(target, "HookshotBuilder.exe");
            if (!File.Exists(exe)) throw new FileNotFoundException("The download has no HookshotBuilder.exe (your antivirus may have removed it).");
            var si = new ProcessStartInfo(exe) { UseShellExecute = false, WorkingDirectory = target };
            foreach (var arg in new[] { "--update", folder, "--tag", newTag, "--fetched" }) si.ArgumentList.Add(arg);
            Process.Start(si);
            Application.Current.Shutdown();
        }
        catch (OperationCanceledException)
        {
            w.DownloadFailed("The download was cancelled. Your game folder is unchanged.");
        }
        catch (Exception e)
        {
            w.DownloadFailed(e.Message + " Your game folder is unchanged; you can also download the new version from GitHub yourself.");
        }
    }

    static async Task<HttpResponseMessage> GetWithRetries(MainWindow w, HttpClient http, string url, CancellationToken token,
        string? accept = null, TimeSpan? timeout = null)
    {
        Exception? last = null;
        for (var attempt = 0; attempt <= RetryDelays.Length; attempt++)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, url);
                if (accept != null) request.Headers.Accept.ParseAdd(accept);
                using var ask = timeout is null ? null : new CancellationTokenSource(timeout.Value);
                using var both = ask is null ? null : CancellationTokenSource.CreateLinkedTokenSource(token, ask.Token);
                var response = await http.SendAsync(request, HttpCompletionOption.ResponseContentRead, both?.Token ?? token);
                if (response.IsSuccessStatusCode) return response;

                var failure = HttpFailure(response);
                response.Dispose();
                if (!IsTransient(failure)) throw failure;
                last = failure;
            }
            catch (OperationCanceledException e) when (!token.IsCancellationRequested && timeout is not null)
            {
                last = e;
            }
            catch (HttpRequestException e) when (IsTransient(e))
            {
                last = e;
            }

            if (attempt == RetryDelays.Length) break;
            w.Note($"GitHub did not answer{StatusDetail(last)}. Retrying in {(int)RetryDelays[attempt].TotalSeconds} s...");
            await Task.Delay(RetryDelays[attempt], token);
        }
        throw new HttpRequestException($"GitHub's release API did not respond after {RetryDelays.Length + 1} attempts: {last?.Message}",
            last, (last as HttpRequestException)?.StatusCode);
    }

    static async Task DownloadWithRetries(MainWindow w, HttpClient http, string url, string? apiUrl, string path, long size,
        CancellationToken token, Action<double>? progress = null)
    {
        Exception? last = null;
        for (var attempt = 0; attempt <= RetryDelays.Length; attempt++)
        {
            try
            {
                await DownloadOnce(http, url, path, size, token, progress, apiAsset: false);
                return;
            }
            catch (Exception e) when (IsTransient(e))
            {
                last = e;
                if (apiUrl != null) w.Note($"Release download failed{StatusDetail(e)}; trying GitHub's API asset URL.");
            }

            if (apiUrl != null)
            {
                try
                {
                    await DownloadOnce(http, apiUrl, path, size, token, progress, apiAsset: true);
                    return;
                }
                catch (Exception e) when (IsTransient(e))
                {
                    last = e;
                }
            }

            if (attempt == RetryDelays.Length) break;
            w.Note($"GitHub's download servers did not answer{StatusDetail(last)}. Retrying in {(int)RetryDelays[attempt].TotalSeconds} s...");
            await Task.Delay(RetryDelays[attempt], token);
        }
        throw new HttpRequestException($"GitHub's asset download failed after {RetryDelays.Length + 1} attempts: {last?.Message}",
            last, (last as HttpRequestException)?.StatusCode);
    }

    static async Task DownloadOnce(HttpClient http, string url, string path, long size, CancellationToken token,
        Action<double>? progress, bool apiAsset)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        if (apiAsset) request.Headers.Accept.ParseAdd("application/octet-stream");
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token);
        if (!response.IsSuccessStatusCode) throw HttpFailure(response);

        var total = response.Content.Headers.ContentLength ?? size;
        await using var from = await response.Content.ReadAsStreamAsync(token);
        await using var to = File.Create(path);
        var buffer = new byte[1 << 20];
        long have = 0;
        var shown = DateTime.MinValue;
        int n;
        while (true)
        {
            try { n = await from.ReadAsync(buffer, token); }
            catch (IOException e) { throw new HttpRequestException("The download connection ended unexpectedly.", e); }
            if (n == 0) break;
            await to.WriteAsync(buffer.AsMemory(0, n), token);
            have += n;
            if (progress != null && total > 0 && DateTime.UtcNow - shown > TimeSpan.FromMilliseconds(200))
            {
                shown = DateTime.UtcNow;
                progress(Math.Min(1.0, (double)have / total));
            }
        }
        if (total > 0 && have != total) throw new HttpRequestException($"The download ended early ({have >> 20} of {total >> 20} MB).");
    }

    static HttpRequestException HttpFailure(HttpResponseMessage response) =>
        new($"GitHub returned HTTP {(int)response.StatusCode} ({response.ReasonPhrase}).", null, response.StatusCode);

    static bool IsTransient(Exception error) =>
        error is HttpRequestException request && (request.StatusCode is null || (int)request.StatusCode >= 500);

    static string StatusDetail(Exception? error) =>
        error is HttpRequestException { StatusCode: { } status } ? $" (HTTP {(int)status})" : "";

    /// The zip's HookshotBuilder folder, as target (an older one there replaced)
    static async Task<string> Unpack(string zip, string target)
    {
        var part = target + ".part";
        if (Directory.Exists(part)) Directory.Delete(part, true);
        await Task.Run(() => ZipFile.ExtractToDirectory(zip, part));
        var inner = Path.Combine(part, "HookshotBuilder");
        if (Directory.Exists(target)) Directory.Delete(target, true);
        Directory.Move(Directory.Exists(inner) ? inner : part, target);
        if (Directory.Exists(part)) Directory.Delete(part, true);
        return target;
    }
}
