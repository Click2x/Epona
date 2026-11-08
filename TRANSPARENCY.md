# Transparency

How we think about openness, and what you can check for yourself. We would rather tell you what we did **not** verify than let a
confident-looking page imply it.

## What Epona is, and what it is not

- Epona is a **fork of [Hookshot](https://github.com/NotRexed/Hookshot) by NotRexed**. Almost everything is the original author's and the
  contributors credited in [`readme.md`](readme.md#credits). Epona adds setup checks, a guided menu, a visible download list, logging and a
  safer updater. **The recompiler and the renderer were not touched.**
- It is **not** affiliated with Nintendo or with the original author, and **not** endorsed by either. See [`LEGAL.md`](LEGAL.md).
- It contains no game files and never downloads any.

## Everything it can download, in one place

- `py -I nx2/make_game.py --list-tools` prints every download and install the builder can make: where from, how big, how it is checked,
  and the switch that says yes ahead of time. [`EPONA.md`](EPONA.md) has the same list in a table.
- **Nothing is downloaded until you say yes**, item by item, in the menu (or at a prompt on the command line). Without a terminal that can
  ask, nothing is downloaded at all.
- Two kinds of download are checked differently, and we say which: pinned downloads (a compiler, headers, SDL) are compared with a SHA-256
  written into the code; the prebuilt FFmpeg is a **rolling daily build that cannot be pinned**, so it is only compared with the hash GitHub
  lists for it that day. That catches a corrupt download. It does **not** make the publisher trustworthy.
- If you would rather not trust that, decline it and build FFmpeg yourself with `scripts/epona_build_ffmpeg.sh` (it checks a GPG signature).

## What the software does on your PC

- No telemetry, no accounts, no analytics. Settings, logs and your choices stay on your PC in `%LOCALAPPDATA%\Epona`.
- The game's own update check is **off unless you set an update source** (`HOOKSHOT_UPDATE_REPO` or `update_repo.txt`). A game built from
  source never asks. If you turn it on, the downloaded builder must come from github.com for that repository and match the SHA-256 GitHub
  lists for it.
- It changes your PATH **only if you answer yes** to that one question, for your account only, and saves the old value so you can undo it.

## What was checked, and how far

- **Read:** the changes Epona made, line by line, for network, process and file calls. The whole inherited tree was searched for network,
  shell, registry, persistence, clipboard, anti-debug and dynamic-code calls, for every URL it names, and for committed binaries; every
  hit was read. The four speed-up data files from the original release were read and scanned (they hold only addresses, function names and
  counters). The findings are in [`EPONA.md`](EPONA.md#findings).
- **Not read line by line:** the recompiler's and the renderer's logic, and the vendored libraries (zstd, Opus, stb, Eden's and suyu's
  shader code). **A search for suspicious patterns cannot prove those are free of a deliberate flaw.**
- **Not used:** the original project's prebuilt `HookshotBuilder.zip`. On one test PC Windows Defender flagged a release zip as
  `Trojan:Script/Sabsik.EN.A!ml`, a generic machine-learning detection. It was never opened, so it is neither confirmed nor cleared.
  Building from source avoids that file.

## What has and has not been tested

Be honest with yourself about this before you trust it:

- **Tested:** that the code compiles and that the screens draw (a script checks that every panel row is the same width); the PC checks on
  one PC (an RTX 3090 with AVX2); the translation step; a compile of the translated game code and host that took about 17 minutes there.
- **Not tested:** a **complete build that ends in a game you can play**, started through Epona. At the time of writing, that first full run
  has not finished. The Vulkan back end had been silently skipped in an earlier compile (a bug in Epona's setup, since fixed) and has not
  been compiled yet. Arrow-key handling, the C# changes, and the FFmpeg-from-source script have never been run on a real machine.
- The unit tests in `tests/` were written but, in several cases, **not yet run**. [`EPONA.md`](EPONA.md#limits) lists each gap.
- One test PC restarted unexpectedly during testing, and several times the day before the build ran. The cause was not found, and the
  build's memory use was measured and ruled out. It is mentioned so nobody is surprised.

## Mistakes we made, and said

We keep a running account in [`EPONA.md`](EPONA.md#findings): FFmpeg was first called optional (it is required); the first compile built
no Vulkan back end while Epona's own check said all was well; a link check refused a download because the project had moved on GitHub; an
early memory theory for a freeze was not supported by the measurements. Each was corrected in the open.

## How it was built

Much of Epona's setup code, menu and documentation was written with an **AI coding assistant (Claude, by Anthropic)** working with the
maintainer, who directed and reviewed the work. An assistant can be wrong, which is why this page says what was and was not run. Every
change is in the git history, and `git diff ba594da` shows exactly how this fork differs from the upstream commit it started from.

## How to check for yourself

1. `git diff ba594da --stat` and read the diff. It is small compared with the project.
2. `py -I nx2/make_game.py --list-tools`, then decline whatever you do not want.
3. Run the build in a normal (non-administrator) terminal, and watch what it asks.
4. Compare the hashes in the code and in `EPONA.md` with the sources they name.
5. Tell us what we missed: open an issue.
