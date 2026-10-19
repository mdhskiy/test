# Without a Mac: the D3 loop on Windows

The README's flow (extract → rewrite → shaders → `build_ipa.sh` → IPA) needs a Mac for the app build and the Metal compiler.
This page is the same result with **no Mac of your own**: a CI runner builds the game-less "shell" once, and everything game-specific
is done on Windows. The shell is the D2R-era `DM_SHELL` build of `dm/ios` (loader.c's `DM_SHELL` branch): it holds the whole host,
no game content, and loads the game program from `Frameworks/Guest.framework/Guest` at boot.

```
┌─ once ──────────────────────────────────────────────────────────────┐
│ GitHub Actions (macOS runner, public repo = free)                  │
│   dm/ios/tools/shell_build.sh  →  DmIOS-shell-build-input.zip      │
│   (host executable + generic fonts; no game data, no keys)         │
└────────────────────────────────────────────────────────────────────┘
                              ↓ artifact
┌─ every iteration (Windows) ────────────────────────────────────────┐
│ patch_nso.py (native ruleset) → [your guest-side patches]          │
│ dmsh_xlate + spirv-cross (1,364 shaders → MSL, ~10 min first time) │
│ guest_dylib.py → Frameworks/Guest.framework/Guest                  │
│ d3rm_pack.py: shell + Guest + tables + msl/b-<V>/ + aoc → .ipa     │
│ iLoader / AltStore / Sideloadly: sign + install                    │
│ phone: Documents/log.txt (the boot log), Documents/romfs (game)    │
└────────────────────────────────────────────────────────────────────┘
```

## One-time: build the shell

The repository that goes to the public CI holds **host sources only** — `dm/`, `scripts/d3rm_pack.py`, the D3 game profile
(`dm/games/01001B300B9BE000/`: metadata — build IDs, memory constants, table file names; no game files), and the workflow
`.github/workflows/build-shell.yml`. No NSPs, no RomFS, no modules, no `prod.keys` ever leave your machine.

Push it public, run *Actions → Build shell → Run workflow*, download the artifact. (Or run `dm/ios/tools/shell_build.sh`
on any Mac with Xcode + `brew install xcodegen`.) The shell's bundle ID / team ID are placeholders; your sideloading tool
replaces them at install time. `dm/shell_manifest.txt` lists what `d3rm_pack.py` must build in; `dm/shell_info.txt` records
the product generation and the shader chain version the shell expects.

## Every iteration: pack on Windows

```bash
# one-time per machine: .NET SDK 10 on PATH (or DOTNET_ROOT), spirv-cross on PATH, the venv python (lz4, capstone)
set DM_GAME=01001B300B9BE000
set DM_GAMES_DIR=C:\Users\GZPI\d3-work\nsp-full\01001B300B9BE000_build\profile
set DM_ROOT=C:\Users\GZPI\d3-work\nsp-full\01001B300B9BE000_build
set PATH=C:\Users\GZPI\d2r-tools;%PATH%          # spirv-cross
set DOTNET_ROOT=C:\Users\GZPI\.dotnet            # this machine's bare "dotnet" is the runtime-only install

python nxnative-src\scripts\d3rm_pack.py ^
  --shell DmIOS-shell-build-input.zip ^
  --game C:\Users\GZPI\d3-work\nsp-full\01001B300B9BE000_survey\extract ^
  --aoc  C:\Users\GZPI\d3-work\nsp-full\01001B300B9BE000_survey\extract\aoc ^
  --out  D3Mobile_nxnative_未签名.ipa
```

- `--game` points at the directory with `ExeFS/{main,sdk}` (the merged 2.7.7 extraction). The build IDs are checked against
  the profile; a mismatch stops the pack.
- `--aoc` packs the DLC RomFS (`aoc/<index>/`; 简中 = index 11). Without it the game still boots, without the language pack.
- The **RomFS is not packed**: put the merged `CPKs/` tree into the phone's `Documents/romfs` through file sharing
  (i4Tools or the Files app). `main.m` accepts `Documents/romfs` as well as the in-app copy.
- `--guest-patch your.py` runs your guest-side patches (the VAMM initialization chain of your franken-ipa line) between the
  rewrite and the dylib; paths arrive through `PATCHED` / `GAME_DIR` / `EXEFS`.

What the packer does (each step skips when its output is already there): rewrite the modules with the current
`patch_nso.py` → re-register the translation chain for the local tools (Windows has no Metal compiler, so the chain
version forms its own branch; the lock rewrite is local) → `dmsh_build.py` under `nometal_run.py`: NVN → SPIR-V → MSL,
with the MSL **source** going into the package as `<key>_b.metallib` — the device compiles it on first use
(`nvn_mtl.m` detects an uncompiled library, the system caches the result) → align the chain version to the shell's
(directory name, each json's `chain` field, `c1_full.tsv`'s first line) → `guest_dylib.py` (pure Python, byte-identical
on Windows) → the rewriter tables + `shader_map.tsv` + `pso_manifest.tsv` into `dm/` → zip (already-compressed files stored).

## What you lose without a Mac

- **No Mac desktop host** (`make -C dm/host` + `boot.sh`): iteration happens on the device, reading `Documents/log.txt`
  (the same three markers: `UNIMPL <fn>`, `【红】…`, crash backtraces). One round-trip slower, same information.
- **No compile-time MSL validation**: a shader that fails to compile reports on the device, not at build time.
- No Instruments / GPU debugging.

## Why the shell is worth it for D3

The current host reads the memory layout (`mem_reserve / mem_alias / mem_stack / app_pool`) and the NVN constants from the
**game profile at build time** — your D3 provisional profile asks for Engage's partition (alias 4.375 GB), which covers
D3's 768 MB `StandardAllocator` carve outright, so the four immediate patches of your build 9 are configuration here.
It also carries the SDK 8.2.0 bring-up fixes (Link's Awakening's audio parameter, DSP command numbering,
`BindNpadStyleSetUpdateEvent`, the `vi` no-ops) that the D2R-era shell predates.
