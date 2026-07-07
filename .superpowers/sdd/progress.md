# DCSS Remastered Audio — Progress Ledger

Fase 0 (prova del ponte): complete (commit 48e7488, bridge intercept confermato in-game)

Fase 2 (Director): router TDD 6/6, engine+pipe+main — complete (commit 38ead12; pygame-ce su py3.14)
Fase 2.3 (proxy->pipe + Director integrato): complete — SFX sovrapposti confermati in-game dall'utente
Fase 3 (musica dinamica per zona + ducking): complete — confermato in-game. Fix: launcher + fade-out su disconnessione.

## Revisione finale codice (2026-07-07)
CRITICI: (1) CreateNamedPipe fuori da try/except -> director muore in silenzio se pipe occupata;
(2) nessun isolamento eccezioni nel dispatch -> una entry malformata di soundmap crasha il director.
IMPORTANT: (3) WriteFile bloccante + load Sound non in cache sull'hot path -> rischio hang gioco (fix: prewarm);
(4) duck/unduck non tocca _music_next durante crossfade; (6) ERROR_PIPE_CONNECTED non gestito.
Fix in corso via subagent. Accettati/minori: #5 (globals C, single-thread ok), #7-#10 (edge).
Fix robustezza (review finale): complete (commit 0f470a5) — pipe lifecycle robusto, isolamento eccezioni, prewarm SFX, duck su entrambi i canali. Test 6/6.
Fase 4 (musica 22 branch + SFX veri sintetizzati): complete.
