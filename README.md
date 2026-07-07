# DCSS Remastered Audio

**Dynamic, zone-aware music and layered sound effects for Dungeon Crawl Stone Soup — added to the stock *precompiled* Windows Tiles binary, with no source code and no recompilation.**

DCSS (Tiles, Windows) ships with a bare-bones audio backend: it plays a single WAV at a
time through the WinMM `sndPlaySoundW` call. This project turns that single-channel,
event-only backend into a full **adaptive soundtrack** — per-branch music with crossfades,
HP-based ducking, and overlapping sound effects — **without touching the game's source.**

The upstream game lives at **[crawl/crawl](https://github.com/crawl/crawl)**. This repository
is a standalone add-on; it contains **no** Crawl source or binaries.

---

## Why this is different

Other DCSS audio projects either (a) require compiling the engine with `SOUND` support
(BindTheEarth, Crawler's Sound Patch), or (b) run in the **browser** on top of WebTiles
(the SoundSupport extension module). Both are great — but neither adds an adaptive
soundtrack to the **native, already-compiled desktop binary.**

This project does exactly that, using a **DLL-proxy hook** on `crawl.exe` — an approach
that, as far as public projects go, appears to be **unique for DCSS.**

| Project | Runs on | Recompile? | Zone music | Method |
|---|---|:---:|:---:|---|
| BindTheEarth / Crawler's Sound Patch | native | ✅ yes | ❌ | built-in `SOUND` system |
| SoundSupport (webtiles-extension) | browser (WebTiles) | ❌ | ✅ | JS extension module |
| **DCSS Remastered Audio (this)** | **native `crawl.exe`** | ❌ | ✅ | **`winmm.dll` proxy + external mixer** |

---

## How it works

```
                        crawl.exe (stock binary, unmodified)
                                     │  sndPlaySoundW("....wav")
                                     ▼
                     winmm.dll  ◄── proxy DLL (this project, C / x86 / MSVC)
                     │      │        forwards every unrelated WinMM export to the
                     │      │        real winmm.dll; intercepts sndPlaySoundW
                     │      ▼
                     │   real winmm (SysWOW64)   ← native passthrough fallback
                     ▼
              \\.\pipe\dcss_audio  (named pipe)
                     │
                     ▼
            Audio Director (Python + pygame-ce)
            multi-channel mixer:
              • per-branch music with crossfade
              • HP ducking (music dips on low-HP warning)
              • overlapping SFX groups
```

Two mechanisms feed the Director:

1. **Instant SFX** — Crawl's own `sound +=` rules (in `config/remaster.rc`) map log
   messages (`You hit`, `open the door`, `climb downwards`, …) to tiny WAV paths. The
   proxy sees the path and forwards a token over the pipe.

2. **State changes (music / ducking)** — a sandboxed **Lua `ready()` hook** watches
   `you.branch()`, `you.hp()`, and new-game transitions, then calls
   `crawl.playsound(".../state__branch_<X>.wav")`. These are **marker paths**, not real
   audio — the proxy reads the *filename*, maps it to a `music` / `duck` / `unduck`
   command, and the Director crossfades accordingly. The game believes it played a WAV;
   the Director actually swapped the soundtrack.

The Director always has a native passthrough fallback, so audio degrades gracefully if it
isn't running.

---

## Repository layout

```
remaster/
├── proxy/       winmm_proxy.c   — DLL forwarder + sndPlaySoundW hook (C, x86, MSVC)
│                build.ps1 / deploy.ps1
├── director/    director.py     — orchestrator
│                audio_engine.py — pygame-ce multi-channel mixer
│                pipe_server.py  — named-pipe server
│                router.py       — path→token→action mapping
│                soundmap.json   — event/branch → audio config
│                tests/          — TDD unit tests for the router
├── config/      remaster.rc     — sound rules + Lua ready() hook
│                gen_init.py     — wires remaster.rc into init.txt
├── tools/       fetch_music.py  — downloads CC-BY music (not bundled)
│                make_sfx.py     — synthesizes CC0 SFX
│                make_markers.py — generates marker WAVs
│                dump_imports.py — reverse-engineering helper
└── play-remaster.ps1            — one-click launcher (Director + game lifecycle)
```

Audio assets and the compiled `winmm.dll` are intentionally **not committed** (see
`.gitignore`) — music is fetched, SFX and markers are generated locally.

---

## Setup

> Requires the DCSS **Tiles for Windows 0.34** build (x86) and Python 3.

```powershell
# 1. Install the Director's dependencies
pip install -r director/requirements.txt

# 2. Generate SFX and marker WAVs
python tools/make_sfx.py
python tools/make_markers.py

# 3. Fetch the per-branch music (Kevin MacLeod, CC-BY — see CREDITS.txt)
python tools/fetch_music.py

# 4. Build the proxy DLL (x86 — must match crawl.exe)  and deploy it next to crawl.exe
powershell -File proxy/build.ps1
powershell -File proxy/deploy.ps1

# 5. Wire remaster.rc into the game's init.txt
python config/gen_init.py
```

Then launch with **`play-remaster.ps1`** (or the `Play DCSS Remastered.bat` shortcut): it
starts the Audio Director, launches the game, and shuts the Director down on exit.

---

## Reverse-engineering notes

Findings from analyzing the stock binary — useful if you port this to another build:

- The Tiles build uses the **WinMM `sndPlaySoundW`** backend (not SDL_mixer): natively WAV
  only, single channel. That single call is the entire hook surface.
- `crawl.exe` is **x86**, so the proxy must be x86, and the real `winmm.dll` must be copied
  from **`SysWOW64`** (not `System32`).
- DLL export forwarding must use
  `#pragma comment(linker, "/EXPORT:name=winmm_orig.name")` — the `.def` syntax is **not**
  interpreted as forwarding by MSVC.
- Crawl's config Lua is **sandboxed** (no `io`/`os`); the only way out to an external
  process is `crawl.playsound()` — which is exactly what the marker-path trick exploits.
- The startup warning *"sound will have no effect on this build"* is misleading — audio
  works fine through this path.

---

## Credits & licensing

- **Music** — Kevin MacLeod ([incompetech.com](https://incompetech.com)),
  Creative Commons **CC-BY 4.0**. Per-track attribution in [`CREDITS.txt`](CREDITS.txt).
  Not redistributed here; `fetch_music.py` downloads it.
- **Sound effects** — procedurally synthesized for this project (`tools/make_sfx.py`),
  released as **CC0 / public domain**.
- **Dungeon Crawl Stone Soup** is a separate GPL-2.0 project — [crawl/crawl](https://github.com/crawl/crawl).
  This add-on ships none of its code or binaries and communicates with the stock game only
  through the WinMM ABI and a named pipe.

This add-on's own code is provided as-is for **personal, non-commercial use** —
see [`LICENSE`](LICENSE).
