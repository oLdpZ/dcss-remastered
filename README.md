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

## Graphics layer (video remaster)

**Dynamic screen grading, tint/desaturation, vignette, and "juice" (flash/shake/bloom
pulses) added on top of the audio remaster above — same idea, same no-recompile
constraint, applied to the video path instead of the audio path.**

The audio Director already knows the game's state (branch, HP, events) from the tokens
described above. The graphics layer reuses that same brain: **one Director process now
drives both audio and video**, writing the current visual target into a small shared-memory
block that a second proxy DLL reads once per frame and renders as a full-screen
post-process pass.

### Architecture

```
                        crawl.exe (stock binary, unmodified)
                                     │  wglMakeCurrent / glDraw* / ... (OpenGL calls)
                                     │  gdi32!SwapBuffers(hdc)   ← frame presentation
                                     ▼
                     opengl32.dll  ◄── proxy DLL (this project, C / x86 / MSVC)
                     │      │        forwards every OpenGL export to the real
                     │      │        opengl32.dll (367 forwarders, generated);
                     │      ▼        IAT-hooks gdi32!SwapBuffers in crawl.exe's
                     │   real opengl32 (SysWOW64)   import table
                     │
                     ▼ (on every hooked SwapBuffers call)
              dcss_gfx_state  (named shared-memory block, 108 bytes)
                     ▲
                     │  written once per Director tick
            Director (Python) — same process as the audio mixer
              VisualRouter: game token → VisualState → shared memory
              config: director/visualmap.json (grades, modifiers, events)
                     │
                     ▼
            postprocess.c (GLSL fragment shader, runs inside crawl.exe's
            own GL context, right after the hooked SwapBuffers call):
              capture back buffer → tint · desaturate · vignette
              + flash / shake / bloom envelopes + unstable/low-HP/death pulses
              → draw full-screen quad → let the real SwapBuffers present it
```

**Reverse-engineering note:** the Tiles binary does **not** call `wglSwapBuffers`
directly — it presents frames through **`gdi32!SwapBuffers`**, which is how GDI
generic-implementation OpenGL apps flip the back buffer. This is why the hook target
is `gdi32.dll`'s import address table entry for `SwapBuffers`, not something inside
`opengl32.dll` itself. `crawl.exe` imports `OPENGL32.dll` directly (which is what makes
the classic DLL-proxy trick from the audio layer work again here), and IAT hooking
`SwapBuffers` is the only reliable point to inject a post-process pass without patching
the binary.

### Repository layout (additions)

```
remaster/
├── gfx/
│   ├── gl_proxy.c        — OPENGL32.dll proxy: forwards every GL entry point,
│   │                        installs the SwapBuffers IAT hook, drives the frame
│   ├── gl_forwarders.h   — generated export-forwarding table (gen_forwarders.py)
│   ├── iat_hook.c/.h     — import-table scanning + hook installation
│   ├── postprocess.c/.h  — GLSL post-process pass (tint/desaturate/vignette/juice)
│   ├── shmem.c/.h        — reads the dcss_gfx_state shared-memory block
│   ├── shared_state.h    — GfxState struct (must match gfx_state.py's PACK_FORMAT)
│   ├── build.ps1         — builds opengl32.dll (x86 MSVC)
│   ├── deploy.ps1        — copies opengl32.dll next to crawl.exe
│   └── harness/          — headless GL test harness (build.ps1 + gl_harness.c),
│                            exercises pp_init()/pp_draw() without launching the game
├── director/
│   ├── gfx_state.py      — VisualState + PACK_FORMAT (Python mirror of GfxState)
│   ├── visual_router.py  — VisualRouter: token → VisualState, master enable/intensity
│   └── visualmap.json    — grades per branch, HP/unstable modifiers, event pulses
```

### Building & deploying

> Same toolchain constraint as the audio proxy: **x86 MSVC**, because `crawl.exe` is x86.

```powershell
# Build the proxy DLL (needs a real 32-bit opengl32.dll from SysWOW64 on PATH/in the
# VS dev prompt environment — build.ps1 sets this up)
powershell -File gfx/build.ps1

# Copy opengl32.dll next to crawl.exe (fails harmlessly if the game is running and
# has the DLL locked — just close the game and re-run)
powershell -File gfx/deploy.ps1

# Optional: headless sanity check without launching the game
powershell -File gfx/harness/build.ps1
gfx/harness/gl_harness.exe        # should print "PP_INIT: OK"
```

The Director (`director/director.py`) is the same process already started by
`play-remaster.ps1` for audio — no separate launcher for graphics.

### Tuning

All visual behavior — per-branch grades, tint colors, desaturation/vignette strength,
HP-low and unstable-branch modifiers, event pulse colors/intensities — lives in
**`director/visualmap.json`**. Edit the JSON and **restart the Director**; no rebuild of
the DLL is needed, since the proxy only reads numbers out of shared memory and never
embeds any game-state logic itself.

### Kill-switch

Set the environment variable **`DCSS_GFX_OFF=1`** before launching to disable the video
remaster entirely (audio remaster is unaffected) — human-verified passthrough.

### Graceful degradation

Every failure mode falls back to the **stock, untouched rendering path** — never a crash:

- **Director not running / shared memory absent** — `shmem_get()` returns `NULL`,
  `pp_draw` never draws.
- **`DCSS_GFX_OFF=1`** — proxy skips installing the hook / post-process entirely.
- **`master.enable = 0` in `visualmap.json`** — `VisualRouter.__init__` writes
  `master_enable = 0` into `VisualState`, and `pp_draw`'s first check
  (`!st->master_enable`) early-returns before touching any GL state.
- **Shader compile/link failure** — `pp_init()` checks `GL_COMPILE_STATUS` after
  compiling the fragment shader and `GL_LINK_STATUS` after linking the program; either
  failure returns 0 and `pp_draw` becomes a permanent no-op for that process.
- **Repeated GL error** — after every draw, `pp_draw` drains `glGetError()` in a loop
  (after state restore, so the drain itself can't perturb rendering). If a non-zero
  error recurs for 60 consecutive frames, the module logs once via
  `OutputDebugStringA` and sets a permanent `g_disabled` flag; every subsequent frame
  is passthrough. This guards against a driver/state problem persisting indefinitely.

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
