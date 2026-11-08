# Third-party components and their licenses

Epona is a modified version of **Hookshot by NotRexed** and is under the same license, **GPL-3.0-or-later** ([`LICENSE`](LICENSE)). Hookshot is
built from, and ships with, the work of many others. This page lists what is in this repository, what Epona can fetch for you, and what each is
licensed under.

**How sure each line is.** Lines marked **(file)** were checked by reading the license text, header or provenance note named beside them.
Lines marked **(their word)** are what the project says about itself, or common knowledge, and were **not** checked here: read the project's
own license before relying on them. If you find a mistake or a missing credit, please open an issue.

## How the licenses combine

The original project says it plainly (`third_party/a64-kit/NOTICE.TOTKPort.md`): *"Because of the GPL parts, `a64emit.dll`, the generated
runtime, the lifted C and every game build made with this kit are GPL. Game data and code are Nintendo's and are not included."* (file).
The whole is distributed under GPL-3.0-or-later; permissive parts (BSD, MIT, zlib and so on) keep their own notices, which must stay with them.

## 1. In this repository

| Component | Where | License | Where the text or notice is |
|---|---|---|---|
| **Hookshot, Rexcomp and the a64-kit tools** (NotRexed) and the contributors credited in [`readme.md`](readme.md#credits) | the whole repository | GPL-3.0-or-later (file) | [`LICENSE`](LICENSE); per-file SPDX headers (146 files say GPL-3.0-or-later) |
| **suyu**: the AArch64-to-C translator (`arm64_to_c.h`), the shader recompiler, common and video_core parts | `third_party/a64-kit/lift/suyu/`, `gpu/third_party/suyu/` | GPL-2.0-or-later and GPL-3.0-or-later, per file (file; 430 files say GPL-2.0-or-later) | `GPL-2.0-or-later.txt` and `GPL-3.0-or-later.txt` in `gpu/third_party/suyu/`; `third_party/a64-kit/NOTICE.TOTKPort.md` |
| **Eden**: the shader recompiler with its SPIR-V back end and the NVN2 task/mesh support | `gpu/vk/eden/`, `gpu/vk/compat/` | GPL-3.0-or-later, Eden Emulator Project (file) | per-file SPDX headers; `gpu/PROVENANCE.md`, `gpu/vk/VULKAN.md` |
| **Orchid** (MythosOfs) | credited in the readme as the source of a fog and exposure workaround | GPL (their word: the original readme says "under the GPL too") | the original `readme.md` license section |
| **Sirit** v1.0.5, plus Eden's mesh-shader ops patch | `gpu/vk/sirit/` | The source files say **"3-Clause BSD License", Copyright (c) 2019 sirit** (file). **But see the note below** | headers of the files in `gpu/vk/sirit/`; also `LICENSE` and `LICENSE.txt` there |
| **Opus** 1.5.2 | `third_party/opus/` | BSD-3-Clause (file) | `third_party/opus/COPYING` |
| **SDL** | `third_party/sdl2/` (the license; the DLL is fetched, see below) | zlib (file) | `third_party/sdl2/LICENSE.txt` |
| **stb_truetype** v1.26 | `third_party/stb/` | public domain or MIT, at your choice (file) | the end of `stb_truetype.h`; `third_party/stb/PROVENANCE.md` |
| **zbic** (kinnay), with Atmosphere-NX's single-file **zstd** | `third_party/zbic/` | zstd is BSD-or-GPLv2; the ZBIC parts come from Atmosphere-NX, GPLv2 (file) | `third_party/zbic/LICENSE` (the GPLv2 text); `third_party/zbic/PROVENANCE.md`. It is a separate tool used only to unpack the dump's modules: none of it is linked into the game |
| **NVN API types** (h1k421, as adapted by jhaizhou), the **native NVN layer's design** (d2r-mobile / MacNativeGames, jhaizhou), **AMD FidelityFX Super Resolution 1** (ported), **RenderDoc's `renderdoc_app.h`** | `gpu/render/`, `host/nvn_native.c` | MIT (file, per `NOTICE.TOTKPort.md` and `gpu/PROVENANCE.md`) | text in the files |
| **deko3d texture layout** (fincs) | `host/nvn_layout.c` | zlib (file, per `NOTICE.TOTKPort.md`) | `NOTICE.TOTKPort.md` |
| Small stand-ins for boost, fmt and ankerl::unordered_dense headers | `gpu/vk/compat/` | see each file | headers of each file |

### Files inside the suyu and Eden trees that carry another license as well

A file can hold code under several licenses. These carry a second one (file; read from their SPDX headers):

- `gpu/third_party/suyu/video_core/textures/astc.cpp`: GPL-3.0-or-later, and **Apache-2.0** for the part copyrighted 2016 by The University of North Carolina at Chapel Hill.
- `gpu/third_party/suyu/common/alignment.h`: GPL-3.0-or-later, and **CC0-1.0** for the part by Jannik Vogel (2014).
- `gpu/third_party/suyu/common/bit_field.h`: GPL-3.0-or-later, and **BSD-3-Clause AND GPL-2.0-or-later** for the part by Tony Wasserka and the Dolphin Emulator Project (2014).
- `gpu/vk/compat/common/container_hash.h`: GPL-3.0-or-later (Eden Emulator Project), and **BSL-1.0** for the part by Daniel James (2005-2014) and Austin Appleby (2016).
- `.../logic_operation_three_input_lut3.py` (two copies): **WTFPL**, by degasus (2022).

### A note on Sirit's license files (not resolved)

The Sirit source files carry a "3-Clause BSD License" notice, as the upstream readme describes ("other licenses that work with the GPL").
The same folder, `gpu/vk/sirit/`, also holds a **GPL-3.0** text (`LICENSE.txt`) and a **GNU Affero GPL-3.0** text (`LICENSE`). They do not
agree with the file headers, and **we do not know which governs**, or whether those texts came in with Eden's mesh-shader patch. We have not
changed anything. A BSD-3-Clause part combines with GPL-3.0 without trouble; if the AGPL text applies, its extra obligation is about offering
source to people who use the software over a network, which this program is not. **This is a question for the original author**; Epona will
follow whatever they confirm.

## 2. What Epona can fetch (not in this repository)

Every download asks first; `py -I nx2/make_game.py --list-tools` and [`EPONA.md`](EPONA.md) list sources, sizes and checks.

| Tool | License | Where the text is | How sure |
|---|---|---|---|
| **llvm-mingw** (Martin Storsj&ouml;) | The LLVM project: **Apache-2.0 with LLVM Exceptions** (file). The package also bundles mingw-w64 and other parts, each with its own license | `LICENSE.TXT` at the top of the unpacked `llvm-mingw` folder, and the license files inside it | file (the LLVM text); the rest their word |
| **Vulkan-Headers** (Khronos Group) | **Apache-2.0**, or **MIT** for some files (file) | `LICENSE.md` and `LICENSES/` in `work/eg/.cache/cpm/vulkanheaders/...` | file |
| **SPIRV-Headers** (Khronos Group) | Khronos's MIT-style "Materials" license (file) | `LICENSE` in `work/eg/.cache/cpm/spirv-headers/...` | file |
| **Vulkan Memory Allocator** (AMD GPUOpen) | **MIT** (file) | `LICENSE.txt` in `work/eg/.cache/cpm/vulkanmemoryallocator/...` | file |
| **SDL2** (`SDL2.dll`) | **zlib** (file) | `third_party/sdl2/LICENSE.txt` | file |
| **FFmpeg**, the prebuilt shared build from the FFmpeg-Builds project (formerly BtbN) | **LGPL-2.1-or-later** for the build variant named "lgpl", which leaves out the GPL-only parts | `LICENSE.txt` inside the zip; Epona now keeps a copy next to the extracted files and in the game folder | **their word**: the variant's name and its page, not read from the zip here. Source: ffmpeg.org; build scripts: FFmpeg-Builds |
| **Python packages** (installed by `pip` into your Python): lz4, numpy, capstone, unicorn, zstandard | lz4 BSD-3-Clause; numpy BSD-3-Clause; capstone BSD; **unicorn GPL-2.0**; zstandard BSD-3-Clause | each package's metadata, in your Python's `site-packages` | **their word**: not checked here. Epona does not redistribute them |
| **emsdk** (only on the Visual Studio route) and **Visual Studio Build Tools** | their own licenses and terms | their own installers and repositories | not checked here |

`wgpu-native` is not used by Epona's build. Its license (MIT or Apache-2.0, per the original notice) applies only if you supply it yourself.

## 3. How Epona keeps the notices with what it builds

When it finishes a build, Epona copies **`LICENSE`**, this file, and the license texts it holds for the tools above (FFmpeg's, SDL's) into a
**`licenses`** folder inside the install folder, so the game folder carries its own notices. That does not change section 3 of
[`LEGAL.md`](LEGAL.md): the game folder contains Nintendo's data and **must not be shared**.

## 4. If you redistribute Epona's source

You may, under the GPL: keep every license and copyright notice, say what you changed, and offer the source of any modified version. Do not
include the game, a dump, keys, or a built game folder. This page is information, not legal advice.
