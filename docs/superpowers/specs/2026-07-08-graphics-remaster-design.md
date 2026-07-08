# DCSS Remastered — Graphics Layer (event-driven post-processing)

**Data:** 2026-07-08
**Stato:** approvato, pronto per il piano d'implementazione
**Contesto:** secondo pilastro sensoriale del progetto DCSS Remastered. L'audio dinamico
(proxy `winmm.dll` → named pipe → Audio Director Python) è già completo. Questo spec
aggiunge il **video**: post-processing grafico pilotato dagli stessi eventi di gioco,
**senza ricompilare** `crawl.exe` — coerente con la filosofia del progetto (tutto
costruito dal binario nudo, nessun engine esterno).

---

## Obiettivo

Un remaster **audiovisivo pieno a strati**: un layer di *grading atmosferico* sempre
attivo (tinte/desatura/vignette per branch e stato HP) + un layer di *juice reattivo*
sugli eventi puntuali (flash, shake, bloom), entrambi sincronizzati con l'audio perché
governati dallo **stesso Director**.

## Vincoli non negoziabili

- **Nessuna ricompilazione** di `crawl.exe` (x86, build Tiles 0.34).
- **Non far mai crashare il gioco.** Se qualcosa fallisce → passthrough puro, DCSS intatto.
- **Un solo cervello:** il Director (Python) resta l'autorità su audio e video.
- **Il gusto sta in JSON** editabile a caldo; il proxy è un renderer "stupido".

## Fatti tecnici verificati (dal binario)

- `crawl.exe` importa `OPENGL32.DLL` (render legacy, profilo compatibility) e presenta
  i frame con **`SwapBuffers` di `gdi32.dll`** (NON `wglSwapBuffers`).
- Da opengl32 importa tra l'altro `glViewport` → intercettandola conosciamo sempre la
  risoluzione del framebuffer.
- Le tile sono atlas PNG esterni e i font TTF esterni (non oggetto di questo spec, ma
  confermano l'approccio asset-esterni).
- Il pattern proxy-DLL è già provato (winmm): forwarder via
  `#pragma comment(linker,"/EXPORT:nome=orig.nome")`, x86, real DLL da `SysWOW64`.

---

## Architettura

```
crawl.exe (x86, invariato)
 ├── winmm.dll   → pipe → Director            (audio, già fatto)
 └── opengl32.dll (NUOVO proxy)
        ├─ forwarda tutti i gl*/wgl* al vero opengl32 (opengl32_orig.dll)
        ├─ intercetta glViewport  → traccia la risoluzione corrente
        └─ IAT-hook di gdi32!SwapBuffers → inietta il passo di post-processing
              ↑ legge lo stato visivo da…
        [ MEMORIA CONDIVISA  "dcss_gfx_state" ]
              ↑ scritta da…
     Director (Python) — token stream → visualmap.json → struct
```

**Perché proxare opengl32 e non gdi32:** gdi32 ha 600+ export critici (proxy rischioso);
opengl32 ha export omogenei (gl*/wgl*, forwarder auto-generabili) **e** intercettare
`glViewport` regala la risoluzione. `SwapBuffers` (che sta in gdi32) si aggancia con un
**IAT-hook** chirurgico sulla import table del modulo principale — una sola voce, robusto,
senza trampolini inline.

**Fallback (considerato, tenuto in riserva):** installare l'hook dal proxy `winmm`
già esistente invece di introdurre il proxy opengl32. Evita di forwardare gli export
di opengl32, ma mette audio e video nella stessa DLL (meno pulito). Da usare solo se il
forwarding di opengl32 si rivela problematico.

---

## Componenti

### C1 — Proxy `opengl32.dll` (C, x86, MSVC) — `remaster/gfx/`
Responsabilità:
1. **Forwarding**: tutti gli export gl*/wgl* → `opengl32_orig.dll`. Forwarder
   auto-generati da uno script che legge la export table della opengl32 reale.
2. **Tracking risoluzione**: wrappa `glViewport` per memorizzare width/height correnti.
3. **Frame hook**: in `DllMain` (o al primo frame) installa l'IAT-hook su
   `gdi32!SwapBuffers` nel modulo principale. La funzione hook:
   - legge lo stato dalla memoria condivisa;
   - esegue il passo di post-processing (vedi C4);
   - chiama il `SwapBuffers` originale.
4. **Degradazione**: se init fallisce o si accumulano GL error → auto-disabilita,
   passthrough. Kill-switch via env var (es. `DCSS_GFX_OFF=1`).

Dipendenze: `opengl32_orig.dll` (copiato da `SysWOW64`), la memoria condivisa.

### C2 — Estensione Director (Python) — `remaster/director/`
Responsabilità:
- Carica `visualmap.json`.
- Sul token stream esistente (lo stesso che guida l'audio) calcola lo **stato visivo**
  (grade target + eventuali pulse) e lo **scrive nella memoria condivisa**.
- Nessuna nuova sorgente di eventi: riusa i token già in pipe.

Dipendenze: `visualmap.json`, modulo di scrittura shared-memory.

### C3 — `visualmap.json` (dati) — `remaster/director/`
Gemello di `soundmap.json`. Contiene:
- `grades`: per ciascuno dei 22 branch un grade base (`tint[3]`, `strength`,
  `desaturate`, `vignette`, `bloom_base`, flag `unstable` per Abyss/Pan).
- `modifiers`: `hp_low`, `hp_ok`, `player_death`.
- `events`: mapping evento→pulse (`flash`, `shake`, `bloom_pulse` con colore/intensità).
- `master`: `enable`, `intensity` globale.

### C4 — Passo di post-processing (dentro C1)
Allo `SwapBuffers` intercettato, con il contesto GL dell'app corrente:
1. Salva lo stato GL toccato (`glPushAttrib`/matrici; DCSS è compatibility profile).
2. Copia il back buffer in una texture (`glCopyTexSubImage2D`, dimensione dal glViewport
   tracciato).
3. Disegna un fullscreen quad con **un fragment shader** (GLSL 2.0 via
   `wglGetProcAddress`): tint · desatura · vignette · flash · bloom; **shake = offset UV
   + leggero zoom** per nascondere i bordi neri.
4. Ripristina lo stato GL → chiama il vero `SwapBuffers`.

Il proxy fa lo **smoothing** frame-per-frame (clock via QueryPerformanceCounter): lerp
current→target per i grade (crossfade ~1s) e inviluppi di decadimento per i pulse.

---

## Contratto IPC — memoria condivisa `dcss_gfx_state`

File mapping con nome (es. `Local\dcss_gfx_state`), struct a **layout fisso little-endian**.
Il Director scrive **target**, non ogni frame; il proxy interpola.

Campi:
- **Meta**: `version` (uint32), `master_enable` (uint32), `master_intensity` (float).
- **Base continua** (proxy lerpa current→target):
  `tint_r/g/b` (float), `grade_strength`, `desaturate`, `vignette`, `bloom_base`.
- **Pulse one-shot** (contatore `seq` per effetto; il proxy nota il cambio di seq e
  arma un inviluppo con clock proprio):
  - `flash`: `seq` (uint32), `r/g/b`, `intensity`.
  - `shake`: `seq` (uint32), `intensity`.
  - `bloom_pulse`: `seq` (uint32), `r/g/b`, `intensity`.

Regole:
- Il Director **incrementa** il `seq` di un pulse per innescarlo; non deve azzerarlo.
- Il proxy conserva l'ultimo `seq` visto per effetto; su cambio (ri)arma l'inviluppo.
- **Assenza della memoria condivisa** (Director spento) → passthrough puro.

---

## Mappa eventi → effetti (vocabolario già in pipe)

Stati continui → grading di base:
`state__branch_{D,Temple,Lair,Swamp,Shoals,Snake,Spider,Slime,Orc,Elf,Vaults,Crypt,`
`Tomb,Depths,Zot,Hell,Coc,Geh,Tar,Dis,Abyss,Pan}`, `state__hp_low`, `state__hp_ok`,
`state__player_death`.

Eventi puntuali → juice:
`evt__melee_hit`, `evt__ranged`, `evt__cast_spell`, `evt__kill`, `evt__level_up`,
`evt__quaff`, `evt__read`, `evt__pickup`, `evt__door(_close)`, `evt__stairs_up/down`,
`evt__spot`.

Grading di base (indicativo, tunabile in JSON):
- Lair verde-umido · Swamp verde-bruno torbido · Shoals cyan chiaro · Snake giallo-verde
- Spider viola cupo (vignette alta) · Slime verde malato (bloom) · Orc bruno caldo
- Elf blu-viola magico · Vaults acciaio neutro · Crypt blu freddo desaturato (vignette alta)
- Tomb oro sabbia cupo · Depths neutro scuro · Zot magico vivido (bloom)
- Hell rosso · Geh fuoco rosso-arancio · Coc ghiaccio · Tar nero desaturato · Dis grigio ferro
- Abyss/Pan `unstable` → pulsano lentamente · D neutro appena freddo

Modificatori stato (si sommano al base):
- `hp_low` → +desatura ~0.4, vignette rossa pulsante · `hp_ok` → clear
- `player_death` → fade a nero desaturato (~2s)

Juice per-evento (default conservativi — no over-juice):
- `melee_hit`/`kill` → micro-flash bianco + micro-shake
- `ranged` → sottile · `cast_spell` → bloom pulse arcano
- `level_up` → flash dorato + bloom radiale
- `quaff`/`read`/`pickup`/`door`/`stairs`/`spot` → sottili o nulli

---

## Sicurezza & degradazione

- Se init shader fallisce o si accumulano `glGetError` → auto-disabilita, passthrough.
- Kill-switch env var (`DCSS_GFX_OFF=1`) per far girare il proxy in passthrough (debug).
- State save/restore rigoroso per non corrompere il rendering di DCSS (matrici, texture
  binding, blend, depth).
- Assenza Director / shared-mem → passthrough. Il gioco funziona sempre, con o senza layer.

## Testing

- **Director/visualmap** (Python): unit test token→struct, sullo stile dei test router
  esistenti. Testabile senza gioco.
- **Passo GL**: mini-harness standalone (finestrella GL) per validare shader/pass in
  isolamento **prima** di iniettarlo in crawl.
- **Integrazione golden path**: avvia gioco → entra in Lair (screenshot tinta) → hp_low
  (screenshot) → level_up (screenshot bloom). Verifica visiva + GIF.

## Ordine di costruzione (v1 = tutto, ma per de-rischiare)

1. **Skeleton**: proxy opengl32 carica + forwarda + IAT-hook su SwapBuffers → disegna una
   tinta rossa fissa 20%. Prova la pipeline end-to-end **senza rompere DCSS**.
2. **Shared-mem + grade statico**: contratto IPC; Director scrive un grade fisso, il proxy
   lo applica.
3. **Grading dinamico**: `visualmap.json`, mapping 22 branch + hp/death, crossfade smooth.
4. **Juice**: inviluppi flash/shake/bloom + mapping eventi.
5. **Rifinitura**: tuning, config `master`, degradazione robusta, docs.

## Fuori scope (per ora)

- HD/upscale delle tile (i coord pixel sono compilati nell'exe → richiederebbe altro).
- Swap font.
- Overlay esterni (Discord Rich Presence / OBS).
- Bloom "vero" multi-pass di alta qualità (v1 usa un bloom economico single-pass;
  l'upgrade a bright-pass + blur è un miglioramento successivo).
