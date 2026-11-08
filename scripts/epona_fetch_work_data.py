# SPDX-FileCopyrightText: 2026 The Epona contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Epona: fetch ONLY the four speed-up data files out of the author's HookshotBuilder.zip, without downloading the zip.

Run it yourself:   py -I scripts/epona_fetch_work_data.py [--repo owner/name] [--out folder]

It asks GitHub for the latest release of the repository (NotRexed/Hookshot unless you say otherwise), then reads the zip's index and
those four entries by HTTP range requests, a megabyte at a time. It stops if the server sends the whole file instead of a range, or if
more than 64 MB would be read. Only the four named files are written, nothing is unpacked or run, and they land in work_incoming/
(not work/), so you can look them over before the build uses them:

    hot_funcs.txt   hot_order.txt   hookshot_pieces.prof   image/chunks.txt

Their SHA-256 is printed. The zip's own digest cannot be checked, because the zip is not downloaded: what protects the files is https
from github.com, and your look at them. When you are satisfied, copy them into work/ (keeping image/chunks.txt in work/image/).
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

WANT = ("hot_funcs.txt", "hot_order.txt", "hookshot_pieces.prof", "image/chunks.txt")
BLOCK = 1 << 20
LIMIT = 64 << 20          # most this will read from the zip in all
MEMBER_LIMIT = 128 << 20  # a data file bigger than this is skipped
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = "epona-fetch-work-data"


class HttpRange(io.RawIOBase):
    """A read-only, seekable file over an https URL, fetched a block at a time with Range requests"""

    def __init__(self, url, size):
        self.url, self.size, self.pos, self.fetched, self.blocks = url, size, 0, 0, {}

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        self.pos = offset if whence == io.SEEK_SET else self.pos + offset if whence == io.SEEK_CUR else self.size + offset
        return self.pos

    def _block(self, i):
        if i not in self.blocks:
            start = i * BLOCK
            end = min(self.size, start + BLOCK) - 1
            req = urllib.request.Request(self.url, headers={"Range": "bytes=%d-%d" % (start, end), "User-Agent": AGENT})
            with urllib.request.urlopen(req, timeout=60) as r:
                if r.status != 206:
                    sys.exit("The server did not honour a range request (status %d), so this stops here instead of downloading the whole "
                             "zip." % r.status)
                data = r.read()
            self.fetched += len(data)
            if self.fetched > LIMIT:
                sys.exit("This would read more than %d MB of the zip, so it stops. Nothing was written." % (LIMIT >> 20))
            self.blocks[i] = data
        return self.blocks[i]

    def readinto(self, b):
        n = min(len(b), self.size - self.pos)
        if n <= 0:
            return 0
        done = 0
        while done < n:
            i, off = divmod(self.pos, BLOCK)
            chunk = self._block(i)[off:off + (n - done)]
            b[done:done + len(chunk)] = chunk
            done += len(chunk)
            self.pos += len(chunk)
        return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default="NotRexed/Hookshot", help="owner/name of the repository whose latest release to read")
    ap.add_argument("--out", default=os.path.join(ROOT, "work_incoming"), help="where the four files go (default: work_incoming)")
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", a.repo):
        sys.exit("--repo must look like owner/name")
    api = urllib.request.Request("https://api.github.com/repos/%s/releases/latest" % a.repo,
                                 headers={"User-Agent": AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(api, timeout=30) as r:
        release = json.load(r)
    asset = next((x for x in release.get("assets", []) if x.get("name") == "HookshotBuilder.zip"), None)
    if not asset:
        sys.exit("The latest release of %s has no HookshotBuilder.zip." % a.repo)
    url, size = asset["browser_download_url"], int(asset["size"])
    if not url.startswith("https://github.com/%s/releases/download/" % a.repo):
        sys.exit("The release's download link is not on github.com for %s, so it was not used." % a.repo)
    print("release %s, HookshotBuilder.zip is %d MB: reading its index and the four data files only" % (release.get("tag_name"), size >> 20))
    raw = HttpRange(url, size)
    got = 0
    with zipfile.ZipFile(io.BufferedReader(raw, buffer_size=BLOCK)) as z:
        names = {n.replace("\\", "/"): n for n in z.namelist()}
        for want in WANT:
            name = next((names[k] for k in ("HookshotBuilder/tools/work/" + want, "tools/work/" + want) if k in names), None)
            if name is None:
                print("  not in the zip: " + want)
                continue
            if z.getinfo(name).file_size > MEMBER_LIMIT:
                print("  skipped (too big): " + want)
                continue
            data = z.read(name)
            dest = os.path.join(a.out, *want.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
            print("  %-22s %10d bytes  sha256 %s" % (want, len(data), hashlib.sha256(data).hexdigest()))
            got += 1
    print("fetched %.1f MB of the %d MB zip; %d of %d files written to %s" % (raw.fetched / 2 ** 20, size >> 20, got, len(WANT), a.out))


if __name__ == "__main__":
    main()
