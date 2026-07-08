# DCSS Remastered — Pacchetto "estrai e gioca" (design)

**Data:** 2026-07-08
**Obiettivo:** un unico download che funzioni subito per chiunque, anche non tecnici —
"scaricalo e parte". Nessun Python, nessuna compilazione, nessun download aggiuntivo.

## Problema

L'installazione attuale richiede 6 passaggi manuali, ognuno un muro per un non-tecnico:

1. Procurarsi DCSS Tiles 0.34 x86
2. Installare Python 3 + `pip install pygame-ce pywin32`
3. Generare SFX (`make_sfx.py`) e marker (`make_markers.py`)
4. Scaricare ~195 MB di musica (`fetch_music.py`)
5. Compilare i proxy DLL con MSVC (`proxy/build.ps1`, `gfx/build.ps1`)
6. Cablare la config (`config/gen_init.py`)

## Decisioni prese (con l'utente)

- **Formato:** ZIP portable (niente installer, niente admin, niente registro).
- **Contenuto:** tutto incluso — gioco (crawl.exe 0.34) + musica + SFX + config.
- **Antivirus:** gestione a costo zero (guida chiara), niente firma digitale del codice.
- **Launcher:** il `.bat` attuale per ora (icona `.lnk` eventualmente dopo).

## Le 3 leve

Spostare il lavoro dall'utente (ogni volta) allo sviluppatore (una volta, in packaging):

1. **Niente Python** → `director.exe` congelato con PyInstaller (impacchetta
   Python + pygame-ce + pywin32). Il launcher usa `director.exe` se presente,
   altrimenti `python director.py` → **workflow di sviluppo intatto**.
2. **Niente compilazione** → proxy DLL (`winmm.dll`, `opengl32.dll`) pre-compilati e inclusi.
3. **Niente download/setup** → asset (musica, SFX, marker) e config già pronti nel pacchetto.

## Layout del bundle

```
DCSS-Remastered/
├─ crawl.exe                       (gioco 0.34 — GPL)
├─ winmm.dll  opengl32.dll         (proxy audio+grafico, pre-compilati)
├─ init.txt                        (config già cablata: include remaster/config/remaster.rc)
├─ ▶ Gioca a DCSS Remastered.bat   (launcher; usa director.exe)
├─ LEGGIMI.txt                     (avvio + sblocco antivirus, italiano)
├─ LICENSES/  CREDITS.txt          (GPL + offerta sorgenti; attribuzione musica CC-BY)
├─ dat/ …                          (dati del gioco, invariati)
└─ remaster/
   ├─ director/director.exe        (Director congelato)
   ├─ director/soundmap.json, visualmap.json
   ├─ config/remaster.rc
   └─ audio/  (music ~195MB + sfx + markers, già generati)
```

Note: nel bundle **non** vanno sorgenti `.py`/`.c`, toolchain, `__pycache__`, test,
`director.log`, `.git`. Solo runtime.

## Script di release (lato sviluppatore, idempotente)

`remaster/tools/build_release.ps1`:

1. Builda i DLL (`proxy/build.ps1`, `gfx/build.ps1`).
2. Genera SFX + marker (`make_sfx.py`, `make_markers.py`), scarica musica (`fetch_music.py`).
3. **Congela** `director/director.py` → `director.exe` (PyInstaller).
4. Assembla `dist/DCSS-Remastered/`: copia gioco + DLL + `remaster/` (solo runtime),
   escludendo cruft dev.
5. Genera `init.txt` (via `gen_init.py`), `LEGGIMI.txt`, `LICENSES/`, `CREDITS.txt`.
6. Zippa → `dist/DCSS-Remastered-vX.Y.zip`.

Pubblicazione: `gh release create vX.Y dist/DCSS-Remastered-vX.Y.zip`.
Lo ZIP è un **asset di Release**, non committato nel repo (i binari restano gitignored).

## Antivirus / SmartScreen (costo zero)

I proxy DLL affiancati a `crawl.exe` sono lo schema del DLL-hijacking → falso positivo
probabile. Mitigazioni senza firma:

- Tutto locale, **niente rete a runtime** (musica inclusa) → meno trigger.
- `LEGGIMI.txt` con: sblocca-ZIP (Proprietà → Sblocca prima di estrarre), "Windows ha
  protetto il PC → Ulteriori info → Esegui comunque", nota su esclusione Defender.
- Sezione dedicata nella pagina della Release e nel README.

## Legale

- `crawl.exe` è **GPL**: `LICENSES/` con testo GPL + **offerta sorgenti** (link a
  `crawl/crawl` al tag 0.34). Redistribuzione consentita.
- Musica **Kevin MacLeod / incompetech.com CC-BY**: attribuzione in `CREDITS.txt` (già presente).
- SFX sintetizzati CC0.

## Rischio #1 (make-or-break) — spike di freezing

Congelare **pygame-ce + pywin32** con PyInstaller di solito funziona (hook inclusi), ma
va provato: il named-pipe server (pywin32) e l'audio (pygame) devono girare dentro l'exe.

**Spike:** `pyinstaller --onefile director.py`, poi lanciare `director.exe` in un ambiente
senza Python nel PATH e verificare: (a) parte, (b) apre `\\.\pipe\dcss_audio`, (c) inizializza
l'audio, (d) instrada un token di test. Se fallisce → piano B: includere un **Python
embeddable** portatile nel bundle invece di congelare.

## Criteri di successo

- Un tester che estrae lo ZIP su una macchina **senza Python** e fa doppio clic sul
  launcher **sente musica e SFX in gioco** senza altri passaggi.
- Nessun passaggio manuale oltre: sblocca-ZIP → estrai → doppio clic (+ eventuale
  "Esegui comunque" al primo avvio).

## Fuori scope (per ora)

- Firma digitale del codice.
- Installer .exe (Inno Setup) e collegamento `.lnk` con icona.
- Auto-update.
- Distribuzione non-Windows.
