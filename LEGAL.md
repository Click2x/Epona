# Legal notice and responsible use

**Epona is a tool for people who already own the game. Please read this before you use it.**

*This is a plain-language notice from the people who maintain Epona. It is not legal advice, and it cannot protect you or anyone else
from a law, a court or a rights holder. If you are unsure about your situation, ask a lawyer where you live.*

## 1. You must legally own the game

- You need your own, legally obtained copy of **The Legend of Zelda: Ocarina of Time (Nintendo Switch 2 version)**.
- The dump (`.nup`, or the `exefs` and `romfs` folders) must be one **you made yourself, from your own console, for your own personal use**.
- Do **not** use Epona with a copy that you downloaded, were sent, or do not own. We do not support that and we will not help with it.

## 2. Epona contains no game, and gives you none

- This repository has **no** game files, dumps, keys, firmware, art, audio or text from the game. Epona never downloads any of them.
- The only downloads Epona can make are tools: a compiler, headers, FFmpeg and similar. Each is listed with its source, size and how it is
  checked in [`EPONA.md`](EPONA.md), and `py -I nx2/make_game.py --list-tools` prints the same list.

## 3. Do not share what you build

- Your dump, the files extracted from it, the install folder Epona builds (it holds the game's data), and the finished game contain
  **Nintendo's copyrighted code and data**, in translated form or as they are. **Do not upload, share, sell, mirror or post any of it.**
- Never post keys, firmware or anything else that is used to unlock a console's files.
- Epona's own source code is free software (see section 6) and may be shared. The game it builds from your copy may not.
- Screenshots and videos of the game running are your own responsibility; check the rights holder's published policies first.

## 4. This is an unofficial fan project

- Epona is **not made, endorsed, sponsored or approved by Nintendo**, by the author of Hookshot, or by anyone else named here.
- "Nintendo", "The Legend of Zelda", "Ocarina of Time", "Switch" and every related name, character and mark belong to their owners. They are
  used here only to say which game the tool works with. **"Epona" is the name of a character in that game**; it is used as a nod, and the
  project will be renamed if the rights holder asks.
- No artwork or logo from the game is used. The pictures in this repository are original shapes and text.

## 5. Laws differ, and following yours is up to you

- Copyright, and the rules on copying games or getting around technical protections, differ from country to country. In some places they
  limit dumping or converting a game even when you own it.
- **You are responsible for knowing and following the law where you live.** Using this tool in a way that breaks it is not something we
  can allow or defend.

## 6. License, warranty and liability

- Epona is a fork of **Hookshot by NotRexed** and keeps its license: **GNU General Public License, version 3 or later**
  ([`LICENSE`](LICENSE)). It contains code under other compatible licenses (Eden, suyu, Sirit, SDL, Opus, FFmpeg and others), which keep their
  own notices. What Epona changed is listed in [`EPONA.md`](EPONA.md); if you distribute a modified version you must keep these notices and
  offer its source.
- **There is no warranty.** The software is provided "as is", as the GPL says (sections 15 and 16): no promise that it works, that it is
  safe, or that it is fit for any purpose, and no liability for any loss or damage. You use it at your own risk.
- Tools Epona can download come from third parties and are run on your PC. Read the list first, and decline anything you do not want.
  Antivirus software may flag tools like this one (the original project's release zip was flagged on a test PC; see
  [`TRANSPARENCY.md`](TRANSPARENCY.md)).

## 7. If you are a rights holder

If you believe something in this repository infringes your rights, please **open an issue** in the repository. It will be read, and
handled in good faith and promptly.

## 8. What the menu asks of you

The first time you choose **Start** in the guided menu it shows the short version of this notice and asks you to confirm that you own a
legal copy and agree to these terms. Your confirmation is stored only on your own PC (`%LOCALAPPDATA%\Epona\settings.json`). It is a
reminder, not a contract, and not a substitute for reading this page.
