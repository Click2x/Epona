# Epona

Epona is a fork of **[Hookshot](https://github.com/NotRexed/Hookshot)** by **NotRexed**, a static recompilation of
*The Legend of Zelda: Ocarina of Time* (Nintendo Switch 2) to native Windows and Linux. The recompiler, the Horizon and NVN2
layers, the Vulkan renderer and nearly all of the code are the original author's and the contributors credited in
[readme.md](readme.md#credits). Epona is not made or endorsed by the original author, and the original's license is kept:
**GPL-3.0-or-later** ([LICENSE](LICENSE)). The name is for this fork only; the programs keep their Hookshot names so the
original's fixes can still be merged in.

No game files are in this repository. You supply your own dump. Epona is not affiliated with Nintendo.

If the original author wants any of these changes, they are welcome to take them.

**Modified from Hookshot** (upstream commit `ba594da`, by NotRexed) by the Epona maintainers in November 2026; the git history and
`git diff ba594da` show every change, as the GPL asks. **See also:** [`LEGAL.md`](LEGAL.md) (you must legally own the game),
[`TRANSPARENCY.md`](TRANSPARENCY.md) (what was checked and what was not), [`THIRD_PARTY.md`](THIRD_PARTY.md) (every third-party component and
its license) and [`docs/WHAT_TO_EXPECT.md`](docs/WHAT_TO_EXPECT.md).

## What Epona changes

The changes are in setup, checks, logging and the updater. **The recompiler and the renderer were not touched.** Two small changes
reach beyond setup: the game's update check (`host/hos_update.c`: it asks no one by default) and one message in `nx2/build.py`.
Nothing here has been through a full play-test yet; see [Findings](#findings) for what was measured and [Limits](#limits).

| Area | Change | Where |
|---|---|---|
| Checks before a 40-minute build | `python` on PATH (this run only), missing Python packages, 64-bit Python, disk and memory, a renderer to build, the AV1 Video Extension, a CPU with AVX2, graphics cards that probably lack mesh shaders | `nx2/make_game.py` |
| Compiler | Offers llvm-mingw (no Visual Studio, no emsdk) with a pinned version and SHA-256 | `nx2/make_game.py` |
| A guided menu | Run with no arguments (or double-click `epona.bat`) for a menu that stays open: Install the game, Check this PC, See what gets downloaded, Settings, Help. It finds your `.nup`, suggests a standard install folder, takes the language, shows a checklist of what is missing, and asks once, item by item, before any download. During the build it draws steps and one progress line and keeps a log file. Every command-line option still works unchanged | `nx2/epona_ui.py`, `nx2/make_game.py`, `epona.bat` |
| Credits and licenses carried forward | The original's credits (including its newest EvilBoyce entry) and license text are kept word for word in the readme. `THIRD_PARTY.md` lists every third-party component and its license, read from the files themselves. Each finished game folder gets a `licenses` folder (GPL-3.0, suyu's GPL texts, Opus, SDL, FFmpeg's, `THIRD_PARTY.md`, a short README). Every new file carries an SPDX license header; the original files' headers are untouched | `readme.md`, `THIRD_PARTY.md`, `nx2/make_game.py` |
| First-run notice | Before the first build the menu shows a short legal notice (you must own the game; do not share what you build; unofficial; no warranty) and asks you to confirm. Kept only in your own settings file | `nx2/epona_ui.py`, `LEGAL.md` |
| Pictures | The screens in `docs/screens` are drawn by the menu's own code on sample data (`scripts/render_screens.py`), and `scripts/make_announcement.py` builds a 1280x720 announcement PNG from them with Edge. Original shapes and text only | `scripts/`, `docs/` |
| Vulkan headers | Offers the three pinned header archives, SHA-256 checked | `nx2/make_game.py` |
| Controllers | Offers `SDL2.dll` (SDL 2.32.10, 0.6 MB, SHA-256 checked), which the build only warned about | `nx2/make_game.py` |
| Build output | One free-space note per drive, and no pip "Scripts not on PATH" noise | `nx2/make_game.py` |
| Parallel compiles from the free memory | The number of compiles at once is **suggested from the memory that is free**: 2.5 GB planned per job, at most 70% of what is free, up to the number of logical CPUs (46 GB free and 20 threads gives 12). In a terminal it **asks**, so you can type your own number; `--jobs` or `HOOKSHOT_JOBS` skips the question. The original used half the CPU threads whatever the memory. See [Findings](#findings) for the measurements behind 2.5 GB | `nx2/make_game.py` |
| FFmpeg is checked, and can be fetched or built | FFmpeg is **not optional** (`host/nn_video.c` includes it; even the AV1 movies use its scaler). The build checks for it before the compile and **offers to download BtbN's prebuilt shared build** (about 77 MB, checked against the SHA-256 GitHub lists that day; only the headers, four import libraries and four DLLs are taken, and the DLLs are copied beside the game). `--ffmpeg-zip` uses a zip you downloaded yourself. The alternative, `scripts/epona_build_ffmpeg.sh`, which **you** run in WSL, builds FFmpeg 9.0.2 from source with a pinned toolchain and a GPG-checked tarball | `nx2/make_game.py`, `scripts/epona_build_ffmpeg.sh` |
| Fix before going on: `python` | If `python` is not on PATH (only the `py` launcher, or the Store stub), the build uses the running Python for that run, then **asks** whether to put it on your user PATH for good: your account only, no administrator rights, the old value saved to `work\user_path_before.txt` to undo it | `nx2/make_game.py` |
| Fix before going on: speed-up data | If `work\image` is missing, asks for the path of a `HookshotBuilder.zip` **you downloaded yourself**; only four data files are read out of it (`hot_funcs.txt`, `hot_order.txt`, `hookshot_pieces.prof`, `image/chunks.txt`) and nothing in it is run. Enter goes on without it. Nothing is downloaded | `nx2/make_game.py` |
| Speed-up data without the zip | `scripts/epona_fetch_work_data.py`, which **you** run, reads only the four data files out of the author's `HookshotBuilder.zip` by HTTP range requests (the zip is never downloaded, 64 MB cap), into `work_incoming\` for review | `scripts/epona_fetch_work_data.py` |
| Ctrl+C is not an error | Pressing Ctrl+C now stops the step and every compiler it started, and says "Stopped by you (Ctrl+C)... running the same command again carries on", instead of a traceback and "an error it did not expect" | `nx2/make_game.py` |
| Clearer build message | "no wgpu-native ... building without the renderer" now says it is the WebGPU fallback that is skipped, that this is expected, and that the game draws with Vulkan | `nx2/build.py` |
| Visual Studio route | Offers emsdk (with the `python` fix) and the Visual Studio Build Tools, each only when asked | `third_party/a64-kit/tools/toolchain.py`, `nx2/make_game.py` |
| Visibility | `--list-tools` prints every download and install below, and downloads nothing | `nx2/make_game.py` |
| Builder logging | Every line the build tools print goes to a log file as well (issue 267) | `builder/HookshotBuilder/Runner.cs` |
| Updater | The update source is set by you (`HOOKSHOT_UPDATE_REPO` or `update_repo.txt`), the default is none, the download must be from GitHub for that repository, and its SHA-256 as GitHub lists it must match before anything is unpacked or run | `builder/HookshotBuilder/Updater.cs`, `host/hos_update.c` |

## What you need

- 64-bit Windows 10 or 11, with a CPU that has **AVX2** (Intel Haswell, AMD Zen 1 or newer).
- A graphics card with **Vulkan 1.3 and mesh shaders**: NVIDIA GTX 16 / RTX 20 and newer, AMD RX 6000 and newer, Intel Arc.
  Only NVIDIA has been tested upstream; AMD and Intel reports are open on the original's issue page.
- 16 GB of RAM or more, about 60 GB of free disk space while building.
- Your own copy of the game at the supported version: program `0400486024DEC000`, update v131072, build `e0f3ccfa`
  (`.nup` file, or the `romfs` and `exefs` folders).
- Python 3 (64-bit) from python.org, not the Microsoft Store's: packages from the Store's Python are not seen by `python -I`.
- Git, only if you use the Visual Studio / emsdk route.
- Microsoft's **AV1 Video Extension** (free, Microsoft Store). The game's movies need it; without it they show a green screen.
- **FFmpeg** (headers and the libraries avcodec, swscale, swresample, avutil): required. `make_game.py` offers BtbN's prebuilt
  shared build (below); or build it from source with `scripts/epona_build_ffmpeg.sh` in WSL; or put a folder at
  `work\eg\.cache\cpm\ffmpeg\<version>\{include,lib}` yourself (the libraries as `lib\avcodec.lib` and so on). A shared build also
  puts four DLLs beside the game; a static one does not.
- The renderer's other inputs. A clone has no `tools\` folder, so the Vulkan headers and `SDL2.dll` are offered for you (below).
  Two things are **not** fetched: the WebGPU renderer's `wgpu-native` (only the fallback; the game uses Vulkan unless told
  otherwise, so the build says it is skipping the WebGPU fallback and goes on), and the speed-up data in `work\` (the game builds,
  a little slower).
- **For the FFmpeg script only:** WSL with an Ubuntu, and `sudo apt install build-essential curl xz-utils gnupg` (the script never
  uses sudo; it tells you if something is missing).

## The easy way: the guided menu

Double-click **`epona.bat`**, or in a terminal in this folder run `py -I nx2/make_game.py` with no arguments. You never have to leave it.

The look is inspired by the file-select screens of Ocarina of Time (the original game's art and text are not used): a deep-blue panel
with a cream title, a plate of its own for each choice with the chosen one lit, a thin line between groups, and a strip below. The
header above it is a panel on the same blue. Move with the
**arrow keys** and press **Enter** to decide, or just type a choice's number or letter; **Esc** cancels. The confirmation ("Start this
build?") shows your game, folder and language on plates, one heart for each compile running at once, and the **six medallions**, lit
for each requirement that is ready (Forest: Python packages, Fire: the compiler, Water: the Vulkan headers, Spirit: FFmpeg, Shadow:
controller support, Light: the AV1 movies extension). While it builds, 20 hearts fill as the life meter does, 5% each, and they are **one meter for the whole job**, with the step it is on
and that step's own percentage beside them. Each step counts for a share of the job, roughly its time on the test PC (reading the game
35%, translating 5%, compiling 55%, finishing 5%), so the meter is an estimate; it never goes backwards. Reading the game reports no
fraction of its own, so the menu works it out from the "N files, X GB" lines. Where
the terminal cannot take colour or arrow keys it falls back to a plain numbered prompt (`EPONA_KEYS=0` forces that, `EPONA_ASCII=1` forces
plain characters, `NO_COLOR=1` turns colour off).

| Menu item | What it does |
|---|---|
| **Start** | Asks for your game file (it looks for `.nup` files in your Downloads, Desktop and Documents and in a Downloads folder on each drive; or paste or drag a path), where to install (standard: `%USERPROFILE%\Games\Epona`), the language, then shows what is missing and asks before fetching it. Then it builds, with a progress display |
| **Check this PC** | Your processor, memory, graphics card and free disk, and what is installed or missing. Downloads nothing |
| **Downloads** | The full list of downloads: source, size, how each is checked |
| **Settings** | Change the game file, install folder, language or the number of compiles at once. These are remembered in `%LOCALAPPDATA%\Epona\settings.json` (paths, language and job count only) |
| **Help** | Where logs and settings live, and how to stop and resume |

How consent works: the menu shows the checklist, and you choose *fetch what is required*, *fetch everything missing*, *choose one by one*
or *fetch nothing*. Only what you say yes to is allowed for that run (`HOOKSHOT_AUTO_<NAME>=1`); the rest is switched off (`=0`). Putting
Python on your PATH is never part of "fetch everything": it is asked separately. Ctrl+C during a build is always safe; choose Start
again to carry on. Build logs are kept in `%LOCALAPPDATA%\Epona\logs` (the last ten).

## Running the builder from the command line

```
cd <this folder>
py -I nx2/make_game.py --nup "<your game>.nup" --out "<game folder>" --language en-US
```

Use an interactive terminal, so you can answer the questions. In order, it will:

1. Check that `python` is on PATH (if not, offers the permanent fix; `HOOKSHOT_AUTO_PYPATH=1` says yes, `=0` never asks) and the
   Python packages (offers `pip install` for what is missing).
2. Check disk, memory, CPU, graphics cards and the renderer inputs (offers the Vulkan headers).
3. Look for a compiler and offer llvm-mingw if there is none.
4. Note if the AV1 Video Extension is missing.
5. Check for FFmpeg. If it is missing, it says so and offers to download BtbN's prebuilt build (it asks first); if you decline it
   offers to stop here, so you can build it from source first (or go on: the compile is cached, and only the link waits).
6. Ask how many compiles to run at once (a number is suggested from your free memory; Enter takes it).
7. Read your game, translate it and compile it. This takes about 40 minutes or more and uses up to 60 GB.

Each question defaults to **No**. `HOOKSHOT_AUTO_PIP`, `HOOKSHOT_AUTO_MINGW`, `HOOKSHOT_AUTO_DEPS`, `HOOKSHOT_AUTO_EMSDK` and
`HOOKSHOT_AUTO_VS` set to `1` say yes ahead of time. Without an interactive terminal nothing is downloaded and the builder tells
you what to install by hand.

## Everything the builder can download (full list: `py -I nx2/make_game.py --list-tools`)

| What | From | Pinned and checked? | Where it goes | When |
|---|---|---|---|---|
| Python packages: lz4, numpy, capstone, unicorn >=2.1,<2.2, zstandard | pypi.org, through `pip` | No hash check. Only unicorn is version-pinned. pip can run a package's install code | your Python | only the ones missing |
| llvm-mingw 20261104 (`ucrt-x86_64`, 191,037,046 bytes) | github.com/mstorsjo/llvm-mingw | Yes: SHA-256 `552191b5754c49a5a20723276a6fc56541ea1922c4c50b7b669022333fc1b40f`, size checked, deleted on a mismatch | `llvm-mingw\` in this folder | no compiler set up |
| Vulkan-Headers `v1.4.345` | github.com/KhronosGroup/Vulkan-Headers | Yes, SHA-256 | `work\eg\.cache\cpm\` | no `RX_CPM` has them |
| SPIRV-Headers `vulkan-sdk-1.4.341.0` | github.com/KhronosGroup/SPIRV-Headers | Yes, SHA-256 | same | same |
| Vulkan Memory Allocator `v3.3.0` | github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator | Yes, SHA-256 | same | same |
| SDL 2.32.10 (`SDL2-2.32.10-win32-x64.zip`, 608,965 bytes); only `SDL2.dll` is taken | github.com/libsdl-org/SDL | Yes: SHA-256 `6cf9706eefd0a4a06dc764007934d428afaf029fabdd408a9e646048c91e18fb`, size checked | `third_party\sdl2\` | `SDL2.dll` missing |
| emsdk (newest), then clang and node/python tools (about 1 GB) | `git clone` of github.com/emscripten-core/emsdk, then storage.googleapis.com | **No**: not pinned, not hash-checked here. Runs `emsdk.bat` | `C:\emsdk` (or `EMSDK`) | only on the Visual Studio route |
| Visual Studio 2022 Build Tools (several GB) | `winget` (Microsoft) | Microsoft's installer. Asks Windows for administrator approval | system-wide | only on the Visual Studio route |

**FFmpeg, the quick way (`make_game.py`; `HOOKSHOT_AUTO_FFMPEG=1` says yes ahead of time):**

| What | From | Pinned and checked? | Where it goes |
|---|---|---|---|
| `ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip` (about 77 MB; 76,624,572 bytes when this was written) | github.com/FFmpeg-Builds/FFmpeg-Builds, release tag `latest` (the project, formerly `BtbN/FFmpeg-Builds`, **moved** to that organization; both names are accepted and no others) | **Not pinned**: a rolling daily build whose contents change every day. Checked against the SHA-256 GitHub lists for that file at the moment (a bad or truncated download fails). That does not make BtbN trustworthy: it publishes both the file and its digest. These are third-party binaries that are loaded into the game | `work\eg\.cache\cpm\ffmpeg\9.0-btbn\` (headers, four import libraries, four DLLs; no programs), with `EPONA-FFMPEG.txt` recording the digest and the SHA-256 of every file taken. The four DLLs are also copied beside the game |

**The FFmpeg script, the slower and checkable way** (`scripts/epona_build_ffmpeg.sh`, run by you in WSL; it asks first, `EPONA_YES=1` says yes ahead of time):

| What | From | Pinned and checked? | Where it goes |
|---|---|---|---|
| llvm-mingw 20261104, the Linux-hosted `ucrt-ubuntu-22.04-x86_64` build (84,104,244 bytes) | github.com/mstorsjo/llvm-mingw | Yes: SHA-256 `919380403de87dca3c581c2053230cd298af5e891286628ba0613b7fed370926`, size checked, deleted on a mismatch | `~/epona-ffmpeg` (scratch) |
| FFmpeg 9.0.2 source, `ffmpeg-9.0.2.tar.xz` (about 11 MB) and its `.asc` | ffmpeg.org/releases | GPG signature checked against the release key pinned in the script (FFmpeg publishes no checksum). The key's fingerprint was written from memory: confirm it on ffmpeg.org. If it is wrong the check fails and nothing is built | `~/epona-ffmpeg` (scratch), then `work\eg\.cache\cpm\ffmpeg\9.0.2\` |

It builds only the VP8 and VP9 decoders and the scaler, as static libraries, with no network code and no assembly, and records the
source and library SHA-256 values in `EPONA-BUILD.txt` beside the result. It does not use `sudo`, and nothing it builds is run.

Not downloads: the AV1 extension (the builder can open its Microsoft Store page; the Store installs it), and four read-only
questions it asks your PC: PowerShell `Get-AppxPackage` (is the AV1 extension there), PowerShell `Get-CimInstance Win32_VideoController`
(graphics card names), `IsProcessorFeaturePresent` (AVX2), disk space and memory.

The Hookshot Builder **app's** updater (not `make_game.py`) downloads `HookshotBuilder.zip` only from the repository you name
in `HOOKSHOT_UPDATE_REPO` or `update_repo.txt` (the default is none, so nothing), only from github.com for that repository,
and only if the SHA-256 GitHub lists for the file matches. It then runs the `HookshotBuilder.exe` inside, after you press Yes
in the game's update box. A game folder built from source never asks.

## Findings

What was actually measured and found while building from source with Epona's checks. One PC, one run each, so read these as one data
point, not a benchmark.

**The test PC:** Windows 11 Pro, 20 logical CPUs, 63.7 GB of RAM, an RTX 3090, AVX2, the AV1 Video Extension installed, llvm-mingw
compiler (no Visual Studio), `.nup` dump of 25.02 GB (186,592 files, 26.24 GB of romfs).

| Stage | Result |
|---|---|
| Translating the game | 294,529 functions and 17,646,501 instructions, 100.00% translated, 57 code files, **165 s** |
| Compile, 10 jobs at once | 230 files, **1,034 s (17.2 minutes)** with 31 objects already cached, 269 objects in the cache afterwards |
| Memory during that compile | **10 jobs used about 11 GB in all** (a little over 1 GB each). Free memory never fell under **37.0 GB** of 63.7; committed memory peaked at 21%; no paging |
| CPU and GPU during it | Average **54%** CPU while compiling (peak 100%), so 10 jobs did not keep 20 threads busy. GPU at most 50 °C |
| Result | Everything compiled except `host/nn_video.c` (FFmpeg headers missing), so the game was not yet linked. **And, as found afterwards, that compile did not include the Vulkan back end at all** (see below), so 17 minutes is the time for the translated game code and the host, not for the whole game |

**What the numbers changed:**
- The upstream note says one compile chunk takes 3 to 8 GB. That is for the `-O2`/`-O3` hot chunks. These `-O1` files use about 1 GB each,
  which is why the job count is now suggested from free memory at 2.5 GB a job instead of being fixed at half the CPU threads.
- The default had been "half the logical CPUs" whatever the memory. On a 16 GB PC with 8 threads that would be 4 jobs and could be too many;
  the suggestion for 11 GB free is 3.

**An unexplained freeze.** During the first compile attempt (also 10 jobs) the PC froze and restarted at about 6:04 PM (Windows logged
Kernel-Power 41, no blue screen, no GPU, disk, memory or hardware-error events). It had been slowing down before it did. The same 10 jobs
later ran for 17 minutes with free memory never under 37 GB, so **memory pressure from the build is not supported as the cause**. The PC had
also restarted uncleanly three other times in the previous day, before the build. The cause is not identified.

**Other findings:**
- **The first end-to-end run worked.** Built through the menu on the test PC, then played. The game's own log shows the Vulkan back end
  loaded on an RTX 3090 (Vulkan 1.4, mesh shaders: yes), **110,847 frames presented** over roughly an hour, and a clean exit when the
  window was closed. In its last five seconds it averaged 29 fps, with frame times mostly 30 to 40 ms (whether that was the game's own
  frame cap or a slowdown is not known). A rebuild with most of the work cached took about 9 minutes. The install folder held `hookshot.exe`
  (448 MB), `hookshot_vk.dll`, the four FFmpeg DLLs, `SDL2.dll`, the game image, the shader list, and the caches and `user` saves that only
  a played game creates. The maintainer reports that it **played well**: a personal account of one session on one PC, not a systematic test.
- **The first compile silently built no Vulkan back end, and Epona's own renderer check said everything was fine.** `nx2/build.py`
  looks for the Vulkan headers and FFmpeg in `RX_CPM`, then in `<work>/eg/.cache/cpm`, where `<work>` is the builder's folder under
  `%LOCALAPPDATA%`, not this project's `work\`. Epona's downloads went to the project's `work\`, and its check looked there too, so it
  reported success while `build.py` found nothing: it skipped `hookshot_vk.dll` without a word (its design) and `nn_video.c` could not
  find FFmpeg. It was caught only because the same error repeated after FFmpeg had been installed. The build now passes `RX_CPM` to
  `build.py`. The rebuild therefore compiles the Vulkan back end for the first time: a large C++ job whose time and memory use were not
  measured.
- **FFmpeg is required.** An early version of these notes called it optional. That was wrong: `host/nn_video.c` includes FFmpeg's headers
  and uses its scaler (`sws_scale`) and packet type even for the AV1 movies (53 FFmpeg calls in that file). Only the AV1 *decoder* is
  Windows' own.
- **The prebuilt FFmpeg project moved on GitHub.** `BtbN/FFmpeg-Builds`, which ffmpeg.org's download page still links, is now
  `FFmpeg-Builds/FFmpeg-Builds`: GitHub redirects the old name, but its release data gives download links under the new one and its
  search no longer finds the old name. The download step first refused the link ("not on github.com for BtbN/FFmpeg-Builds"), which was
  the safety check working without knowing about the move. The two names are now accepted explicitly, nothing broader. It is the same
  project (about 11.9k stars, 1,042 commits, MIT licence, updated the same day), but the new organization lists no public members, so
  that BtbN controls it could not be confirmed from public pages.
- **`wgpu-native` is not needed.** The message "building without the renderer" meant the WebGPU fallback only. The game draws with Vulkan;
  `host/rx_nowgpu.c` stands in for the fallback.
- **The speed-up data is clean.** The four files from the author's zip (`hot_funcs.txt` 849 function names, `hot_order.txt` 3,682 names,
  `image/chunks.txt` 56 hex addresses, `hookshot_pieces.prof` a 6.6 MB LLVM indexed profile) hold only addresses, `f_xxxxxxxx` names and
  counters: no URLs, paths, executables or secrets, and nothing embedded. How the build uses each one cannot run code. Reviewed by
  reading and a byte-level scan, not by trusting the author.
- **The release zip was flagged** by Windows Defender (`Trojan:Script/Sabsik.EN.A!ml`, a generic machine-learning detection). It was
  not opened, so nothing is known beyond that.
- **No unexplained network code or committed binaries** were found in the original's source (see Limits for what that covers).

## Limits

- **The prebuilt FFmpeg route has worked once.** On the maintainer's end-to-end run the download, the digest check, the extraction, the
  link with the import libraries and the game starting with the four DLLs beside it all worked (`avcodec`, `avutil`, `swscale` and
  `swresample` are in the install folder). One run on one PC is all that is known. `tests/test_epona_prompts.py` covers the extraction from
  a made-up zip and has not been run. The digest GitHub lists is replaced daily with the file, so a match proves the download is intact,
  not that the project is safe.
- **The guided menu has been driven once, by the maintainer, in Windows Terminal.** Screenshots from that use showed the arrow keys, the
  colours and the heart meter working, and they exposed three layout bugs (a header wider than the terminal, plates running together,
  clipped file names), all since fixed. A script also checked that every panel row is the same width, with colour on and off, in Unicode and
  plain characters, at 60 to 100 columns. Not seen: the first-run legal notice (added afterwards), other terminals (the old console, PowerShell
  7, VS Code's), and the whole flow on a second PC. The pure helpers have tests in `tests/test_epona_prompts.py`, not yet run. It needs a
  terminal that accepts colour codes; otherwise it falls back to a plain numbered prompt.
- **The FFmpeg script is untested.** It has been syntax-checked (`bash -n`) and never run. The configure options, the release-key
  fingerprint and whether the GNU-ABI static libraries link cleanly with this build's link line are all unproven. The first run may need
  changes, and the FFmpeg 9.0.2 headers may not match what `nn_video.c` expects.
- **The job count suggestion** is calibrated on one PC (1 GB a job measured, 2.5 GB planned). The prompt and the free-memory reading are
  untested on other machines.
- **Tested here:** Python syntax, the graphics-card name patterns on sample names, the AV1 and graphics-card queries on one PC
  (an RTX 3090 with AVX2 and the extension installed), the tool listing, and a syntax-only compile of `host/hos_update.c`.
  `tests/test_epona_prompts.py` covers the PATH merge and the four-file zip extraction in a temporary folder; it was written but
  **not yet run**. The PATH write itself ran once on the test PC (its backup file was made), and undoing it has not been tried.
- **Not tested:** the C# changes were not compiled (the project targets .NET 8 for Windows), so the builder app's logging and updater are
  unproven. The full build through Epona has been run end to end **once**, on one PC; no other hardware, no AMD or Intel card, no Linux.
- **The updater's SHA-256** proves a download matches what GitHub lists, so it catches a bad or truncated download. It does not
  prove the repository's owner is trustworthy: they publish both the file and its digest.
- **The graphics-card check is a guess from the card's name.** It only warns.
- **What was audited, in the original too:** the whole tree was searched for network, process, shell, registry, persistence,
  clipboard, anti-debug and dynamic-code calls, for every URL it names, and for committed binaries; each hit was read. Result: the
  only network code is the update check (`host/hos_update.c`, now pointed at no one by default) and the builder's updater; the
  only program launches are the AV1 Store link, the builder opening Explorer and the game, and (Linux only) a `popen` of
  `fc-match` with a fixed argument; there are no committed binaries (`a64emit.dll` and `zbic.dll` are built from source during a
  build); every URL is a documentation, GitHub, Khronos, NVIDIA, FFmpeg, dav1d, Eden or Microsoft address; `make_game.py` runs
  Visual Studio's own `vcvars64.bat` with `shell=True` on the Visual Studio route only. **Not read line by line:** the
  recompiler's and renderer's logic, and the vendored libraries (zstd, Opus, stb, Eden's and suyu's shader code). A pattern search
  cannot prove those are free of a deliberate flaw.
- **The original's prebuilt `HookshotBuilder.zip`** is not used by this fork. On one test PC, Windows Defender flagged a release
  zip of it as `Trojan:Script/Sabsik.EN.A!ml`, a generic machine-learning detection that often hits builders bundling Python
  and compilers. This was never confirmed as a real threat or a false alarm. Building from source avoids that file.
- **Legal:** the original is an unofficial fan project and Nintendo does take such projects down. Never post game files, keys
  or dumps.
