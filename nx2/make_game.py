"""A game folder from the user's own dump: what the builder app (builder/) runs.

    python -I nx2/make_game.py --nup <file.nup> --out <folder> [--work <folder>] [--jobs <n>]
    python -I nx2/make_game.py --romfs <dir> --exefs <dir> --out <folder> [--work <folder>] [--jobs <n>]
    python -I nx2/make_game.py --check --nup <file.nup>       (or --exefs <dir>: is this the right game and version?)
    python -I nx2/make_game.py --update <folder>             (a folder built before, again with these tools: the game files it keeps)

The folder holds the executable and all it needs, started with a double click: nothing goes back into the repository, and no game
data ever comes with the tools. Lines the app reads, each on its own line of stdout:

    @@stage <id> <text>      a step begins
    @@progress <0..1>        how far that step is
    @@check <ok|bad> <text>  (--check) the answer
    @@done <folder>          finished
    @@error <text>           stopped
"""
import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = [sys.executable, "-I", "-u", "-X", "utf8"]   # (utf8: every step's output in UTF-8 whatever the console's code page: lift.py crashed on a letter, #180)   # (-u: the steps' output as it comes, not in 8 KB blocks minutes apart)
BUILD_ID = "e0f3ccfa"   # (the version the patches, the hot list and the profile were made from)
LINUX = os.name != "nt"
BESIDE = ["hookshot", "hookshot_vk.so", "libSDL2-2.0.so.0"] if LINUX else ["hookshot.exe", "hookshot_vk.dll", "SDL2.dll", "wgpu_native.dll"]
LANGUAGES = [("en-US", "English (US)"), ("en-GB", "English (UK)"), ("fr", "French (France)"), ("fr-CA", "French (Canada)"), ("de", "German"),
             ("it", "Italian"), ("es", "Spanish (Spain)"), ("es-419", "Spanish (Latin America)"), ("pt-BR", "Portuguese (Brazil)"), ("nl", "Dutch"),
             ("pl", "Polish"), ("ru", "Russian"), ("ja", "Japanese"), ("ko", "Korean"), ("zh-Hans", "Chinese (Simplified)"),
             ("zh-Hant", "Chinese (Traditional)")]


def no_throttle(handle=None):
    """(issue 87) Windows' power throttling (EcoQoS) slows a background window's processes to almost nothing on some machines: the
    build sat at 0% CPU. Turned off for this process, or the one whose handle this is"""
    if os.name != "nt":
        return
    import ctypes
    class State(ctypes.Structure):
        _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]
    k = ctypes.WinDLL("kernel32")
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    s = State(1, 1, 0)   # (PROCESS_POWER_THROTTLING_EXECUTION_SPEED in the mask, off in the state)
    try:
        k.SetProcessInformation(ctypes.c_void_p(int(handle)) if handle else k.GetCurrentProcess(), 4, ctypes.byref(s), ctypes.sizeof(s))
    except (OSError, ValueError, TypeError):
        pass


UI = None   # (nx2/epona_ui.py's screen, while the guided menu runs this: it draws the "@@" lines and the build's output instead of printing them)


def emit(line):
    """One line of output: printed as it is, or handed to the guided menu to draw"""
    if UI is not None:
        UI.line(line)
    else:
        print(line, flush=True)


def say(*words):
    emit("@@" + " ".join(str(w) for w in words))


def fail(text):
    say("error", text)
    sys.exit(1)


def failure_reason(lines):
    """The line a stopped step is named with. Only the last 12 lines used to be kept, so a compiler's "error:" hundreds
    of lines earlier was replaced by "compiled in 790s, 1 failed"."""
    tail, seen = [], None
    for line in lines:
        tail = (tail + [line])[-12:]
        if "error:" in line.lower() and "CalledProcessError" not in line:
            seen = line
    if seen is not None:
        return seen
    return tail[-1] if tail else "no output"


def reported(line):
    """The sentence a builder shows. @@check is '@@check <ok|bad> <text>'; @@error is '@@error <text>'. None otherwise."""
    if line.startswith("@@error "):
        return line[len("@@error "):]
    if line.startswith("@@check "):
        parts = line.split(" ", 2)
        return parts[2] if len(parts) == 3 else ""
    return None


def run(cmd, env=None, on_line=None):
    e = dict(os.environ, PYTHONIOENCODING="utf-8")
    e.update(env or {})
    p = subprocess.Popen(cmd, cwd=ROOT, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace", bufsize=1)
    no_throttle(getattr(p, "_handle", None))
    lines = []
    try:
        for line in p.stdout:
            line = line.rstrip()
            emit(line)
            lines.append(line)
            if on_line:
                on_line(line)
        failed = p.wait()
    except KeyboardInterrupt:
        # (Ctrl+C: the step and every compiler it started stop with it, and are not left running in the background using memory)
        if os.name == "nt":
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            p.kill()
        raise
    if failed:
        step = next((os.path.basename(c) for c in cmd[1:] if c.endswith(".py")), os.path.basename(cmd[-1]))   # (issue 154: not "-u")
        fail("%s stopped: %s" % (step, failure_reason(lines)))


def build_id(main):
    """the module id of an NSO, plain or compressed: the header is the same"""
    with open(main, "rb") as f:
        head = f.read(0x60)
    if head[:4] != b"NSO0":
        fail("%s is not a game executable" % main)
    return head[0x40:0x60].hex()


def check_modules(exefs):
    """Every module of the exefs is one the tools can read: said here, not as a Python error from the translator"""
    for name in os.listdir(exefs):
        if name != "main.npdm" and not name.endswith(".part"):
            with open(os.path.join(exefs, name), "rb") as f:
                head = f.read(16)
            if head[:4] != b"NSO0":
                fail("The file %s in this dump is not a game module (it starts %s). Try another dump of the game, or send this message to the "
                     "Hookshot developers." % (name, head.hex()))


def check_supported_build(exefs):
    bid = build_id(os.path.join(exefs, "main"))
    if not bid.startswith(BUILD_ID):
        fail("This is build %s. Hookshot supports build %s." % (bid[:8], BUILD_ID))


def check_cache_paths(out, paths):
    """Resolve generated paths and reject symbolic links/reparse points before replacement."""
    root = os.path.realpath(out)
    for path in paths:
        try:
            inside = os.path.commonpath((root, os.path.realpath(path))) == root
        except ValueError:
            inside = False
        attrs = os.lstat(path) if os.path.lexists(path) else None
        linked = os.path.islink(path) or bool(
            getattr(attrs, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        if not inside or linked:
            fail("The generated cache path %s is not a normal path inside the build folder (symbolic links and reparse points are not supported). "
                 "Choose a different output folder." % path)


def check(a, work):
    check_windows_sdk()   # (first: said in plain words when the game is chosen, not after it has been read)
    if a.nup:
        probe = os.path.join(work, "probe")
        shutil.rmtree(probe, ignore_errors=True)
        run(PY + ["nx2/nup.py", a.nup, "--extract", probe, "--only", "exefs"])
        check_modules(os.path.join(probe, "exefs"))
        bid = build_id(os.path.join(probe, "exefs", "main"))
        shutil.rmtree(probe, ignore_errors=True)
    else:
        bid = build_id(os.path.join(a.exefs, "main"))
    if bid.startswith(BUILD_ID):
        say("check", "ok", "This is the version Hookshot supports (build %s)." % bid[:8])
    else:
        say("check", "bad", "This is build %s. Hookshot supports build %s." % (bid[:8], BUILD_ID))


def visual_studio_environment():
    """What Visual Studio's own vcvars64.bat sets, for a compiler that does not find it by itself; None without one"""
    vswhere = os.path.join(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"), "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.exists(vswhere):
        return None
    r = subprocess.run([vswhere, "-latest", "-prerelease", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                        "-property", "installationPath"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = r.stdout.strip().splitlines()
    if not lines:
        return None
    bat = os.path.join(lines[-1], "VC", "Auxiliary", "Build", "vcvars64.bat")
    if not os.path.exists(bat):
        return None
    r = subprocess.run('"%s" >nul && set' % bat, shell=True, capture_output=True, text=True, encoding="mbcs", errors="replace")
    keep = ("INCLUDE", "LIB", "LIBPATH", "PATH", "VCINSTALLDIR", "VCTOOLSINSTALLDIR", "VCTOOLSVERSION", "WINDOWSSDKDIR", "WINDOWSSDKVERSION",
            "UCRTVERSION", "UNIVERSALCRTSDKDIR")
    found = {}
    for line in r.stdout.splitlines():
        name, eq, value = line.partition("=")
        if eq and name.upper() in keep:
            found[name] = value
    return found if any(k.upper() == "INCLUDE" for k in found) else None


def windows_kits_environment(base):
    """INCLUDE and LIB with the Windows SDK's C library (ucrt) and headers added from where its installer puts them: Visual Studio's
    vcvars leaves them out when the SDK came apart from it (issue 89: 'stdio.h' file not found with MSVC installed). None without one"""
    kits = os.path.join(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"), "Windows Kits", "10")
    inc = os.path.join(kits, "Include")
    try:
        versions = sorted((v for v in os.listdir(inc) if os.path.exists(os.path.join(inc, v, "ucrt", "stdio.h"))),
                          key=lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")])
    except OSError:
        return None
    if not versions:
        return None
    v = versions[-1]
    env = dict(base or {})
    get = lambda k: next((env[n] for n in env if n.upper() == k), os.environ.get(k, ""))
    env["INCLUDE"] = ";".join(x for x in [get("INCLUDE")] + [os.path.join(inc, v, d) for d in ("ucrt", "um", "shared", "winrt")] if x)
    env["LIB"] = ";".join(x for x in [get("LIB")] + [os.path.join(kits, "Lib", v, d, "x64") for d in ("ucrt", "um")] if x)
    print("the Windows SDK %s from %s" % (v, kits), flush=True)
    return env


def compile_test(toolchain):
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w") as f:
            # (_UCRT: the C library of Visual Studio 2015 and later. An older one's stdio.h compiled, and the link failed 40 minutes later
            # on __iob_func: issue 80)
            f.write(chr(10).join(("#include <stdio.h>", "#ifndef _UCRT", "#error \"stdio.h is from an old C library (before Visual Studio 2015)\"",
                                  "#endif", "#include <windows.h>", "int main(void) { return 0; }", "")))
        return subprocess.run([toolchain.need(toolchain.find("clang"))] + toolchain.native_target() + ["-c", src, "-o", os.path.join(d, "t.o")],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")


def check_cpp_library(toolchain):
    """Check the renderer's C++20 library features before the long build (issues 39 and 100)."""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.cpp")
        with open(src, "w") as f:
            # Projected find: frontend/maxwell/structured_control_flow.cpp; predicate find and
            # comparator sort: ir_opt/texture_pass.cpp (under gpu/vk/eden/shader_recompiler).
            f.write(chr(10).join(("#include <algorithm>", "#include <format>", "#include <string>", "#include <vector>",
                                  "std::string t(int v) { return std::vformat(\"{}\", std::make_format_args(v)); }",
                                  "namespace { struct Entry { int value; }; }",
                                  "bool ranges_test() {",
                                  "    std::vector<Entry> entries{{2}, {1}};",
                                  "    const auto found = std::ranges::find(entries, 1, &Entry::value);",
                                  "    const auto matching = std::ranges::find_if(entries, [](const Entry& e) { return e.value == 2; });",
                                  "    std::ranges::sort(entries, [](const Entry& a, const Entry& b) { return a.value < b.value; });",
                                  "    return found != entries.end() && matching != entries.end();",
                                  "}", "")))
        r = subprocess.run([toolchain.need(toolchain.find("clang++"))] + toolchain.native_target() + ["-std=c++20", "-c", src, "-o", os.path.join(d, "t.o")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(r.stdout + r.stderr, flush=True)
        fail("Your Visual Studio is too old for this game's renderer. Open the Visual Studio Installer, press Update on "
             "Visual Studio 2022 (or install it), then build again.")


def check_linux_compiler():
    """(linux) A C compiler that builds and links a program here (the AppImage's own clang and sysroot, else the system's):
    found now, not 40 minutes in"""
    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
    import toolchain
    cc = toolchain.find("clang")
    if not os.path.isfile(cc):
        fail("No C compiler was found. Install clang (and lld), or use the Hookshot AppImage, which brings its own.")
    sysroot = os.environ.get("HOOKSHOT_SYSROOT")
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w") as f:
            f.write(chr(10).join(("#include <stdio.h>", "#include <pthread.h>", "int main(void) { return 0; }", "")))
        r = subprocess.run([cc] + (["--sysroot=" + sysroot] if sysroot else []) + ["-fuse-ld=lld", src, "-o", os.path.join(d, "t")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(r.stdout + r.stderr, flush=True)
        errors = [l for l in r.stderr.splitlines() if "error" in l]
        fail("The compiler could not build a test program: %s (install clang, lld and your system's C library headers: "
             "libc6-dev on Debian and Ubuntu, glibc-devel on Fedora)" % (errors[0] if errors else "no message"))


def bundled_mingw():
    """(as TotK Recomp's installer) llvm-mingw in the tools folder: its clang, headers and libraries build the game, and nothing of
    Visual Studio or the Windows SDK is needed. HOOKSHOT_MINGW set already wins; HOOKSHOT_MSVC=1: the Visual Studio route"""
    if LINUX or os.environ.get("HOOKSHOT_MSVC") == "1":
        return os.environ.get("HOOKSHOT_MINGW", "")
    if not os.environ.get("HOOKSHOT_MINGW"):
        here = os.path.join(ROOT, "llvm-mingw")
        if os.path.isfile(os.path.join(here, "bin", "clang.exe")):
            os.environ["HOOKSHOT_MINGW"] = here
    return os.environ.get("HOOKSHOT_MINGW", "")


def check_mingw():
    """The bundled compiler builds and links a Windows program: found now, not 40 minutes in"""
    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
    import toolchain
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w") as f:
            f.write(chr(10).join(("#include <stdio.h>", "#include <windows.h>", "int main(void) { return 0; }", "")))
        r = subprocess.run([toolchain.need(toolchain.find("clang"))] + toolchain.native_target() + toolchain.native_link() +
                           [src, "-o", os.path.join(d, "t.exe")], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(r.stdout + r.stderr, flush=True)
        errors = [l for l in r.stderr.splitlines() if "error" in l]
        fail("The builder's own compiler (tools/llvm-mingw) could not build a test program: %s. Unpack the zip again into a folder "
             "your antivirus allows." % (errors[0] if errors else "no message"))
    print("the compiler: %s (no Visual Studio needed)" % os.environ["HOOKSHOT_MINGW"], flush=True)


def install_build_tools():
    """Offer Microsoft's free Visual Studio 2022 Build Tools (C++ tools and a Windows 11 SDK) through winget, for the
    MSVC route only (llvm-mingw needs none). Asks first (or HOOKSHOT_AUTO_VS=1). Windows asks for administrator
    approval. Returns True if it installed."""
    if os.environ.get("HOOKSHOT_AUTO_VS") == "0":   # (=0: declined ahead of time, as the guided menu does)
        return False
    if os.environ.get("HOOKSHOT_AUTO_VS") != "1":
        if not sys.stdin or not sys.stdin.isatty():
            return False
        print("The Windows SDK / C++ tools were not found. Install Microsoft's Visual Studio 2022 Build Tools with winget "
              "(several GB; Windows will ask for administrator approval)? Or answer N and set HOOKSHOT_MINGW to an "
              "llvm-mingw folder instead. [y/N] ", end="", flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            return False
    winget = shutil.which("winget")
    if not winget:
        print("winget was not found: install the Build Tools by hand from https://visualstudio.microsoft.com/downloads/", flush=True)
        return False
    r = subprocess.run([winget, "install", "--id", "Microsoft.VisualStudio.2022.BuildTools", "-e",
                        "--accept-package-agreements", "--accept-source-agreements", "--override",
                        "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools "
                        "--add Microsoft.VisualStudio.Component.Windows11SDK.22621 --includeRecommended"])
    return r.returncode in (0, 3010)   # (3010: installed, restart wanted)


# (llvm-mingw's release asset, as GitHub publishes it: size and SHA-256 are from its release data)
LLVM_MINGW = ("20261104", "llvm-mingw-20261104-ucrt-x86_64.zip", 191037046,
              "552191b5754c49a5a20723276a6fc56541ea1922c4c50b7b669022333fc1b40f")


def fetch_llvm_mingw():
    """Offer the Windows compiler that needs no Visual Studio: llvm-mingw (about 182 MB, github.com/mstorsjo/llvm-mingw),
    unpacked into <project>/llvm-mingw, which bundled_mingw() uses by itself. Asks first, or HOOKSHOT_AUTO_MINGW=1.
    Checked against the published SHA-256. Returns True if it is there afterwards."""
    here = os.path.join(ROOT, "llvm-mingw")
    if os.path.isfile(os.path.join(here, "bin", "clang.exe")):
        return True
    if os.environ.get("HOOKSHOT_AUTO_MINGW") == "0":
        return False
    if os.environ.get("HOOKSHOT_AUTO_MINGW") != "1":
        if not sys.stdin or not sys.stdin.isatty():
            return False
        print("No Windows C++ compiler was set up. Download llvm-mingw %s (about 182 MB, from github.com/mstorsjo/llvm-mingw) into %s? "
              "It needs no Visual Studio. Answer N to use Visual Studio instead. [y/N] " % (LLVM_MINGW[0], here), end="", flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            return False
    import hashlib, urllib.request, zipfile
    tag, name, size, sha = LLVM_MINGW
    url = "https://github.com/mstorsjo/llvm-mingw/releases/download/%s/%s" % (tag, name)
    part = os.path.join(ROOT, "work", name + ".part")
    os.makedirs(os.path.dirname(part), exist_ok=True)
    h, got, shown = hashlib.sha256(), 0, 0
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if got - shown >= 32 << 20:
                    shown = got
                    print("  llvm-mingw: %d of %d MB" % (got >> 20, size >> 20), flush=True)
    except OSError as e:
        print("could not download %s: %s" % (url, e), flush=True)
        return False
    if got != size or h.hexdigest() != sha:
        os.remove(part)
        fail("The download of %s does not match its published size and SHA-256, so it was not used and has been deleted." % url)
    tmp = here + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(part) as z:   # (extractall drops absolute and ".." paths)
        z.extractall(tmp)
    os.remove(part)
    inner = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
    src = os.path.join(tmp, inner[0]) if len(inner) == 1 and not os.path.isdir(os.path.join(tmp, "bin")) else tmp
    shutil.rmtree(here, ignore_errors=True)
    os.replace(src, here)
    shutil.rmtree(tmp, ignore_errors=True)
    print("installed llvm-mingw %s" % tag, flush=True)
    return os.path.isfile(os.path.join(here, "bin", "clang.exe"))


def check_windows_sdk():
    """The compiler is bundled; Microsoft's C library and Windows SDK may not be, by their licences. Found now, not 40 minutes in."""
    if LINUX:
        return check_linux_compiler()
    if not bundled_mingw() and os.environ.get("HOOKSHOT_MSVC") != "1" and fetch_llvm_mingw():
        bundled_mingw()   # (picks up <project>/llvm-mingw)
    if bundled_mingw():
        return check_mingw()
    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
    import toolchain
    # (an INCLUDE set for the whole machine, by an old Visual Studio or another tool, is all clang reads: without the Windows SDK's C
    # library in it, it is dropped and the compiler looks for Visual Studio itself. Issues 80 and 89)
    for k in [n for n in os.environ if n.upper() == "INCLUDE"]:
        if "ucrt" not in os.environ[k].lower():
            print("INCLUDE is set on this PC without the Windows SDK's C library: not used (%s)" % os.environ[k][:200], flush=True)
            for n in [n for n in os.environ if n.upper() in ("INCLUDE", "LIB", "LIBPATH")]:
                del os.environ[n]
            break
    r = compile_test(toolchain)
    found = None
    if r.returncode:   # (clang looks for Visual Studio its own way, and does not always find it: then ask Visual Studio)
        found = visual_studio_environment()
        if found:
            print("the compiler did not find Visual Studio by itself: using vcvars64", flush=True)
            os.environ.update(found)
            r = compile_test(toolchain)
    if r.returncode and found and ("stdio.h" in r.stderr or "windows.h" in r.stderr.lower()):
        # (only on top of vcvars' INCLUDE: clang takes INCLUDE as all of its system headers once it is set)
        kits = windows_kits_environment(found)
        if kits:
            for k in [n for n in os.environ if n.upper() in ("INCLUDE", "LIB")]:
                del os.environ[k]
            os.environ.update(kits)
            r = compile_test(toolchain)
    if not r.returncode:
        check_cpp_library(toolchain)
        return
    if not getattr(check_windows_sdk, "tried_install", False) and \
            any(s in r.stderr.lower() for s in ("stdio.h", "windows.h", "file not found")):
        check_windows_sdk.tried_install = True
        if install_build_tools():
            return check_windows_sdk()   # (looked for again, now that Visual Studio's tools are there)
    print(r.stdout + r.stderr, flush=True)   # (all of it, for Show details)
    errors = [l for l in r.stderr.splitlines() if "error:" in l]
    why = errors[0].split("error:", 1)[1].strip() if errors else (r.stderr.strip().splitlines() or ["no message"])[-1]
    if "old c library" in why.lower():
        fail("The compiler found an old Visual Studio's C library (from before 2015) instead of the Windows SDK's. In the Visual Studio "
             "Installer choose Modify on Visual Studio 2022, tick \"Desktop development with C++\" with a Windows 11 SDK, then build again. (%s)" % why)
    if "windows.h" in why.lower() or "stdio.h" in why.lower():
        fail("The Windows SDK was not found. In the Visual Studio Installer choose Modify, and under \"Desktop development with C++\" tick a "
             "Windows 11 SDK, then build again. (%s)" % why)
    if "file not found" in why:
        fail("Visual Studio's C++ tools were not found. In the Visual Studio Installer choose Modify, tick \"Desktop development with C++\" "
             "and its MSVC x64/x86 build tools, then build again. (%s)" % why)
    fail("The compiler could not run a test build: %s" % why)


def drop_stale_objects(work):
    """(issue 231) Objects compiled against other system headers are not reused. A first build that compiled with an old Visual Studio's
    stdio.h (before 2015) left its objects in the cache; once the PC was fixed every later build reused them and the link failed on
    __iob_func. The headers the compiler finds are noted, and when they change the compiled objects go"""
    if LINUX:
        return
    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
    import hashlib
    import toolchain
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w") as f:
            f.write(chr(10).join(("#include <stdio.h>", "#include <stdlib.h>", "#include <windows.h>", "")))
        r = subprocess.run([toolchain.need(toolchain.find("clang"))] + toolchain.native_target() + ["-M", src], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    if r.returncode:
        return
    heads = sorted({h.lower() for h in re.findall(r"\S+\.h\b", r.stdout.replace("\\" + chr(10), " "))})
    stamp = hashlib.sha1(chr(10).join(heads).encode()).hexdigest()
    note = os.path.join(work, "system_headers.txt")
    try:
        with open(note) as f:
            if f.read().strip() == stamp:
                return
    except OSError:
        pass
    for sub in (os.path.join(work, "objcache"), os.path.join(work, "sa", "build", "obj")):
        if os.path.isdir(sub):
            print("the system headers changed since the last build: its compiled objects are not reused (%s)" % sub, flush=True)
            shutil.rmtree(sub, ignore_errors=True)
    with open(note, "w") as f:
        f.write(stamp + chr(10))


def folder_language(out):
    """the language a game folder was built in: the code line of its language.txt"""
    try:
        with open(os.path.join(out, "language.txt"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and any(line == code for code, _ in LANGUAGES):
                    return line
    except OSError:
        pass
    return None


def profile_readable(prof):
    """(linux) the profile is made by a recent clang (the Windows tools'): an older one, the system's, cannot read it and stops the
    build. Then the game is built without it (a little slower in play), not at all"""
    if not LINUX:
        return True
    sys.path.insert(0, os.path.join(ROOT, "third_party", "a64-kit", "tools"))
    import toolchain
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "t.c")
        with open(src, "w") as f:
            f.write("int f(int x) { return x + 1; }" + chr(10))
        r = subprocess.run([toolchain.find("clang"), "-O2", "-Wno-everything", "-fprofile-instr-use=" + prof, "-c", src, "-o",
                            os.path.join(d, "t.o")], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print("this compiler cannot read the play profile (%s): building without it" % (r.stderr.strip().splitlines() or ["?"])[-1],
              flush=True)
    return r.returncode == 0


def link_or_copy(src, dst):
    """the romfs by hard links where the disk allows: 26 GB not written twice"""
    files = [os.path.join(d, f) for d, _, fs in os.walk(src) for f in fs]
    for i, s in enumerate(files):
        t = os.path.join(dst, os.path.relpath(s, src))
        os.makedirs(os.path.dirname(t), exist_ok=True)
        if not os.path.exists(t):
            try:
                os.link(s, t)
            except OSError:
                shutil.copy2(s, t)
        if i % 500 == 0:
            say("progress", "%.3f" % (i / max(1, len(files))))


def shader_census_cmd(romfs, out):
    """The shader list, under the same UTF-8 mode as the other steps. -I alone follows the console's code page, and an
    archive name that page cannot print stopped this step: the game then compiled its shaders as it played."""
    return PY + [os.path.join(HERE, "shader_census.py"), romfs, "--out", out]


def merge_path(current, add):
    """A PATH value with the folders in add put in front of it (those already in it left where they are); None when there is nothing to add"""
    have = [p for p in current.split(";") if p]
    norm = lambda p: os.path.normcase(p.rstrip("\\/"))
    new = [a for a in add if norm(a) not in {norm(p) for p in have}]
    return ";".join(new + have) if new else None


def offer_python_path(folder):
    """The permanent fix, offered before the build goes on: this Python on the user's PATH, so `python` works in every new terminal.
    Only the current user's PATH changes (HKCU\\Environment), with no administrator rights, and the old value is saved to
    work/user_path_before.txt to undo it. HOOKSHOT_AUTO_PYPATH=1 says yes ahead of time, =0 never asks."""
    if os.name != "nt" or os.environ.get("HOOKSHOT_AUTO_PYPATH") == "0" or not (sys.stdin and sys.stdin.isatty()):
        return
    if UI is not None and os.environ.get("HOOKSHOT_AUTO_PYPATH") != "1":   # (the guided menu asks on its checklist)
        return
    scripts = os.path.join(folder, "Scripts")
    saved = os.path.join(ROOT, "work", "user_path_before.txt")
    if os.environ.get("HOOKSHOT_AUTO_PYPATH") != "1":
        print("Fix it for good?\n  This puts these two folders at the front of YOUR user PATH (your account only, no administrator rights):\n"
              "    %s\n    %s\n  The old PATH is saved to %s so you can undo it. New terminal windows then find python.\n"
              "  y = fix it now    Enter = go on, using it for this run only    (Ctrl+C stops the build)   [y/N] " % (folder, scripts, saved),
              end="", flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            try:
                current, kind = winreg.QueryValueEx(k, "Path")
            except FileNotFoundError:
                current, kind = "", winreg.REG_EXPAND_SZ
            new = merge_path(current, [folder, scripts])
            if new is None:
                print("Your user PATH already has them; open a new terminal window.", flush=True)
                return
            os.makedirs(os.path.dirname(saved), exist_ok=True)
            with open(saved, "w", encoding="utf-8") as f:
                f.write(current + "\n")
            winreg.SetValueEx(k, "Path", 0, kind if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) else winreg.REG_EXPAND_SZ, new)
        import ctypes   # (tell running programs the environment changed; new terminal windows pick it up)
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000, None)
        print("Done. Open a NEW terminal window for `python` to work there; this run already has it. Undo: put the line in %s back as your user PATH." % saved, flush=True)
    except OSError as e:
        print("Could not change your PATH (%s); going on for this run only." % e, flush=True)


def ensure_python_on_path():
    """Tools the build starts (emsdk.bat, for one) run plain "python". Many Windows PCs only have the "py" launcher, or
    the Microsoft Store stub that opens the Store. If so, put the Python running this build first on PATH, for this
    run only (nothing on the PC is changed)."""
    if LINUX:
        return
    found = shutil.which("python")
    if found and "WindowsApps" not in found:
        return
    folder = os.path.dirname(os.path.abspath(sys.executable))
    if not os.path.isfile(os.path.join(folder, "python.exe")):
        return
    os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
    print("'python' was not on PATH; using %s for this run" % folder)
    offer_python_path(folder)


PYTHON_PACKAGES = (("lz4", "lz4"), ("numpy", "numpy"), ("capstone", "capstone"), ("unicorn", "unicorn>=2.1,<2.2"),
                   ("zstandard", "zstandard"))   # (module name, what pip installs)


def ensure_python_packages():
    """Checked first: a missing package otherwise stops the build after the game is half extracted. Offers pip install
    (asks first, or HOOKSHOT_AUTO_PIP=1)."""
    import importlib, importlib.util
    missing = [pkg for mod, pkg in PYTHON_PACKAGES if importlib.util.find_spec(mod) is None]
    if not missing:
        return
    hand = "py -m pip install " + " ".join('"%s"' % m for m in missing)
    if os.environ.get("HOOKSHOT_AUTO_PIP") != "1":
        if not sys.stdin or not sys.stdin.isatty():
            fail("Python packages are missing: %s. Install them with: %s" % (", ".join(missing), hand))
        print("Python packages are missing: %s. Install them with pip now? [y/N] " % ", ".join(missing), end="", flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            fail("Install the missing packages with: " + hand)
    # (the two flags only quiet pip: the "Scripts not on PATH" warning and the "new pip" notice are no use here)
    if subprocess.call([sys.executable, "-m", "pip", "install", "--no-warn-script-location", "--disable-pip-version-check"] + missing) != 0:
        fail("pip could not install: %s. Try it by hand: %s" % (", ".join(missing), hand))
    importlib.invalidate_caches()
    # (this run is isolated (py -I), which ignores the per-user package folder pip may have used)
    still = [pkg for mod, pkg in PYTHON_PACKAGES if importlib.util.find_spec(mod) is None]
    if still:
        fail("Installed, but this run cannot see: %s. Run the build again." % ", ".join(still))


HEADERS_HOME = os.path.join(ROOT, "work", "eg", ".cache", "cpm")   # (where nx2/build.py's cpm_dirs looks first, with no RX_CPM)
# (name, GitHub repo, tag, SHA-256 of that tag's .tar.gz): the versions scripts/linux/deps.sh uses for the Linux AppImage
HEADER_PACKAGES = (
    ("vulkanheaders", "KhronosGroup/Vulkan-Headers", "v1.4.345", "99E19205DF172C33229F18B5574C9258BC73EA229EC7D6B04DAA357B2430F6C8"),
    ("spirv-headers", "KhronosGroup/SPIRV-Headers", "vulkan-sdk-1.4.341.0", "CAB0A654C4917E16367483296B44CDB1D614E3120C721BEAFCD37E3A8580486C"),
    ("vulkanmemoryallocator", "GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator", "v3.3.0", "C4F6BBE6B5A45C2EB610CA9D231158E313086D5B1A40C9922CB42B597419B14E"),
)


def fetch_vulkan_headers():
    """The Vulkan back end's headers (about 4 MB from github.com), unpacked into work/eg/.cache/cpm: asks first, or
    HOOKSHOT_AUTO_DEPS=1. Each archive is checked against its SHA-256 (if GitHub ever repacks a tag, update the hash here after
    comparing it with the source). Returns True if they were installed."""
    if os.environ.get("HOOKSHOT_AUTO_DEPS") == "0":
        return False
    if os.environ.get("HOOKSHOT_AUTO_DEPS") != "1":
        if not sys.stdin or not sys.stdin.isatty():
            return False
        print("The Vulkan and SPIR-V headers were not found. Download them (about 4 MB, from github.com/KhronosGroup and "
              "GPUOpen) into %s? [y/N] " % HEADERS_HOME, end="", flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            return False
    import hashlib, io, tarfile, urllib.request
    for name, repo, tag, sha in HEADER_PACKAGES:
        dest = os.path.join(HEADERS_HOME, name, tag)
        if os.path.isdir(dest) and os.listdir(dest):
            continue
        url = "https://github.com/%s/archive/refs/tags/%s.tar.gz" % (repo, tag)
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
        except OSError as e:
            print("could not download %s: %s" % (url, e), flush=True)
            return False
        if hashlib.sha256(data).hexdigest().upper() != sha:
            fail("The download of %s does not match the expected SHA-256, so it was not used. If GitHub repacked the tag, check the "
                 "source and update HEADER_PACKAGES." % url)
        part = dest + ".part"
        shutil.rmtree(part, ignore_errors=True)
        os.makedirs(part)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
            top = t.getnames()[0].split("/")[0]
            for m in t.getmembers():   # (the archive's top folder dropped; nothing outside the destination, no links)
                rel = m.name.split("/", 1)[1] if "/" in m.name else ""
                target = os.path.realpath(os.path.join(part, rel))
                if not rel or m.issym() or m.islnk() or not (target + os.sep).startswith(os.path.realpath(part) + os.sep):
                    continue
                if m.isdir():
                    os.makedirs(target, exist_ok=True)
                elif m.isfile():
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as f:
                        f.write(t.extractfile(m).read())
        shutil.rmtree(dest, ignore_errors=True)
        os.replace(part, dest)
        print("installed %s %s" % (name, tag), flush=True)
    return True


def physical_memory_gb(available=False):
    """The PC's memory in GB (available=True: the part that is free right now); 0 when it cannot be told"""
    try:
        import ctypes

        class Mem(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                       [(f, ctypes.c_ulonglong) for f in ("phys", "avail_phys", "page", "avail_page", "virt", "avail_virt", "avail_ext")]
        m = Mem()
        m.length = ctypes.sizeof(m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return (m.avail_phys if available else m.phys) / 2 ** 30
    except (OSError, AttributeError):
        pass
    return 0


def suggested_jobs():
    """The compiles to run at once: as many as the FREE memory allows, up to the number of logical CPUs. Measured on a 64 GB PC with 20
    threads (Epona's findings): 10 jobs used about 11 GB in all, a little over 1 GB each (free memory never fell under 37 GB) and the whole
    compile took 17 minutes at 54% average CPU. The upstream note of 3 to 8 GB a job is for the -O2/-O3 hot chunks, not these -O1 files, so
    this plans 2.5 GB a job and uses at most 70% of what is free right now: 46 GB free gives 12, 11 GB free gives 3, 5 GB free gives 1."""
    cpus = max(1, os.cpu_count() or 2)
    gb = physical_memory_gb(available=True)
    return max(1, cpus // 2) if not gb else max(1, min(cpus, int(gb * 0.7 / 2.5)))


def default_jobs():
    """HOOKSHOT_JOBS if you set it, else suggested_jobs()"""
    if os.environ.get("HOOKSHOT_JOBS"):
        return max(1, int(os.environ["HOOKSHOT_JOBS"]))
    return suggested_jobs()


def choose_jobs(explicit):
    """The number of parallel compiles. --jobs or HOOKSHOT_JOBS decide it; otherwise it is suggested from the memory that is free, and in an
    interactive terminal you are asked, so you can type your own number (Enter takes the suggestion)."""
    if explicit:
        return max(1, explicit)
    n = default_jobs()
    if os.environ.get("HOOKSHOT_JOBS") or not (sys.stdin and sys.stdin.isatty()):
        return n
    cpus, gb = os.cpu_count() or 2, physical_memory_gb(available=True)
    print("Parallel compiles: %d suggested (%s, %d CPU threads). More is faster until the memory runs out: 10 jobs used about 11 GB on a 64 GB PC.\n"
          "  Enter = %d, or type your own number (1 to %d; --jobs or HOOKSHOT_JOBS skips this question): " %
          (n, "%.0f GB of memory free" % gb if gb else "free memory unknown", cpus, n, cpus), end="", flush=True)
    answer = sys.stdin.readline().strip()
    if not answer:
        return n
    if not answer.isdigit() or not 1 <= int(answer) <= 4 * cpus:
        print("That is not a number I can use; taking %d." % n, flush=True)
        return n
    chosen = int(answer)
    if gb and chosen * 2.5 > gb * 0.9:
        print("Note: %d jobs may want more memory than is free (%.0f GB). The build keeps its finished work, so Ctrl+C is safe if the PC slows down." % (chosen, gb), flush=True)
    return chosen


def update_repo():
    """The GitHub repository ("owner/name") whose releases the game's update offer and the builder's updater use: HOOKSHOT_UPDATE_REPO,
    else the first line of update_repo.txt beside this project. None when unset or not in that form: then there is no update offer."""
    repo = os.environ.get("HOOKSHOT_UPDATE_REPO", "")
    path = os.path.join(ROOT, "update_repo.txt")
    if not repo.strip() and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            repo = f.readline()
    repo = repo.strip()
    return repo if re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo) else None


def print_tools():
    """--list-tools: everything this builder can download or install, from where, how it is checked and how to say yes or no ahead of
    time. It downloads nothing. (The same list is in EPONA.md.)"""
    print("""Everything this builder can fetch. Each step asks first (y/N) unless you set its HOOKSHOT_AUTO_* variable to 1.
Nothing is fetched until you answer. Fetching does not run what is fetched, but the build afterwards RUNS the tools it got (the compiler, the
Python packages), and the steps marked RUNS run an installer.

Python packages (pip, from pypi.org; only the ones that are missing)
  %s
  Not hash-checked by this builder (unicorn is version-pinned, the rest take the newest). pip can run a package's install code.
  Say yes ahead of time: HOOKSHOT_AUTO_PIP=1

Windows compiler: llvm-mingw %s (only if no compiler is set up; HOOKSHOT_MINGW or HOOKSHOT_MSVC=1 skips this)
  https://github.com/mstorsjo/llvm-mingw/releases/download/%s/%s
  %d bytes, SHA-256 %s (checked; a mismatch deletes it)
  Unpacked into: %s   Say yes ahead of time: HOOKSHOT_AUTO_MINGW=1""" % (
        ", ".join(p for _, p in PYTHON_PACKAGES), LLVM_MINGW[0], LLVM_MINGW[0], LLVM_MINGW[1], LLVM_MINGW[2], LLVM_MINGW[3],
        os.path.join(ROOT, "llvm-mingw")))
    print("""
Vulkan back-end headers (only if no RX_CPM / work\\eg\\.cache\\cpm has them; source archives, about 4 MB, nothing is built from them here)""")
    for name, repo, tag, sha in HEADER_PACKAGES:
        print("  %s %s: https://github.com/%s/archive/refs/tags/%s.tar.gz\n    SHA-256 %s (checked)" % (name, tag, repo, tag, sha))
    print("  Unpacked into: %s   Say yes ahead of time: HOOKSHOT_AUTO_DEPS=1" % HEADERS_HOME)
    print("""
Controller library SDL2.dll (only if third_party\\sdl2\\SDL2.dll is missing; the game builds without it, with no controller support)
  https://github.com/libsdl-org/SDL/releases/download/release-%s/%s
  %d bytes, SHA-256 %s (checked; only SDL2.dll is taken from the zip)
  Unpacked into: %s   Say yes ahead of time: HOOKSHOT_AUTO_SDL=1""" % (
        SDL2[0], SDL2[1], SDL2[2], SDL2[3], os.path.join(ROOT, "third_party", "sdl2")))
    print("""
FFmpeg (required), one of two ways, each asking first:
  A. BtbN's prebuilt shared build, fetched by this script (HOOKSHOT_AUTO_FFMPEG=1 says yes ahead of time; --ffmpeg-zip uses a zip you downloaded):
     https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip  (about 77 MB)
     (the project, formerly BtbN/FFmpeg-Builds, moved to the FFmpeg-Builds organization on GitHub; only these two names are accepted)
     A ROLLING daily build, so it cannot be pinned: it is checked against the SHA-256 GitHub lists for it that day. That catches a bad or
     truncated download; it does not make BtbN trustworthy. Only the headers, 4 import libraries and 4 DLLs are taken out of it (no programs);
     the DLLs are copied beside the game. Into work\\eg\\.cache\\cpm\\ffmpeg\\9.0-btbn
  B. scripts/epona_build_ffmpeg.sh, which YOU run in WSL's Ubuntu, downloads (asking first,
  EPONA_YES=1 says yes ahead of time):
  llvm-mingw 20261104 Linux build: https://github.com/mstorsjo/llvm-mingw/releases/download/20261104/llvm-mingw-20261104-ucrt-ubuntu-22.04-x86_64.tar.xz
    84104244 bytes, SHA-256 919380403de87dca3c581c2053230cd298af5e891286628ba0613b7fed370926 (checked)
  FFmpeg 9.0.2 source: https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz (about 11 MB) and its .asc: GPG signature checked against the release key
    pinned in the script (FFmpeg publishes no checksum)
  and builds the VP8/VP9 decoders and the scaler, as static libraries, into %s\\ffmpeg\\9.0.2. Uses no sudo, runs nothing it builds.""" % HEADERS_HOME)
    print("""
Only on the Visual Studio route (HOOKSHOT_MSVC=1, or you answered N to llvm-mingw):""")
    print("""
  emsdk: git clone (needs git) of https://github.com/emscripten-core/emsdk (newest, not pinned, not hash-checked), then its own
    'emsdk install' fetches clang and node/python tools from storage.googleapis.com (about 1 GB). RUNS emsdk.bat, which runs what it fetched.
    HOOKSHOT_AUTO_EMSDK=1, EMSDK_VERSION=<release>
  Visual Studio 2022 Build Tools: winget install Microsoft.VisualStudio.2022.BuildTools (Microsoft's installer, several GB, asks
    Windows for administrator approval). RUNS Microsoft's installer. HOOKSHOT_AUTO_VS=1

Not a download: Microsoft's AV1 Video Extension. If missing, this offers to open its Microsoft Store page (the Store does the install).

Read-only questions it asks your PC: PowerShell Get-AppxPackage (is the AV1 extension installed), Get-CimInstance Win32_VideoController
  (graphics card names), IsProcessorFeaturePresent (AVX2), disk space and memory.

The Hookshot Builder app's updater (not this script) downloads HookshotBuilder.zip only from the repository named in HOOKSHOT_UPDATE_REPO or
  update_repo.txt (none set: nothing), only over https from github.com for that repository, and only if the SHA-256 GitHub lists matches. RUNS the
  HookshotBuilder.exe inside, after you click Yes in the game's update box.""")


def cpu_has_avx2():
    """None when it cannot be told. The game is built for x86-64-v3 (AVX2, FMA, BMI: Haswell and Zen 1 on), see CPU in nx2/build.py;
    an older CPU crashes at start with 0xc000001d (issue 363)."""
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))   # (PF_AVX2_INSTRUCTIONS_AVAILABLE)
    except (OSError, AttributeError):
        return None


# (graphics cards named by Windows that have no Vulkan mesh shaders, which the world needs: the readme's "Vulkan 1.3 and mesh shaders", and the
# release notes' known problem "GPUs without mesh shaders (GTX 10xx, RX 5000) can't render the world". A guess from the name, so a note and no stop)
GPUS_WITHOUT_MESH = re.compile(
    r"\bGTX\s?(?:10|9|7|6)\d{2}\b|\bGT\s?\d{3,4}\b|\bTITAN\s?(?:X|Xp|V)?\b(?!.*RTX)|\bQuadro\s?[PKM]\d|"
    r"\bRX\s?(?:[45]\d{2}|5\d{3})\b|\bVega\b|\bRadeon\s?(?:HD|R[579])\b|"
    r"\b(?:UHD|HD) Graphics\b|\bIris\b.{0,6}\b(?:Xe|Plus)\b", re.I)


def graphics_cards():
    """The names of the PC's graphics cards, as Windows lists them; [] when it cannot be told"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def check_cpu_gpu(problems, notes):
    avx2 = cpu_has_avx2()
    if avx2 is False:
        if os.environ.get("RX_MARCH"):
            notes.append("This CPU has no AVX2; building for RX_MARCH=%s (slower, and not tested)." % os.environ["RX_MARCH"])
        else:
            problems.append("This CPU has no AVX2, which the game is built for (Intel Haswell / AMD Zen 1 or newer): it would crash at start. "
                            "RX_MARCH=x86-64 builds for older CPUs (slower, and not tested).")
    cards = graphics_cards()
    weak = [c for c in cards if GPUS_WITHOUT_MESH.search(c)]
    if weak:
        notes.append("Graphics card%s %s probably %s no Vulkan mesh shaders, which the game's world needs (it may show a black screen or "
                     "crash). Cards that do: NVIDIA GTX 16 / RTX 20 and newer, AMD RX 6000 and newer, Intel Arc.%s"
                     % ("s" if len(weak) > 1 else "", ", ".join(weak), "have" if len(weak) > 1 else "has",
                        " On a laptop with another card, make sure Windows uses that one for the game (Settings > Graphics)."
                        if len(cards) > len(weak) else ""))
    elif cards and not any(re.search(r"NVIDIA", c, re.I) for c in cards):
        notes.append("Only NVIDIA cards have been tested (%s); AMD and Intel reports are open on the project's issue page." % ", ".join(cards))


# (the four data files of the release's tools\work that the build reads: scripts' CI takes the same four. Addresses and counts, no game code)
WORK_DATA = ("hot_funcs.txt", "hot_order.txt", "hookshot_pieces.prof", "image/chunks.txt")


def offer_work_data():
    """Offered before the build goes on, when work/image is missing: take those four data files out of a HookshotBuilder.zip the user
    downloaded themselves. Nothing is downloaded, and only those four named files are read out of the zip; nothing in it is run.
    True if work/image exists afterwards."""
    if os.environ.get("HOOKSHOT_SKIP_WORKDATA") == "1" or not (sys.stdin and sys.stdin.isatty()):   # (SKIP: the guided menu asked already)
        return False
    print("The speed-up data (work\\image: the hot-function list, link order and play profile) is not here. The game builds without it but runs\n"
          "  slower. It is only in the author's HookshotBuilder.zip (its tools\\work folder). If you downloaded that zip yourself, type its path:\n"
          "  only these four data files are read from it (%s) and nothing in it is run.\n"
          "  Enter = go on without it.   Path to the zip: " % ", ".join(WORK_DATA), end="", flush=True)
    path = sys.stdin.readline().strip().strip('"')
    if not path:
        return False
    return take_work_data(path)


def take_work_data(path):
    """Read those four data files out of the zip at path (and nothing else). True if work/image exists afterwards."""
    here = os.path.join(ROOT, "work")
    import zipfile
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        print("Could not open that as a zip (%s); going on without the data." % e, flush=True)
        return False
    got = []
    with z:
        for name in z.namelist():
            norm = name.replace("\\", "/")
            for want in WORK_DATA:
                if norm in ("HookshotBuilder/tools/work/" + want, "tools/work/" + want):
                    if z.getinfo(name).file_size > 256 << 20:
                        continue
                    dest = os.path.join(here, *want.split("/"))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with z.open(name) as src, open(dest + ".part", "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    os.replace(dest + ".part", dest)
                    got.append(want)
    print("Took %d of %d data files from the zip: %s" % (len(got), len(WORK_DATA), ", ".join(got) or "none (is it the right zip?)"), flush=True)
    return os.path.isdir(os.path.join(here, "image"))


# BtbN's prebuilt FFmpeg 9.0 (shared, LGPL): a ROLLING daily build (the release tag "latest" is replaced each day), so there is no hash to pin
# (the project moved on GitHub from BtbN/FFmpeg-Builds to the FFmpeg-Builds organization: GitHub still redirects the old name, but its release data
# now gives download links under the new one. Exactly these two names are accepted, nothing broader; whether BtbN controls the new organization
# cannot be seen from its public pages, which list no members)
FFMPEG_PREBUILT = ("FFmpeg-Builds/FFmpeg-Builds", "latest", "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip")
FFMPEG_PREBUILT_NAMES = ("ffmpeg-builds/ffmpeg-builds", "btbn/ffmpeg-builds")


def prebuilt_url_ok(url):
    """Is this download link on github.com, under one of the two accepted repository names, as a release download? (case-insensitive, as GitHub is)"""
    return any(url.lower().startswith("https://github.com/%s/releases/download/" % n) for n in FFMPEG_PREBUILT_NAMES)

FFMPEG_NEEDED_LIBS = ("avcodec", "swscale", "swresample", "avutil")
FFMPEG_DLL = re.compile(r"(avcodec|avutil|swscale|swresample)-\d+\.dll")
FFMPEG_HOME = os.path.join(HEADERS_HOME, "ffmpeg", "9.0-btbn")


def ffmpeg_dlls(d):
    """The FFmpeg DLLs that go beside the game (a shared build has them in bin/; a static one has none)"""
    b = os.path.join(d, "bin") if d else ""
    return sorted(os.path.join(b, f) for f in os.listdir(b) if FFMPEG_DLL.fullmatch(f)) if os.path.isdir(b) else []


def extract_ffmpeg_zip(z, dest):
    """From an FFmpeg shared-build zip take ONLY what the build needs, into dest: the headers (include/**/*.h), the four import libraries
    (lib/<name>.lib) and the four DLLs (bin/<name>-<n>.dll). Nothing else in the zip is read out: no program (ffmpeg.exe and the others), no
    other DLL, no documentation, and nothing that would land outside dest. Returns [(relative path, sha256)]; ValueError when something
    the build needs is not in the zip."""
    import hashlib
    want_libs = {"lib/%s.lib" % n for n in FFMPEG_NEEDED_LIBS}
    root = os.path.realpath(dest)
    written = []
    for info in z.infolist():
        if info.is_dir():
            continue
        parts = info.filename.replace("\\", "/").split("/")
        if len(parts) < 3 or ".." in parts or parts[0] in ("", "."):
            continue
        rel = "/".join(parts[1:])   # (the zip's own top folder dropped)
        take = (parts[1] == "include" and rel.endswith(".h")) or rel in want_libs or \
               (parts[1] == "bin" and len(parts) == 3 and FFMPEG_DLL.fullmatch(parts[2]) is not None)
        if not take:
            continue
        target = os.path.realpath(os.path.join(dest, *rel.split("/")))
        if not (target + os.sep).startswith(root + os.sep):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        h = hashlib.sha256()
        with z.open(info) as src, open(target, "wb") as out:
            for chunk in iter(lambda: src.read(1 << 20), b""):
                out.write(chunk)
                h.update(chunk)
        written.append((rel, h.hexdigest()))
    have = {r for r, _ in written}
    missing = [r for r in sorted(want_libs) + ["include/libavcodec/avcodec.h"] if r not in have]
    for n in FFMPEG_NEEDED_LIBS:   # (all four DLLs: a missing one and the game does not start)
        if not any(r.startswith("bin/") and re.fullmatch(re.escape(n) + r"-\d+\.dll", os.path.basename(r)) for r in have):
            missing.append("bin/%s-<n>.dll" % n)
    if missing:
        raise ValueError("the zip does not hold what the build needs: " + ", ".join(missing))
    return written


def fetch_ffmpeg(zip_path=None):
    """Offer BtbN's prebuilt FFmpeg 9.0 shared build (github.com/BtbN/FFmpeg-Builds, about 77 MB): the quick way to the FFmpeg the game needs.
    Asks first, or HOOKSHOT_AUTO_FFMPEG=1; zip_path (--ffmpeg-zip) uses a zip you downloaded yourself. It is a rolling daily build, so there is
    no pinned hash: the zip is checked against the SHA-256 GitHub lists for that file right now. That catches a bad or truncated download; it
    does not make BtbN trustworthy, since the same project publishes both. Only the headers, four import libraries and four DLLs are taken
    out of it (extract_ffmpeg_zip); the DLLs are copied beside the game. True if FFmpeg is in place afterwards."""
    repo, tag, asset = FFMPEG_PREBUILT
    if not zip_path and os.environ.get("HOOKSHOT_AUTO_FFMPEG") == "0":
        return False
    if not zip_path and os.environ.get("HOOKSHOT_AUTO_FFMPEG") != "1":
        if not (sys.stdin and sys.stdin.isatty()):
            return False
        print("Download the prebuilt FFmpeg 9.0 from BtbN's builds (%s, about 77 MB, github.com/%s, formerly BtbN/FFmpeg-Builds)?\n"
              "  A rolling daily build: it is checked against the SHA-256 GitHub lists for it today. Only the headers, 4 libraries and 4 DLLs are\n"
              "  taken out of it (no programs); the DLLs go beside the game. Into %s   [y/N] " % (asset, repo, FFMPEG_HOME), end="", flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            return False
    import hashlib, json, urllib.request, zipfile

    def listed():
        req = urllib.request.Request("https://api.github.com/repos/%s/releases/tags/%s" % (repo, tag),
                                     headers={"User-Agent": "epona-make-game", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            rel = json.load(r)
        a = next((x for x in rel.get("assets", []) if x.get("name") == asset), None)
        if not a or not str(a.get("digest", "")).startswith("sha256:") or len(a["digest"]) != 7 + 64:
            raise OSError("GitHub lists no SHA-256 for %s, so it will not be used" % asset)
        url = a["browser_download_url"]
        if not prebuilt_url_ok(url):
            raise OSError("the download link (%s) is not a github.com release download of %s or its old name BtbN/FFmpeg-Builds, so it will not be used" % (url, repo))
        return url, int(a["size"]), a["digest"][7:].lower()

    part = os.path.join(ROOT, "work", asset + ".part")
    try:
        os.makedirs(os.path.dirname(part), exist_ok=True)
        zipfile_path = None
        for attempt in (1, 2):   # (the file is replaced once a day: a second look if it changed while it was downloading)
            url, size, want = listed()
            h = hashlib.sha256()
            if zip_path:
                with open(zip_path, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                path = zip_path
            else:
                got, shown = 0, 0
                req = urllib.request.Request(url, headers={"User-Agent": "epona-make-game"})
                with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
                    for chunk in iter(lambda: r.read(1 << 20), b""):
                        f.write(chunk)
                        h.update(chunk)
                        got += len(chunk)
                        if got - shown >= 16 << 20:
                            shown = got
                            print("  FFmpeg: %d of %d MB" % (got >> 20, size >> 20), flush=True)
                path = part
            if h.hexdigest() == want:
                zipfile_path = path
                print("FFmpeg zip: SHA-256 matches the one GitHub lists (%s)" % want, flush=True)
                break
            if not zip_path:
                os.remove(part)
            print("The zip's SHA-256 (%s) is not the one GitHub lists (%s)%s" % (h.hexdigest(), want,
                  ": looking again" if attempt == 1 else ""), flush=True)
        if not zipfile_path:
            fail("The FFmpeg zip does not match the SHA-256 GitHub lists for it, so it was not used%s." %
                 (" (this build is replaced daily: download it again)" if zip_path else ""))
        dest = FFMPEG_HOME + ".part"
        shutil.rmtree(dest, ignore_errors=True)
        with zipfile.ZipFile(zipfile_path) as z:
            written = extract_ffmpeg_zip(z, dest)
        with open(os.path.join(dest, "EPONA-FFMPEG.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write("FFmpeg from %s, release tag %s, file %s\nSHA-256 of the zip, as GitHub listed it: %s\nfiles taken out of it (SHA-256):\n" %
                    (repo, tag, asset, want))
            f.writelines("  %s  %s\n" % (d, r) for r, d in written)
        shutil.rmtree(FFMPEG_HOME, ignore_errors=True)
        os.replace(dest, FFMPEG_HOME)
        if not zip_path and os.path.exists(part):
            os.remove(part)
    except (OSError, zipfile.BadZipFile, ValueError) as e:
        print("could not get FFmpeg: %s\n  It asked https://api.github.com/repos/%s/releases/tags/%s . To check by hand, open https://github.com/%s/releases/tag/%s\n"
              "  in a browser. A \"404\" there means the repository or the release moved; \"403\" usually means GitHub's anonymous rate limit (try later).\n"
              "  Or download %s yourself and run again with --ffmpeg-zip <that file>." % (e, repo, tag, repo, tag, asset), flush=True)
        return False
    print("installed FFmpeg into %s (%d files; its DLLs will be copied beside the game)" % (FFMPEG_HOME, len(written)), flush=True)
    return ffmpeg_dir() is not None


def ffmpeg_dir():
    """The FFmpeg folder nx2/build.py would use (headers in include/, static libraries in lib/, in a CPM cache's ffmpeg/<version>/), or None.
    The same places as build.py's cpm_dirs()."""
    for r in (os.environ.get("RX_CPM"), HEADERS_HOME, os.path.join(os.path.dirname(ROOT), "mkw-recomp", "work", "eg", ".cache", "cpm"),
              os.path.join(os.path.dirname(ROOT), "Eglantine", ".cache", "cpm")):
        top = os.path.join(r, "ffmpeg") if r else None
        if top and os.path.isdir(top):
            for v in sorted(os.listdir(top)):
                d = os.path.join(top, v)
                if os.path.isfile(os.path.join(d, "include", "libavcodec", "avcodec.h")) and \
                        all(os.path.isfile(os.path.join(d, "lib", n + ".lib")) for n in ("avcodec", "swscale", "swresample", "avutil")):
                    return d
    return None


def check_ffmpeg(zip_path=None):
    """FFmpeg is not optional: host/nn_video.c includes its headers, and even the AV1 movies go through its swscale and packet type. Without it
    the compile ends with that one file failing (the rest is built and kept). Said now, with the choice to stop and add it first."""
    if ffmpeg_dir():
        return
    print("note: FFmpeg (its headers and the static libraries avcodec, swscale, swresample and avutil) was not found. The game needs it: without it\n"
          "  the compile builds everything else and then fails on host\\nn_video.c, and the game cannot be linked. Build it from source with\n"
          "  scripts/epona_build_ffmpeg.sh (in WSL; see EPONA.md), or put an FFmpeg folder at %s\\ffmpeg\\<version>\\{include,lib} (lib\\avcodec.lib ...)." % HEADERS_HOME,
          flush=True)
    if fetch_ffmpeg(zip_path):   # (asks first: the prebuilt, checked download)
        return
    if UI is not None or not (sys.stdin and sys.stdin.isatty()):   # (in the guided menu this was asked, and answered, on its checklist)
        return
    print("  1 = stop now, so you can add FFmpeg first      Enter = go on anyway (the compile is cached; the link waits for FFmpeg)   [1/Enter] ", end="", flush=True)
    if sys.stdin.readline().strip() == "1":
        say("error", "Stopped before the compile so FFmpeg can be added first (scripts/epona_build_ffmpeg.sh, see EPONA.md). Nothing is lost: run the "
            "same command again afterwards.")
        sys.exit(0)


# (SDL2's own release asset, size and SHA-256 as GitHub lists them: the controller library the game loads beside itself, host/pad_sdl.c)
SDL2 = ("2.32.10", "SDL2-2.32.10-win32-x64.zip", 608965, "6cf9706eefd0a4a06dc764007934d428afaf029fabdd408a9e646048c91e18fb")


def fetch_sdl2():
    """Offer SDL2.dll (about 0.6 MB, github.com/libsdl-org/SDL) for third_party/sdl2: controllers need it, the build does not. Asks first,
    or HOOKSHOT_AUTO_SDL=1. Checked against the published size and SHA-256; only SDL2.dll is taken from the zip. True if it is there."""
    dll = os.path.join(ROOT, "third_party", "sdl2", "SDL2.dll")
    if os.path.isfile(dll):
        return True
    if os.environ.get("HOOKSHOT_AUTO_SDL") == "0":
        return False
    if os.environ.get("HOOKSHOT_AUTO_SDL") != "1":
        if not sys.stdin or not sys.stdin.isatty():
            return False
        print("SDL2.dll (controller support) was not found. Download SDL %s (0.6 MB, from github.com/libsdl-org/SDL) into %s? [y/N] "
              % (SDL2[0], os.path.dirname(dll)), end="", flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            return False
    import hashlib, io, urllib.request, zipfile
    version, name, size, sha = SDL2
    url = "https://github.com/libsdl-org/SDL/releases/download/release-%s/%s" % (version, name)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read(size + 1)
    except OSError as e:
        print("could not download %s: %s" % (url, e), flush=True)
        return False
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
        fail("The download of %s does not match its published size and SHA-256, so it was not used." % url)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        with z.open("SDL2.dll") as src, open(dll + ".part", "wb") as dst:
            shutil.copyfileobj(src, dst)
    os.replace(dll + ".part", dll)
    print("installed SDL2.dll %s" % version, flush=True)
    return True


def vulkan_headers_present():
    """Are the Vulkan and SPIR-V headers in a CPM cache that nx2/build.py searches?"""
    cpm = [d for d in (os.environ.get("RX_CPM"), HEADERS_HOME,
                       os.path.join(os.path.dirname(ROOT), "mkw-recomp", "work", "eg", ".cache", "cpm"),
                       os.path.join(os.path.dirname(ROOT), "Eglantine", ".cache", "cpm")) if d and os.path.isdir(d)]
    has = lambda name: any(os.path.isdir(os.path.join(d, name)) and os.listdir(os.path.join(d, name)) for d in cpm)
    return has("vulkanheaders") and has("spirv-headers")


def llvm_mingw_present():
    """Is a Windows compiler that needs no Visual Studio set up (HOOKSHOT_MINGW, or <project>/llvm-mingw)?"""
    for d in (os.environ.get("HOOKSHOT_MINGW"), os.path.join(ROOT, "llvm-mingw")):
        if d and os.path.isfile(os.path.join(d, "bin", "clang.exe" if os.name == "nt" else "clang")):
            return True
    return False


def sdl2_present():
    return os.path.isfile(os.path.join(ROOT, "third_party", "sdl2", "SDL2.dll"))


def work_data_present():
    return os.path.isdir(os.path.join(ROOT, "work", "image"))


def av1_installed():
    """Microsoft's AV1 Video Extension: True, False, or None when it cannot be told"""
    if LINUX:
        return True
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "(Get-AppxPackage -Name Microsoft.AV1VideoExtension | Measure-Object).Count"],
                           capture_output=True, text=True, timeout=30)
        return int(r.stdout.strip().splitlines()[-1]) > 0
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def check_requirements(out, work):
    """Everything else a build needs, said now and not 40 minutes in: 64-bit Windows, disk, memory, and a renderer to build.
    (A clone has none of the HookshotBuilder zip's tools folder: cpm, wgpu-native, SDL2.dll, work; the readme lists them.)"""
    problems, notes = [], []
    if sys.maxsize <= 2 ** 32:
        problems.append("This Python is 32-bit. Install 64-bit Python 3.")
    seen = set()
    for label, path in (("the output and work folders", out), ("the work folder", work)):
        drive = os.path.splitdrive(os.path.abspath(path))[0].upper()
        if drive in seen:   # (one note per drive: both folders are usually on C:)
            continue
        seen.add(drive)
        try:
            free = shutil.disk_usage(path).free / 2 ** 30
        except OSError:
            continue
        if free < 55:   # (the readme says about 60 GB while building; a little under is not worth stopping for)
            notes.append("Only %.0f GB free on %s (%s); the build needs about 60 GB." % (free, drive or path, label))
    try:
        import ctypes

        class Mem(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                       [(f, ctypes.c_ulonglong) for f in ("phys", "avail_phys", "page", "avail_page", "virt", "avail_virt", "avail_ext")]
        m = Mem()
        m.length = ctypes.sizeof(m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)) and m.phys / 2 ** 30 < 15:
            notes.append("This PC has %.0f GB of memory; Hookshot wants 16 GB or more, and the build may run out." % (m.phys / 2 ** 30))
    except (OSError, AttributeError):
        pass
    check_cpu_gpu(problems, notes)
    # (nx2/build.py builds the Vulkan back end only when a CPM cache has the Vulkan and SPIR-V headers, and the WebGPU one only
    # when wgpu-native is found. With neither, the build still "succeeds" and the game cannot draw)
    vulkan = vulkan_headers_present()
    if not vulkan and fetch_vulkan_headers():
        vulkan = vulkan_headers_present()
    wgpu_root = os.environ.get("WGPU_NATIVE") or os.path.join(os.path.expanduser("~"), "Desktop", "TOTKPort", "third_party", "wgpu-native")
    wgpu = os.path.isfile(os.path.join(wgpu_root, "include", "webgpu", "webgpu.h"))
    if not vulkan and not wgpu:
        problems.append("No renderer can be built from this folder: set RX_CPM to a folder with the Vulkan and SPIR-V headers "
                        "(tools\\cpm in the HookshotBuilder zip) and WGPU_NATIVE to wgpu-native (tools\\wgpu-native). See \"What you "
                        "need\" in the readme.")
    elif not vulkan:
        notes.append("The Vulkan back end will not be built (RX_CPM has no vulkanheaders and spirv-headers); Hookshot is tested on Vulkan.")
    if not os.path.isfile(os.path.join(ROOT, "third_party", "sdl2", "SDL2.dll")) and not fetch_sdl2():
        notes.append("third_party\\sdl2\\SDL2.dll is not there: the game will build without controller support.")
    if not os.path.isdir(os.path.join(ROOT, "work", "image")) and not offer_work_data():
        notes.append("work\\image (the hot-function list, link order and profile, from the zip's tools\\work) is not there: "
                     "the game builds but runs slower.")
    for n in notes:
        print("note: " + n, flush=True)
    if problems:
        fail(" ".join(problems))
    check_av1_extension()


AV1_STORE_PAGE = "ms-windows-store://pdp/?ProductId=9MVZQVXJBQ9V"   # (the same page host/mf_av1.c opens)


def check_av1_extension():
    """The game's movies are AV1, which Windows decodes through Microsoft's free AV1 Video Extension (Microsoft.AV1VideoExtension).
    Without it they show as a green screen and the intro never ends (host/mf_av1.c). Said now, as a note and not a stop: the build
    does not need it, the game does. Offers to open the Store page (it asks first)."""
    if av1_installed() is not False or UI is not None:   # (installed, or cannot tell: said nothing; in the guided menu it is on the checklist)
        return
    print("note: Microsoft's AV1 Video Extension is not installed. The game's movies need it: without it they show a green screen "
          "and the intro never ends. Install it from the Microsoft Store (free): " + AV1_STORE_PAGE, flush=True)
    if sys.stdin and sys.stdin.isatty():
        print("Open the Microsoft Store page for it now? [y/N] ", end="", flush=True)
        if sys.stdin.readline().strip().lower() in ("y", "yes"):
            try:
                os.startfile(AV1_STORE_PAGE)
            except OSError:
                print("could not open the Store: search for \"AV1 Video Extension\" in it", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--nup")
    p.add_argument("--romfs")
    p.add_argument("--exefs")
    p.add_argument("--out")
    p.add_argument("--work", default=os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "hookshot-builder")
                   if LINUX else os.path.join(os.environ.get("LOCALAPPDATA", ROOT), "HookshotBuilder"))
    # (HOOKSHOT_JOBS: fewer compilers on a PC short of memory; the AppImage's builds pass no --jobs)
    p.add_argument("--jobs", type=int, default=None, help="compiles at once (default: suggested from the free memory, and asked in a terminal; HOOKSHOT_JOBS sets it too)")
    p.add_argument("--language", default="en-US", help="the game's language: a code from LANGUAGES, written to language.txt")
    p.add_argument("--check", action="store_true")
    p.add_argument("--ffmpeg-zip", help="a BtbN FFmpeg shared-build zip you downloaded yourself; it is checked against GitHub's SHA-256 and used instead of downloading")
    p.add_argument("--ui", action="store_true", help="the guided menu (running with no arguments in a terminal does the same)")
    p.add_argument("--ui-preview", action="store_true", help="draw the guided menu's screens once, asking nothing and building nothing, to look at them")
    p.add_argument("--list-tools", action="store_true", help="show everything this builder can download or install, and where from; downloads nothing")
    p.add_argument("--update", help="a game folder built before: built again from the game files it keeps (the game's update offer)")
    a = p.parse_args()
    if a.ui_preview or a.ui or (len(sys.argv) == 1 and sys.stdin and sys.stdin.isatty() and sys.stdout.isatty()):
        sys.path.insert(0, HERE)   # (-I leaves the script's folder off the path)
        import epona_ui
        mg = sys.modules[__name__]
        return epona_ui.preview(mg) if a.ui_preview else epona_ui.run(mg)
    if a.list_tools:
        return print_tools()
    ensure_python_on_path()
    ensure_python_packages()
    os.makedirs(a.work, exist_ok=True)
    no_throttle()
    if os.name == "nt":   # (the PC kept awake while this runs: a build is 45 minutes, and sleep stopped it)
        import ctypes
        ctypes.WinDLL("kernel32").SetThreadExecutionState(0x80000000 | 0x00000001)
    if a.check:
        return check(a, a.work)
    if a.update:
        a.out = a.update
        a.language = folder_language(a.update) or a.language
    if not a.out or not (a.update or a.nup or (a.romfs and a.exefs)):
        fail("needs --out, and --nup or --romfs with --exefs")
    out = os.path.abspath(a.out)
    work = os.path.abspath(a.work)
    os.makedirs(out, exist_ok=True)
    # (linux) the compiler probe waits until the compile. The game-free cache test stops at the lift, and a missing
    # compiler is still said before the long compile, not after the package has been read
    if not LINUX:
        check_requirements(out, work)
        check_windows_sdk()
        check_ffmpeg(a.ffmpeg_zip)
    a.jobs = choose_jobs(a.jobs)   # (asked last, just before the long compile)
    drop_stale_objects(work)
    exefs = os.path.join(work, "exefs")
    romfs = os.path.join(out, "romfs")

    say("stage", "read", "Reading your game files")
    shutil.rmtree(exefs, ignore_errors=True)
    kept = os.path.join(out, ".hookshot_exefs")   # (the game's code as read, kept in the folder: what an update builds from again)
    if a.update:
        if not os.path.isdir(kept) or not os.path.isdir(romfs):
            fail("This game folder has no copy of the game files to update from: it was built before updates came in. Choose your game files "
                 "in Hookshot Builder and build into the same folder once; updates after that work by themselves.")
        check_cache_paths(out, (kept, romfs))
        shutil.copytree(kept, exefs)
        check_modules(exefs)
    elif a.nup:
        # (what an earlier build left is not kept without a reason to trust it: builders before the compressed .nup fix wrote those files as
        # they lay, so a folder they left held broken game data, and the game crashed at start over its empty dictionaries)
        game = os.path.join(out, ".game")
        good = os.path.join(out, ".hookshot_romfs")
        check_cache_paths(out, (game, good, kept, romfs))
        # (an update of the builder over the same .nup: nothing to read again, only what the build needs. Issues 21 and 28)
        st = os.stat(a.nup)
        stamp = "unpacked by this builder: %s %d" % (os.path.basename(a.nup), st.st_size)
        same = False
        if os.path.exists(good) and os.path.isdir(romfs) and os.path.isdir(kept):
            with open(good) as f:
                same = f.read().strip() == stamp
        if same:
            print("the game was read from this .nup before: reading it again is skipped", flush=True)
            shutil.copytree(kept, exefs)
        else:
            shutil.rmtree(game, ignore_errors=True)
            run(PY + ["nx2/nup.py", a.nup, "--extract", game])
            # Keep the last usable cache until the new package has been read and validated.
            staged_exefs = os.path.join(game, "exefs")
            check_modules(staged_exefs)
            check_supported_build(staged_exefs)
            if not os.path.isdir(os.path.join(game, "romfs")):
                fail("The package did not contain a romfs folder.")
            if os.path.exists(romfs):
                shutil.rmtree(romfs)
            shutil.move(os.path.join(game, "romfs"), romfs)
            shutil.move(staged_exefs, exefs)
            shutil.rmtree(game, ignore_errors=True)
            shutil.rmtree(kept, ignore_errors=True)
            shutil.copytree(exefs, kept)
            with open(good, "w") as f:
                f.write(stamp + chr(10))
        check_modules(exefs)
    else:
        shutil.copytree(a.exefs, exefs)   # (unpacked in place: the user's copy stays as it is)
        run(PY + ["nx2/unpack.py", exefs])
        link_or_copy(a.romfs, romfs)
        check_cache_paths(out, (kept,))
        shutil.rmtree(kept, ignore_errors=True)
        shutil.copytree(exefs, kept)
    check_supported_build(exefs)

    # (made once on the development PC: lists of addresses and counts, no game code)
    for name in ("hot_funcs.txt", "hot_order.txt", "hookshot_pieces.prof", "hookshot.res"):
        src = os.path.join(ROOT, "work", name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(work, name))
    os.makedirs(os.path.join(work, "image"), exist_ok=True)
    src = os.path.join(ROOT, "work", "image", "chunks.txt")   # (where the lifted code's files begin: addresses)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(work, "image", "chunks.txt"))
    env = {"OOT_WORK": work, "OOT_EXEFS": exefs, "OOT_ROMFS": romfs, "OOT_DUMP": out, "RX_RELEASE": "1", "A64_HOT_CHUNK": "1"}
    if os.path.exists(os.path.join(work, "hot_funcs.txt")):
        env["A64_HOT_FUNCS"] = os.path.join(work, "hot_funcs.txt")
    if os.path.exists(os.path.join(work, "hookshot_pieces.prof")) and profile_readable(os.path.join(work, "hookshot_pieces.prof")):
        env["RX_PGO"] = os.path.join(work, "hookshot_pieces.prof")
    # (nx2/build.py looks for the Vulkan headers and FFmpeg in RX_CPM first, then in <work>/eg/.cache/cpm; and <work> is the builder's own
    # folder under LOCALAPPDATA, not this project's work/ where the downloads above are put. Without this it found neither: it skipped the
    # Vulkan back end without a word, and nn_video.c could not find FFmpeg's headers)
    if not os.environ.get("RX_CPM") and os.path.isdir(HEADERS_HOME):
        env["RX_CPM"] = HEADERS_HOME

    say("stage", "lift", "Translating the game to PC code")
    run(PY + ["nx2/lift.py", "--standalone", "--write", "--exefs", exefs, "--work", work], env)
    if os.path.isfile(os.path.join(work, "sa", "gen", "code_hot.c")):
        run(PY + ["nx2/split_hot.py", os.path.join(work, "sa", "gen")], env)   # (eight files side by side: ~6 minutes, not 79)

    if LINUX:
        check_linux_compiler()
    say("stage", "compile", "Compiling")
    done = {"n": 0, "of": 1}

    def compiled(line):
        m = re.match(r"(\d+) files, ", line)
        if m:
            done["of"] = int(m.group(1))
        elif re.match(r"\s+\S+\s+\d+ MB\s+\d+s", line):
            done["n"] += 1
            say("progress", "%.3f" % (done["n"] / done["of"]))
    run(PY + ["nx2/build.py", "--standalone", "--jobs", str(a.jobs)], env, compiled)

    say("stage", "finish", "Putting the game folder together")
    built = os.path.join(work, "sa", "build")
    for name in BESIDE:
        if os.path.exists(os.path.join(built, name)):
            if os.path.exists(os.path.join(out, name)):   # (linux: not over a running copy's file: a new one in its place)
                os.remove(os.path.join(out, name))
            shutil.copy2(os.path.join(built, name), os.path.join(out, name))
    for dll in ffmpeg_dlls(ffmpeg_dir()):   # (a shared FFmpeg: its DLLs beside hookshot.exe, or the game does not start)
        shutil.copy2(dll, os.path.join(out, os.path.basename(dll)))
    shutil.copy2(os.path.join(work, "sa", "image", "image.bin"), os.path.join(out, "image.bin"))
    # every shader of the game, for its first start to translate (gpu/vk/vk_shader.cpp seed_open). Without it the game still runs, compiling them
    # as it meets them: not worth stopping a finished build for
    if subprocess.call(shader_census_cmd(romfs, os.path.join(out, "hookshot_shaders.bin")), stdout=sys.stderr):
        print("the shader list was not made: the game will compile its shaders as it plays", flush=True)
    language = os.path.join(out, "language.txt")   # (the same text as host/nn_applet.c writes)
    with open(language, "w", encoding="utf-8", newline="\n") as f:
        f.write("# The game's language. Change the line below to one of the codes listed here, save, and start the game again.\n\n%s\n\n" % a.language)
        f.writelines("# %-8s %s\n" % l for l in LANGUAGES)
    # (what the game's update offer reads, host/hos_update.c: which release these tools are, and where the builder that made the folder is)
    version = os.path.join(ROOT, "version.txt")
    if os.path.isfile(version):
        with open(version, encoding="utf-8") as f:
            tag = f.read().strip()
        with open(os.path.join(out, "hookshot_version.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write("version=%s\n" % tag)
            repo = update_repo()
            if repo:   # (where the game's update offer looks for newer releases: none set, no offer)
                f.write("repo=%s\n" % repo)
            if os.environ.get("HOOKSHOT_BUILDER_EXE"):
                f.write("builder=%s\n" % os.environ["HOOKSHOT_BUILDER_EXE"])
    say("done", out)


if __name__ == "__main__":
    # (an error nobody foresaw is said in the window, not as "The game files could not be read" or "something went wrong" with the reason
    # only in a console nobody sees: the traceback's last lines go to Show details, its last line to the message)
    try:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")   # (-I ignores PYTHONIOENCODING: a path's letters crashed a print)
            except (AttributeError, ValueError):
                pass
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        # (you pressed Ctrl+C: not an error. What is compiled is kept, so the same command carries on from there)
        say("error", "Stopped by you (Ctrl+C). Nothing is broken: what is already built is kept, and running the same command again carries "
            "on from there.")
        sys.exit(130)
    except BaseException as e:
        import traceback
        print(traceback.format_exc(), flush=True)
        say("error", "The builder stopped on an error it did not expect: %s: %s. Please send the text under Show details to the "
            "Hookshot issues page." % (type(e).__name__, str(e)[:300]))
        sys.exit(1)
