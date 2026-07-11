# Save-Guard — checkpoint automatici e ripristino alla morte — Design

**Data:** 2026-07-12
**Stato:** approvato, pronto per il piano

## Contesto

DCSS è un roguelike con **permadeath**: il file `saves/<nome>.cs` **è** lo stato
del mondo (i livelli vengono scritti/letti da lì quando entri/esci da un piano), il
gioco lo aggiorna automaticamente e alla morte lo **cancella**, scrivendo solo un
morgue + una riga in `scores`. L'autosalvataggio è quindi a **senso unico**: avanza
sempre e non è recuperabile.

L'utente vuole trasformare l'esperienza in **save/load classico**:
- Alla **morte** il personaggio non va perso: viene **ripristinato** e si riparte da
  un punto recente.
- Al posto dell'autosalvataggio a senso unico, vuole **checkpoint automatici da cui
  poter tornare indietro**.

Decisioni prese in fase di brainstorming (2026-07-12):
- **Esperienza:** ricarica da un punto (la morte non è permanente).
- **Granularità checkpoint:** a ogni piano (punto di flush naturale di DCSS).
- **Ritenzione:** ultimi 3–5 checkpoint a rotazione (default 5).
- **Approccio:** A — "save-guard" gestito dal Director via sorveglianza dei file.
  Scartati: B (patch del binario) e C (IAT-hook di `DeleteFileW`) — tenuti come
  eventuale hardening futuro se servisse funzionare senza Director.

Vincolo tecnico centrale: lo stato **a metà piano** vive in memoria, non su disco; il
`.cs` su disco riflette l'ultimo flush (ingresso piano / save-quit). Quindi i
checkpoint "a costo zero" osservabili dall'esterno sono naturalmente **per piano**.

## Obiettivo

Un modulo isolato che, **senza ricompilare** il gioco e **senza toccare** audio,
grafica, Lua o binario, faccia snapshot a rotazione del salvataggio a ogni piano e
lo ripristini automaticamente alla morte del personaggio.

## Architettura

### Componente: `director/save_guard.py`

Una classe `SaveGuard` con **una sola responsabilità** (checkpoint + ripristino),
avviata come **thread daemon** dal Director prima di entrare in
`PipeServer(...).serve_forever()`. Nessun'altra parte del sistema viene modificata,
a parte:
- `director/director.py`: avvia il thread e, in `handle()`, notifica al guard il
  token `state__player_death` (per armare il ripristino).
- `play-remaster.ps1`: esporta `DCSS_SAVES_DIR` verso il Director.

### Individuazione dei path

- **saves dir:** da env var `DCSS_SAVES_DIR` (esportata dal launcher). Fallback in
  sviluppo: `HERE/../../saves` (dove `HERE` è la cartella del Director; due livelli
  sopra sta la root del gioco `stone_soup-tiles-0.34/`).
- **checkpoints dir:** `<saves_parent>/remaster_checkpoints/<nome>/` — **fuori** da
  `saves/` per non interferire con la scansione dei salvataggi di DCSS.

### Meccanica — polling (nessuna dipendenza nuova)

Il thread scandisce `saves/*.cs` ogni `poll_seconds` (default 1.5) mantenendo per
ciascun file l'ultimo `(mtime, size)` noto.

**Snapshot (su `.cs` creato/modificato):**
1. Rilevata una variazione di `(mtime, size)` rispetto allo stato noto, si applica un
   **debounce**: si attende che la dimensione resti stabile tra due poll consecutivi
   (DCSS potrebbe essere ancora in fase di scrittura).
2. Si calcola l'hash del contenuto; se è **identico** all'ultimo snapshot di quel
   personaggio, si salta (dedup — evita snapshot doppi da riscritture equivalenti).
3. Altrimenti si copia il `.cs` in `remaster_checkpoints/<nome>/` con nome ordinabile
   (indice incrementale, es. `0007.cs` + eventuale `.meta` con timestamp/turno se
   disponibile).
4. **Rotazione:** si mantengono al massimo `keep` snapshot (default 5), eliminando i
   più vecchi.

**Ripristino (su `.cs` sparito = morte):**
1. Un file `.cs` prima presente ora assente indica che DCSS lo ha cancellato.
2. Il ripristino avviene **solo se armato** dal token di morte (vedi sotto). Se armato,
   si copia l'ultimo snapshot disponibile di quel personaggio in `saves/<nome>.cs`.
3. Dopo il ripristino si verifica che il file persista per qualche poll (nessuna
   ri-cancellazione da parte del gioco) e si **disarma**.

### Disambiguazione morte vs. cancellazione volontaria

Il Director riceve già il token `state__player_death` nel suo `handle()`. Alla
ricezione, chiama `save_guard.arm_restore()` che imposta un flag con timestamp
(finestra ~30 s). Il ripristino su `.cs` sparito procede **solo** se il flag è armato
e non scaduto. Così, cancellare un personaggio dal menu (senza morte) non lo
resuscita.

**Fallback:** se in-game il timing del token risultasse inaffidabile (arriva troppo
tardi rispetto alla cancellazione, o non arriva), si passa a *ripristina su qualsiasi
cancellazione* — comportamento più semplice e comunque coerente con l'intento
dell'utente (non perdere mai il personaggio). La scelta è controllata da un flag di
config (`require_death_token`, default `true`).

### Configurazione — `director/saveguard.json`

```json
{
  "enabled": true,
  "keep": 5,
  "poll_seconds": 1.5,
  "require_death_token": true,
  "restore_window_seconds": 30
}
```

Editabile a caldo (riletto dal Director al riavvio, come soundmap/visualmap). Se il
file manca, valgono i default sopra. Se `enabled` è `false`, il thread non parte
(comportamento DCSS invariato: permadeath).

## Flusso dati

```
DCSS (crawl.exe)                 SaveGuard thread (nel Director)
-----------------                --------------------------------
entra in nuovo piano
  -> riscrive saves/X.cs  --->   poll rileva (mtime,size) cambiati
                                 -> debounce -> hash -> snapshot
                                    remaster_checkpoints/X/NNNN.cs (keep 5)

muore
  -> emette msg morte     --->   token state__player_death (via pipe/handle)
                                 -> save_guard.arm_restore()  [flag 30s]
  -> cancella saves/X.cs   --->   poll rileva X.cs sparito + flag armato
                                 -> copia ultimo snapshot -> saves/X.cs
                                 -> disarma

utente rilancia / character-select
  -> DCSS carica saves/X.cs (stato inizio piano) -> personaggio vivo
```

## Isolamento e interfaccia del modulo

`SaveGuard` è progettato per essere testato senza gioco:

- **Costruttore:** `SaveGuard(saves_dir, checkpoints_dir, config)` — path iniettabili.
- **`poll_once()`:** esegue **una** scansione (snapshot/rotazione/eventuale restore) e
  ritorna un piccolo resoconto strutturato (es. `{"snapshotted": [...], "restored":
  [...]}`). È la primitiva pura testabile.
- **`arm_restore()` / `_armed`:** stato del flag di morte.
- **`run_forever()`:** loop che chiama `poll_once()` ogni `poll_seconds`; è ciò che
  gira nel thread daemon. Non contiene logica testabile oltre lo sleep.

Dipendenze: solo stdlib (`os`, `shutil`, `hashlib`, `time`, `threading`, `json`).
Nessun `watchdog` — polling per semplicità e per evitare grane col freeze PyInstaller.

## Testing

Suite pytest in `director/tests/` (già presente), con `tmp_path`:

1. **snapshot base:** creo `saves/X.cs`, `poll_once()` → esiste 1 snapshot.
2. **dedup:** stesso contenuto riscritto → nessun nuovo snapshot.
3. **nuovo contenuto:** contenuto diverso → nuovo snapshot.
4. **rotazione:** oltre `keep` snapshot → restano solo gli ultimi `keep`.
5. **debounce:** file in crescita tra due poll → snapshot solo quando la size si
   stabilizza.
6. **restore armato:** snapshot presente, `arm_restore()`, cancello `saves/X.cs`,
   `poll_once()` → `saves/X.cs` ripristinato = ultimo snapshot.
7. **restore non armato:** senza `arm_restore()` (e `require_death_token=true`),
   cancello `saves/X.cs` → **nessun** ripristino.
8. **finestra scaduta:** `arm_restore()` + tempo oltre `restore_window_seconds` →
   nessun ripristino.
9. **fallback:** `require_death_token=false` → ripristino anche senza token.
10. **disabilitato:** `enabled=false` → il Director non avvia il thread (test a
    livello di wiring, o `SaveGuard` inerte).

Il tempo nei test è iniettabile (parametro/monkeypatch su un `now()` interno) per
evitare `time.sleep` reali e testare la finestra di 30 s in modo deterministico.

## Rischi e validazione (ordine nel piano)

1. 🔴 **Il `.cs` viene riscritto su disco a ogni cambio piano senza uscire dal gioco?**
   Assunzione cardine dei checkpoint per-piano. **Prima validazione empirica del
   piano:** avviare una partita, cambiare piano senza save-quit, osservare mtime/size
   di `saves/<nome>.cs`. Se **falso** (flush solo al save-quit), i checkpoint
   avverrebbero solo al save-quit → si rivede la granularità con l'utente (non si
   procede assumendo).
2. **La morte cancella `saves/<nome>.cs`.** Standard DCSS, molto probabile; da
   confermare osservando la cartella durante una morte reale.
3. **Un `.cs` ripristinato ricarica pulito all'inizio del piano.** Da verificare
   ricaricando dopo un ripristino: personaggio vivo, coerente, giocabile.
4. **Timing del token di morte vs. cancellazione del file.** Se il token arriva dopo
   la cancellazione, la finestra di 30 s copre comunque il caso (si arma dopo, ma il
   poll di restore riprova ad ogni ciclo finché il flag è valido). Se non arriva
   affatto, si usa il fallback `require_death_token=false`.
5. **Il personaggio ripristinato è selezionabile nella stessa sessione** (senza
   rilanciare crawl.exe) oppure serve un rilancio? Da verificare; nel dubbio la UX
   garantita è "rilancia dal `.bat`". Non blocca il design.

## Fuori scope (YAGNI)

- Checkpoint a metà piano / ogni N turni (richiederebbe forzare un flush su disco:
  invasivo). Escluso per scelta in brainstorming.
- Patch del binario (B) e IAT-hook `DeleteFileW` (C).
- Interfaccia utente per scegliere/gestire i checkpoint (per ora rotazione automatica).
- Pulizia della riga di morte in `scores`/morgue (cosmetica, innocua).
