import os, shutil

HERE = os.path.dirname(os.path.abspath(__file__))


def emsdk():
    return os.environ.get("EMSDK") or (r"C:\emsdk" if os.name == "nt" else os.path.expanduser("~/emsdk"))


def mingw():
    """(hookshot) HOOKSHOT_MINGW=<llvm-mingw folder>: Windows builds with that toolchain's clang, headers and libraries (the GNU ABI
    on the UCRT), as TotK Recomp's installer does: nothing of Visual Studio or the Windows SDK is needed. Empty: the MSVC target"""
    return os.environ.get("HOOKSHOT_MINGW", "") if os.name == "nt" else ""


def find(tool):
    if mingw() and (tool in ("clang", "clang++", "lld") or tool.startswith("llvm-")):
        path = os.path.join(mingw(), "bin", ("ld.lld" if tool == "lld" else tool) + ".exe")
        if os.path.isfile(path):
            return path
    root = emsdk()
    exts = (".exe", ".bat") if os.name == "nt" else ("",)
    native = tool in ("clang", "clang++", "lld") or tool.startswith("llvm-")
    folder = os.path.join(root, "upstream", "bin") if native else os.path.join(root, "upstream", "emscripten")
    for ext in exts:
        path = os.path.join(folder, tool + ext)
        if os.path.isfile(path):
            return path
    return shutil.which(tool) or os.path.join(folder, tool + exts[0])


EMSDK_REPO = "https://github.com/emscripten-core/emsdk"


def install_emsdk():
    """Fetch the official emsdk into emsdk() and install its clang. Asks first (or HOOKSHOT_AUTO_EMSDK=1).
    EMSDK_VERSION picks the release (default latest). Returns True if clang is there afterwards."""
    import subprocess, sys
    root = emsdk()
    if os.environ.get("HOOKSHOT_AUTO_EMSDK") == "0":
        return False
    if os.environ.get("HOOKSHOT_AUTO_EMSDK") != "1":
        if not sys.stdin or not sys.stdin.isatty():
            return False
        print("clang was not found. Install emsdk from %s into %s? (a few GB download) [y/N] " % (EMSDK_REPO, root),
              end="", flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            return False
    script = os.path.join(root, "emsdk.bat" if os.name == "nt" else "emsdk")
    if not os.path.isfile(script):
        if os.path.isdir(root) and os.listdir(root):
            raise SystemExit("%s exists but has no emsdk in it; remove it or set EMSDK to another folder" % root)
        # (git only: a zip fetched with urllib had nothing to check it against, and its script is run next)
        if not shutil.which("git"):
            raise SystemExit("git was not found: install Git for Windows, or get emsdk yourself from %s into %s" % (EMSDK_REPO, root))
        subprocess.check_call(["git", "clone", "--depth", "1", EMSDK_REPO + ".git", root])
    version = os.environ.get("EMSDK_VERSION", "latest")
    # emsdk.bat runs plain "python", which is often missing on Windows (only the "py" launcher is installed), so
    # point it at the Python running this build
    env = dict(os.environ, EMSDK_PYTHON=sys.executable)
    for step in ("install", "activate"):
        if subprocess.call([script, step, version], cwd=root, env=env) != 0:
            raise SystemExit("emsdk %s %s failed (see the output above). Fix that, or install emsdk by hand at %s"
                             % (step, version, root))
    return True


def need(path):
    # (not with llvm-mingw: HOOKSHOT_MINGW names the compiler then, and emsdk is not part of that route)
    if not os.path.isfile(path) and not mingw() and path.startswith(emsdk()):
        install_emsdk()
    if not os.path.isfile(path):
        raise SystemExit("%s not found: set EMSDK to an emsdk checkout (now %s), or put %s on PATH"
                         % (path, emsdk(), os.path.splitext(os.path.basename(path))[0]))
    return path


def lld_link():
    """emsdk's lld under the name lld-link (lld picks its COFF linker from its own file name), made on first use"""
    path = os.path.join(HERE, "lld-link-mingw.exe" if mingw() else "lld-link.exe")
    if not os.path.exists(path):
        shutil.copyfile(need(find("lld")), path)
    return path


def native_target():
    if mingw():   # (-fms-extensions: __try/__except and __declspec, which clang takes on this target too)
        return ["--target=x86_64-w64-mingw32", "-fms-extensions", "-D_CRT_SECURE_NO_WARNINGS"]
    return ["--target=x86_64-pc-windows-msvc", "-fms-extensions", "-D_CRT_SECURE_NO_WARNINGS"] if os.name == "nt" else []


def native_link():
    # (-fuse-ld=lld, found through -B: clang ignores --ld-path for the MSVC target and ran Microsoft's link.exe, which
    # cannot read the renderer's ThinLTO bitcode)
    if mingw():   # (its own lld; the C++ runtime and winpthread linked in, so no DLLs of the toolchain go beside the game)
        # (/nodefaultlib: libraries built with Microsoft's compiler, the CPM cache's FFmpeg, ask in their objects for its C runtime;
        # the MinGW one stands in, with host/mingw_msvc_shims.c for what it lacks)
        return ["-fuse-ld=lld", "-static"] + ["-Wl,-Xlink=/nodefaultlib:" + l for l in ("libcmt", "oldnames", "libvcruntime", "msvcrt")]
    return ["-fuse-ld=lld", "-B" + os.path.dirname(lld_link())] if os.name == "nt" else []


def link_opt(opt):
    """A link.exe-style option ("/map:x"): as it is for the MSVC target, through lld's MinGW driver (-Xlink) for llvm-mingw"""
    return "-Wl,-Xlink=" + opt if mingw() else "-Wl," + opt


def default_jobs(gb_per_job=3.5):
    """Parallel compiles that fit in memory: a -O3 compile of one of the game's big lifted chunks takes 3-8 GB, and one
    job per logical core ran 16 GB machines out of memory (22 threads on an Ultra 7 155H). 80% of the physical memory
    at gb_per_job each, at most one a core. RX_JOBS=<n> sets it. (After SkyboundTotk PR 14 by leonelalej.)"""
    if os.environ.get("RX_JOBS"):
        return max(1, int(os.environ["RX_JOBS"]))
    total = 0
    try:
        if os.name == "nt":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                           [(f, ctypes.c_ulonglong) for f in ("phys", "avail_phys", "page", "avail_page", "virt",
                                                              "avail_virt", "avail_ext")]
            m = MemoryStatus()
            m.length = ctypes.sizeof(m)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                total = m.phys
        else:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, AttributeError):
        pass
    cores = os.cpu_count() or 1
    if not total:
        return cores
    return max(1, min(cores, int(total / 2 ** 30 * 0.8 / gb_per_job)))
