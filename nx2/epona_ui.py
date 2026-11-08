# SPDX-FileCopyrightText: 2026 The Epona contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Epona's guided terminal menu: pick your game file, check this PC, say yes or no to what gets downloaded, and watch the build.

Start it with `py -I nx2/make_game.py` (no arguments, in a terminal), or double-click epona.bat. Everything happens inside it; the
command-line options of nx2/make_game.py still work for scripts and for the Hookshot Builder app, and nothing here is needed by them.

It draws, and asks. The work is nx2/make_game.py's, called in this process. Downloads are never started by this file: it shows what
each one is, where from and how big, asks, and only then lets nx2/make_game.py do the ones you said yes to (HOOKSHOT_AUTO_<NAME>=1),
leaving the others off (=0). What you chose is kept in %LOCALAPPDATA%\\Epona\\settings.json (paths, language, job count; no secrets).
"""
import collections
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time

APP = "Epona"
DATA = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Epona")
SETTINGS_FILE = os.path.join(DATA, "settings.json")
LOG_DIR = os.path.join(DATA, "logs")
DEFAULT_INSTALL = os.path.join(os.path.expanduser("~"), "Games", "Epona")
NEED_GB = 60
ANSI = re.compile(r"\x1b\[[0-9;]*m")
T = None   # the terminal's look, made by init()


class Quit(Exception):
    pass


# ------------------------------------------------------------------------------------------------------------------ the look

def _enable_vt():
    """Windows: ask the console to understand colour codes. True when it does."""
    if os.name != "nt":
        return True
    try:
        k = ctypes.windll.kernel32
        k.GetStdHandle.restype = ctypes.c_void_p
        k.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        k.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        h = k.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k.SetConsoleMode(h, mode.value | 0x0004))
    except (OSError, AttributeError):
        return False


class Term:
    CODES = dict(bold="1", dim="2", red="31", green="32", yellow="33", blue="34", magenta="35", cyan="36", white="37", gray="90")

    def __init__(self):
        out = sys.stdout
        self.tty = bool(getattr(out, "isatty", lambda: False)())
        self.color = not os.environ.get("NO_COLOR") and (os.environ.get("EPONA_COLOR") == "1" or (self.tty and _enable_vt()))   # (EPONA_COLOR=1: colour into a file, to check it)
        enc = (getattr(out, "encoding", None) or "").lower()
        # (boxes and arrows only where the terminal is known to draw them: Windows Terminal, VS Code, most others; the old console gets plain ASCII)
        self.uni = "utf" in enc and not os.environ.get("EPONA_ASCII") and (
            os.environ.get("EPONA_UNICODE") == "1" or os.name != "nt" or bool(os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM")))
        g = self.uni
        self.s = dict(ok="\u2713" if g else "OK", bad="\u2717" if g else "X", warn="!", arrow="\u203a" if g else ">", dot="\u2022" if g else "*",
                      tl="\u256d" if g else "+", tr="\u256e" if g else "+", bl="\u2570" if g else "+", br="\u256f" if g else "+",
                      h="\u2500" if g else "-", v="\u2502" if g else "|", full="\u2588" if g else "#", empty="\u2591" if g else ".",
                      marker="\u25b6" if g else ">", bullet="\u25cf" if g else "*", heart="\u2665" if g else "#", heart0="\u2665" if g else ".",
                      disc="\u25cf" if g else "O",
                      ring="\u25cb" if g else "o", back="\u25c2" if g else "<", updown="\u2191\u2193" if g else "Up/Down")

    def c(self, text, *styles):
        if not self.color or not styles:
            return text
        return "\x1b[" + ";".join(self.CODES[s] for s in styles) + "m" + text + "\x1b[0m"

    def width(self):
        return max(56, min(shutil.get_terminal_size((90, 24)).columns - 4, 100))   # (never to the last column: some consoles wrap early there)


def init():
    global T
    T = Term()
    return T


def vlen(s):
    """The width a string takes on screen (colour codes take none)"""
    return len(ANSI.sub("", s))


def wrap(text, width, indent=""):
    return textwrap.wrap(text, width, initial_indent=indent, subsequent_indent=indent) or [""]


def p(text=""):
    print(text, flush=True)


def fit(line, inner):
    """The line as one or more lines no wider than inner: a long one is wrapped on its plain text, keeping the colour it starts with"""
    if vlen(line) <= inner:
        return [line]
    prefix = re.match(r"((?:\x1b\[[0-9;]*m)*)", line).group(1)
    suffix = "\x1b[0m" if prefix else ""
    return [prefix + piece + suffix for piece in (textwrap.wrap(ANSI.sub("", line), inner) or [""])]


def box(lines, title=None, tone="cyan", width=None):
    """A bordered panel, never wider than the terminal: a line too long for it is wrapped, so the right edge always lines up."""
    w = min(width, T.width()) if width else T.width()
    inner = w - 4
    s = T.s
    lines = [piece for line in lines for piece in fit(line, inner)]
    if title:
        label = " " + title + " "
        top = T.c(s["tl"] + s["h"], tone) + T.c(label, "bold", tone) + T.c(s["h"] * max(0, w - 3 - len(label)) + s["tr"], tone)
    else:
        top = T.c(s["tl"] + s["h"] * (w - 2) + s["tr"], tone)
    p("  " + top)
    for line in lines:
        pad = " " * max(0, inner - vlen(line))
        p("  " + T.c(s["v"], tone) + " " + line + pad + " " + T.c(s["v"], tone))
    p("  " + T.c(s["bl"] + s["h"] * (w - 2) + s["br"], tone))


def banner(settings=None):
    """the header: a panel on the same navy as the menu below it, so the two read as one screen"""
    s = T.s
    p()
    p("  " + paint(s["tl"] + s["h"] * (panel_width() - 2) + s["tr"], STEEL, NAVY))
    p(pframe(prow((" E P O N A", 222, None, True))))
    p(pframe(prow((" Ocarina of Time, built from your own copy", CREAM))))
    for l in ("a fork of Hookshot by NotRexed", "GPL-3.0  " + s["dot"] + "  not affiliated with Nintendo"):
        p(pframe(prow((" " + l, 245))))
    p("  " + paint(s["bl"] + s["h"] * (panel_width() - 2) + s["br"], STEEL, NAVY))


def heading(text, step=None):
    p()
    label = ("Step %d of %d  %s  " % (step[0], step[1], T.s["arrow"]) + text) if isinstance(step, tuple) and step[1] > 1 else text
    p("  " + T.c(label, "bold", "cyan"))
    p("  " + T.c(T.s["h"] * min(len(label), T.width() - 2), "gray"))


def line_ok(text, detail=""):
    p("   " + T.c(T.s["ok"], "green", "bold") + "  " + text + (T.c("   " + detail, "gray") if detail else ""))


def line_bad(text, detail=""):
    p("   " + T.c(T.s["bad"], "red", "bold") + "  " + text + (T.c("   " + detail, "gray") if detail else ""))


def line_warn(text, detail=""):
    p("   " + T.c(T.s["warn"], "yellow", "bold") + "  " + text + (T.c("   " + detail, "gray") if detail else ""))


def note(text):
    for l in wrap(text, T.width() - 6):
        p("   " + T.c(l, "gray"))


def ask(label, default=None, path=False):
    shown = (" [" + str(default) + "]") if default not in (None, "") else ""
    try:
        s = input("  " + T.c(label, "bold") + T.c(shown, "gray") + T.c(" " + T.s["arrow"] + " ", "cyan"))
    except EOFError:
        raise Quit()
    s = s.strip()
    if path:
        s = s.strip('"').strip("'").strip()
    return s if s else (default if default is not None else "")


def yesno(label, default=False):
    d = "Y/n" if default else "y/N"
    while True:
        s = ask(label + " (" + d + ")", None).lower()
        if not s:
            return default
        if s in ("y", "yes"):
            return True
        if s in ("n", "no"):
            return False
        p("   " + T.c("Please answer y or n.", "yellow"))


# ------------------------------------------------------------------------------------------------------------------ the file-select look
# Inspired by Ocarina of Time's file-select screens: a deep-blue panel with a cream title, rounded plates for the choices with the chosen one
# lit, a gap between groups, hearts and the six medallions, and a "Decide / Cancel" strip below. Arrow keys move and Enter decides (like the
# game); the number or letter of a choice picks it at once. Without a console that takes colour it falls back to a plain numbered prompt.

NAVY, STEEL, CREAM, SOFT, PLATE, PLATE_HI, TEAL, GREEN, RED, EMPTY_HEART = 17, 67, 230, 110, 24, 66, 80, 41, 196, 238
MEDALLION_COLORS = (34, 196, 33, 208, 129, 220)   # Forest, Fire, Water, Spirit, Shadow, Light
MEDALLION_ITEMS = ("pip", "mingw", "vulkan", "ffmpeg", "sdl2", "av1")   # the checklist items the six medallions stand for, in that order
HOME_GROUPS = [[("1", "Start", "your game, then build")],
               [("2", "Check this PC", "what is missing"), ("3", "Downloads", "every tool and its source")],
               [("4", "Settings", "folder, language, speed"), ("5", "Help", "")],
               [("q", "Quit", "")]]
SUMMARY_BUTTONS = [[("y", "Yes", "start building"), ("q", "Quit", "back to the menu")]]


def paint(text, fg=None, bg=None, bold=False):
    """text in 256-colour foreground and background (plain text where there is no colour)"""
    if not T.color:
        return text
    codes = (["1"] if bold else []) + (["38;5;%d" % fg] if fg is not None else []) + (["48;5;%d" % bg] if bg is not None else [])
    return ("\x1b[" + ";".join(codes) + "m" + text + "\x1b[0m") if codes else text


def panel_width():
    return min(T.width(), 64)


def panel_inner():
    return panel_width() - 4


def prow(*segs):
    """The inside of one panel row: segments (text, fg, bg, bold) on the navy, cut and padded to exactly the panel's inner width"""
    n, out, used = panel_inner(), "", 0
    for s in segs:
        text = s[0][:max(0, n - used)]
        out += paint(text, s[1] if len(s) > 1 else None, s[2] if len(s) > 2 and s[2] is not None else NAVY, s[3] if len(s) > 3 else False)
        used += len(text)
    return out + paint(" " * (n - used), None, NAVY)


def pframe(content):
    v = T.s["v"]
    return "  " + paint(v, STEEL, NAVY) + paint(" ", None, NAVY) + content + paint(" ", None, NAVY) + paint(v, STEEL, NAVY)


def tail(text, n):
    return text if len(text) <= n else "…" + text[-(n - 1):] if T.uni else "..." + text[-(n - 3):]


def plate_row(name, value, width=10):
    """a plate with a name, an arrow and its value: the file plate of the 'Open this file?' screen"""
    return prow((" " + name.ljust(width - 1), 153, PLATE), (" " + T.s["back"] + " ", TEAL, None, True),
                (tail(value, panel_inner() - width - 4), CREAM))


def hearts_row(filled, total, label=""):
    h = T.s["heart"]
    filled = max(0, min(total, filled))
    return prow((" ",), (h * filled, RED), (T.s["heart0"] * (total - filled), EMPTY_HEART), ("  " + label, SOFT))


def medallions_row(states, label=""):
    """six medallions, lit (a filled disc in their colour) when ready and a grey ring when not; states: True / False / None"""
    segs = [(" ",)]
    for i, state in enumerate(states):
        segs.append(((T.s["disc"] if state else T.s["ring"]) + " ", MEDALLION_COLORS[i % 6] if state else 244, None, True))
    segs.append(("  " + label, SOFT))
    return prow(*segs)


def shorten(text, n):
    """text cut to n characters with the middle replaced by an ellipsis, so a long file name keeps both its start and its end"""
    if len(text) <= n:
        return text
    dots = "…" if T.uni else "..."
    if n <= len(dots) + 2:
        return text[:n]
    keep = n - len(dots)
    head = (keep + 1) // 2
    return text[:head] + dots + text[len(text) - (keep - head):]


def item_rows(groups, idx):
    labels = [lab for g in groups for _, lab, _ in g]
    plate_w = max(24, min(max((len(l) for l in labels), default=0) + 3, panel_inner() - 12))
    rows, n = [], 0
    for gi, group in enumerate(groups):
        for ii, (key, label, hint) in enumerate(group):
            if ii:
                rows.append(prow())   # (a blank row between plates in a group, so each plate stands on its own)
            elif gi:
                rows.append(prow((" " + T.s["h"] * (panel_inner() - 2), STEEL)))   # (a thin line between groups, as the game sets Copy / Erase apart)
            sel = n == idx
            plate = (" " + shorten(label, plate_w - 1)).ljust(plate_w)
            beside = panel_inner() - 5 - plate_w - 2   # (the room left of the plate for its hint)
            under = bool(hint) and len(hint) > beside   # (a hint too long for that goes on its own line below the plate, in full)
            rows.append(prow((" " + key[:1] + " ", SOFT), ((T.s["marker"] if sel else " ") + " ", TEAL, None, True),
                             (plate, 255 if sel else 153, PLATE_HI if sel else PLATE, sel), (("  " + hint) if hint and not under else "", SOFT)))
            if under:
                rows.append(prow((" " * 6 + shorten(hint, panel_inner() - 7), SOFT)))
            n += 1
    return rows


def render_panel(title, groups, idx, extra=None, keys_mode=True):
    """The lines of one panel: a title, optional rows of your own (extra, from prow), the choices, and the strip below. idx -1: none lit."""
    pw, s = panel_width(), T.s
    lines = ["  " + paint(s["tl"] + s["h"] * (pw - 2) + s["tr"], STEEL, NAVY), pframe(prow())]
    if title:
        lines += [pframe(prow((" " + title, CREAM, None, True))), pframe(prow())]
    lines += [pframe(e) for e in (extra or [])]
    if extra and groups:
        lines.append(pframe(prow()))
    lines += [pframe(r) for r in item_rows(groups, idx)]
    lines += [pframe(prow()), "  " + paint(s["bl"] + s["h"] * (pw - 2) + s["br"], STEEL, NAVY)]
    if groups:
        if keys_mode:
            lines.append("   " + paint(s["updown"] + " Move   Enter - Decide ", TEAL) + paint(s["bullet"], GREEN, None, True) + paint(" Esc - Cancel", TEAL))
        else:
            lines.append("   " + paint("Type the number or letter of your choice, then Enter", TEAL))
    return lines


def keys_available():
    """Arrow-key menus: Windows, a real console that takes colour, and not turned off (EPONA_KEYS=0)"""
    return os.name == "nt" and bool(T.color) and bool(sys.stdin) and sys.stdin.isatty() and os.environ.get("EPONA_KEYS") != "0"


def read_key():
    """One key press: 'up', 'down', 'home', 'end', 'enter', 'esc', or the character typed"""
    import msvcrt
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        return {"H": "up", "P": "down", "G": "home", "O": "end"}.get(msvcrt.getwch(), "")
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x1b":
        return "esc"
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


def _redraw(out, n, lines):
    out.write("\x1b[%dA" % n + "".join("\r\x1b[2K" + l + "\n" for l in lines))
    out.flush()


def select_menu(title, groups, default=None, extra=None):
    """Show a panel of choices (groups of (key, label, hint)) and return the key picked."""
    flat = [it for g in groups for it in g]
    keys = [k.lower() for k, _, _ in flat]
    idx = keys.index(default.lower()) if default and default.lower() in keys else 0
    if not keys_available():
        for line in render_panel(title, groups, -1, extra, keys_mode=False):
            p(line)
        p()
        while True:
            ans = ask("Choose", flat[idx][0]).lower()
            if ans in keys:
                return flat[keys.index(ans)][0]
            p("   " + T.c("Please type one of: " + ", ".join(k for k, _, _ in flat), "yellow"))
    out = sys.stdout
    out.write("\x1b[?25l")   # (the cursor is hidden while the panel is up)
    try:
        lines = render_panel(title, groups, idx, extra)
        n = len(lines)
        out.write("".join("\r\x1b[2K" + l + "\n" for l in lines))
        out.flush()
        while True:
            k = read_key()
            if k == "enter":
                break
            if k == "esc":
                cancel = next((i for i, key in enumerate(keys) if key in ("b", "q", "c", "m")), None)
                if cancel is None:
                    continue
                idx = cancel
                _redraw(out, n, render_panel(title, groups, idx, extra))
                break
            if k == "up":
                idx = (idx - 1) % len(flat)
            elif k == "down":
                idx = (idx + 1) % len(flat)
            elif k == "home":
                idx = 0
            elif k == "end":
                idx = len(flat) - 1
            elif len(k) == 1 and k.lower() in keys:
                idx = keys.index(k.lower())
                _redraw(out, n, render_panel(title, groups, idx, extra))
                break
            else:
                continue
            _redraw(out, n, render_panel(title, groups, idx, extra))
    finally:
        out.write("\x1b[?25h")
        out.flush()
    return flat[idx][0]


def choose(items, default=None, title=None, extra=None):
    """items: [(key, label, help)]. Returns the key chosen (arrow keys and Enter, or type its key)."""
    return select_menu(title, [items], default, extra)


def pause(text="Press Enter to go back to the menu"):
    try:
        input("  " + T.c(text + " ", "gray"))
    except EOFError:
        raise Quit()


# ------------------------------------------------------------------------------------------------------------------ settings

def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(st):
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8", newline="\n") as f:
            json.dump(st, f, indent=2)
    except OSError:
        pass   # (not being able to remember is not worth stopping for)


# ------------------------------------------------------------------------------------------------------------------ the game file

def check_dump(path):
    """(kind, problem): kind is "nup" or "folders" when the path looks like a game dump; otherwise kind is None and problem says why"""
    if not path:
        return None, "Nothing was typed."
    if os.path.isfile(path):
        if path.lower().endswith(".nup"):
            return "nup", ""
        return None, "That is a file, but not a .nup. Epona reads a .nup dump, or a folder holding both exefs and romfs."
    if os.path.isdir(path):
        if os.path.isdir(os.path.join(path, "exefs")) and os.path.isdir(os.path.join(path, "romfs")):
            return "folders", ""
        return None, "That folder has no exefs and romfs inside it. Point at the .nup file instead, or at the folder that holds both."
    return None, "I can't find that. Check the spelling, or drag the file onto this window."


def find_dumps(limit=8, budget=4.0):
    """.nup files in the usual places (your Downloads, Desktop and Documents, and a Downloads folder on each fixed drive), two folders deep"""
    home = os.path.expanduser("~")
    roots = [os.path.join(home, d) for d in ("Downloads", "Desktop", "Documents")]
    if os.name == "nt":
        try:
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                letter = chr(65 + i) + ":\\"
                if mask & (1 << i) and ctypes.windll.kernel32.GetDriveTypeW(letter) == 3:
                    roots.append(os.path.join(letter, "Downloads"))
        except (OSError, AttributeError):
            pass
    found, seen, start = [], set(), time.time()
    for root in roots:
        if not os.path.isdir(root) or root.lower() in seen:
            continue
        seen.add(root.lower())
        for depth_dir, depth in _walk(root, 2):
            if time.time() - start > budget or len(found) >= limit:
                return found
            try:
                for e in os.scandir(depth_dir):
                    if e.is_file() and e.name.lower().endswith(".nup"):
                        found.append((e.path, e.stat().st_size))
            except OSError:
                continue
    return found


def _walk(root, depth):
    yield root, 0
    if depth <= 0:
        return
    try:
        subs = [e.path for e in os.scandir(root) if e.is_dir() and not e.name.startswith(".")]
    except OSError:
        return
    for s in subs[:60]:
        yield s, 1
        if depth > 1:
            try:
                for e in os.scandir(s):
                    if e.is_dir() and not e.name.startswith("."):
                        yield e.path, 2
            except OSError:
                continue


def gb(n):
    return "%.1f GB" % (n / 2 ** 30)


def step_game(st, n=1, total=4):
    """Ask for the game file. Returns the path, or None if the user went back."""
    heading("Your game file", (n, total))
    note("Epona builds the game from YOUR copy of Ocarina of Time (the Switch 2 version, as a .nup dump). It reads it and never changes it.")
    p()
    saved = st.get("dump")
    if saved and check_dump(saved)[0]:
        kind, _ = check_dump(saved)
        size = os.path.getsize(saved) if kind == "nup" else None
        line_ok("Last time you used", saved + ("   (" + gb(size) + ")" if size else ""))
        if yesno("Use it again", True):
            return saved
        p()
    p("   " + T.c("Looking for .nup files on this PC...", "gray"))
    found = [(path, size) for path, size in find_dumps() if path != saved]
    items = []
    for i, (path, size) in enumerate(found, 1):
        items.append((str(i), os.path.basename(path), gb(size) + "   in " + os.path.dirname(path)))
    items.append(("t", "Type or paste a path", "or drag the file onto this window"))
    items.append(("b", "Back to the menu", ""))
    p()
    choice = choose(items, "1" if found else "t", title="Please select a file." if found else "No .nup file found in the usual places.")
    if choice == "b":
        return None
    if choice != "t":
        return found[int(choice) - 1][0]
    while True:
        path = ask("Path to your .nup file (or b to go back)", path=True)
        if path.lower() == "b":
            return None
        kind, problem = check_dump(path)
        if kind:
            return path
        p("   " + T.c(problem, "yellow"))


# ------------------------------------------------------------------------------------------------------------------ install folder, language

def free_gb(path):
    probe = os.path.abspath(path)
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        return shutil.disk_usage(probe).free / 2 ** 30
    except OSError:
        return None


def step_folder(st, n=2, total=4):
    heading("Where to install", (n, total))
    note("This is the folder the finished game goes in (about %d GB is needed while building, far less once it is done)." % NEED_GB)
    p()
    default = st.get("install_dir") or DEFAULT_INSTALL
    while True:
        folder = ask("Install folder (Enter keeps this one)", default, path=True)
        folder = os.path.abspath(os.path.expandvars(os.path.expanduser(folder)))
        free = free_gb(folder)
        if free is not None and free < NEED_GB:
            line_warn("Only %.0f GB free on that drive; the build needs about %d GB." % (free, NEED_GB))
            if not yesno("Use it anyway", False):
                continue
        elif free is not None:
            line_ok("%.0f GB free there" % free)
        try:
            if os.path.isdir(folder) and os.listdir(folder):
                line_warn("The folder is not empty.", "an earlier build there is continued, nothing is deleted")
        except OSError:
            line_warn("I can't look inside that folder.", "check that you may write there")
        return folder


def step_language(mg, st, n=3, total=4):
    heading("Language", (n, total))
    langs = mg.LANGUAGES
    cur = st.get("language") or "en-US"
    half = (len(langs) + 1) // 2
    for i in range(half):
        left = langs[i]
        right = langs[i + half] if i + half < len(langs) else None
        cell = lambda idx, item: "   " + T.c(str(idx + 1).rjust(2), "bold", "cyan") + "  " + (item[1] + (" *" if item[0] == cur else "")).ljust(28)
        p(cell(i, left) + (cell(i + half, right) if right else ""))
    p()
    codes = [c for c, _ in langs]
    default = str(codes.index(cur) + 1) if cur in codes else "1"
    while True:
        ans = ask("Number or code (Enter = *)", default)
        if ans.isdigit() and 1 <= int(ans) <= len(langs):
            return langs[int(ans) - 1][0]
        if ans in codes:
            return ans
        p("   " + T.c("Pick a number from the list.", "yellow"))


# ------------------------------------------------------------------------------------------------------------------ this PC, and what is installed

def pc_rows(mg, install_dir=None):
    """[(state, label, detail)]: state is "ok", "warn", "bad" or "info"."""
    rows = []
    avx2 = mg.cpu_has_avx2()
    cpus = os.cpu_count() or 0
    rows.append(("ok" if avx2 else "bad" if avx2 is False else "info", "Processor",
                 "%d threads, AVX2 %s" % (cpus, "yes" if avx2 else "NO (the game needs it)" if avx2 is False else "unknown")))
    total, free = mg.physical_memory_gb(), mg.physical_memory_gb(available=True)
    if total:
        rows.append(("ok" if total >= 15 else "warn", "Memory", "%.0f GB, %.0f GB free now" % (total, free)))
    cards = mg.graphics_cards()
    if cards:
        for c in cards:
            weak = bool(mg.GPUS_WITHOUT_MESH.search(c))
            virtual = bool(re.search(r"virtual|parsec|remote|basic", c, re.I))
            rows.append(("info" if virtual else "warn" if weak else "ok", "Graphics", c + ("  (probably no mesh shaders)" if weak else "")))
    drive = free_gb(install_dir or DEFAULT_INSTALL)
    if drive is not None:
        rows.append(("ok" if drive >= NEED_GB else "warn", "Free disk", "%.0f GB on the install drive (need about %d)" % (drive, NEED_GB)))
    return rows


def tool_items(mg):
    """The checklist: what the build needs, what is there, and what Epona could fetch. Each: dict(id, name, required, present, ...)"""
    import importlib.util
    missing_pkgs = [pkg for mod, pkg in mg.PYTHON_PACKAGES if importlib.util.find_spec(mod) is None]
    python_ok = bool(shutil.which("python")) and "WindowsApps" not in (shutil.which("python") or "")
    return [
        dict(id="pip", name="Python packages", required=True, present=not missing_pkgs, env="HOOKSHOT_AUTO_PIP", size="a few MB",
             source="pypi.org, through pip", what="installs " + ", ".join(missing_pkgs) if missing_pkgs else "", note="pip can run a package's install code"),
        dict(id="mingw", name="Windows compiler (llvm-mingw)", required=True, present=mg.llvm_mingw_present(), env="HOOKSHOT_AUTO_MINGW",
             size="182 MB", source="github.com/mstorsjo/llvm-mingw", what="checked against a pinned SHA-256; no Visual Studio needed",
             note=""),
        dict(id="vulkan", name="Vulkan headers", required=True, present=mg.vulkan_headers_present(), env="HOOKSHOT_AUTO_DEPS", size="4 MB",
             source="github.com/KhronosGroup and GPUOpen", what="three source archives, each checked against a pinned SHA-256", note=""),
        dict(id="ffmpeg", name="FFmpeg (video)", required=True, present=bool(mg.ffmpeg_dir()), env="HOOKSHOT_AUTO_FFMPEG", size="77 MB",
             source="github.com/FFmpeg-Builds (formerly BtbN)", what="a prebuilt daily build, checked against the SHA-256 GitHub lists; only headers, "
             "4 libraries and 4 DLLs are taken", note="third-party binaries: they cannot be pinned"),
        dict(id="sdl2", name="Controller support (SDL2.dll)", required=False, present=mg.sdl2_present(), env="HOOKSHOT_AUTO_SDL", size="0.6 MB",
             source="github.com/libsdl-org/SDL", what="checked against a pinned SHA-256", note=""),
        dict(id="work", name="Speed-up data", required=False, present=mg.work_data_present(), env=None, size="from a file you have",
             source="the author's HookshotBuilder.zip, if you already have it", what="four data files are read out of it; nothing in it is run", note=""),
        dict(id="av1", name="AV1 Video Extension (movies)", required=False, present=mg.av1_installed(), env=None, size="free from Microsoft",
             source="the Microsoft Store", what="opens its Store page; the Store installs it", note=""),
        dict(id="pypath", name="'python' command in new terminals", required=False, present=python_ok, env="HOOKSHOT_AUTO_PYPATH", size="nothing",
             source="your Python folder", what="adds it to YOUR user PATH only; the old PATH is saved to undo it", note=""),
    ]


def show_checklist(items):
    col = max(len(it["name"]) + (0 if it["required"] else 11) for it in items) + 2   # (the details line up in a column)
    for it in items:
        label = (it["name"] + ("" if it["required"] else "  (optional)")).ljust(col)
        if it["present"] is None:
            line_warn(label, "could not tell")
        elif it["present"]:
            line_ok(label, "found")
        elif it["required"]:
            line_bad(label, "missing  " + T.s["arrow"] + "  " + it["size"] + " from " + it["source"])
        else:
            line_warn(label, "missing  " + T.s["arrow"] + "  " + it["size"])


def show_pc(mg, install_dir=None):
    for state, label, detail in pc_rows(mg, install_dir):
        {"ok": line_ok, "bad": line_bad, "warn": line_warn, "info": line_ok}[state](label.ljust(10), detail)


def show_medallions(items):
    """the six medallions, lit for what is ready, in a small panel"""
    by = {it["id"]: it["present"] for it in items}
    states = [by.get(i) for i in MEDALLION_ITEMS]
    for l in render_panel("Requirements", [], -1, [medallions_row(states, "%d of %d ready" % (sum(1 for s in states if s), len(states)))]):
        p(l)


def summary_rows(mg, st):
    """the rows of the 'Start this build?' panel: plates for the choices, hearts for the compiles, the medallions"""
    items = tool_items(mg)
    ready = {it["id"]: bool(it["present"]) or bool(it["env"] and os.environ.get(it["env"]) == "1") for it in items}
    lang = next((name for code, name in mg.LANGUAGES if code == st.get("language")), st.get("language") or "en-US")
    jobs = int(st.get("jobs") or 1)
    return [plate_row("Game", os.path.basename(st.get("dump") or "")), plate_row("Install", st.get("install_dir") or DEFAULT_INSTALL),
            plate_row("Language", lang), prow(),
            hearts_row(jobs, max(jobs, os.cpu_count() or jobs), "%d compiles at once" % jobs),
            medallions_row([ready.get(i) for i in MEDALLION_ITEMS], "requirements ready or about to be fetched"),
            prow(), prow((" About %d GB while building; 30 to 60 minutes." % NEED_GB, SOFT))]


def screen_check(mg, st):
    heading("Your PC")
    p("   " + T.c("Checking...", "gray"))
    show_pc(mg, st.get("install_dir"))
    heading("What the build needs")
    items = tool_items(mg)
    show_medallions(items)
    p()
    show_checklist(items)
    p()
    note("Nothing is downloaded from this screen. Choose 'Start' and you are asked, item by item, before anything is fetched.")
    pause()


def consent(mg, st):
    """The checklist and the single place downloads are agreed to. Sets HOOKSHOT_AUTO_<NAME> to 1 (yes) or 0 (no) for this run.
    Returns False if something required is missing and was declined."""
    items = tool_items(mg)
    heading("What the build needs", (4, 4))
    p("   " + T.c("Checking this PC...", "gray"))
    show_pc(mg, st.get("install_dir"))
    p()
    show_medallions(items)
    p()
    show_checklist(items)
    p()
    # (the PATH change is not a download and is never part of "fetch everything": it is asked on its own, below)
    todo = [it for it in items if it["present"] is False and it["env"] and it["id"] != "pypath"]
    if not todo:
        line_ok("Nothing to fetch.")
    else:
        req = [it for it in todo if it["required"]]
        opt = [it for it in todo if not it["required"]]
        p("   Epona can fetch what is missing. " + T.c("Nothing is downloaded until you say yes.", "bold"))
        p()
        pick = choose([("1", "Fetch what is required", "%d item%s" % (len(req), "" if len(req) == 1 else "s") if req else "nothing required"),
                       ("2", "Fetch everything missing", "required + optional"),
                       ("3", "Let me choose one by one", "I'll show each"),
                       ("4", "Don't fetch anything", "I'll add them myself")], "1" if req else "2")
        for it in todo:
            if pick == "1":
                yes = it["required"]
            elif pick == "2":
                yes = True
            elif pick == "3":
                p()
                p("   " + T.c(it["name"], "bold") + T.c("   %s from %s" % (it["size"], it["source"]), "gray"))
                note(it["what"] + (". Note: " + it["note"] if it["note"] else ""))
                yes = yesno("Fetch it", it["required"])
            else:
                yes = False
            os.environ[it["env"]] = "1" if yes else "0"
            it["yes"] = yes
        declined = [it for it in req if not it.get("yes")]
        if declined:
            p()
            line_bad("Without " + ", ".join(it["name"] for it in declined) + " the game cannot be built.")
            note("Add them yourself (EPONA.md lists how), or run this again and say yes.")
            return False
    # the things that are not downloads
    os.environ["HOOKSHOT_SKIP_WORKDATA"] = "1"
    os.environ["HOOKSHOT_AUTO_PYPATH"] = "0"
    pypath = next((it for it in items if it["id"] == "pypath"), None)
    if pypath and pypath["present"] is False:
        p()
        p("   " + T.c("The 'python' command", "bold") + T.c("   optional: the build works without this", "gray"))
        note("Your terminal has no 'python' command (only 'py'). Epona can add your Python folder to the front of YOUR user PATH so new "
             "terminal windows find it: your account only, no administrator rights, and your old PATH is saved so you can undo it.")
        if yesno("Do it", False):
            os.environ["HOOKSHOT_AUTO_PYPATH"] = "1"
    work = next((it for it in items if it["id"] == "work"), None)
    if work and work["present"] is False:
        p()
        p("   " + T.c("Speed-up data", "bold") + T.c("   optional: the game builds and runs without it, a little slower", "gray"))
        path = ask("If you already have the author's HookshotBuilder.zip, its path (Enter skips)", path=True)
        if path:
            mg.take_work_data(path)
    av1 = next((it for it in items if it["id"] == "av1"), None)
    if av1 and av1["present"] is False:
        p()
        line_warn("The AV1 Video Extension is missing.", "the game's movies need it (a green screen without it)")
        if yesno("Open its Microsoft Store page now (free)", True):
            try:
                os.startfile(mg.AV1_STORE_PAGE)
            except (OSError, AttributeError):
                note("Could not open the Store: search for 'AV1 Video Extension' in it.")
    return True


def step_jobs(mg, st):
    n = mg.suggested_jobs()
    free = mg.physical_memory_gb(available=True)
    p()
    note("The build runs several compiles at once. More is faster until the memory runs out. Suggested: %d%s." %
         (n, " (%.0f GB of memory is free now)" % free if free else ""))
    while True:
        ans = ask("Parallel compiles (Enter takes the suggestion)", st.get("jobs") or n)
        if str(ans).isdigit() and 1 <= int(ans) <= 4 * (os.cpu_count() or 8):
            return int(ans)
        p("   " + T.c("Type a whole number.", "yellow"))


# ------------------------------------------------------------------------------------------------------------------ watching the build

class Live:
    """Draws the build: step headers, one moving progress line, the important lines kept, the rest written to a log file."""
    STAGES = ["read", "lift", "compile", "finish"]
    # (where each step starts in the whole job and how much of it the step is: roughly the time each took on the test PC, about 25 min reading
    # the game, 3 translating, 17 or more compiling, a couple finishing. The meter is an estimate; it never goes backwards)
    SPAN = {"read": (0.00, 0.35), "lift": (0.35, 0.05), "compile": (0.40, 0.55), "finish": (0.95, 0.05)}

    def __init__(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        for old in sorted(os.listdir(LOG_DIR))[:-9]:
            try:
                os.remove(os.path.join(LOG_DIR, old))
            except OSError:
                pass
        self.log_path = os.path.join(LOG_DIR, time.strftime("build-%Y%m%d-%H%M%S.log"))
        self.log = open(self.log_path, "w", encoding="utf-8", errors="replace")
        self.tail = collections.deque(maxlen=60)
        self.frac, self.last, self.stage, self.t0, self.t_stage = 0.0, "", None, time.time(), time.time()
        self.drawn, self.last_draw, self.error, self.done, self.failed, self.mark = False, 0.0, None, None, 0, -1
        self.known, self.total_gb, self.base = False, None, 0.0   # (is this step's own fraction known; the game's size to extract; the job's progress between steps)

    def close(self):
        self.clear()
        try:
            self.log.close()
        except OSError:
            pass

    # -- drawing
    def clear(self):
        if self.drawn and T.tty:
            sys.stdout.write("\r" + ("\x1b[2K" if T.color else " " * (T.width() + 1) + "\r"))
            sys.stdout.flush()
        self.drawn = False

    def draw(self, force=False):
        if not T.tty:
            return
        now = time.time()
        if not force and now - self.last_draw < 0.12:
            return
        self.last_draw = now
        width = T.width()
        head = self.bar_text()
        room = max(0, width - vlen(head) - 1)
        sys.stdout.write("\r" + ("\x1b[2K" if T.color else "") + head + T.c(self.last[:room], "gray"))
        sys.stdout.flush()
        self.drawn = True

    def overall(self):
        """how far through the WHOLE job, 0 to 1: each step counts for a share of it (see SPAN)"""
        span = self.SPAN.get(self.stage)
        return self.base if span is None else span[0] + span[1] * self.frac

    def bar_text(self):
        """the meter: 20 hearts for the whole job, like the life meter (5% each; blocks where hearts cannot be drawn), then the percentage of
        the whole job and, in grey, which step it is on and that step's own percentage when it is known"""
        bar_w = 20
        total = self.overall()
        filled = int(total * bar_w)
        num = self.STAGES.index(self.stage) + 1 if self.stage in self.STAGES else None
        step = ("  step %d/%d" % (num, len(self.STAGES)) + (" %d%%" % int(self.frac * 100) if self.known else "")) if num else ""
        tail_ = T.c(" %3d%%" % int(total * 100), "cyan") + T.c(step, "gray") + "  "
        if T.uni:
            return "  " + paint(T.s["heart"] * filled, RED) + paint(T.s["heart0"] * (bar_w - filled), EMPTY_HEART) + tail_
        return "  " + T.s["full"] * filled + T.s["empty"] * (bar_w - filled) + tail_

    def permanent(self, text):
        self.clear()
        p(text)
        self.draw(True)

    # -- input from nx2/make_game.py
    def line(self, raw):
        try:
            self.log.write(raw + "\n")
        except (OSError, ValueError):
            pass
        self.tail.append(raw)
        if raw.startswith("@@"):
            self.proto(raw)
        else:
            self.plain(raw)

    def proto(self, raw):
        parts = raw.split(" ", 2)
        kind = parts[0][2:]
        if kind == "stage":
            self.end_stage()
            name = parts[1] if len(parts) > 1 else ""
            text = parts[2] if len(parts) > 2 else name
            self.stage, self.frac, self.t_stage, self.last, self.mark, self.known = name, 0.0, time.time(), "", -1, False
            num = self.STAGES.index(name) + 1 if name in self.STAGES else None
            self.clear()
            p()
            p("  " + T.c(("Step %d of %d  %s  " % (num, len(self.STAGES), T.s["arrow"]) if num else "") + text, "bold", "cyan"))
            self.draw(True)
        elif kind == "progress":
            try:
                self.frac = max(0.0, min(1.0, float(parts[1])))
            except (IndexError, ValueError):
                return
            self.known = True
            if not T.tty:   # (a pipe or a log: a line every 10%)
                tenth = int(self.frac * 10)
                if tenth != self.mark:
                    self.mark = tenth
                    p("  %3d%%" % (tenth * 10))
            self.draw()
        elif kind == "error":
            self.error = parts[1] + (" " + parts[2] if len(parts) > 2 else "") if len(parts) > 1 else "The build stopped."
        elif kind == "done":
            self.done = parts[1] if len(parts) > 1 else ""

    def plain(self, raw):
        s = raw.strip()
        if not s:
            return
        self.last = s
        # (reading the game prints "romfs N files, X GB" once and then "N files, Y GB" every few thousand files, but no fraction: made here)
        m = re.search(r"romfs (\d+) files, ([\d.]+) GB", s)
        if m:
            self.total_gb = float(m.group(2))
        m = re.match(r"(\d+) files, ([\d.]+) GB$", s)
        if m and self.total_gb and self.stage == "read":
            self.frac, self.known = min(1.0, float(m.group(2)) / self.total_gb), True
        if re.search(r"\bFAILED\b|error:|Traceback", s):
            self.failed += 1
            self.permanent("   " + T.c(T.s["bad"] + "  " + s[:T.width() - 8], "red"))
        elif s.startswith("note:") or re.match(r"WARNING", s):
            self.permanent("   " + T.c(T.s["warn"] + "  " + s[:T.width() - 8], "yellow"))
        elif re.match(r"(installed|the compiler:|linked |compiled in )", s):
            self.permanent("   " + T.c(T.s["ok"] + "  " + s[:T.width() - 8], "green"))
        else:
            self.draw()

    def end_stage(self):
        if self.stage is None:
            return
        self.clear()
        secs = int(time.time() - self.t_stage)
        p("   " + T.c(T.s["ok"], "green", "bold") + "  done " + T.c("(%d min %02d s)" % (secs // 60, secs % 60), "gray"))
        span = self.SPAN.get(self.stage)
        if span:
            self.base = span[0] + span[1]   # (the whole-job meter keeps this step's share)
        self.stage = None


# ------------------------------------------------------------------------------------------------------------------ the build

def do_build(mg, st):
    dump, out = st["dump"], st["install_dir"]
    args = ["make_game.py"]
    if os.path.isdir(dump):
        args += ["--romfs", os.path.join(dump, "romfs"), "--exefs", os.path.join(dump, "exefs")]
    else:
        args += ["--nup", dump]
    args += ["--out", out, "--language", st.get("language") or "en-US", "--jobs", str(st.get("jobs") or mg.suggested_jobs())]
    live = Live()
    mg.UI = live
    old_argv, code, why = sys.argv, 0, None
    sys.argv = args
    p()
    note("Building. You can press Ctrl+C at any time: what is finished is kept, and starting again carries on.")
    try:
        mg.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except KeyboardInterrupt:
        code, why = "stopped", "Stopped by you."
    except Exception as e:   # noqa: BLE001 (anything: shown plainly, with the log, instead of a traceback)
        code, why = 1, "%s: %s" % (type(e).__name__, str(e)[:200])
    finally:
        mg.UI = None
        sys.argv = old_argv
        live.end_stage() if code == 0 else live.clear()
        live.close()
    return code, why, live


def result_screen(mg, st, code, why, live):
    p()
    exe = os.path.join(st["install_dir"], "hookshot.exe")
    if code == 0 and os.path.isfile(exe):
        box([T.c("Your game is ready.", "bold", "green"), "",
             "Folder:  " + st["install_dir"], "Start it:  hookshot.exe in that folder",
             T.c("The first start prepares shaders, so the first minutes of play can stutter; it gets better.", "gray")], "All done", "green")
        p()
        pick = choose([("1", "Start the game now", ""), ("2", "Open the folder", ""), ("m", "Back to the menu", "")], "m")
        try:
            if pick == "1":
                os.startfile(exe)
            elif pick == "2":
                os.startfile(st["install_dir"])
        except (OSError, AttributeError) as e:
            note("Could not open it: %s" % e)
        return
    if code == "stopped":
        box([T.c("Stopped.", "bold", "yellow"), "Nothing is broken. What was finished is kept, and choosing Start again carries on from there."], "Paused", "yellow")
        pause()
        return
    reason = why or live.error or "The build stopped without saying why."
    lines = [T.c("The build did not finish.", "bold", "red"), ""] + wrap(reason, T.width() - 6)
    hint = None
    if re.search(r"nn_video|avcodec|libav", reason + " ".join(live.tail), re.I):
        hint = "FFmpeg is missing or not found. Choose Start again and say yes to FFmpeg."
    elif re.search(r"Windows SDK|stdio\.h|windows\.h", reason):
        hint = "The compiler could not find its headers. Choose Start again and say yes to the Windows compiler."
    elif re.search(r"No renderer", reason):
        hint = "The Vulkan headers are missing. Choose Start again and say yes to them."
    if hint:
        lines += ["", T.c(hint, "yellow")]
    lines += ["", T.c("Full log: " + live.log_path, "gray")]
    box(lines, "Stopped", "red")
    p()
    if yesno("Show the last lines of the log", False):
        p()
        for l in list(live.tail)[-25:]:
            p("   " + T.c(l[:T.width() - 6], "gray"))
        p()
    pause()


# ------------------------------------------------------------------------------------------------------------------ screens

LEGAL_VERSION = "2026-11-07"   # (change this when the notice changes, and everyone is asked again)
LEGAL_POINTS = (
    "You must legally own a copy of Ocarina of Time (the Nintendo Switch 2 version) and dump it yourself, from a console you own, for your "
    "own use. Epona contains no game, keys, firmware or Nintendo files, and never downloads any.",
    "Never share, upload or sell your dump, the extracted files or the game folder Epona builds. They contain Nintendo's copyrighted code "
    "and data. Epona is for your own use, on your own PC.",
    "Epona is an unofficial fan project. It is not made, approved or sponsored by Nintendo or by the Hookshot author. Names and trademarks "
    "belong to their owners.",
    "Laws on copying games, and on getting around protections, differ by country. Following yours is your responsibility. This is not "
    "legal advice.",
    "Everything is provided as is, with no warranty, under the GPL-3.0. Tools it can download come from third parties: read the Downloads "
    "screen first.")


def legal_gate(st):
    """The short legal notice, shown until you have confirmed it (the confirmation is kept only in your own settings file). True to go on."""
    if st.get("legal_ack") == LEGAL_VERSION:
        return True
    heading("Before you start")
    rows = []
    for point in LEGAL_POINTS:
        for i, l in enumerate(wrap(point, panel_inner() - 4)):
            rows.append(prow((" " + (T.s["dot"] if i == 0 else " ") + " " + l, CREAM)))
        rows.append(prow())
    rows.append(prow((" The full text is in LEGAL.md, next to this program.", SOFT)))
    for l in render_panel("Please read this first", [], -1, rows):
        p(l)
    p()
    if not yesno("I own a legal copy of this game and I agree to these terms", False):
        p("   " + T.c("No problem. Nothing was started.", "gray"))
        return False
    st["legal_ack"] = LEGAL_VERSION
    save_settings(st)
    return True


def install_flow(mg, st):
    if not legal_gate(st):
        pause()
        return
    dump = step_game(st)
    if not dump:
        return
    st["dump"] = dump
    st["install_dir"] = step_folder(st)
    st["language"] = step_language(mg, st)
    save_settings(st)
    if not consent(mg, st):
        pause()
        return
    st["jobs"] = step_jobs(mg, st)
    save_settings(st)
    p()
    if select_menu("Start this build?", SUMMARY_BUTTONS, "y", summary_rows(mg, st)) != "y":
        return
    code, why, live = do_build(mg, st)
    result_screen(mg, st, code, why, live)


def settings_screen(mg, st):
    while True:
        heading("Settings")
        p("   Game file:    " + (st.get("dump") or T.c("not chosen yet", "gray")))
        p("   Install to:   " + (st.get("install_dir") or DEFAULT_INSTALL + T.c("  (standard)", "gray")))
        p("   Language:     " + (st.get("language") or "en-US"))
        p("   Compiles:     " + (str(st.get("jobs")) if st.get("jobs") else "suggested from free memory"))
        p()
        k = choose([("1", "Change the game file", ""), ("2", "Change the install folder", ""), ("3", "Change the language", ""),
                    ("4", "Change the parallel compiles", ""), ("b", "Back", "")], "b")
        if k == "1":
            d = step_game(st, 1, 1)
            if d:
                st["dump"] = d
        elif k == "2":
            st["install_dir"] = step_folder(st, 1, 1)
        elif k == "3":
            st["language"] = step_language(mg, st, 1, 1)
        elif k == "4":
            st["jobs"] = step_jobs(mg, st)
        else:
            return
        save_settings(st)


def help_screen():
    heading("Help")
    for text in ("Start walks you through it: your game file, where to put it, the language, then what to fetch. Nothing downloads "
                 "until you say yes to it.",
                 "Stopping is always safe. Press Ctrl+C during a build; what is finished is kept, and Start again carries on.",
                 "Logs of every build are in " + LOG_DIR + ".",
                 "Your choices are remembered in " + SETTINGS_FILE + ". It holds paths, the language and the job count, nothing else.",
                 "'See what gets downloaded' lists every download with its source and size. EPONA.md explains the rest, including what was "
                 "tested and what was not.",
                 "The same build can be started from a script: py -I nx2/make_game.py --nup <file> --out <folder> (see --help).",
                 "Never share your game files or keys. This project is an unofficial fan effort and is not affiliated with Nintendo. The notice you "
                 "confirm on your first Start is in LEGAL.md, and TRANSPARENCY.md says what was and was not checked or tested."):
        for i, l in enumerate(wrap(text, T.width() - 8)):
            p("   " + (T.c(T.s["dot"], "cyan") + " " if i == 0 else "  ") + l)
        p()
    pause()


def home(mg):
    st = load_settings()
    while True:
        if T.tty and T.color:
            sys.stdout.write("\x1b[2J\x1b[H")   # (the visible screen only, so the header and the menu start at the top and fit; scrollback is kept)
        banner(st)
        if st.get("dump") and shutil.get_terminal_size((90, 40)).lines >= 34:   # (these two lines only when the window is tall enough for them)
            p("   " + T.c("Game file:  ", "gray") + tail(st["dump"], T.width() - 16))
            p("   " + T.c("Install to: ", "gray") + tail(st.get("install_dir") or DEFAULT_INSTALL, T.width() - 16))
        p()
        k = select_menu("Please select an option.", HOME_GROUPS, "1")
        try:
            if k == "1":
                install_flow(mg, st)
            elif k == "2":
                screen_check(mg, st)
            elif k == "3":
                heading("What gets downloaded")
                mg.print_tools()
                p()
                pause()
            elif k == "4":
                settings_screen(mg, st)
            elif k == "5":
                help_screen()
            else:
                raise Quit()
        except KeyboardInterrupt:
            p()
            p("  " + T.c("Back at the menu.", "gray"))


def run(mg):
    init()
    try:
        home(mg)
    except (Quit, KeyboardInterrupt):
        pass
    p()
    p("  " + T.c("Goodbye.", "gray"))
    p()


def preview(mg):
    """--ui-preview: the screens drawn once with real data, asking nothing and building nothing"""
    init()
    st = {"dump": r"C:\Users\you\Downloads\The Legend of Zelda Ocarina of Time.nup", "install_dir": DEFAULT_INSTALL, "language": "en-US", "jobs": 12}
    banner(st)
    p("   " + T.c("Game file:  ", "gray") + st["dump"])
    p("   " + T.c("Install to: ", "gray") + st["install_dir"])
    p()
    for l in render_panel("Please select an option.", HOME_GROUPS, 0):
        p(l)
    heading("What the build needs", (4, 4))
    show_pc(mg, st["install_dir"])
    p()
    items = tool_items(mg)
    show_medallions(items)
    p()
    show_checklist(items)
    heading("The confirmation ('Start this build?')")
    for l in render_panel("Start this build?", SUMMARY_BUTTONS, 0, summary_rows(mg, st)):
        p(l)
    heading("The meter: the whole job, then the step")
    meter = Live()
    for stage, frac, known, text in (("read", 0.30, True, "50000 files, 7.9 GB"), ("lift", 0.0, False, "translating"),
                                     ("compile", 0.35, True, "compiling nvdrv.c"), ("finish", 0.9, True, "putting the folder together")):
        meter.stage, meter.frac, meter.known = stage, frac, known
        p(meter.bar_text() + T.c(text, "gray"))
    meter.close()
    heading("Watching the build")
    live = Live()
    for raw in ("@@stage read Reading your game files", "@@progress 0.40", "extracting title 0 to the install folder", "@@progress 1.0",
                "@@stage compile Compiling", "@@progress 0.35", "FAILED nn_video.c (0 MB, 0s):", "@@progress 0.987", "compiled in 1034s, 1 failed"):
        live.line(raw)
    live.end_stage()
    live.close()
    p()
    box([T.c("The build did not finish.", "bold", "red"), "", "build.py stopped: host\\nn_video.c: 'libavcodec/avcodec.h' file not found", "",
         T.c("FFmpeg is missing or not found. Choose Start again and say yes to FFmpeg.", "yellow")], "Stopped", "red")
    p()
    box([T.c("Your game is ready.", "bold", "green"), "", "Folder:  " + st["install_dir"]], "All done", "green")
    p()
