# Graphics Remaster Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an event-driven graphics post-processing layer (branch grading + HP/death modifiers + event juice) to DCSS Tiles 0.34 without recompiling `crawl.exe`.

**Architecture:** A new `opengl32.dll` proxy (twin of the existing `winmm.dll` audio proxy) forwards all GL calls to the real driver, tracks resolution via `glViewport`, and IAT-hooks `gdi32!SwapBuffers` to inject a fullscreen post-process pass. The existing Python Director (already the audio brain) becomes the video brain too: it maps the existing event-token stream to a visual-state struct written into named shared memory, which the proxy reads each frame and smooths/decays.

**Tech Stack:** C (MSVC, x86), legacy OpenGL (compatibility profile) + GLSL 2.0, Win32 file-mapping shared memory, Python 3 (`mmap` + `struct`), pytest.

## Global Constraints

- **Target x86.** `crawl.exe` is 32-bit. Build every DLL with `vcvarsall.bat x86` + `cl /LD /MACHINE:X86`. Real system DLL is copied from `C:\Windows\SysWOW64` (NOT System32).
- **Never recompile `crawl.exe`.** All behavior is added externally via proxy DLL + shared memory.
- **Never crash the game.** Any failure (missing shared memory, shader compile error, GL error) → silent passthrough. DCSS must run identically with the layer disabled.
- **Director is the sole brain.** All taste/mapping lives in Python + `visualmap.json` (hot-editable). The proxy is a dumb renderer.
- **Forwarders use the pragma pattern**, never `.def`: `#pragma comment(linker, "/EXPORT:name=opengl32_orig.name")`. Overridden exports use decorated form, e.g. `/EXPORT:glViewport=_glViewport@16`.
- **Shared memory name:** `dcss_gfx_state`, identical bare name on both sides (same user session).
- **Kill-switch:** env var `DCSS_GFX_OFF=1` forces proxy passthrough.

---

## File Structure

**New — GL proxy (`remaster/gfx/`):**
- `gl_proxy.c` — DllMain, `glViewport` override, IAT-hook install, `SwapBuffers` wrapper, per-frame orchestration.
- `gl_forwarders.h` — generated `#pragma` forwarders for all opengl32 exports except `glViewport`.
- `gen_forwarders.py` — reads real `opengl32.dll` exports, writes `gl_forwarders.h`.
- `iat_hook.c` / `iat_hook.h` — generic IAT patch helper.
- `postprocess.c` / `postprocess.h` — GL post-process: framebuffer capture, shader, fullscreen quad, state save/restore, smoothing/envelopes.
- `shared_state.h` — the shared-memory struct (C side of the IPC contract).
- `shmem.c` / `shmem.h` — open/map the shared memory read-only, with retry.
- `build.ps1` / `deploy.ps1` — mirror `remaster/proxy/` scripts.
- `harness/gl_harness.c` — standalone Win32+GL window to validate `postprocess.c` in isolation.

**New/modified — Director (`remaster/director/`):**
- `visualmap.json` — grades (22 branches), modifiers, events, master. (new)
- `visual_router.py` — token → `VisualState` (new)
- `gfx_state.py` — packs `VisualState` into the struct + writes named shared memory (new)
- `director.py` — wire visual_router + gfx_state into `handle()` (modify)
- `tests/test_visual_router.py`, `tests/test_gfx_state.py` (new)

---

## Task 1: opengl32 passthrough proxy (forwarders + build + deploy)

Deliverable: an `opengl32.dll` that forwards everything to the real driver. The game runs **identically** with it in place. De-risks the forwarding mechanism before any hooking.

**Files:**
- Create: `remaster/gfx/gen_forwarders.py`, `remaster/gfx/gl_forwarders.h` (generated), `remaster/gfx/gl_proxy.c`, `remaster/gfx/build.ps1`, `remaster/gfx/deploy.ps1`

**Interfaces:**
- Produces: `opengl32.dll` (passthrough); `gl_forwarders.h` included by `gl_proxy.c`.

- [ ] **Step 1: Write the forwarder generator**

Create `remaster/gfx/gen_forwarders.py`:

```python
"""Genera gl_forwarders.h dai nomi export della opengl32 reale (SysWOW64).
Ogni export viene inoltrato a opengl32_orig.<name>, TRANNE quelli che
sovrascriviamo noi (OVERRIDES)."""
import pefile, os

REAL = r"C:\Windows\SysWOW64\opengl32.dll"
OVERRIDES = {"glViewport"}   # implementati in gl_proxy.c
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "gl_forwarders.h")

pe = pefile.PE(REAL, fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
lines = ["/* AUTO-GENERATO da gen_forwarders.py — non modificare a mano */\n"]
n = 0
for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
    if not exp.name:
        continue  # export solo-ordinale: opengl32 non ne ha di rilevanti
    name = exp.name.decode()
    if name in OVERRIDES:
        continue
    lines.append('#pragma comment(linker, "/EXPORT:%s=opengl32_orig.%s")\n' % (name, name))
    n += 1
open(OUT, "w", encoding="ascii").write("".join(lines))
print("scritti %d forwarder in %s" % (n, OUT))
```

- [ ] **Step 2: Generate the header**

Run: `python remaster/gfx/gen_forwarders.py`
Expected: `scritti <N> forwarder in ...gl_forwarders.h` (N in the ~360–380 range).

- [ ] **Step 3: Write the passthrough proxy**

Create `remaster/gfx/gl_proxy.c` (glViewport override present but inert for now — just tracks + forwards):

```c
#include <windows.h>
#include "gl_forwarders.h"

/* Sovrascriviamo glViewport per conoscere la risoluzione del framebuffer.
   Nome decorato __stdcall: 4 argomenti da 4 byte -> @16. */
#pragma comment(linker, "/EXPORT:glViewport=_glViewport@16")

static HMODULE g_real = NULL;
int g_vp_w = 0, g_vp_h = 0;   /* aggiornati da glViewport, letti dal postprocess */

typedef void (WINAPI *glViewport_t)(GLint, GLint, GLsizei, GLsizei);

static HMODULE real_gl(void) {
    if (!g_real) g_real = LoadLibraryW(L"opengl32_orig.dll");
    return g_real;
}

void WINAPI glViewport(GLint x, GLint y, GLsizei w, GLsizei h) {
    g_vp_w = (int)w; g_vp_h = (int)h;
    HMODULE hm = real_gl();
    if (hm) {
        glViewport_t real = (glViewport_t)GetProcAddress(hm, "glViewport");
        if (real) real(x, y, w, h);
    }
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID unused) {
    (void)unused;
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(h);
    return TRUE;
}
```

Note: `GLint`/`GLsizei` come from `<GL/gl.h>`. Add `#include <GL/gl.h>` after `<windows.h>`.

- [ ] **Step 4: Write build.ps1**

Create `remaster/gfx/build.ps1` (mirror of `remaster/proxy/build.ps1`):

```powershell
$ErrorActionPreference = "Stop"
$vc = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat"
$here = $PSScriptRoot
python "$here\gen_forwarders.py"
if ($LASTEXITCODE -ne 0) { throw "gen_forwarders fallito" }
Remove-Item "$here\opengl32.dll","$here\opengl32.lib","$here\opengl32.exp","$here\*.obj" -ErrorAction SilentlyContinue
cmd /c "`"$vc`" x86 && cl /nologo /LD /O2 `"$here\gl_proxy.c`" `"$here\postprocess.c`" `"$here\iat_hook.c`" `"$here\shmem.c`" /Fe:`"$here\opengl32.dll`" /link /MACHINE:X86 opengl32.lib gdi32.lib user32.lib"
if ($LASTEXITCODE -ne 0) { throw "compilazione fallita (exit $LASTEXITCODE)" }
if (Test-Path "$here\opengl32.dll") { Write-Output "BUILD OK -> $here\opengl32.dll" } else { throw "opengl32.dll non prodotta" }
```

Note: `postprocess.c`, `iat_hook.c`, `shmem.c` are created in later tasks. For Task 1 only, temporarily build with just `gl_proxy.c` — edit the `cl` line to list only `gl_proxy.c`, then restore the full list at Task 2/4. (The linked `opengl32.lib` here is the SDK import lib for the *decorations reference* only; our forwarders resolve at load time against `opengl32_orig.dll`.)

- [ ] **Step 5: Write deploy.ps1**

Create `remaster/gfx/deploy.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$game = Split-Path (Split-Path $PSScriptRoot)   # ...\stone_soup-tiles-0.34
Copy-Item "$PSScriptRoot\opengl32.dll" "$game\opengl32.dll" -Force
if (-not (Test-Path "$game\opengl32_orig.dll")) {
    Copy-Item "C:\Windows\SysWOW64\opengl32.dll" "$game\opengl32_orig.dll" -Force
}
Write-Output "deploy gfx ok in $game"
```

- [ ] **Step 6: Build, deploy, verify passthrough**

Run:
```
powershell -File "remaster/gfx/build.ps1"
powershell -File "remaster/gfx/deploy.ps1"
```
Then launch `Play DCSS Remastered.bat` and confirm the game renders normally and runs a few turns without crashing. This is the pass condition: **no visual change, no crash.**

- [ ] **Step 7: Commit**

```bash
git add remaster/gfx/gen_forwarders.py remaster/gfx/gl_forwarders.h remaster/gfx/gl_proxy.c remaster/gfx/build.ps1 remaster/gfx/deploy.ps1
git commit -m "feat(gfx): opengl32 passthrough proxy + forwarder generator"
```

---

## Task 2: SwapBuffers IAT hook + constant tint overlay (the de-risk milestone)

Deliverable: a constant 20%-red tint visible in-game via a blended fullscreen overlay drawn at each frame present, with rigorous GL state save/restore and a working kill-switch. Proves the hook + draw + restore pipeline end-to-end **without** framebuffer capture or shaders (lowest-risk possible effect).

**Files:**
- Create: `remaster/gfx/iat_hook.c`, `remaster/gfx/iat_hook.h`, `remaster/gfx/postprocess.c`, `remaster/gfx/postprocess.h`
- Modify: `remaster/gfx/gl_proxy.c`

**Interfaces:**
- Consumes: `g_vp_w`, `g_vp_h` (from `gl_proxy.c`).
- Produces:
  - `void *iat_hook(const char *dll, const char *func, void *replacement);` → returns original pointer, or NULL on failure.
  - `void pp_draw_overlay(int w, int h);` → draws the current post-process overlay for a `w×h` framebuffer.

- [ ] **Step 1: Write the IAT hook helper**

Create `remaster/gfx/iat_hook.h`:

```c
#pragma once
/* Sostituisce nella Import Address Table del modulo principale la voce
   dll!func con `replacement`. Ritorna il puntatore originale, o NULL. */
void *iat_hook(const char *dll, const char *func, void *replacement);
```

Create `remaster/gfx/iat_hook.c`:

```c
#include <windows.h>
#include "iat_hook.h"

void *iat_hook(const char *dll, const char *func, void *replacement) {
    HMODULE base = GetModuleHandleW(NULL);           /* crawl.exe */
    if (!base) return NULL;
    HMODULE target = GetModuleHandleA(dll);
    if (!target) return NULL;
    FARPROC orig_addr = GetProcAddress(target, func);
    if (!orig_addr) return NULL;

    BYTE *b = (BYTE *)base;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)b;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(b + dos->e_lfanew);
    DWORD rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!rva) return NULL;
    IMAGE_IMPORT_DESCRIPTOR *imp = (IMAGE_IMPORT_DESCRIPTOR *)(b + rva);

    for (; imp->Name; imp++) {
        const char *name = (const char *)(b + imp->Name);
        if (lstrcmpiA(name, dll) != 0) continue;
        IMAGE_THUNK_DATA *thunk = (IMAGE_THUNK_DATA *)(b + imp->FirstThunk);
        for (; thunk->u1.Function; thunk++) {
            void **slot = (void **)&thunk->u1.Function;
            if (*slot != (void *)orig_addr) continue;
            DWORD old;
            VirtualProtect(slot, sizeof(void *), PAGE_READWRITE, &old);
            void *original = *slot;
            *slot = replacement;
            VirtualProtect(slot, sizeof(void *), old, &old);
            return original;
        }
    }
    return NULL;
}
```

- [ ] **Step 2: Write the overlay post-process (constant tint, immediate mode)**

Create `remaster/gfx/postprocess.h`:

```c
#pragma once
void pp_draw_overlay(int w, int h);
```

Create `remaster/gfx/postprocess.c`:

```c
#include <windows.h>
#include <GL/gl.h>
#include "postprocess.h"

/* Passo minimale: quad fullscreen semitrasparente rosso in blending.
   Nessuna cattura framebuffer, nessuno shader — solo prova di pipeline.
   Salva/ripristina rigorosamente lo stato GL per non corrompere DCSS. */
void pp_draw_overlay(int w, int h) {
    if (w <= 0 || h <= 0) return;

    glPushAttrib(GL_ALL_ATTRIB_BITS);
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity();
    glOrtho(0, 1, 0, 1, -1, 1);
    glMatrixMode(GL_MODELVIEW);  glPushMatrix(); glLoadIdentity();

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_TEXTURE_2D);
    glDisable(GL_LIGHTING);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    glColor4f(1.0f, 0.0f, 0.0f, 0.20f);   /* rosso 20% */
    glBegin(GL_QUADS);
        glVertex2f(0, 0); glVertex2f(1, 0);
        glVertex2f(1, 1); glVertex2f(0, 1);
    glEnd();

    glMatrixMode(GL_PROJECTION); glPopMatrix();
    glMatrixMode(GL_MODELVIEW);  glPopMatrix();
    glPopAttrib();
}
```

- [ ] **Step 3: Wire the SwapBuffers hook into the proxy**

Modify `remaster/gfx/gl_proxy.c`: add includes, the hook typedef/pointer, an install-once routine called from `glViewport` (guaranteed to run after the GL context exists), and the wrapper.

Add near the top (after existing includes):

```c
#include "iat_hook.h"
#include "postprocess.h"

typedef BOOL (WINAPI *SwapBuffers_t)(HDC);
static SwapBuffers_t g_real_swap = NULL;
static int g_hook_tried = 0;
static int g_off = -1;   /* kill-switch cache: -1 unknown, 0 on, 1 off */

static int gfx_off(void) {
    if (g_off < 0) g_off = GetEnvironmentVariableA("DCSS_GFX_OFF", NULL, 0) ? 1 : 0;
    return g_off;
}

static BOOL WINAPI hook_SwapBuffers(HDC hdc) {
    if (!gfx_off() && g_vp_w > 0 && g_vp_h > 0)
        pp_draw_overlay(g_vp_w, g_vp_h);
    return g_real_swap ? g_real_swap(hdc) : SwapBuffers(hdc);
}

static void install_hook_once(void) {
    if (g_hook_tried) return;
    g_hook_tried = 1;
    void *orig = iat_hook("gdi32.dll", "SwapBuffers", (void *)hook_SwapBuffers);
    if (orig) g_real_swap = (SwapBuffers_t)orig;
}
```

Then in `glViewport`, call `install_hook_once();` as the first line (before forwarding). This guarantees the hook is installed once rendering has begun.

- [ ] **Step 4: Restore full source list in build.ps1**

Ensure the `cl` line in `remaster/gfx/build.ps1` lists `gl_proxy.c postprocess.c iat_hook.c` (shmem.c is added in Task 4 — for now omit it and its call sites don't exist yet).

- [ ] **Step 5: Build, deploy, verify tint + kill-switch**

Run:
```
powershell -File "remaster/gfx/build.ps1"
powershell -File "remaster/gfx/deploy.ps1"
```
Launch the game: the whole view should have a faint red wash. Confirm the game still renders sprites/UI correctly underneath (state restore works) and does not crash over several turns.
Then set the kill-switch and relaunch:
```
setx DCSS_GFX_OFF 1   # or run: $env:DCSS_GFX_OFF=1 before launching from the same shell
```
Expected: no tint, normal game. Unset afterward.

- [ ] **Step 6: Capture evidence**

Take a screenshot with tint ON and one with `DCSS_GFX_OFF=1`. Save under `remaster/gfx/harness/` as `skeleton_on.png` / `skeleton_off.png` for the record.

- [ ] **Step 7: Commit**

```bash
git add remaster/gfx/iat_hook.c remaster/gfx/iat_hook.h remaster/gfx/postprocess.c remaster/gfx/postprocess.h remaster/gfx/gl_proxy.c remaster/gfx/build.ps1
git commit -m "feat(gfx): IAT-hook SwapBuffers + constant tint overlay (pipeline proven)"
```

---

## Task 3: Shared-memory contract + Python writer (TDD)

Deliverable: the `VisualState`→struct packing and named-shared-memory writer on the Python side, fully unit-tested, plus the matching C header. No game interaction yet.

**Files:**
- Create: `remaster/gfx/shared_state.h`, `remaster/director/gfx_state.py`, `remaster/director/tests/test_gfx_state.py`

**Interfaces:**
- Produces (Python):
  - `PACK_FORMAT = "<IIf fff ffff I ffff I f I ffff"` (little-endian; see fields below)
  - `STRUCT_SIZE` (== `struct.calcsize(PACK_FORMAT)` == 88)
  - `class VisualState` with fields: `version:int=1`, `master_enable:int=1`, `master_intensity:float=1.0`, `tint=(r,g,b)`, `grade_strength:float`, `desaturate:float`, `vignette:float`, `bloom_base:float`, `flash_seq:int`, `flash=(r,g,b)`, `flash_intensity:float`, `shake_seq:int`, `shake_intensity:float`, `bloom_seq:int`, `bloom=(r,g,b)`, `bloom_intensity:float`
  - `def pack(vs: VisualState) -> bytes` (len == 88)
  - `class GfxShmem` with `open()`, `write(vs)`, `close()` using `mmap.mmap(-1, STRUCT_SIZE, tagname="dcss_gfx_state")`
- Produces (C): `shared_state.h` struct `GfxState` matching the byte layout exactly.

- [ ] **Step 1: Write the failing test**

Create `remaster/director/tests/test_gfx_state.py`:

```python
import os, sys, struct
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), ""))
from gfx_state import VisualState, pack, STRUCT_SIZE, PACK_FORMAT

def test_struct_is_88_bytes():
    assert STRUCT_SIZE == 88
    assert struct.calcsize(PACK_FORMAT) == 88

def test_pack_roundtrip_fields_in_order():
    vs = VisualState()
    vs.tint = (0.1, 0.2, 0.3); vs.grade_strength = 0.5
    vs.desaturate = 0.4; vs.vignette = 0.6; vs.bloom_base = 0.05
    vs.flash_seq = 7; vs.flash = (1.0, 0.9, 0.0); vs.flash_intensity = 0.8
    vs.shake_seq = 3; vs.shake_intensity = 0.25
    vs.bloom_seq = 2; vs.bloom = (0.2, 0.6, 1.0); vs.bloom_intensity = 0.7
    raw = pack(vs)
    vals = struct.unpack(PACK_FORMAT, raw)
    assert vals[0] == 1                 # version
    assert vals[1] == 1                 # master_enable
    assert abs(vals[2] - 1.0) < 1e-6    # master_intensity
    assert tuple(round(v, 3) for v in vals[3:6]) == (0.1, 0.2, 0.3)   # tint
    assert vals[10] == 7                # flash_seq
    assert vals[15] == 3                # shake_seq
    assert vals[17] == 2                # bloom_seq

def test_defaults_are_neutral():
    v = struct.unpack(PACK_FORMAT, pack(VisualState()))
    assert v[3:6] == (0.0, 0.0, 0.0)    # no tint
    assert v[6] == 0.0                  # grade_strength
    assert v[7] == 0.0                  # desaturate
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest remaster/director/tests/test_gfx_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gfx_state'`.

- [ ] **Step 3: Write gfx_state.py**

Create `remaster/director/gfx_state.py`:

```python
"""Lato Python del contratto IPC grafico: impacchetta lo stato visivo e lo
scrive nella memoria condivisa 'dcss_gfx_state' letta dal proxy opengl32."""
import mmap, struct

# Ordine campi (little-endian). DEVE combaciare con GfxState in shared_state.h.
#  version(I) master_enable(I) master_intensity(f)
#  tint_r/g/b(f) grade_strength(f) desaturate(f) vignette(f) bloom_base(f)
#  flash_seq(I) flash_r/g/b(f) flash_intensity(f)
#  shake_seq(I) shake_intensity(f)
#  bloom_seq(I) bloom_r/g/b(f) bloom_intensity(f)
PACK_FORMAT = "<IIf" "ffff" "fff" "I" "ffff" "If" "I" "ffff"
STRUCT_SIZE = struct.calcsize(PACK_FORMAT)   # == 88
SHMEM_NAME = "dcss_gfx_state"

class VisualState:
    def __init__(self):
        self.version = 1
        self.master_enable = 1
        self.master_intensity = 1.0
        self.tint = (0.0, 0.0, 0.0)
        self.grade_strength = 0.0
        self.desaturate = 0.0
        self.vignette = 0.0
        self.bloom_base = 0.0
        self.flash_seq = 0
        self.flash = (0.0, 0.0, 0.0)
        self.flash_intensity = 0.0
        self.shake_seq = 0
        self.shake_intensity = 0.0
        self.bloom_seq = 0
        self.bloom = (0.0, 0.0, 0.0)
        self.bloom_intensity = 0.0

def pack(vs):
    return struct.pack(
        PACK_FORMAT,
        vs.version, vs.master_enable, vs.master_intensity,
        vs.tint[0], vs.tint[1], vs.tint[2], vs.grade_strength,
        vs.desaturate, vs.vignette, vs.bloom_base,
        vs.flash_seq, vs.flash[0], vs.flash[1], vs.flash[2], vs.flash_intensity,
        vs.shake_seq, vs.shake_intensity,
        vs.bloom_seq, vs.bloom[0], vs.bloom[1], vs.bloom[2], vs.bloom_intensity,
    )

class GfxShmem:
    def __init__(self):
        self._mm = None
    def open(self):
        # -1 fd => mapping su pagefile, con nome: il proxy fa OpenFileMapping(SHMEM_NAME).
        self._mm = mmap.mmap(-1, STRUCT_SIZE, tagname=SHMEM_NAME)
    def write(self, vs):
        if self._mm is None:
            return
        self._mm.seek(0)
        self._mm.write(pack(vs))
    def close(self):
        if self._mm is not None:
            self._mm.close(); self._mm = None
```

Wait — the packed field count must equal the format. Verify: `PACK_FORMAT` groups → `I I f | f f f f | f f f | I | f f f f | I f | I | f f f f` = 2+1 +4 +3 +1 +4 +2 +1 +4 = 22 items. `pack()` passes exactly 22 values. Good.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest remaster/director/tests/test_gfx_state.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Write the matching C header**

Create `remaster/gfx/shared_state.h`:

```c
#pragma once
#include <stdint.h>

/* DEVE combaciare byte-per-byte con PACK_FORMAT in gfx_state.py.
   Tutti i campi 4 byte, nessun padding. Totale 88 byte. */
#pragma pack(push, 1)
typedef struct {
    uint32_t version;
    uint32_t master_enable;
    float    master_intensity;
    float    tint_r, tint_g, tint_b;
    float    grade_strength;
    float    desaturate;
    float    vignette;
    float    bloom_base;
    uint32_t flash_seq;
    float    flash_r, flash_g, flash_b, flash_intensity;
    uint32_t shake_seq;
    float    shake_intensity;
    uint32_t bloom_seq;
    float    bloom_r, bloom_g, bloom_b, bloom_intensity;
} GfxState;
#pragma pack(pop)

/* Verifica dimensione a compile-time. */
typedef char _gfxstate_size_check[(sizeof(GfxState) == 88) ? 1 : -1];
```

- [ ] **Step 6: Commit**

```bash
git add remaster/gfx/shared_state.h remaster/director/gfx_state.py remaster/director/tests/test_gfx_state.py
git commit -m "feat(gfx): shared-memory IPC contract + Python writer (tested)"
```

---

## Task 4: Proxy reads shared memory → applies a static grade

Deliverable: the proxy opens `dcss_gfx_state` (with retry), and the overlay uses `tint`, `grade_strength`, `vignette` from the struct instead of hardcoded red. A tiny Director-less smoke script writes a static green grade; the game shows it. Director absent → passthrough.

**Files:**
- Create: `remaster/gfx/shmem.c`, `remaster/gfx/shmem.h`, `remaster/director/tools/gfx_poke.py`
- Modify: `remaster/gfx/postprocess.c`, `remaster/gfx/postprocess.h`, `remaster/gfx/gl_proxy.c`, `remaster/gfx/build.ps1`

**Interfaces:**
- Produces:
  - `const GfxState *shmem_get(void);` → pointer to a local snapshot of the mapped struct, or NULL if not mapped. Call `shmem_poll()` once per frame to refresh (opens on first success, copies bytes).
  - `void pp_draw(const GfxState *st, int w, int h);` → replaces `pp_draw_overlay`; renders tint·strength + radial vignette as blended overlays (still no framebuffer capture — desaturate deferred to Task 5).

- [ ] **Step 1: Write shmem.c/.h**

Create `remaster/gfx/shmem.h`:

```c
#pragma once
#include "shared_state.h"
/* Ritorna lo snapshot corrente, o NULL se non mappato. */
const GfxState *shmem_get(void);
/* Da chiamare una volta per frame: apre (con retry) e copia lo struct. */
void shmem_poll(void);
```

Create `remaster/gfx/shmem.c`:

```c
#include <windows.h>
#include "shmem.h"

static HANDLE  g_map = NULL;
static void   *g_view = NULL;
static GfxState g_snap;
static int      g_have = 0;
static int      g_frames = 0;

static void try_open(void) {
    /* Riprova ogni ~60 frame se il Director non c'e' ancora. */
    if (g_map) return;
    if ((g_frames++ % 60) != 0) return;
    g_map = OpenFileMappingA(FILE_MAP_READ, FALSE, "dcss_gfx_state");
    if (!g_map) return;
    g_view = MapViewOfFile(g_map, FILE_MAP_READ, 0, 0, sizeof(GfxState));
    if (!g_view) { CloseHandle(g_map); g_map = NULL; }
}

void shmem_poll(void) {
    try_open();
    if (g_view) { memcpy(&g_snap, g_view, sizeof(GfxState)); g_have = 1; }
}

const GfxState *shmem_get(void) { return g_have ? &g_snap : NULL; }
```

- [ ] **Step 2: Replace overlay with struct-driven draw**

Modify `remaster/gfx/postprocess.h`:

```c
#pragma once
#include "shared_state.h"
void pp_draw(const GfxState *st, int w, int h);
```

Rewrite `remaster/gfx/postprocess.c` body of the draw (keep the state save/restore skeleton from Task 2):

```c
#include <windows.h>
#include <GL/gl.h>
#include <math.h>
#include "postprocess.h"

void pp_draw(const GfxState *st, int w, int h) {
    if (!st || !st->master_enable || w <= 0 || h <= 0) return;
    float mi = st->master_intensity;

    glPushAttrib(GL_ALL_ATTRIB_BITS);
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity();
    glOrtho(0, 1, 0, 1, -1, 1);
    glMatrixMode(GL_MODELVIEW);  glPushMatrix(); glLoadIdentity();
    glDisable(GL_DEPTH_TEST); glDisable(GL_TEXTURE_2D); glDisable(GL_LIGHTING);
    glEnable(GL_BLEND);

    /* Tinta: colore * strength su blending alpha. */
    float a = st->grade_strength * mi;
    if (a > 0.0f) {
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glColor4f(st->tint_r, st->tint_g, st->tint_b, a);
        glBegin(GL_QUADS);
            glVertex2f(0,0); glVertex2f(1,0); glVertex2f(1,1); glVertex2f(0,1);
        glEnd();
    }

    /* Vignette: quad radiale scuro ai bordi (approssimazione a fan). */
    float vg = st->vignette * mi;
    if (vg > 0.0f) {
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glBegin(GL_TRIANGLE_FAN);
            glColor4f(0,0,0,0.0f); glVertex2f(0.5f, 0.5f);       /* centro trasparente */
            glColor4f(0,0,0,vg);
            for (int i = 0; i <= 24; i++) {
                float t = (float)i / 24.0f * 6.2831853f;
                glVertex2f(0.5f + 0.75f*cosf(t), 0.5f + 0.75f*sinf(t));
            }
        glEnd();
    }

    glMatrixMode(GL_PROJECTION); glPopMatrix();
    glMatrixMode(GL_MODELVIEW);  glPopMatrix();
    glPopAttrib();
}
```

- [ ] **Step 3: Wire shmem into the frame hook**

Modify `remaster/gfx/gl_proxy.c`: include `shmem.h`; in `hook_SwapBuffers`, poll + draw with the struct:

```c
static BOOL WINAPI hook_SwapBuffers(HDC hdc) {
    if (!gfx_off()) {
        shmem_poll();
        pp_draw(shmem_get(), g_vp_w, g_vp_h);
    }
    return g_real_swap ? g_real_swap(hdc) : SwapBuffers(hdc);
}
```

Add `#include "shmem.h"` and remove the old `pp_draw_overlay` reference.

- [ ] **Step 4: Add shmem.c to build**

Edit `remaster/gfx/build.ps1` `cl` line to include `shmem.c`: `gl_proxy.c postprocess.c iat_hook.c shmem.c`.

- [ ] **Step 5: Write the poke smoke tool**

Create `remaster/director/tools/gfx_poke.py`:

```python
"""Scrive uno stato grafico statico nella shared memory e lo tiene vivo,
per testare il proxy senza il Director completo. Ctrl-C per uscire."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gfx_state import VisualState, GfxShmem

vs = VisualState()
vs.tint = (0.15, 0.6, 0.2); vs.grade_strength = 0.35; vs.vignette = 0.3  # verde Lair
shm = GfxShmem(); shm.open(); shm.write(vs)
print("shared memory scritta (verde). Ctrl-C per uscire.")
try:
    while True: time.sleep(1); shm.write(vs)
except KeyboardInterrupt:
    shm.close()
```

- [ ] **Step 6: Build, deploy, verify static grade + passthrough**

Run:
```
powershell -File "remaster/gfx/build.ps1"
powershell -File "remaster/gfx/deploy.ps1"
```
First launch the game with **no** poke tool running → confirm passthrough (no tint). Then, in a separate shell, run `python remaster/director/tools/gfx_poke.py`, launch the game → confirm a green wash + edge vignette appear. Close the poke tool, relaunch → passthrough again.

- [ ] **Step 7: Commit**

```bash
git add remaster/gfx/shmem.c remaster/gfx/shmem.h remaster/gfx/postprocess.c remaster/gfx/postprocess.h remaster/gfx/gl_proxy.c remaster/gfx/build.ps1 remaster/director/tools/gfx_poke.py
git commit -m "feat(gfx): proxy reads shared memory, renders struct-driven grade"
```

---

## Task 5: GLSL shader pass with framebuffer capture (enables desaturate)

Deliverable: replace the blended-overlay approximation with a single fullscreen shader pass that captures the frame to a texture and computes tint·desaturate·vignette in the fragment shader. Validated first in the standalone harness, then in-game. This unlocks true desaturation (needed by `hp_low`/death) which overlays cannot do.

**Files:**
- Create: `remaster/gfx/harness/gl_harness.c`
- Modify: `remaster/gfx/postprocess.c`, `remaster/gfx/postprocess.h`

**Interfaces:**
- Consumes: `GfxState`, `g_vp_w/h`.
- Produces: `pp_draw(const GfxState*, int w, int h)` now uses a captured-frame shader; adds internal `int pp_init(void)` (lazy, returns 0 on failure → caller falls back to passthrough).

- [ ] **Step 1: Add GL extension entry points + shader source**

In `remaster/gfx/postprocess.c`, add at top a minimal loader for the GL2 shader/texture entry points via `wglGetProcAddress` (types from `<GL/gl.h>` + manual typedefs). Include the fragment shader source as a string:

```c
/* --- entry point GL2 caricati a runtime --- */
typedef unsigned int GLenumx;
typedef char GLcharx;
typedef GLuint (WINAPI *PFNGLCREATESHADER)(GLenum);
typedef void   (WINAPI *PFNGLSHADERSOURCE)(GLuint, GLsizei, const GLcharx* const*, const GLint*);
typedef void   (WINAPI *PFNGLCOMPILESHADER)(GLuint);
typedef GLuint (WINAPI *PFNGLCREATEPROGRAM)(void);
typedef void   (WINAPI *PFNGLATTACHSHADER)(GLuint, GLuint);
typedef void   (WINAPI *PFNGLLINKPROGRAM)(GLuint);
typedef void   (WINAPI *PFNGLUSEPROGRAM)(GLuint);
typedef GLint  (WINAPI *PFNGLGETUNIFORMLOCATION)(GLuint, const GLcharx*);
typedef void   (WINAPI *PFNGLUNIFORM1F)(GLint, GLfloat);
typedef void   (WINAPI *PFNGLUNIFORM3F)(GLint, GLfloat, GLfloat, GLfloat);
typedef void   (WINAPI *PFNGLUNIFORM1I)(GLint, GLint);
typedef void   (WINAPI *PFNGLGETSHADERIV)(GLuint, GLenum, GLint*);

static PFNGLCREATESHADER   pglCreateShader;
static PFNGLSHADERSOURCE   pglShaderSource;
static PFNGLCOMPILESHADER  pglCompileShader;
static PFNGLCREATEPROGRAM  pglCreateProgram;
static PFNGLATTACHSHADER   pglAttachShader;
static PFNGLLINKPROGRAM    pglLinkProgram;
static PFNGLUSEPROGRAM     pglUseProgram;
static PFNGLGETUNIFORMLOCATION pglGetUniformLocation;
static PFNGLUNIFORM1F      pglUniform1f;
static PFNGLUNIFORM3F      pglUniform3f;
static PFNGLUNIFORM1I      pglUniform1i;
static PFNGLGETSHADERIV    pglGetShaderiv;

#define GL_FRAGMENT_SHADER 0x8B30
#define GL_COMPILE_STATUS  0x8B81

static const char *FRAG_SRC =
"uniform sampler2D tex;\n"
"uniform vec3 tint; uniform float strength;\n"
"uniform float desat; uniform float vignette;\n"
"uniform vec2 res;\n"
"void main(){\n"
"  vec2 uv = gl_FragCoord.xy / res;\n"
"  vec3 c = texture2D(tex, uv).rgb;\n"
"  float l = dot(c, vec3(0.299,0.587,0.114));\n"
"  c = mix(c, vec3(l), desat);\n"
"  c = mix(c, tint, strength);\n"
"  float d = distance(uv, vec2(0.5));\n"
"  c *= 1.0 - vignette * smoothstep(0.35, 0.75, d);\n"
"  gl_FragColor = vec4(c, 1.0);\n"
"}\n";
```

- [ ] **Step 2: Implement pp_init (load entry points, compile program, create texture)**

Add to `postprocess.c`:

```c
static int g_ready = -1;   /* -1 unknown, 0 failed, 1 ok */
static GLuint g_prog = 0, g_tex = 0;
static GLint u_tint,u_strength,u_desat,u_vignette,u_res,u_tex;

#define LOAD(var,type,name) var=(type)wglGetProcAddress(name); if(!var) return 0;

static int load_entrypoints(void){
    LOAD(pglCreateShader,PFNGLCREATESHADER,"glCreateShader");
    LOAD(pglShaderSource,PFNGLSHADERSOURCE,"glShaderSource");
    LOAD(pglCompileShader,PFNGLCOMPILESHADER,"glCompileShader");
    LOAD(pglCreateProgram,PFNGLCREATEPROGRAM,"glCreateProgram");
    LOAD(pglAttachShader,PFNGLATTACHSHADER,"glAttachShader");
    LOAD(pglLinkProgram,PFNGLLINKPROGRAM,"glLinkProgram");
    LOAD(pglUseProgram,PFNGLUSEPROGRAM,"glUseProgram");
    LOAD(pglGetUniformLocation,PFNGLGETUNIFORMLOCATION,"glGetUniformLocation");
    LOAD(pglUniform1f,PFNGLUNIFORM1F,"glUniform1f");
    LOAD(pglUniform3f,PFNGLUNIFORM3F,"glUniform3f");
    LOAD(pglUniform1i,PFNGLUNIFORM1I,"glUniform1i");
    LOAD(pglGetShaderiv,PFNGLGETSHADERIV,"glGetShaderiv");
    return 1;
}

int pp_init(void){
    if (g_ready >= 0) return g_ready;
    g_ready = 0;
    if (!load_entrypoints()) return 0;
    GLuint fs = pglCreateShader(GL_FRAGMENT_SHADER);
    pglShaderSource(fs, 1, &FRAG_SRC, NULL);
    pglCompileShader(fs);
    GLint ok = 0; pglGetShaderiv(fs, GL_COMPILE_STATUS, &ok);
    if (!ok) return 0;
    g_prog = pglCreateProgram();
    pglAttachShader(g_prog, fs);
    pglLinkProgram(g_prog);
    pglUseProgram(g_prog);
    u_tint=pglGetUniformLocation(g_prog,"tint");
    u_strength=pglGetUniformLocation(g_prog,"strength");
    u_desat=pglGetUniformLocation(g_prog,"desat");
    u_vignette=pglGetUniformLocation(g_prog,"vignette");
    u_res=pglGetUniformLocation(g_prog,"res");
    u_tex=pglGetUniformLocation(g_prog,"tex");
    pglUseProgram(0);
    glGenTextures(1, &g_tex);
    g_ready = 1;
    return 1;
}
```

Note: `u_res` is a `vec2`; set it via a `pglUniform2f` — add that typedef/loader alongside the others (`PFNGLUNIFORM2F`, `glUniform2f`).

- [ ] **Step 3: Rewrite pp_draw to capture + shade**

```c
void pp_draw(const GfxState *st, int w, int h){
    if (!st || !st->master_enable || w<=0 || h<=0) return;
    if (!pp_init()) return;                 /* fallback: nessun effetto */
    float mi = st->master_intensity;

    glPushAttrib(GL_ALL_ATTRIB_BITS);
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity(); glOrtho(0,1,0,1,-1,1);
    glMatrixMode(GL_MODELVIEW);  glPushMatrix(); glLoadIdentity();
    glDisable(GL_DEPTH_TEST); glDisable(GL_LIGHTING); glDisable(GL_BLEND);
    glEnable(GL_TEXTURE_2D);

    /* Cattura il back buffer nella texture. */
    glBindTexture(GL_TEXTURE_2D, g_tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glCopyTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, 0, 0, w, h, 0);

    pglUseProgram(g_prog);
    pglUniform1i(u_tex, 0);
    pglUniform3f(u_tint, st->tint_r, st->tint_g, st->tint_b);
    pglUniform1f(u_strength, st->grade_strength * mi);
    pglUniform1f(u_desat, st->desaturate * mi);
    pglUniform1f(u_vignette, st->vignette * mi);
    pglUniform2f(u_res, (float)w, (float)h);

    glBegin(GL_QUADS);
        glTexCoord2f(0,0); glVertex2f(0,0);
        glTexCoord2f(1,0); glVertex2f(1,0);
        glTexCoord2f(1,1); glVertex2f(1,1);
        glTexCoord2f(0,1); glVertex2f(0,1);
    glEnd();
    pglUseProgram(0);

    glMatrixMode(GL_PROJECTION); glPopMatrix();
    glMatrixMode(GL_MODELVIEW);  glPopMatrix();
    glPopAttrib();
}
```

- [ ] **Step 4: Write the standalone harness**

Create `remaster/gfx/harness/gl_harness.c`: a minimal Win32 window with a GL context that draws a colorful test scene (a few colored quads) each frame, then calls `pp_draw(&fake, w, h)` with a hardcoded `GfxState` (green tint 0.35, desat 0.5, vignette 0.3). Include `postprocess.c` in its own build line. Purpose: confirm the shader compiles and desaturates/tints correctly *without* launching crawl. Provide a `harness/build.ps1` that compiles `gl_harness.c postprocess.c` to `gl_harness.exe` linking `opengl32.lib gdi32.lib user32.lib`.

(Full harness source: a standard `WinMain` + `RegisterClass` + `wglCreateContext` loop drawing `glClearColor`, a red quad, a blue quad, then `pp_draw`, then `SwapBuffers`. ~120 lines of boilerplate — write it in full when implementing this task; no game-specific logic.)

- [ ] **Step 5: Validate in harness, then in-game**

Run `powershell -File remaster/gfx/harness/build.ps1` then `remaster/gfx/harness/gl_harness.exe`. Expected: the test scene appears desaturated + green-tinted + vignetted. If the shader fails to compile, `pp_init` returns 0 and the scene renders untouched — fix and repeat.
Then rebuild/redeploy the proxy and verify in-game with the poke tool (green + now genuine desaturation of the dungeon).

- [ ] **Step 6: Commit**

```bash
git add remaster/gfx/postprocess.c remaster/gfx/postprocess.h remaster/gfx/harness/
git commit -m "feat(gfx): GLSL post-process pass (capture + tint/desat/vignette)"
```

---

## Task 6: visualmap.json + visual_router (token → target state, TDD)

Deliverable: the Python mapping from event tokens to a `VisualState` target, data-driven by `visualmap.json`, fully unit-tested. No proxy interaction (that's Task 7).

**Files:**
- Create: `remaster/director/visualmap.json`, `remaster/director/visual_router.py`, `remaster/director/tests/test_visual_router.py`

**Interfaces:**
- Consumes: `VisualState` from `gfx_state.py`.
- Produces:
  - `class VisualRouter(visualmap: dict)` with:
    - `def branch(self, token) -> bool` — if token is `state__branch_*`, set the base grade target; return True if handled.
    - `def modifier(self, token) -> bool` — handle `state__hp_low/hp_ok/player_death`.
    - `def event(self, token) -> bool` — handle `evt__*`; bump the relevant pulse seq + set pulse color/intensity.
    - `def route(self, token) -> bool` — dispatches to the above; returns True if the token changed visual state.
    - `.state -> VisualState` — the current accumulated target (branch grade + active modifier).

- [ ] **Step 1: Write visualmap.json**

Create `remaster/director/visualmap.json`:

```json
{
  "master": {"enable": 1, "intensity": 1.0},
  "grades": {
    "D":      {"tint": [0.10,0.12,0.18], "strength": 0.10, "vignette": 0.20, "bloom_base": 0.0},
    "Temple": {"tint": [0.55,0.45,0.20], "strength": 0.14, "vignette": 0.15, "bloom_base": 0.05},
    "Lair":   {"tint": [0.15,0.45,0.18], "strength": 0.22, "vignette": 0.25, "bloom_base": 0.0},
    "Swamp":  {"tint": [0.25,0.30,0.12], "strength": 0.26, "vignette": 0.30, "bloom_base": 0.0},
    "Shoals": {"tint": [0.20,0.45,0.60], "strength": 0.20, "vignette": 0.15, "bloom_base": 0.03},
    "Snake":  {"tint": [0.35,0.42,0.12], "strength": 0.22, "vignette": 0.20, "bloom_base": 0.0},
    "Spider": {"tint": [0.28,0.15,0.35], "strength": 0.26, "vignette": 0.45, "bloom_base": 0.0},
    "Slime":  {"tint": [0.25,0.45,0.10], "strength": 0.30, "vignette": 0.25, "bloom_base": 0.06},
    "Orc":    {"tint": [0.45,0.28,0.12], "strength": 0.20, "vignette": 0.25, "bloom_base": 0.0},
    "Elf":    {"tint": [0.30,0.30,0.55], "strength": 0.22, "vignette": 0.20, "bloom_base": 0.06},
    "Vaults": {"tint": [0.25,0.30,0.38], "strength": 0.16, "vignette": 0.25, "bloom_base": 0.0},
    "Crypt":  {"tint": [0.18,0.22,0.30], "strength": 0.30, "vignette": 0.45, "bloom_base": 0.0},
    "Tomb":   {"tint": [0.45,0.38,0.20], "strength": 0.24, "vignette": 0.35, "bloom_base": 0.0},
    "Depths": {"tint": [0.14,0.14,0.20], "strength": 0.22, "vignette": 0.40, "bloom_base": 0.0},
    "Zot":    {"tint": [0.30,0.35,0.55], "strength": 0.24, "vignette": 0.20, "bloom_base": 0.08},
    "Hell":   {"tint": [0.55,0.15,0.12], "strength": 0.30, "vignette": 0.35, "bloom_base": 0.0},
    "Geh":    {"tint": [0.60,0.25,0.10], "strength": 0.32, "vignette": 0.30, "bloom_base": 0.05},
    "Coc":    {"tint": [0.35,0.55,0.70], "strength": 0.30, "vignette": 0.30, "bloom_base": 0.03},
    "Tar":    {"tint": [0.10,0.10,0.12], "strength": 0.34, "vignette": 0.50, "bloom_base": 0.0},
    "Dis":    {"tint": [0.32,0.34,0.38], "strength": 0.30, "vignette": 0.35, "bloom_base": 0.0},
    "Abyss":  {"tint": [0.35,0.15,0.40], "strength": 0.30, "vignette": 0.40, "bloom_base": 0.05, "unstable": 1},
    "Pan":    {"tint": [0.40,0.25,0.45], "strength": 0.30, "vignette": 0.35, "bloom_base": 0.05, "unstable": 1}
  },
  "modifiers": {
    "hp_low":  {"desaturate": 0.40, "vignette_add": 0.30, "vignette_tint": [0.6,0.0,0.0]},
    "hp_ok":   {},
    "player_death": {"desaturate": 1.0, "fade_black": 1.0}
  },
  "events": {
    "evt__melee_hit": {"flash": [1,1,1], "flash_intensity": 0.12, "shake": 0.10},
    "evt__kill":      {"flash": [1,1,1], "flash_intensity": 0.18, "shake": 0.15},
    "evt__ranged":    {"flash": [0.8,0.9,1.0], "flash_intensity": 0.08},
    "evt__cast_spell":{"bloom": [0.3,0.6,1.0], "bloom_intensity": 0.5},
    "evt__level_up":  {"flash": [1.0,0.9,0.4], "flash_intensity": 0.35, "bloom": [1.0,0.85,0.3], "bloom_intensity": 0.7}
  }
}
```

- [ ] **Step 2: Write the failing test**

Create `remaster/director/tests/test_visual_router.py`:

```python
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), ""))
from visual_router import VisualRouter

VMAP = {
  "master": {"enable": 1, "intensity": 1.0},
  "grades": {"Lair": {"tint": [0.15,0.45,0.18], "strength": 0.22, "vignette": 0.25, "bloom_base": 0.0}},
  "modifiers": {"hp_low": {"desaturate": 0.4, "vignette_add": 0.3, "vignette_tint": [0.6,0,0]},
                "hp_ok": {}, "player_death": {"desaturate": 1.0, "fade_black": 1.0}},
  "events": {"evt__level_up": {"flash": [1.0,0.9,0.4], "flash_intensity": 0.35,
                               "bloom": [1.0,0.85,0.3], "bloom_intensity": 0.7}},
}

def test_branch_sets_grade():
    r = VisualRouter(VMAP)
    assert r.route("state__branch_Lair") is True
    assert tuple(round(x,3) for x in r.state.tint) == (0.15,0.45,0.18)
    assert r.state.grade_strength == 0.22

def test_hp_low_adds_desaturate_over_current_branch():
    r = VisualRouter(VMAP)
    r.route("state__branch_Lair")
    r.route("state__hp_low")
    assert r.state.desaturate == 0.4
    assert tuple(round(x,3) for x in r.state.tint) == (0.15,0.45,0.18)  # branch mantenuto

def test_hp_ok_clears_desaturate():
    r = VisualRouter(VMAP)
    r.route("state__branch_Lair"); r.route("state__hp_low"); r.route("state__hp_ok")
    assert r.state.desaturate == 0.0

def test_event_bumps_pulse_seq_each_time():
    r = VisualRouter(VMAP)
    s0 = r.state.flash_seq
    r.route("evt__level_up")
    assert r.state.flash_seq == s0 + 1
    assert r.state.bloom_seq == 1
    r.route("evt__level_up")
    assert r.state.flash_seq == s0 + 2

def test_unknown_token_returns_false():
    assert VisualRouter(VMAP).route("evt__nope") is False
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest remaster/director/tests/test_visual_router.py -v`
Expected: FAIL `No module named 'visual_router'`.

- [ ] **Step 4: Write visual_router.py**

Create `remaster/director/visual_router.py`:

```python
"""Traduce i token di gioco (gli stessi che guidano l'audio) in un VisualState
target. Il branch imposta il grade di base; i modificatori (hp) vi si sommano;
gli eventi incrementano i seq dei pulse."""
from gfx_state import VisualState

_BRANCH_PREFIX = "state__branch_"

class VisualRouter:
    def __init__(self, visualmap):
        self.vmap = visualmap
        self.state = VisualState()
        m = visualmap.get("master", {})
        self.state.master_enable = int(m.get("enable", 1))
        self.state.master_intensity = float(m.get("intensity", 1.0))
        self._branch = None      # grade di base corrente (dict)
        self._hp_mod = None      # modificatore hp corrente (dict)
        self._apply()

    def branch(self, token):
        if not token.startswith(_BRANCH_PREFIX):
            return False
        key = token[len(_BRANCH_PREFIX):]
        g = self.vmap.get("grades", {}).get(key)
        if g is None:
            return False
        self._branch = g
        self._apply()
        return True

    def modifier(self, token):
        mods = self.vmap.get("modifiers", {})
        if token == "state__hp_low":
            self._hp_mod = mods.get("hp_low", {}); self._apply(); return True
        if token == "state__hp_ok":
            self._hp_mod = None; self._apply(); return True
        if token == "state__player_death":
            self._hp_mod = mods.get("player_death", {}); self._apply(); return True
        return False

    def event(self, token):
        e = self.vmap.get("events", {}).get(token)
        if e is None:
            return False
        if "flash" in e:
            self.state.flash_seq += 1
            self.state.flash = tuple(e["flash"])
            self.state.flash_intensity = float(e.get("flash_intensity", 0.0))
        if "shake" in e:
            self.state.shake_seq += 1
            self.state.shake_intensity = float(e["shake"])
        if "bloom" in e:
            self.state.bloom_seq += 1
            self.state.bloom = tuple(e["bloom"])
            self.state.bloom_intensity = float(e.get("bloom_intensity", 0.0))
        return True

    def route(self, token):
        return self.branch(token) or self.modifier(token) or self.event(token)

    def _apply(self):
        """Ricalcola i campi continui: grade di base + modificatore hp."""
        g = self._branch or {}
        self.state.tint = tuple(g.get("tint", (0.0, 0.0, 0.0)))
        self.state.grade_strength = float(g.get("strength", 0.0))
        self.state.vignette = float(g.get("vignette", 0.0))
        self.state.bloom_base = float(g.get("bloom_base", 0.0))
        self.state.desaturate = 0.0
        hp = self._hp_mod or {}
        if "desaturate" in hp:
            self.state.desaturate = float(hp["desaturate"])
        if "vignette_add" in hp:
            self.state.vignette = min(1.0, self.state.vignette + float(hp["vignette_add"]))
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest remaster/director/tests/test_visual_router.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add remaster/director/visualmap.json remaster/director/visual_router.py remaster/director/tests/test_visual_router.py
git commit -m "feat(gfx): visualmap.json + visual_router (token->state, tested)"
```

---

## Task 7: Wire visual state into the Director + proxy smoothing

Deliverable: `director.py` drives the shared memory on every token (audio unchanged), and the proxy crossfades continuous fields over ~1s. In-game: entering a branch smoothly grades the screen; `hp_low` desaturates + reddens; death fades.

**Files:**
- Modify: `remaster/director/director.py`, `remaster/gfx/postprocess.c`

**Interfaces:**
- Consumes: `VisualRouter`, `GfxShmem` (Python); `GfxState` (C).
- Produces: continuous-field smoothing inside `pp_draw` (proxy keeps a `current` state, lerps toward the struct target).

- [ ] **Step 1: Wire the Director**

Modify `remaster/director/director.py`:
- Import: `from visual_router import VisualRouter` and `from gfx_state import GfxShmem`.
- In `main()`, after loading `soundmap`: load `visualmap.json`, create `vrouter = VisualRouter(visualmap)`, create `shm = GfxShmem(); shm.open(); shm.write(vrouter.state)`.
- In `handle(raw)`, after the audio routing loop, add:

```python
        if vrouter.route(token):
            shm.write(vrouter.state)
```

- In `on_disconnect()`, optionally write a neutral state (game gone): `vrouter.state.master_enable = 1` is fine; leave as-is (proxy passthrough when game closes). No change required.

Exact insertion: `token` is already computed at the top of `handle`. Reuse it.

- [ ] **Step 2: Add smoothing to the proxy**

Modify `remaster/gfx/postprocess.c`: keep a static `current` copy of the continuous fields; each frame lerp toward the target from the struct before feeding uniforms. Add near the draw:

```c
static float cur_tint[3]={0,0,0}, cur_strength=0, cur_desat=0, cur_vignette=0;
static float lerp(float a,float b,float k){ return a + (b-a)*k; }

/* dentro pp_draw, dopo aver ricavato st e prima di settare gli uniform: */
    float k = 0.08f;   /* ~1s di crossfade a 60fps */
    cur_tint[0]=lerp(cur_tint[0], st->tint_r, k);
    cur_tint[1]=lerp(cur_tint[1], st->tint_g, k);
    cur_tint[2]=lerp(cur_tint[2], st->tint_b, k);
    cur_strength=lerp(cur_strength, st->grade_strength*mi, k);
    cur_desat=lerp(cur_desat, st->desaturate*mi, k);
    cur_vignette=lerp(cur_vignette, st->vignette*mi, k);
```

Then set uniforms from `cur_*` instead of the raw struct values.

- [ ] **Step 3: Build, deploy, integration test**

Run:
```
powershell -File "remaster/gfx/build.ps1"
powershell -File "remaster/gfx/deploy.ps1"
```
Start the real Director (`Play DCSS Remastered.bat` launches it per existing setup, or run `python remaster/director/director.py`), then play: descend into different branches → grade crossfades; drop below 30% HP → desaturate + red vignette; die → fade. Audio must still work unchanged.

- [ ] **Step 4: Capture evidence**

Record a short GIF descending Dungeon→Lair→low-HP. Save as `remaster/gfx/harness/grading_demo.gif`.

- [ ] **Step 5: Run all Python tests**

Run: `python -m pytest remaster/director/tests/ -v`
Expected: all pass (router + gfx_state + visual_router).

- [ ] **Step 6: Commit**

```bash
git add remaster/director/director.py remaster/gfx/postprocess.c
git commit -m "feat(gfx): Director drives visual state; proxy crossfades grades"
```

---

## Task 8: Event juice — pulse envelopes (flash/shake/bloom)

Deliverable: the proxy detects pulse-seq changes and animates decaying envelopes: additive flash, screen shake (UV offset + slight zoom to hide edges), and bloom pulse. Validated in the harness (fake seq bumps), then in-game.

**Files:**
- Modify: `remaster/gfx/postprocess.c`, shader source in it

**Interfaces:**
- Consumes: `GfxState` pulse fields (`flash_seq/…`, `shake_seq/…`, `bloom_seq/…`), `QueryPerformanceCounter` for dt.
- Produces: envelope state internal to `postprocess.c`; extended fragment shader with `flash`, `shake` (via UV), and `bloom` uniforms.

- [ ] **Step 1: Extend the fragment shader**

In `FRAG_SRC` add uniforms and logic:

```glsl
uniform vec3 flash; uniform float flash_i;   // additivo
uniform float shake;                          // zoom per nascondere i bordi
uniform vec3 bloom_c; uniform float bloom_i;  // bloom pulse (fake, cheap)
```
UV shake: sample with `uv2 = (uv - 0.5) * (1.0 - 0.03*shake) + 0.5 + shakeOffset;` where `shakeOffset` is a small per-frame jitter passed as a `vec2` uniform `shake_off`. Add flash: `c += flash * flash_i;`. Cheap bloom pulse: `c += bloom_c * bloom_i * smoothstep(0.4,1.0,l);` (brighten already-bright pixels toward the pulse color).

Add uniform locations + loaders for `flash,flash_i,shake,shake_off,bloom_c,bloom_i` in `pp_init` (mirror existing pattern with `pglUniform2f/3f/1f`).

- [ ] **Step 2: Add envelope + dt tracking**

In `postprocess.c`:

```c
#include <math.h>
static LARGE_INTEGER g_freq, g_last; static int g_clock=0;
static unsigned last_flash_seq=0, last_shake_seq=0, last_bloom_seq=0;
static float env_flash=0, env_shake=0, env_bloom=0;   /* 0..1 decaying */
static float flash_col[3]={0,0,0}, bloom_col[3]={0,0,0};

static float tick_dt(void){
    if(!g_clock){ QueryPerformanceFrequency(&g_freq); QueryPerformanceCounter(&g_last); g_clock=1; return 0.016f; }
    LARGE_INTEGER now; QueryPerformanceCounter(&now);
    float dt=(float)(now.QuadPart-g_last.QuadPart)/(float)g_freq.QuadPart; g_last=now;
    if(dt>0.1f) dt=0.1f; return dt;
}
static void decay(float *e, float dt, float rate){ *e -= dt*rate; if(*e<0)*e=0; }
```

In `pp_draw`, after reading `st`:

```c
    float dt = tick_dt();
    if (st->flash_seq != last_flash_seq){ last_flash_seq=st->flash_seq; env_flash=st->flash_intensity;
        flash_col[0]=st->flash_r; flash_col[1]=st->flash_g; flash_col[2]=st->flash_b; }
    if (st->shake_seq != last_shake_seq){ last_shake_seq=st->shake_seq; env_shake=st->shake_intensity; }
    if (st->bloom_seq != last_bloom_seq){ last_bloom_seq=st->bloom_seq; env_bloom=st->bloom_intensity;
        bloom_col[0]=st->bloom_r; bloom_col[1]=st->bloom_g; bloom_col[2]=st->bloom_b; }
    decay(&env_flash, dt, 3.0f);   /* ~0.3s */
    decay(&env_shake, dt, 4.0f);   /* ~0.25s */
    decay(&env_bloom, dt, 2.0f);   /* ~0.5s */
```

Shake offset: `float sx = env_shake * 0.02f * sinf((float)g_last.QuadPart*0.001f); float sy = ...cosf...;` pass to `shake_off`. Feed `env_flash`, `flash_col`, `env_shake`, `env_bloom`, `bloom_col` as uniforms.

- [ ] **Step 3: Validate in harness**

Extend `gl_harness.c` to bump `fake.flash_seq`/`shake_seq`/`bloom_seq` on keypress (e.g. every 60 frames). Rebuild, run: confirm a decaying white flash, a brief shake with no black edges (zoom hides them), and a bloom pulse. Fix shader/decay constants as needed.

- [ ] **Step 4: In-game verify**

Rebuild/redeploy proxy. Play: hit a monster → micro flash+shake; kill → stronger; cast a spell → arcane bloom; level up → golden flash+bloom. Confirm no black edges during shake.

- [ ] **Step 5: Commit**

```bash
git add remaster/gfx/postprocess.c remaster/gfx/harness/gl_harness.c
git commit -m "feat(gfx): event juice — flash/shake/bloom decaying envelopes"
```

---

## Task 9: Event mapping wiring + unstable branches + polish pass

Deliverable: confirm every `evt__*` in `visualmap.json` reaches a pulse in-game, add the slow pulsing for `unstable` branches (Abyss/Pan), and do a taste-tuning pass on default intensities.

**Files:**
- Modify: `remaster/director/visual_router.py`, `remaster/gfx/postprocess.c`, `remaster/director/visualmap.json`

**Interfaces:**
- Consumes: `grades[*].unstable` flag.
- Produces: `VisualState` gets no new fields; instability is rendered proxy-side as a slow sinusoidal modulation of `grade_strength` when a per-branch `unstable` flag is set. Pass the flag via an unused high bit of `master_enable`? No — add a dedicated `uint32 flags` field.

- [ ] **Step 1: Add a `flags` field to the contract**

This changes the struct (append at end to preserve earlier offsets — but the compile-time size check + PACK_FORMAT must both update). Update in lockstep:
- `shared_state.h`: add `uint32_t flags;` as the LAST field; change size check `88` → `92`.
- `gfx_state.py`: append `I` to `PACK_FORMAT`; add `self.flags = 0` to `VisualState`; add `vs.flags` as the final packed value; update `STRUCT_SIZE` expectation in `test_gfx_state.py` (`88`→`92`, and the format-length assertion).
- Define bit `FLAG_UNSTABLE = 1`.

Run `python -m pytest remaster/director/tests/test_gfx_state.py -v` — update the two size asserts to 92, confirm pass.

- [ ] **Step 2: Set the flag in visual_router**

In `_apply()`, set `self.state.flags = 1 if (self._branch or {}).get("unstable") else 0`. Add a test in `test_visual_router.py`:

```python
def test_unstable_branch_sets_flag():
    vm = {"master":{"enable":1,"intensity":1.0},
          "grades":{"Abyss":{"tint":[0.35,0.15,0.40],"strength":0.30,"vignette":0.40,"bloom_base":0.05,"unstable":1}},
          "modifiers":{}, "events":{}}
    r = VisualRouter(vm); r.route("state__branch_Abyss")
    assert r.state.flags == 1
```
Run the test → pass.

- [ ] **Step 3: Render instability in the proxy**

In `pp_draw`, if `(st->flags & 1)`, modulate `cur_strength` by `1.0 + 0.25*sinf(time)` where `time` accumulates from `tick_dt()`. Keep it slow (period ~4s).

- [ ] **Step 4: Tuning pass**

Play through several branches and adjust `visualmap.json` values so grading reads as *atmospheric*, not a cheap color filter (keep `strength` ≤ ~0.32, avoid muddy tints). Since it's JSON, no rebuild needed — restart the Director to reload. Commit the tuned values.

- [ ] **Step 5: Commit**

```bash
git add remaster/gfx/shared_state.h remaster/director/gfx_state.py remaster/director/tests/ remaster/director/visual_router.py remaster/gfx/postprocess.c remaster/director/visualmap.json
git commit -m "feat(gfx): unstable-branch pulsing + event wiring + tuning pass"
```

---

## Task 10: Robust degradation, master controls, docs

Deliverable: production hardening — self-disable on GL error, honor `master.enable`/`intensity`, document the graphics layer in the README, and update the memory/CREDITS as needed.

**Files:**
- Modify: `remaster/gfx/postprocess.c`, `remaster/gfx/gl_proxy.c`, `remaster/README.md`

**Interfaces:** none new.

- [ ] **Step 1: Self-disable on repeated GL error**

In `pp_draw`, after the draw, call `glGetError()` in a loop; if a non-zero error recurs on N consecutive frames, set a static `g_disabled=1` and early-return on subsequent frames (passthrough). Log once to `OutputDebugStringA`.

- [ ] **Step 2: Honor master toggle end-to-end**

Confirm `master.enable=0` in `visualmap.json` → Director writes `master_enable=0` → `pp_draw` early-returns. Test by flipping the JSON and restarting the Director (no rebuild).

- [ ] **Step 3: Verify the full safety matrix**

Manually verify each row renders the game correctly (no crash, sensible behavior):
- Director running, effects on → full remaster.
- Director not running → passthrough (shmem absent).
- `DCSS_GFX_OFF=1` → passthrough.
- `master.enable=0` → passthrough.
- Forced shader failure (temporarily break `FRAG_SRC`) → passthrough, game fine.

- [ ] **Step 4: Document in README**

Add a "Graphics layer" section to `remaster/README.md`: architecture (opengl32 proxy + IAT-hook SwapBuffers + shared memory), how to build/deploy (`remaster/gfx/build.ps1`, `deploy.ps1`), how to tune (`visualmap.json`), the kill-switch, and the RE note that DCSS presents frames via `gdi32!SwapBuffers`.

- [ ] **Step 5: Final full test run**

Run: `python -m pytest remaster/director/tests/ -v` → all pass.
Do one full play session touching several branches + combat + level-up + low HP + death. Confirm audio + video both correct, no crashes.

- [ ] **Step 6: Commit**

```bash
git add remaster/gfx/postprocess.c remaster/gfx/gl_proxy.c remaster/README.md
git commit -m "feat(gfx): robust degradation, master controls, docs"
```

---

## Self-Review notes (author)

- **Spec coverage:** proxy+forwarders (T1), SwapBuffers hook (T2), shared-mem contract (T3), struct-driven render (T4), shader/desaturate (T5), visualmap+router (T6), Director wiring+smoothing (T7), juice envelopes (T8), unstable branches+events+tuning (T9), degradation+master+docs (T10). All spec sections mapped.
- **Struct consistency:** `PACK_FORMAT` (Python) and `GfxState` (C) both defined in T3 with a compile-time size check; T9 changes both in lockstep (88→92) with the test updated. `flash_seq/shake_seq/bloom_seq` names identical across `gfx_state.py`, `visual_router.py`, `shared_state.h`, `postprocess.c`.
- **Never-crash invariant:** every `pp_*` guards on init/enable and early-returns to passthrough; `shmem` absence → NULL → no draw.
- **Known risk to watch during T2:** if `iat_hook` finds no matching `SwapBuffers` thunk (e.g. bound imports), fall back to the reserved winmm-foothold approach noted in the spec, or hook via `GetProcAddress`-address match across all import descriptors (already implemented by scanning every descriptor's thunks).
