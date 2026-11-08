#!/usr/bin/env bash
# Epona: build FFmpeg for the Windows game from source, inside WSL (Ubuntu). Run it yourself:
#
#     wsl -d Ubuntu
#     cd /mnt/c/Hookshot-new        (this project's folder; the drive letter is lowercase after /mnt/)
#     bash scripts/epona_build_ffmpeg.sh
#
# Why: host/nn_video.c includes FFmpeg, and the game cannot be linked without its headers and four static libraries (avcodec, swscale,
# swresample, avutil). They normally come from the author's HookshotBuilder.zip; this builds them from source instead.
#
# What it downloads (it asks first, EPONA_YES=1 says yes ahead of time), both over https:
#   1. llvm-mingw 20261104, the Linux-hosted build of the SAME toolchain the Windows build uses (84,104,244 bytes, SHA-256 checked)
#   2. FFmpeg 9.0.2 source, ffmpeg.org (about 11 MB; FFmpeg publishes a GPG signature, no checksum, so the signature is checked
#      against the release signing key pinned below)
# What it needs from Ubuntu (it never uses sudo; it tells you the apt line if something is missing):
#   curl tar xz make gpg sha256sum, and the usual build tools.
# What it writes: ~/epona-ffmpeg (a scratch folder, safe to delete) and <project>/work/eg/.cache/cpm/ffmpeg/9.0.2/{include,lib},
# which nx2/build.py already searches. Nothing else on your PC is touched, and nothing it builds is run.
#
# Only the VP8 and VP9 decoders and the scaler are built (the game's AV1 movies are decoded by Windows). Static, w32 threads, no
# network, no assembly (so no nasm needed), and every optional library switched off.
set -euo pipefail

FFMPEG_VER=9.0.2
FFMPEG_URL="https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VER.tar.xz"
# FFmpeg's release signing key. CHECK THIS FINGERPRINT against the one ffmpeg.org publishes before you trust it: if it is wrong the
# signature simply fails to verify and this stops (it can fail, it cannot be fooled by it).
FFMPEG_KEY="FCF986EA15E6E293A5644F10B4322F04D67658D8"
MINGW_VER=20261104
MINGW_TAR="llvm-mingw-$MINGW_VER-ucrt-ubuntu-22.04-x86_64.tar.xz"
MINGW_URL="https://github.com/mstorsjo/llvm-mingw/releases/download/$MINGW_VER/$MINGW_TAR"
MINGW_SHA256="919380403de87dca3c581c2053230cd298af5e891286628ba0613b7fed370926"
MINGW_SIZE=84104244

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${EPONA_WORK:-$HOME/epona-ffmpeg}"
OUT="$PROJECT/work/eg/.cache/cpm/ffmpeg/$FFMPEG_VER"

say() { printf '%s\n' "$*"; }
die() { printf 'STOPPED: %s\n' "$*" >&2; exit 1; }

[ -f "$PROJECT/nx2/make_game.py" ] || die "run this from the project folder (it should hold nx2/make_game.py); found $PROJECT"
[ "$(uname -s)" = "Linux" ] || die "this is for Linux (WSL's Ubuntu)"

missing=()
for t in curl tar xz make gpg sha256sum gcc awk; do command -v "$t" >/dev/null 2>&1 || missing+=("$t"); done
if [ ${#missing[@]} -gt 0 ]; then
  say "Missing from Ubuntu: ${missing[*]}"
  say "Install them yourself, then run this again:"
  say "    sudo apt update && sudo apt install -y build-essential curl xz-utils gnupg"
  exit 1
fi

if [ -f "$OUT/include/libavcodec/avcodec.h" ] && [ -f "$OUT/lib/avcodec.lib" ]; then
  say "FFmpeg $FFMPEG_VER is already in $OUT. Delete that folder to build it again."
  exit 0
fi

say "This will download:"
say "  1. $MINGW_URL"
say "     ($MINGW_SIZE bytes, SHA-256 checked)"
say "  2. $FFMPEG_URL (about 11 MB) and its .asc signature"
say "and build FFmpeg in $WORK, then install it into:"
say "  $OUT"
if [ "${EPONA_YES:-}" != "1" ]; then
  read -r -p "Go ahead? [y/N] " yn
  case "$yn" in y|Y|yes|YES) ;; *) say "Nothing was downloaded."; exit 0;; esac
fi

mkdir -p "$WORK/dl"
cd "$WORK"

fetch() {  # url dest
  curl --proto '=https' --tlsv1.2 -fL --retry 3 -o "$2.part" "$1"
  mv "$2.part" "$2"
}

# ---- 1. the compiler: the same llvm-mingw release as on Windows, hosted on Linux ----
if [ ! -x "$WORK/llvm-mingw/bin/x86_64-w64-mingw32-clang" ]; then
  [ -f "dl/$MINGW_TAR" ] || fetch "$MINGW_URL" "dl/$MINGW_TAR"
  size=$(stat -c %s "dl/$MINGW_TAR")
  sum=$(sha256sum "dl/$MINGW_TAR" | awk '{print $1}')
  if [ "$size" != "$MINGW_SIZE" ] || [ "$sum" != "$MINGW_SHA256" ]; then
    rm -f "dl/$MINGW_TAR"
    die "llvm-mingw does not match its published size and SHA-256 (got $size bytes, $sum); deleted, not used"
  fi
  say "llvm-mingw: size and SHA-256 match"
  rm -rf llvm-mingw llvm-mingw.part
  mkdir llvm-mingw.part
  tar -xJf "dl/$MINGW_TAR" -C llvm-mingw.part --strip-components=1
  mv llvm-mingw.part llvm-mingw
fi
export PATH="$WORK/llvm-mingw/bin:$PATH"
x86_64-w64-mingw32-clang --version | head -1

# ---- 2. FFmpeg source, verified against FFmpeg's release signing key ----
TAR="ffmpeg-$FFMPEG_VER.tar.xz"
[ -f "dl/$TAR" ] || fetch "$FFMPEG_URL" "dl/$TAR"
[ -f "dl/$TAR.asc" ] || fetch "$FFMPEG_URL.asc" "dl/$TAR.asc"
say "FFmpeg tarball SHA-256 (for your records): $(sha256sum "dl/$TAR" | awk '{print $1}')"
export GNUPGHOME="$WORK/gnupg"
mkdir -p -m 700 "$GNUPGHOME"
if ! gpg --list-keys "$FFMPEG_KEY" >/dev/null 2>&1; then
  gpg --batch --keyserver hkps://keyserver.ubuntu.com --recv-keys "$FFMPEG_KEY" >/dev/null 2>&1 || \
  gpg --batch --keyserver hkps://keys.openpgp.org --recv-keys "$FFMPEG_KEY" >/dev/null 2>&1 || true
fi
status=$(gpg --batch --status-fd 1 --verify "dl/$TAR.asc" "dl/$TAR" 2>/dev/null || true)
if printf '%s\n' "$status" | grep -q '^\[GNUPG:\] GOODSIG' && printf '%s\n' "$status" | grep '^\[GNUPG:\] VALIDSIG' | grep -q "$FFMPEG_KEY"; then
  say "FFmpeg signature: good, by the pinned release key $FFMPEG_KEY"
elif [ "${EPONA_SKIP_GPG:-}" = "1" ]; then
  say "WARNING: the FFmpeg signature was NOT verified (EPONA_SKIP_GPG=1). Compare the SHA-256 above with another source before you trust it."
else
  die "the FFmpeg signature did not verify against $FFMPEG_KEY (key not fetched, or the fingerprint here is wrong, or the file is not genuine). Nothing was built. Check the fingerprint on ffmpeg.org; EPONA_SKIP_GPG=1 skips this check at your own risk."
fi

rm -rf "ffmpeg-$FFMPEG_VER" build prefix
tar -xJf "dl/$TAR"
mkdir build prefix
cd build

# ---- 3. configure and build: static, only what the game uses ----
"../ffmpeg-$FFMPEG_VER/configure" \
  --prefix="$WORK/prefix" \
  --enable-cross-compile --target-os=mingw32 --arch=x86_64 \
  --cross-prefix=x86_64-w64-mingw32- --cc=x86_64-w64-mingw32-clang --cxx=x86_64-w64-mingw32-clang++ \
  --enable-static --disable-shared \
  --disable-programs --disable-doc --disable-debug \
  --disable-autodetect --disable-network --disable-x86asm \
  --disable-everything \
  --disable-avformat --disable-avdevice --disable-avfilter --disable-postproc \
  --enable-avcodec --enable-swscale --enable-swresample --enable-avutil \
  --enable-decoder=vp8,vp9 --enable-parser=vp8,vp9 \
  --enable-w32threads --disable-pthreads

make -j"$(nproc)"
make install

# ---- 4. check what came out, then put it where nx2/build.py looks ----
for l in avcodec swscale swresample avutil; do
  [ -f "$WORK/prefix/lib/lib$l.a" ] || die "lib$l.a was not built; nothing was installed"
done
[ -f "$WORK/prefix/include/libavcodec/avcodec.h" ] || die "the headers were not installed; nothing was installed"

rm -rf "$OUT.part"
mkdir -p "$OUT.part/include" "$OUT.part/lib"
cp -r "$WORK/prefix/include/." "$OUT.part/include/"
for l in avcodec swscale swresample avutil; do
  cp "$WORK/prefix/lib/lib$l.a" "$OUT.part/lib/$l.lib"   # (the build names them .lib; lld reads the archive by its contents)
done
{
  echo "FFmpeg $FFMPEG_VER, built by scripts/epona_build_ffmpeg.sh on $(date -u +%Y-%m-%dT%H:%MZ)"
  echo "source: $FFMPEG_URL"
  echo "source sha256: $(sha256sum "$WORK/dl/$TAR" | awk '{print $1}')"
  echo "toolchain: llvm-mingw $MINGW_VER (ucrt), verified sha256 $MINGW_SHA256"
  echo "libraries (sha256):"
  (cd "$OUT.part/lib" && sha256sum ./*.lib)
} > "$OUT.part/EPONA-BUILD.txt"
rm -rf "$OUT"
mkdir -p "$(dirname "$OUT")"
mv "$OUT.part" "$OUT"

say ""
say "Done. FFmpeg $FFMPEG_VER is in:"
say "  $OUT"
cat "$OUT/EPONA-BUILD.txt"
say ""
say "Now run the game build again from Windows. The scratch folder $WORK can be deleted (rm -rf \"$WORK\")."
