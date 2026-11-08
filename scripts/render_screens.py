# SPDX-FileCopyrightText: 2026 The Epona contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Renders Epona's menu screens to SVG files in docs/screens/, for the readme and for announcements.

Run:  py -I scripts/render_screens.py

These are NOT photographs of a terminal. Each screen is drawn by the menu's own code (nx2/epona_ui.py) with SAMPLE values (a made-up
path, hardware and settings, so nothing personal is in them), its coloured output is captured, and every character is placed on a grid in
an SVG that looks like a terminal window. The look is faithful to the program; the fonts depend on whoever opens the file.
"""
import contextlib
import io
import os
import re
import shutil as real_shutil
import sys
import types
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "screens")

# colour into the capture, Unicode boxes and symbols, one fixed width so every screen is the same size
os.environ["EPONA_COLOR"] = "1"
os.environ["EPONA_UNICODE"] = "1"
os.environ["COLUMNS"] = "78"
os.environ.pop("NO_COLOR", None)
os.environ.pop("EPONA_ASCII", None)
sys.path.insert(0, os.path.join(ROOT, "nx2"))
import epona_ui as ui  # noqa: E402

# ------------------------------------------------------------------------------------------------ ANSI text to SVG

PALETTE16 = ["#0c0c0c", "#c50f1f", "#13a10e", "#c19c00", "#0037da", "#881798", "#3a96dd", "#cccccc",
             "#767676", "#e74856", "#16c60c", "#f9f1a5", "#3b78ff", "#b4009e", "#61d6d6", "#f2f2f2"]
DEFAULT_FG = "#cccccc"
WINDOW_BG = "#0c0c0c"
SGR = re.compile(r"\x1b\[([0-9;]*)m")
CW, LH, FS, PAD, BAR = 9.6, 21, 16, 18, 38   # cell width, line height, font size, padding, title-bar height


def xterm(n):
    if n < 16:
        return PALETTE16[n]
    if n < 232:
        c = n - 16
        lv = (0, 95, 135, 175, 215, 255)
        return "#%02x%02x%02x" % (lv[c // 36], lv[(c // 6) % 6], lv[c % 6])
    g = 8 + 10 * (n - 232)
    return "#%02x%02x%02x" % (g, g, g)


def parse_line(line):
    """[(char, fg, bg, bold)] for one line of coloured text"""
    fg, bg, bold, dim = DEFAULT_FG, None, False, False
    cells, i = [], 0
    while i < len(line):
        m = SGR.match(line, i)
        if m:
            codes = [int(c) if c else 0 for c in m.group(1).split(";")]
            k = 0
            while k < len(codes):
                c = codes[k]
                if c == 0:
                    fg, bg, bold, dim = DEFAULT_FG, None, False, False
                elif c == 1:
                    bold = True
                elif c == 2:
                    dim = True
                elif c == 22:
                    bold = dim = False
                elif 30 <= c <= 37:
                    fg = PALETTE16[c - 30]
                elif 90 <= c <= 97:
                    fg = PALETTE16[c - 90 + 8]
                elif c == 38 and k + 2 < len(codes) and codes[k + 1] == 5:
                    fg = xterm(codes[k + 2])
                    k += 2
                elif c == 48 and k + 2 < len(codes) and codes[k + 1] == 5:
                    bg = xterm(codes[k + 2])
                    k += 2
                elif c == 39:
                    fg = DEFAULT_FG
                elif c == 49:
                    bg = None
                k += 1
            i = m.end()
            continue
        cells.append((line[i], fg, bg, bold))
        i += 1
    return cells


def runs(cells):
    out = []
    for ch, fg, bg, bold in cells:
        if out and tuple(out[-1][1:]) == (fg, bg, bold):
            out[-1][0] += ch
        else:
            out.append([ch, fg, bg, bold])
    return [tuple(r) for r in out]


def to_svg(text, title):
    lines = text.rstrip("\n").split("\n")
    rows = [parse_line(l) for l in lines]
    cols = max((len(r) for r in rows), default=1)
    width = int(cols * CW + 2 * PAD)
    height = int(len(rows) * LH + BAR + 2 * PAD)
    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="%s">' %
         (width, height, width, height, escape(title))]
    o.append('<rect width="%d" height="%d" rx="12" fill="%s"/>' % (width, height, WINDOW_BG))
    o.append('<path d="M0 12a12 12 0 0 1 12-12h%da12 12 0 0 1 12 12v%dH0z" fill="#1f1f1f"/>' % (width - 24, BAR - 12))
    for n, colour in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        o.append('<circle cx="%d" cy="%d" r="6" fill="%s"/>' % (20 + n * 20, BAR // 2, colour))
    o.append('<text x="%d" y="%d" fill="#9a9a9a" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="13" text-anchor="middle">%s</text>' %
             (width // 2, BAR // 2 + 5, escape(title)))
    o.append('<g font-family="Cascadia Mono, Cascadia Code, Consolas, DejaVu Sans Mono, Menlo, monospace" font-size="%d">' % FS)
    for r, cells in enumerate(rows):
        x0, top = PAD, BAR + PAD + r * LH
        col = 0
        for text_run, fg, bg, bold in runs(cells):
            n = len(text_run)
            if bg:
                o.append('<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="%s"/>' % (x0 + col * CW, top, n * CW, LH, bg))
            if text_run.strip():
                o.append('<text x="%.1f" y="%d" fill="%s"%s textLength="%.1f" lengthAdjust="spacing" xml:space="preserve">%s</text>' %
                         (x0 + col * CW, top + FS, fg, ' font-weight="bold"' if bold else "", n * CW, escape(text_run)))
            col += n
    o.append("</g></svg>")
    return "\n".join(o)


# ------------------------------------------------------------------------------------------------ sample data (nothing personal)

class SampleShutil:
    """the menu's view of the PC: a fixed width, plenty of disk, and a Python on PATH"""
    get_terminal_size = staticmethod(real_shutil.get_terminal_size)
    which = staticmethod(lambda name: r"C:\Python312\python.exe")
    disk_usage = staticmethod(lambda path: types.SimpleNamespace(free=int(120 * 2 ** 30), total=int(500 * 2 ** 30), used=0))


def sample_mg(missing=()):
    ready = lambda name: name not in missing
    return types.SimpleNamespace(
        LANGUAGES=[("en-US", "English (US)"), ("en-GB", "English (UK)"), ("fr", "French (France)"), ("de", "German")],
        PYTHON_PACKAGES=(), GPUS_WITHOUT_MESH=re.compile(r"$^"), AV1_STORE_PAGE="",
        cpu_has_avx2=lambda: True, physical_memory_gb=lambda available=False: 46.0 if available else 64.0,
        graphics_cards=lambda: ["NVIDIA GeForce RTX 3090"], suggested_jobs=lambda: 12,
        llvm_mingw_present=lambda: ready("mingw"), vulkan_headers_present=lambda: ready("vulkan"), ffmpeg_dir=lambda: "x" if ready("ffmpeg") else None,
        sdl2_present=lambda: ready("sdl2"), work_data_present=lambda: ready("work"), av1_installed=lambda: ready("av1"))


SETTINGS = {"dump": r"C:\Users\you\Downloads\The Legend of Zelda Ocarina of Time [0400486024DEC000].nup",
            "install_dir": r"C:\Users\you\Games\Epona", "language": "en-US", "jobs": 12}


def capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def screen_home():
    ui.banner()
    ui.p()
    for l in ui.render_panel("Please select an option.", ui.HOME_GROUPS, 0):
        ui.p(l)


def screen_picker():
    items = [("1", "The Legend of Zelda Ocarina of Time [0400486024DEC000].nup", "23.3 GB   in C:\\Users\\you\\Downloads"),
             ("2", "another dump.nup", "9.1 GB   in D:\\Dumps"),
             ("t", "Type or paste a path", "or drag the file onto this window"), ("b", "Back to the menu", "")]
    ui.heading("Step 1 of 4  \u203a  Your game file")
    ui.p()
    for l in ui.render_panel("Please select a file.", [items], 0):
        ui.p(l)


def screen_check():
    mg = sample_mg(missing=("work",))
    ui.heading("Your PC")
    ui.show_pc(mg, SETTINGS["install_dir"])
    ui.heading("What the build needs")
    items = ui.tool_items(mg)
    ui.show_medallions(items)
    ui.p()
    ui.show_checklist(items)


def screen_confirm():
    mg = sample_mg()
    for l in ui.render_panel("Start this build?", ui.SUMMARY_BUTTONS, 0, ui.summary_rows(mg, SETTINGS)):
        ui.p(l)


def screen_progress():
    steps = (("read", 0.30, True, "50000 files, 7.9 GB", "Reading your game files"),
             ("lift", 0.0, False, "translating the game", "Translating the game to PC code"),
             ("compile", 0.35, True, "compiling nvdrv.c", "Compiling"),
             ("finish", 0.9, True, "putting the folder together", "Putting the game folder together"))
    base = 0.0
    for n, (stage, frac, known, last, label) in enumerate(steps, 1):
        lv = ui.Live.__new__(ui.Live)   # (not Live(): that would open a log file on this PC)
        lv.stage, lv.frac, lv.known, lv.base, lv.last = stage, frac, known, base, last
        ui.p()
        ui.p("  " + ui.T.c("Step %d of 4  %s  %s" % (n, ui.T.s["arrow"], label), "bold", "cyan"))
        ui.p(lv.bar_text() + ui.T.c(last, "gray"))
        span = ui.Live.SPAN[stage]
        base = span[0] + span[1]
        ui.p("   " + ui.T.c(ui.T.s["ok"], "green", "bold") + "  done " + ui.T.c("(a few minutes)", "gray"))


def screen_done():
    ui.box([ui.T.c("Your game is ready.", "bold", "green"), "", "Folder:  " + SETTINGS["install_dir"], "Start it:  hookshot.exe in that folder",
            ui.T.c("The first start prepares shaders, so the first minutes of play can stutter; it gets better.", "gray")], "All done", "green")


SCREENS = [("01-home", "Epona  \u2014  the menu", screen_home), ("02-game-file", "Epona  \u2014  choosing your game file", screen_picker),
           ("03-check-pc", "Epona  \u2014  checking this PC", screen_check), ("04-confirm", "Epona  \u2014  Start this build?", screen_confirm),
           ("05-progress", "Epona  \u2014  building", screen_progress), ("06-done", "Epona  \u2014  finished", screen_done)]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # (the menu draws boxes and hearts only when its terminal is UTF-8)
    except (AttributeError, ValueError):
        pass
    ui.init()
    ui.shutil = SampleShutil          # (the menu's disk, terminal and Python lookups, replaced by the sample values)
    ui.free_gb = lambda path: 120.0
    os.makedirs(OUT, exist_ok=True)
    for name, title, fn in SCREENS:
        text = capture(fn)
        path = os.path.join(OUT, name + ".svg")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(to_svg(text, title))
        print("%s  (%d lines)" % (os.path.relpath(path, ROOT), text.count("\n")))


if __name__ == "__main__":
    main()
