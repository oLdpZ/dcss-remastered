# Save-Lock Hook — sblocca la lettura del save per i checkpoint per-piano — Design

**Data:** 2026-07-12
**Stato:** approvato, spike-first

## Contesto / root cause

Il [[dcss-remastered-saveguard|Save-Guard]] (polling di `saves/*.cs` → snapshot per
piano → restore alla morte) funziona a gioco spento (snapshot baseline all'avvio del
Director) ma **non** durante il gioco. Diagnosticato con instrumentation (2026-07-12):

```
16:22:40 cambio visto Giote ... new=(...,82822)     # discesa: il .cs cresce
16:22:42 read FAIL Giote: PermissionError(13, 'Permission denied')
16:22:42 snapshot Giote -> False
```

**DCSS tiene il file `saves/<nome>.cs` aperto con una share mode che nega la lettura
ad altri processi** per tutta la durata della partita. Il `SaveGuard` gira in un
processo separato (il Director) e la sua `open(src,"rb")` fallisce con `EACCES`
(sharing violation) finché giochi. Quindi nessun checkpoint per-piano viene creato
durante la sessione, e alla morte il restore ripiega sul baseline = inizio sessione.

Import di `crawl.exe` (pefile): importa **`CreateFileW`/`CreateFileA` diretti da
kernel32** *e* `_wfopen/_wopen/fopen` da **msvcrt.dll** → il save può essere aperto
per via diretta o via C runtime.

## Obiettivo

Permettere al Director di **leggere il `.cs` mentre il gioco lo tiene aperto**, così
il `SaveGuard` esistente riprende a fare i checkpoint per-piano — **senza ricompilare**
il gioco e **senza toccare** la logica di snapshot/restore (che già funziona).

## Idea centrale — shim di share mode (minimale)

Il proxy nativo fa **una sola cosa**: intercetta le `CreateFileW`/`CreateFileA` del
gioco e, **solo** per i path che finiscono in `.cs`, aggiunge `FILE_SHARE_READ` alla
`dwShareMode`, poi chiama la `CreateFile` vera con gli altri argomenti invariati. Il
gioco continua a leggere/scrivere il proprio save esattamente come prima; in più altri
processi possono **leggerlo**. Non si concede mai permesso di scrittura → **integrità
del save intatta**. Con la lettura sbloccata, il `SaveGuard` fa il resto da solo.

## Architettura

### Host: proxy `opengl32.dll` (cartella `remaster/gfx/`)

Riusa l'infrastruttura IAT-hook già presente (`iat_hook.c`, usata per
`gdi32!SwapBuffers`). L'hook si installa nello stesso `install_hook_once()` invocato
da `glViewport` al primo frame — **prima** che tu carichi un personaggio (il save si
apre dopo il menu). Nessun nuovo DLL: DCSS carica solo i proxy esistenti.

### Nuovo modulo: `remaster/gfx/file_hook.c` (+ `.h`)

- **`iat_hook_all(func, replacement) -> void*`**: variante multi-modulo di `iat_hook`.
  Enumera i moduli caricati (`EnumProcessModules`, psapi) e patcha la voce
  `kernel32!CreateFileW`/`A` nell'IAT di **ciascuno** (crawl.exe + msvcrt + altri),
  così copre sia le open dirette sia quelle del CRT. Ritorna il puntatore originale
  (identico in tutti i moduli). L'`iat_hook` esistente (solo crawl.exe) resta invariato.
- **`hook_CreateFileW(lpFileName, dwDesiredAccess, dwShareMode, ...)`**: se
  `save_off()` è falso e `lpFileName` termina in `.cs` (case-insensitive), imposta
  `dwShareMode |= FILE_SHARE_READ` (e lascia il resto). Poi chiama il puntatore reale
  salvato. Analogo `hook_CreateFileA`.
- **`save_off()`**: kill-switch via env `DCSS_SAVEHOOK_OFF` (cache come `gfx_off`).

### Perche' "tutti i moduli" e non solo crawl.exe

`_wfopen`/`_wopen` (msvcrt) chiamano `CreateFileW` **dall'IAT di msvcrt.dll**, non da
quello di crawl.exe. Patchare solo crawl.exe mancherebbe le open via CRT. Patchare
tutti i moduli copre entrambe le vie senza dover indovinare quale usa il save.

## Sicurezza / robustezza (principio "mai crashare", come il layer gfx)

- **Scope stretto:** modifico la share mode **solo** per path `*.cs`. Ogni altra
  `CreateFile` passa con argomenti byte-identici. (Match su `.cs`: sufficiente e sicuro;
  i soli `.cs` che il gioco apre sono i suoi save.)
- **Solo allargare:** aggiungo `FILE_SHARE_READ`, non tolgo mai flag di condivisione.
- **Fallback totale:** se l'hook non si installa, o il puntatore reale e' NULL, o il
  kill-switch e' attivo → si usa la `CreateFile` vera invariata. Un fallimento del hook
  non deve mai impedire al gioco di aprire i suoi file.
- **Nessuna ricorsione:** l'hook chiama il puntatore reale salvato da
  `GetProcAddress(kernel32,"CreateFileW")`, non l'IAT patchato.

## Lettura sporca (torn read)

Nessuna modifica: il `SaveGuard` snapshotta solo dopo che `(mtime,size)` sono **stabili
tra due poll** (debounce gia' presente). DCSS scrive il `.cs` a raffica sulle
transizioni di piano, poi resta fermo → si legge a scrittura finita. Rischio residuo
basso; un eventuale checkpoint "storto" verrebbe comunque superato dal successivo e la
rotazione ne tiene 5.

## Validazione — spike-first

Non e' codice unit-testabile (serve il gioco vero). La validazione e' in-game, sfruttando
l'instrumentation diagnostica gia' aggiunta al `SaveGuard`:

1. **Spike:** build minimale dell'hook, deploy dell'`opengl32.dll`, avvio dal launcher,
   carico un personaggio, **scendo di un piano**. Atteso: **spariscono** i `read FAIL`
   nel `director.log` e **compare** un `[saveguard] checkpoint <nome>` + un `NNNN.cs`
   con la dimensione del piano nuovo. Se cosi', l'assunzione cardine (aggiungere
   `FILE_SHARE_READ` sblocca la lettura) e' confermata.
2. **Morte reale:** scendo qualche piano, muoio → il restore riporta all'**ingresso
   dell'ultimo piano**, non piu' all'inizio partita.
3. Hardening (CreateFileA, kill-switch, scoping) + code review + build/deploy/packaging.

## Fuori scope (YAGNI)

- Hook delle scritture del gioco / mirroring dei chunk (troppo invasivo).
- Inline/trampoline hook di kernel32 (l'IAT multi-modulo basta e riusa il pattern).
- Validazione del `.cs` copiato (integrita' del package): il debounce mitiga; non
  aggiungiamo parsing del formato save.
- Rendere il Save-Guard funzionante senza Director (fuori tema).

## Note

- Diagnostics temporanei nel `SaveGuard` (`[saveguard][diag] ...`): a fine lavoro
  vanno **gated dietro un flag** (`saveguard.json: "debug": false`) o rimossi, per non
  floodare `director.log`.
- C'e' un bug latente correlato in `poll_once`: su `_snapshot` fallito avanza comunque
  `_known[name]`, "consumando" il cambiamento senza snapshot. Con l'hook la lettura non
  fallira' piu', ma va comunque reso robusto (non avanzare `_known` se lo snapshot e'
  fallito, cosi' riprova al poll successivo). Da includere nell'hardening.
- Build/deploy: stessa toolchain MSVC x86 di [[dcss-remastered-graphics]];
  l'`opengl32.dll` ricompilata va deployata nella cartella del gioco e inclusa nel
  bundle ZIP ([[dcss-remastered-packaging]]).

Vedi [[dcss-remastered-saveguard]] [[dcss-remastered-graphics]].
