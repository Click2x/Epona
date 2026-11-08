"""Epona: tests for the two "fix it before going on" offers in nx2/make_game.py, with no registry change, no network and no real
folders: PATH merging, and taking only the four named data files out of a zip into a temporary folder.
Run:  py -I tests/test_epona_prompts.py"""
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nx2"))
import make_game as m  # noqa: E402


class FakeStdin:
    def __init__(self, answer):
        self.answer = answer

    def isatty(self):
        return True

    def readline(self):
        return self.answer + "\n"


class MergePath(unittest.TestCase):
    add = [r"C:\Py312", r"C:\Py312\Scripts"]

    def test_put_in_front(self):
        got = m.merge_path(r"C:\A;C:\B", self.add)
        self.assertEqual(got, r"C:\Py312;C:\Py312\Scripts;C:\A;C:\B")

    def test_nothing_to_add_twice(self):
        once = m.merge_path(r"C:\A", self.add)
        self.assertIsNone(m.merge_path(once, self.add))

    def test_case_and_trailing_slash_are_the_same_folder(self):
        got = m.merge_path("c:\\py312\\;D:\\x", self.add)
        self.assertEqual(got, r"C:\Py312\Scripts;c:\py312\;D:\x")


class WorkData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root, self.old_stdin = m.ROOT, sys.stdin
        m.ROOT = self.tmp.name
        self.zip = os.path.join(self.tmp.name, "fake.zip")
        with zipfile.ZipFile(self.zip, "w") as z:
            for n in m.WORK_DATA:
                z.writestr("HookshotBuilder/tools/work/" + n, "data " + n)
            z.writestr("HookshotBuilder/tools/work/evil.exe", "MZ")
            z.writestr("HookshotBuilder/tools/work/../../escape.txt", "no")
            z.writestr("HookshotBuilder/HookshotBuilder.exe", "MZ")

    def tearDown(self):
        m.ROOT, sys.stdin = self.old_root, self.old_stdin
        self.tmp.cleanup()

    def landed(self):
        return sorted(os.path.relpath(os.path.join(d, f), self.tmp.name).replace("\\", "/")
                      for d, _, fs in os.walk(self.tmp.name) for f in fs if f != "fake.zip")

    def test_only_the_four_named_files_land(self):
        sys.stdin = FakeStdin(self.zip)
        self.assertTrue(m.offer_work_data())
        self.assertEqual(self.landed(), sorted("work/" + n for n in m.WORK_DATA))

    def test_enter_goes_on_without_it(self):
        sys.stdin = FakeStdin("")
        self.assertFalse(m.offer_work_data())
        self.assertEqual(self.landed(), [])

    def test_a_bad_path_goes_on_without_it(self):
        sys.stdin = FakeStdin(r"C:\no\such\file.zip")
        self.assertFalse(m.offer_work_data())
        self.assertEqual(self.landed(), [])


class FfmpegZip(unittest.TestCase):
    """extract_ffmpeg_zip takes only the headers, four import libraries and four DLLs out of a BtbN-style shared-build zip"""
    TOP = "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0/"

    def make_zip(self, path, leave_out=(), extra=()):
        names = ["include/libavcodec/avcodec.h", "include/libswscale/swscale.h", "include/libavutil/avutil.h",
                 "lib/avcodec.lib", "lib/swscale.lib", "lib/swresample.lib", "lib/avutil.lib",
                 "bin/avcodec-62.dll", "bin/avutil-60.dll", "bin/swscale-9.dll", "bin/swresample-6.dll"]
        junk = ["bin/ffmpeg.exe", "bin/ffplay.exe", "bin/ffprobe.exe", "bin/avformat-62.dll", "bin/avfilter-11.dll", "lib/libavcodec.dll.a",
                "lib/pkgconfig/libavcodec.pc", "doc/ffmpeg.html", "LICENSE.txt", "include/readme.txt", "bin/avcodec-62.dll.sig"]
        with zipfile.ZipFile(path, "w") as z:
            for n in names:
                if n not in leave_out:
                    z.writestr(self.TOP + n, "data " + n)
            for n in junk + list(extra):
                z.writestr(self.TOP + n if not n.startswith("..") else "x/" + n, "junk " + n)

    def test_only_what_the_build_needs_is_taken(self):
        with tempfile.TemporaryDirectory() as tmp:
            zp, dest = os.path.join(tmp, "f.zip"), os.path.join(tmp, "out")
            self.make_zip(zp, extra=("../../escape.txt",))
            with zipfile.ZipFile(zp) as z:
                written = m.extract_ffmpeg_zip(z, dest)
            got = sorted(r for r, _ in written)
            self.assertEqual(got, sorted(["include/libavcodec/avcodec.h", "include/libswscale/swscale.h", "include/libavutil/avutil.h",
                                          "lib/avcodec.lib", "lib/swscale.lib", "lib/swresample.lib", "lib/avutil.lib",
                                          "bin/avcodec-62.dll", "bin/avutil-60.dll", "bin/swscale-9.dll", "bin/swresample-6.dll"]))
            on_disk = sorted(os.path.relpath(os.path.join(d, f), dest).replace("\\", "/") for d, _, fs in os.walk(dest) for f in fs)
            self.assertEqual(on_disk, got)
            self.assertFalse(os.path.exists(os.path.join(tmp, "escape.txt")))
            self.assertEqual(len(m.ffmpeg_dlls(dest)), 4)

    def test_a_zip_missing_what_the_build_needs_is_refused(self):
        # (each of: a library, the main header, and any single one of the four DLLs, which the game needs beside it to start)
        for gone in ("lib/avcodec.lib", "include/libavcodec/avcodec.h", "bin/avcodec-62.dll", "bin/avutil-60.dll", "bin/swscale-9.dll",
                     "bin/swresample-6.dll"):
            with self.subTest(gone=gone), tempfile.TemporaryDirectory() as tmp:
                zp = os.path.join(tmp, "f.zip")
                self.make_zip(zp, leave_out=(gone,))
                with zipfile.ZipFile(zp) as z:
                    with self.assertRaises(ValueError):
                        m.extract_ffmpeg_zip(z, os.path.join(tmp, "out"))


class GuidedMenuHelpers(unittest.TestCase):
    """the pure parts of nx2/epona_ui.py: nothing is asked, drawn to a screen or built"""

    def test_a_dump_is_recognised(self):
        import epona_ui as ui
        with tempfile.TemporaryDirectory() as tmp:
            nup = os.path.join(tmp, "game.nup")
            open(nup, "wb").close()
            other = os.path.join(tmp, "notes.txt")
            open(other, "wb").close()
            both = os.path.join(tmp, "dump")
            os.makedirs(os.path.join(both, "exefs"))
            os.makedirs(os.path.join(both, "romfs"))
            half = os.path.join(tmp, "half")
            os.makedirs(os.path.join(half, "exefs"))
            self.assertEqual(ui.check_dump(nup)[0], "nup")
            self.assertEqual(ui.check_dump(both)[0], "folders")
            for bad in (other, half, os.path.join(tmp, "nope.nup"), ""):
                kind, problem = ui.check_dump(bad)
                self.assertIsNone(kind)
                self.assertTrue(problem)

    def test_colour_codes_take_no_width(self):
        import epona_ui as ui
        self.assertEqual(ui.vlen("\x1b[1;32mhello\x1b[0m"), 5)
        self.assertEqual(ui.vlen("plain"), 5)

    def test_a_box_keeps_every_line_the_same_width(self):
        import contextlib
        import io
        import epona_ui as ui
        old = os.environ.get("NO_COLOR")
        os.environ["NO_COLOR"] = "1"
        try:
            ui.init()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ui.box(["short", "a longer line of text"], "Title", "green")
            widths = {len(l) for l in buf.getvalue().splitlines() if l.strip()}
            self.assertEqual(len(widths), 1)
        finally:
            if old is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = old

    def test_every_row_of_a_panel_is_the_same_width(self):
        import epona_ui as ui
        old = {k: os.environ.get(k) for k in ("NO_COLOR", "EPONA_COLOR", "EPONA_ASCII")}
        try:
            for colour in (False, True):
                os.environ.pop("NO_COLOR", None)
                os.environ.pop("EPONA_COLOR", None)
                os.environ["EPONA_ASCII"] = "1"
                os.environ["NO_COLOR" if not colour else "EPONA_COLOR"] = "1"
                ui.init()
                extra = [ui.plate_row("Game", "a" * 200), ui.hearts_row(12, 20, "12 compiles"), ui.medallions_row([True, False, None, True, True, False], "ok")]
                for lines in (ui.render_panel("Title", ui.HOME_GROUPS, 0), ui.render_panel("Start this build?", ui.SUMMARY_BUTTONS, 1, extra),
                              ui.render_panel("Requirements", [], -1, extra)):
                    rows = [ui.vlen(l) for l in lines if l.startswith("  ") and not l.startswith("   ")]
                    self.assertEqual(len(set(rows)), 1, rows)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_a_long_name_keeps_its_start_and_end_and_a_long_hint_goes_underneath(self):
        import epona_ui as ui
        old = os.environ.get("NO_COLOR"), os.environ.get("EPONA_ASCII")
        os.environ["NO_COLOR"], os.environ["EPONA_ASCII"] = "1", "1"
        try:
            ui.init()
            name = "The Legend of Zelda Ocarina of TIme [04004860224DEC000].nup"
            cut = ui.shorten(name, 30)
            self.assertEqual(len(cut), 30)
            self.assertTrue(cut.startswith("The Legend") and cut.endswith("C000].nup"), cut)
            self.assertEqual(ui.shorten("short", 30), "short")
            rows = ui.item_rows([[("1", name, "23.3 GB   in D:\\Downloads\\games\\something\\long"), ("t", "Type a path", "")]], 0)
            self.assertEqual(len(rows), 3 + 1)   # (the first item takes two rows, a blank row separates the second)
            self.assertEqual(len({ui.vlen(r) for r in rows}), 1)
            self.assertIn("23.3 GB", rows[1])
        finally:
            for key, val in zip(("NO_COLOR", "EPONA_ASCII"), old):
                if val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = val

    def test_one_meter_for_the_whole_job_and_extraction_gives_it_a_fraction(self):
        import contextlib
        import io
        import epona_ui as ui
        ui.init()
        live = ui.Live()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                live.line("@@stage read Reading your game files")
                self.assertAlmostEqual(live.overall(), 0.0)
                live.line("title 0: 0400486024dec000 v131072  exefs 5 files (main 1)  romfs 186587 files, 26.24 GB")
                live.line("  13120 files, 13.12 GB")   # (half of the 26.24 GB: no @@progress line was needed)
                self.assertTrue(live.known)
                self.assertAlmostEqual(live.frac, 0.5, places=2)
                self.assertAlmostEqual(live.overall(), 0.175, places=2)   # (half of the first step's 35%)
                live.line("@@stage lift Translating the game to PC code")
                self.assertAlmostEqual(live.overall(), 0.35)   # (the finished step keeps its whole share)
                self.assertFalse(live.known)
                live.line("@@stage compile Compiling")
                live.line("@@progress 0.5")
                self.assertAlmostEqual(live.overall(), 0.40 + 0.55 * 0.5)
                self.assertIn("step 3/4 50%", ui.ANSI.sub("", live.bar_text()))
        finally:
            live.close()

    def test_the_progress_lines_are_read(self):
        import contextlib
        import io
        import epona_ui as ui
        ui.init()
        live = ui.Live()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                live.line("@@stage compile Compiling")
                live.line("@@progress 0.987")
                live.line("FAILED nn_video.c (0 MB, 0s):")
                live.line("@@error build.py stopped: nn_video.c")
            self.assertAlmostEqual(live.frac, 0.987)
            self.assertEqual(live.failed, 1)
            self.assertEqual(live.error, "build.py stopped: nn_video.c")
        finally:
            live.close()


class PrebuiltFfmpegLink(unittest.TestCase):
    """only a github.com release download of the two accepted repository names is used for the prebuilt FFmpeg"""
    A = "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip"

    def test_the_new_and_the_old_name_are_accepted(self):
        self.assertTrue(m.prebuilt_url_ok("https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/latest/" + self.A))
        self.assertTrue(m.prebuilt_url_ok("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/" + self.A))
        self.assertTrue(m.prebuilt_url_ok("https://github.com/btbn/ffmpeg-builds/releases/download/latest/" + self.A))   # (GitHub names ignore case)

    def test_anything_else_is_refused(self):
        for bad in ("http://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/latest/" + self.A,
                    "https://github.com/FFmpeg-Builds/FFmpeg-Builds-evil/releases/download/latest/" + self.A,
                    "https://github.com/someone-else/FFmpeg-Builds/releases/download/latest/" + self.A,
                    "https://github.com.evil.example/FFmpeg-Builds/FFmpeg-Builds/releases/download/latest/" + self.A,
                    "https://evil.example/https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/latest/" + self.A,
                    "https://github.com/FFmpeg-Builds/FFmpeg-Builds/archive/latest.zip", ""):
            with self.subTest(url=bad):
                self.assertFalse(m.prebuilt_url_ok(bad))


if __name__ == "__main__":
    unittest.main()
