# SPDX-FileCopyrightText: 2026 The Epona contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Epona: an unattended "shader warm-up tour" of your own installed game. EXPERIMENTAL: read this first.

The game builds a graphics pipeline the first time something is drawn, so the first visit to each area drops the frame rate while the
PC builds them. They are kept for next time (hookshot_pipelines.bin and the driver's mkw_vk_pipelines.bin), so one visit to each
area, done now while you are away, spares you the hitch later. This tool does those visits for you.

For each area of the game it:
  1. writes that area's name and one of its own start positions (both read from your game's data, Banc/*_Dynamic.bcett.byml.zs, the
     StartPos actors) into ONE save slot, the one you name with --slot (default 5, the sixth). It never touches the other slots;
  2. starts the game with scripted button presses (HOS_INPUT_SCRIPT) that go from the title screen into the slot the game HIGHLIGHTS
     (on the install this was written on, the sixth, slot 5: if a visit starts in the wrong place, the game loaded another slot, so
     give --slot that one), then walks and
     turns the camera for a while so more of the area is drawn;
  3. closes the game and goes on to the next area.
At the end it puts the slot back as it was. Before anything is changed it copies your whole user\\save folder next to the install
folder (<install>-save-backup-<time>), and it tells you where.

What it needs: the game built by Epona, and nothing else. It reads your game's data and writes only to that slot, the backup, and a
log in %LOCALAPPDATA%\\Epona\\logs. It does not use the network and sends nothing anywhere. It never shares anything: the position
lists are made on your PC from your own copy.

What it does NOT know (untested at the time of writing): that every area loads from this edited save (adult-only areas, interiors and
the bosses' arenas may not); how long your PC needs to get from the title to the area (--boot, --dwell); and that the pipelines it
builds are enough to stop the hitches. Try it on two areas first:

    py -I scripts/epona_area_tour.py --dry-run
    py -I scripts/epona_area_tour.py --maps KokiriForest_Child,LostWood_Child --starts 1

Close the game before you run it, and leave the PC alone while it runs (it takes the keyboard focus like the game does). Ctrl+C
stops it, closes the game, and puts the slot back.
"""
import argparse
import datetime
import glob
import json
import os
import shutil
import struct
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nx2"))

# What the saves look like (read from this game's own files; see the checks in patch_slot, which refuse anything that does not match):
# a 16-byte header, then 8-byte entries {u32 flag hash, u32 value} up to the size in the header's third word; a value that is an
# address (strings, vectors) is the offset in the file of its data.
CURRENT_MAP_HASH = 492931546                              # the String64 flag holding the current map's name, e.g. KokiriForest_Child
POSITION_HASHES = (2517292394, 3364127117, 2272522285)    # the three copies of the player's position, 3 little-endian floats each
SECOND_NAME_AFTER = 1356                                  # the area's name without Child/Adult sits this far after the first field
HEIGHT_ABOVE_START = 1.0                                  # (so that the player drops onto the ground)
WALK = "LUP/4000,RRIGHT/2500,LUP/4000,RLEFT/5000,LUP/3000"   # (stick presses for the walk-and-look-around; held milliseconds)


class Byml:
    """The little part of the little-endian BYML version 7 that area files use: dictionaries, arrays, strings, numbers"""

    def __init__(self, d):
        if d[:2] != b"YB":
            raise ValueError("not a little-endian BYML")
        self.d = d
        _, kt, st, root = struct.unpack_from("<HIII", d, 2)
        self.keys, self.strs, self.root = self.table(kt), self.table(st), root

    def table(self, off):
        if not off:
            return []
        n = struct.unpack_from("<I", self.d, off)[0] >> 8
        offs = struct.unpack_from("<%dI" % (n + 1), self.d, off + 4)
        out = []
        for i in range(n):
            a = off + offs[i]
            out.append(self.d[a:self.d.index(b"\0", a)].decode("utf-8", "replace"))
        return out

    def value(self, t, v):
        d = self.d
        if t == 0xA0:
            return self.strs[v]
        if t in (0xC0, 0xC1):
            return self.node(v)
        if t == 0xD0:
            return bool(v)
        if t == 0xD1:
            return struct.unpack("<i", struct.pack("<I", v))[0]
        if t == 0xD2:
            return struct.unpack("<f", struct.pack("<I", v))[0]
        if t == 0xD3:
            return v
        if t == 0xD4:
            return struct.unpack_from("<q", d, v)[0]
        if t == 0xD5:
            return struct.unpack_from("<Q", d, v)[0]
        if t == 0xD6:
            return struct.unpack_from("<d", d, v)[0]
        return None

    def node(self, off=None):
        d = self.d
        off = self.root if off is None else off
        t, n = d[off], struct.unpack_from("<I", d, off)[0] >> 8
        if t == 0xC1:
            out = {}
            for i in range(n):
                e = off + 4 + i * 8
                k = struct.unpack_from("<I", d, e)[0] & 0xFFFFFF
                out[self.keys[k]] = self.value(d[e + 3], struct.unpack_from("<I", d, e + 4)[0])
            return out
        if t == 0xC0:
            types, base = d[off + 4:off + 4 + n], off + 4 + ((n + 3) & ~3)
            return [self.value(types[i], struct.unpack_from("<I", d, base + i * 4)[0]) for i in range(n)]
        raise ValueError("unexpected node type %#x" % t)


def start_positions(romfs, cache):
    """{area name: [(x, y, z), ...]} from every Banc/*/<area>_Dynamic.bcett.byml.zs; kept in cache (a file in this PC's own folder)"""
    if os.path.isfile(cache):
        with open(cache, encoding="utf-8") as f:
            return {k: [tuple(p) for p in v] for k, v in json.load(f).items()}
    import zstandard as zs
    import shader_census as sc
    dicts = sc.dictionaries(romfs, zs)
    out = {}
    for path in sorted(glob.glob(os.path.join(romfs, "Banc", "*", "*_Dynamic.bcett.byml.zs"))):
        name = os.path.basename(path)[:-len("_Dynamic.bcett.byml.zs")]
        try:
            with open(path, "rb") as f:
                root = Byml(sc.unpack(f.read(), dicts, zs)).node()
            out[name] = [tuple(round(x, 3) for x in a["Translate"]) for a in root.get("Actors", []) if a.get("Gyaml") == "StartPos"]
        except (ValueError, KeyError, struct.error, OSError) as e:
            print("  skipped %s (%s)" % (name, e))
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out


def flag_table(data):
    """{flag hash: value} of a progress.sav's entries"""
    end = 16 + struct.unpack_from("<I", data, 8)[0]
    if data[:4] != b"\x04\x03\x02\x01" or end > len(data):
        raise ValueError("this is not a save file this tool knows")
    return {h: v for h, v in (struct.unpack_from("<II", data, 16 + i) for i in range(0, end - 16 - 7, 8))}


def cstring(data, off, limit=64):
    raw = data[off:off + limit]
    return raw.split(b"\0", 1)[0].decode("ascii", "replace")


def patch_slot(data, area, pos):
    """A copy of a progress.sav with the current area and the player's position changed. Refuses (ValueError) anything that does not
    look as it did in the saves this was written from, so a changed save format cannot be damaged by it"""
    table = flag_table(data)
    if CURRENT_MAP_HASH not in table or any(h not in table for h in POSITION_HASHES):
        raise ValueError("the flags this tool changes are not in this save")
    name_at = table[CURRENT_MAP_HASH]
    old = cstring(data, name_at)
    if not old or not all(c.isalnum() or c == "_" for c in old) or len(area) >= 64:
        raise ValueError("the current-area field holds %s, which is not an area name" % ascii(old))
    out = bytearray(data)
    out[name_at:name_at + 64] = area.encode("ascii") + bytes(64 - len(area))
    base_at = name_at + SECOND_NAME_AFTER
    old_base = old.rsplit("_", 1)[0] if old.endswith(("_Child", "_Adult")) else old
    if cstring(data, base_at, 32) == old_base:   # (only when it is what it was in the saves seen: the same area without Child/Adult)
        new_base = area.rsplit("_", 1)[0] if area.endswith(("_Child", "_Adult")) else area
        if len(new_base) >= 32:
            raise ValueError("area name too long")
        out[base_at:base_at + 32] = new_base.encode("ascii") + bytes(32 - len(new_base))
    for h in POSITION_HASHES:
        if table[h] + 12 > len(out):
            raise ValueError("a position lies outside the file")
        struct.pack_into("<3f", out, table[h], pos[0], pos[1] + HEIGHT_ABOVE_START, pos[2])
    if len(out) != len(data):
        raise ValueError("the size changed")
    return bytes(out)


def read_area(data):
    return cstring(data, flag_table(data)[CURRENT_MAP_HASH])


def notes_count(install):
    """How many pipelines hookshot_pipelines.bin lists now (its header's second word is the size of a note)"""
    try:
        path = os.path.join(install, "hookshot_pipelines.bin")
        with open(path, "rb") as f:
            head = f.read(16)
        size, note = os.path.getsize(path), struct.unpack_from("<Q", head, 8)[0]
        return (size - 16) // note if note else 0
    except (OSError, struct.error):
        return 0


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq hookshot.exe"], capture_output=True, text=True, timeout=30).stdout
        return "hookshot.exe" in out.lower()
    except (OSError, subprocess.SubprocessError):
        return False


def kill_tree(proc):
    if proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=60)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass


def visit_key(area, p):
    return "%s|%.1f|%.1f|%.1f" % (area, *p)


def limit_cpus(proc, n):
    """Let a started process run on the first n logical CPUs only (Windows; quietly nothing elsewhere or on failure)"""
    try:
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x0200 | 0x0400, False, proc.pid)   # (SET_INFORMATION | QUERY_INFORMATION)
        if handle:
            ctypes.windll.kernel32.SetProcessAffinityMask(handle, (1 << n) - 1)
            ctypes.windll.kernel32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):
        pass


def plan_for(starts, wanted, per_map, adult, pick=None):
    """The visits: up to per_map start positions of each area, spread out (a start within 15 units of one already taken is no new view)"""
    plan = []
    for area, points in sorted(starts.items()):
        if not points:
            continue
        if wanted and area not in wanted:
            continue
        if not wanted and not adult and "Adult" in area:
            continue
        if pick is not None:   # (a start of your choice, by its number in the area's list; the same for every area)
            plan.append((area, points[min(pick, len(points) - 1)]))
            continue
        taken = []
        for p in points[::max(1, len(points) // per_map)] + points:   # (an even spread first, then any that is left)
            if len(taken) < per_map and all(sum((p[k] - q[k]) ** 2 for k in range(3)) >= 15 ** 2 for q in taken):
                taken.append(p)
        plan += [(area, p) for p in taken]
    return plan


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--install", help="the game folder (default: the one Epona's menu saved in %LOCALAPPDATA%\\Epona\\settings.json)")
    ap.add_argument("--slot", type=int, default=5, help="the one save slot this tool may overwrite, 0 to 5 (default 5, the one the scripted presses load); it is put back at the end")
    ap.add_argument("--maps", help="area names, comma-separated (default: every child and age-neutral area; --adult adds the adult ones)")
    ap.add_argument("--adult", action="store_true", help="also the adult areas (untested: the save is not made an adult's)")
    ap.add_argument("--starts", type=int, default=2, help="start positions to visit in each area (default 2, spread over its list)")
    ap.add_argument("--pick", type=int, help="visit start number N of each area (0 is the first of its list) instead of the spread; with --maps, to try them")
    ap.add_argument("--boot", type=int, default=45, help="seconds the scripted presses need to get from the title screen into the slot (default 45)")
    ap.add_argument("--dwell", type=int, default=75, help="seconds in the area after that, walking and looking around (default 75)")
    ap.add_argument("--pause", type=int, default=15, help="seconds to rest between visits (default 15)")
    ap.add_argument("--cores", type=int, help="let the game use only the first N logical CPUs, for a PC that struggles under full load (default: all)")
    ap.add_argument("--restart", action="store_true", help="forget which visits were done and begin again (by default a cut-short tour carries on)")
    ap.add_argument("--dry-run", action="store_true", help="only list what it would do, change nothing, start nothing")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    a = ap.parse_args()

    local = os.environ.get("LOCALAPPDATA", "")
    install = a.install
    if not install:
        try:
            with open(os.path.join(local, "Epona", "settings.json"), encoding="utf-8") as f:
                install = json.load(f)["install_dir"]
        except (OSError, KeyError, ValueError):
            sys.exit("Say which game folder with --install <folder> (Epona's settings were not found).")
    exe = os.path.join(install, "hookshot.exe")
    romfs = os.path.join(install, "romfs")
    saves = os.path.join(install, "user", "save")
    if not os.path.isfile(exe) or not os.path.isdir(romfs) or not os.path.isdir(saves):
        sys.exit("%s does not look like a game folder built by Epona (hookshot.exe, romfs and user\\save are expected)." % install)
    users = [d for d in os.listdir(saves) if os.path.isdir(os.path.join(saves, d))]
    if len(users) != 1:
        sys.exit("Expected one account folder in %s, found %d: not going on." % (saves, len(users)))
    slot_path = os.path.join(saves, users[0], "slot_%02d" % a.slot, "progress.sav")
    if not os.path.isfile(slot_path):
        sys.exit("%s does not exist: play once and save in slot %d (the sixth is slot 5), then try again." % (slot_path, a.slot))

    starts = start_positions(romfs, os.path.join(ROOT, "work", "tour_starts.json"))
    wanted = [m for m in (a.maps or "").split(",") if m]
    plan = plan_for(starts, wanted, max(1, a.starts), a.adult, a.pick)
    if wanted and any(w not in starts for w in wanted):
        sys.exit("Unknown area(s): %s" % ", ".join(w for w in wanted if w not in starts))
    per_visit = a.boot + a.dwell + 10
    print("%d visits to %d areas, about %d seconds each: roughly %.1f hours. Slot %d of %s is overwritten and put back."
          % (len(plan), len({p[0] for p in plan}), per_visit, len(plan) * per_visit / 3600, a.slot, install))
    for area, p in plan[:6]:
        print("   %-34s at (%.1f, %.1f, %.1f)" % (area, *p))
    if len(plan) > 6:
        print("   ... and %d more" % (len(plan) - 6))
    if a.dry_run:
        return
    if game_running():
        sys.exit("The game is running: close it first.")
    if not a.yes and input("Go ahead? Leave the PC alone while it runs. [y/N] ").strip().lower() not in ("y", "yes"):
        sys.exit("Nothing was changed.")

    # (what a cut-short run leaves: the slot as the tour had patched it. Its original is kept apart before the first patch and put
    # back first thing next time, so a crash or a power loss cannot make a patched slot look like your own save)
    state = os.path.join(install, "user", "epona-tour")
    os.makedirs(state, exist_ok=True)
    for kept in sorted(glob.glob(os.path.join(state, "slot*-original.sav"))):
        n = int(os.path.basename(kept)[4:6])
        target = os.path.join(saves, users[0], "slot_%02d" % n, "progress.sav")
        shutil.copyfile(kept, target)
        os.remove(kept)
        print("An earlier tour was cut short: slot %d is put back as it was before it." % n)
    backup = "%s-save-backup-%s" % (install.rstrip("\\/"), datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copytree(os.path.join(install, "user", "save"), backup)
    print("Your saves are copied to %s" % backup)
    with open(slot_path, "rb") as f:
        original = f.read()
    patch_slot(original, read_area(original), (0.0, 0.0, 0.0))   # (refuses a slot this tool does not understand, before anything is changed)
    kept_original = os.path.join(state, "slot%02d-original.sav" % a.slot)
    with open(kept_original, "wb") as f:
        f.write(original)
    progress_path = os.path.join(state, "progress.json")
    done = set()
    if not a.restart and os.path.isfile(progress_path):
        try:
            with open(progress_path, encoding="utf-8") as f:
                done = set(json.load(f))
        except (OSError, ValueError):
            done = set()
    if done:
        print("%d visits are already done (--restart to begin again)." % len(done & {visit_key(x, y) for x, y in plan}))
    script = "35:A,40:A,%d:A,%s" % (a.boot, ",".join("%d:%s" % (a.boot + 12 + 12 * i, tok) for i, tok in enumerate(WALK.split(","))))
    logdir = os.path.join(local, "Epona", "logs")
    os.makedirs(logdir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    logpath = os.path.join(logdir, "tour-%s.log" % stamp)
    total0, proc = notes_count(install), None
    try:
        with open(logpath, "w", encoding="utf-8") as log:
            for i, (area, p) in enumerate(plan, 1):
                if visit_key(area, p) in done:
                    continue
                try:
                    patched = patch_slot(original, area, p)
                except ValueError as e:   # (an area this tool cannot write into the save, such as a name too long for its field: left out)
                    line = "%3d/%d %-34s SKIPPED: %s" % (i, len(plan), area, e)
                    print(line)
                    log.write(line + "\n")
                    done.add(visit_key(area, p))
                    with open(progress_path, "w", encoding="utf-8") as f:
                        json.dump(sorted(done), f)
                    continue
                with open(slot_path, "wb") as f:
                    f.write(patched)
                env = dict(os.environ, HOS_INPUT_SCRIPT=script)
                before, t0 = notes_count(install), time.time()
                proc = subprocess.Popen([exe], cwd=install, env=env)
                if a.cores:
                    limit_cpus(proc, max(1, a.cores))
                while time.time() - t0 < a.boot + a.dwell and proc.poll() is None:
                    time.sleep(1)
                early = proc.poll() is not None
                kill_tree(proc)
                try:   # (the game's own log of this visit, kept: the next visit overwrites it)
                    shutil.copyfile(os.path.join(install, "hookshot_log.txt"), os.path.join(logdir, "tour-%s-%03d-%s.log" % (stamp, i, area)))
                except OSError:
                    pass
                line = "%3d/%d %-34s start (%.1f, %.1f, %.1f)  +%d pipelines%s" % (i, len(plan), area, *p, notes_count(install) - before,
                                                       "   ENDED EARLY (exit %s)" % proc.returncode if early else "")
                print(line)
                log.write(line + "\n")
                log.flush()
                done.add(visit_key(area, p))
                with open(progress_path, "w", encoding="utf-8") as f:
                    json.dump(sorted(done), f)
                time.sleep(max(3, a.pause))
    except KeyboardInterrupt:
        print("Stopped by you.")
    finally:
        if proc is not None:
            kill_tree(proc)
        with open(slot_path, "wb") as f:
            f.write(original)
        try:
            os.remove(kept_original)
        except OSError:
            pass
        print("Slot %d is back as it was. The pipeline list grew by %d (now %d). Log: %s" % (a.slot, notes_count(install) - total0,
                                                                                         notes_count(install), logpath))


if __name__ == "__main__":
    main()
