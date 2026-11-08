# SPDX-FileCopyrightText: 2026 The Epona contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Makes the announcement graphic: a 1280x720 PNG for Discord and the like, from the screens in docs/screens.

Run:  py -I scripts/make_announcement.py --link github.com/your-name/Epona

It writes docs/img/announcement.html and renders it to docs/img/epona-announcement.png with Microsoft Edge in headless mode (Edge is part of
Windows; nothing is downloaded). Without --link the link box is drawn as an obvious dashed placeholder, so a draft cannot be mistaken for
the final graphic. Run `py -I scripts/render_screens.py` first if docs/screens is missing.

The art is original shapes and text. It uses no Nintendo artwork or logos; the game is named only to say which one the tool builds.
The screens are the tool's own drawing code run on sample data (see render_screens.py), not photographs of a terminal.
"""
import argparse
import html
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCREENS = ROOT / "docs" / "screens"
OUT = ROOT / "docs" / "img"
EDGES = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]


def svg_size(name):
    head = (SCREENS / name).read_text(encoding="utf-8")[:400]
    return int(re.search(r'width="(\d+)"', head).group(1)), int(re.search(r'height="(\d+)"', head).group(1))


def stars(n=150):
    rnd = random.Random(7)   # (the same sky every time)
    dots = "".join('<circle cx="%d" cy="%d" r="%.1f" fill="#fff" opacity="%.2f"/>' % (rnd.randrange(1280), rnd.randrange(720), rnd.choice((.7, .9, 1.2, 1.6)),
                                                                                    rnd.uniform(.15, .8)) for _ in range(n))
    return '<svg class="abs" width="1280" height="720" viewBox="0 0 1280 720">%s</svg>' % dots


def page(link):
    home_w, home_h = svg_size("01-home.svg")
    conf_w, conf_h = svg_size("04-confirm.svg")
    prog_w, prog_h = svg_size("05-progress.svg")
    hh = 420
    cw_ = 300
    medallions = "".join('<i style="--c:%s"></i>' % c for c in ("#2faa4a", "#e0312f", "#2f7be0", "#f09a2c", "#9a3be0", "#f2d33a"))
    hearts = '<span class="on">%s</span><span class="off">%s</span>' % ("\u2665" * 13, "\u2665" * 7)
    if link:
        linkbox = '<div class="link"><small>GET IT</small><b>%s</b></div>' % html.escape(link)
    else:
        linkbox = '<div class="link draft"><small>GET IT</small><b>your link goes here</b></div>'
    template = """<!doctype html><meta charset="utf-8"><title>Epona announcement</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;width:1280px;height:720px;overflow:hidden}
body{position:relative;font-family:"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#e9efff;
background:radial-gradient(980px 560px at 16% 6%,#2a4fa8 0%,#142a74 36%,#08103a 70%,#03051a 100%)}
.abs{position:absolute}
.glow{position:absolute;left:-120px;top:380px;width:760px;height:520px;background:radial-gradient(closest-side,rgba(60,120,255,.28),transparent)}
.pill{left:40px;top:34px;padding:6px 16px;border-radius:999px;background:linear-gradient(180deg,#ffe38a,#f0b33a);color:#3a2a00;font-weight:800;letter-spacing:.2em;font-size:15px}
h1{position:absolute;left:38px;top:66px;margin:0;font-family:Georgia,"Times New Roman",serif;font-size:98px;line-height:1.05;letter-spacing:.07em;white-space:nowrap;
background:linear-gradient(180deg,#fffbe0 0%,#ffe08a 55%,#e9a93a 100%);-webkit-background-clip:text;background-clip:text;color:transparent;
filter:drop-shadow(0 6px 14px rgba(0,0,0,.45))}
.tag{left:42px;top:178px;width:420px;font-size:25px;line-height:1.3;color:#dfe8ff}
.tag b{color:#ffe9a8}
ul.bul{position:absolute;left:42px;top:268px;width:410px;margin:0;padding:0;list-style:none;font-size:18px;line-height:1.35;color:#cdd9ff}
ul.bul li{padding-left:30px;margin-bottom:11px;position:relative}
ul.bul li:before{content:"\\25C6";position:absolute;left:2px;color:#7fd6ff;font-size:15px;top:2px}
ul.bul b{color:#fff}
.meter{left:42px;top:484px;font-size:27px;letter-spacing:.06em;white-space:nowrap}
.meter .on{color:#ec2a35}.meter .off{color:#2c3768}
.med{left:44px;top:530px;display:flex;gap:11px}
.med i{display:block;width:26px;height:26px;border-radius:50%;background:radial-gradient(circle at 35% 30%,#fff9,var(--c) 45%,#0006 100%);
box-shadow:0 0 12px var(--c),inset 0 0 0 2px rgba(255,255,255,.35)}
.link{position:absolute;left:42px;top:590px;width:auto;max-width:420px;padding:10px 20px 12px;border-radius:14px;background:rgba(10,20,70,.75);border:2px solid #6fb2ff;box-shadow:0 8px 24px rgba(0,0,0,.4)}
.link small{display:block;font-size:12px;letter-spacing:.3em;color:#8fc4ff;font-weight:700}
.link b{font-family:"Cascadia Mono",Consolas,monospace;font-size:25px;color:#fff;letter-spacing:.01em}
.link.draft{border-style:dashed;border-color:#ffb347}.link.draft b{color:#ffd28a;font-family:"Segoe UI",sans-serif;font-style:italic}
.shot{border-radius:12px;box-shadow:0 20px 44px rgba(0,0,0,.6),0 0 0 1px rgba(255,255,255,.1)}
.cap{font-size:12px;color:#8fa2d8;letter-spacing:.04em}
.strip{left:480px;top:532px;width:770px;height:112px;border-radius:16px;background:rgba(8,16,62,.78);border:1px solid rgba(140,180,255,.35);
display:grid;grid-template-columns:1.25fr 1fr 1.35fr;gap:0;box-shadow:0 12px 30px rgba(0,0,0,.45)}
.strip>div{padding:13px 18px;border-right:1px solid rgba(140,180,255,.22)}.strip>div:last-child{border-right:0}
.strip h3{margin:0 0 5px;font-size:12px;letter-spacing:.24em;color:#8fc4ff;font-weight:700}
.strip p{margin:0;font-size:15.5px;line-height:1.33;color:#e6edff}.strip p b{color:#fff}.strip em{font-style:normal;color:#ffe08a}
.foot{left:40px;right:40px;top:672px;font-size:13px;line-height:1.35;color:#9fb1e6}
.foot b{color:#ffd9a0}
</style>
<div class="glow"></div>
@@stars@@
<div class="abs pill">INTRODUCING</div>
<h1>EPONA</h1>
<div class="abs tag">Ocarina of Time on your PC, <b>built from your own copy</b></div>
<ul class="bul">
<li><b>A guided menu</b> for the Hookshot recompilation: arrow keys, no command line</li>
<li><b>Checks your PC first</b>, before an hour-long build</li>
<li><b>Asks before every download</b>, with its source, size and check shown</li>
<li><b>Safe to stop</b>: Ctrl+C keeps your progress</li>
</ul>
<div class="abs meter">@@hearts@@</div>
<div class="abs med">@@medallions@@</div>
@@linkbox@@
<img class="abs shot" src="../screens/01-home.svg" style="left:480px;top:70px;height:@@hh@@px;width:@@hw@@px">
<img class="abs shot" src="../screens/04-confirm.svg" style="left:950px;top:70px;width:@@cw@@px;height:@@ch@@px">
<img class="abs shot" src="../screens/05-progress.svg" style="left:950px;top:@@py@@px;width:@@cw@@px;height:@@ph@@px">
<div class="abs cap" style="left:480px;top:494px">Screens drawn by the tool from sample data, not photos of a terminal</div>
<div class="abs strip">
<div><h3>THE GAME</h3><p><b>The Legend of Zelda: Ocarina of Time</b><br>Nintendo Switch 2 version. <em>You supply your own copy.</em></p></div>
<div><h3>SUPPORTED BUILD</h3><p>e0f3ccfa<br>program 0400486024DEC000<br>update v131072</p></div>
<div><h3>YOU NEED</h3><p>Windows 10/11 64-bit &middot; <b>AVX2</b> CPU &middot; 16 GB RAM &middot; about 60 GB free &middot; a Vulkan 1.3 GPU with <b>mesh shaders</b> (RTX 20 / GTX 16+, RX 6000+, Arc)</p></div>
</div>
<div class="abs foot"><b>Bring your own legally owned copy.</b> No game files are included or downloaded. Unofficial fan project, not affiliated with or endorsed by Nintendo.
Built on Hookshot by NotRexed (GPL-3.0). Built and played on one PC (an RTX 3090) and it played well there: expect rough edges elsewhere.</div>
"""
    values = dict(stars=stars(), hearts=hearts, medallions=medallions, linkbox=linkbox, hh=hh, hw=int(home_w * hh / home_h), cw=cw_,
                  ch=int(conf_h * cw_ / conf_w), py=70 + int(conf_h * cw_ / conf_w) + 14, ph=int(prog_h * cw_ / prog_w))
    for key, value in values.items():
        template = template.replace("@@%s@@" % key, str(value))
    return template


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--link", help="the address to show, for example github.com/your-name/Epona (without it a dashed placeholder is drawn)")
    ap.add_argument("--out", help="where to write the PNG (default: docs/img/epona-announcement.png, or ...-DRAFT.png without --link)")
    a = ap.parse_args()
    a.out = a.out or str(OUT / ("epona-announcement.png" if a.link else "epona-announcement-DRAFT.png"))
    if not SCREENS.is_dir() or not (SCREENS / "01-home.svg").exists():
        sys.exit("docs/screens is missing: run  py -I scripts/render_screens.py  first")
    OUT.mkdir(parents=True, exist_ok=True)
    html_path = OUT / "announcement.html"
    html_path.write_text(page(a.link), encoding="utf-8", newline="\n")
    edge = next((e for e in EDGES if os.path.isfile(e)), None)
    if not edge:
        sys.exit("Microsoft Edge was not found; open %s in any browser and screenshot it at 1280x720" % html_path)
    with tempfile.TemporaryDirectory() as profile:
        cmd = [edge, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1", "--window-size=1280,720",
               "--user-data-dir=" + profile, "--screenshot=" + a.out, html_path.as_uri()]
        subprocess.run(cmd, capture_output=True, timeout=90)
    if not os.path.isfile(a.out):
        sys.exit("Edge did not write the picture; open %s in a browser instead" % html_path)
    print("wrote %s (%d KB)%s" % (a.out, os.path.getsize(a.out) // 1024, "" if a.link else "  DRAFT: no --link given"))


if __name__ == "__main__":
    main()
