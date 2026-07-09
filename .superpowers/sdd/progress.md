# Pickup Sounds Per-Class — SDD progress ledger

Plan: docs/superpowers/plans/2026-07-09-pickup-sounds-per-class.md
Branch: feat/pickup-sounds
Base commit: 7d49b81

- Task 1: complete (commit f017c0f, review clean — 13 filenames/seeds correct, verbatim, arity verified)
- Task 2: complete (commit f4eea38, review clean — 13 tokens registered, JSON valid, real-Router test, 23/23). Minor(final): item pickup vol 0.55/0.6 < quaff/read 0.7 (design, sanity-check in-game); test pins op/group not filename.
- Task 3: complete (commit 7bc22f6, review clean — pcall-guarded, diff logic correct, cap=2 dedup, new-game suppression, 13-token+fallback, generic rule removed). Minor(final): dead CLASS_SND["gold"] entry (theoretical double-play, gold not inv-listed); it.slot/it.quantity unwrapped (matches existing style); DEBUG_CLASS relies on director.log logging missing paths.
- FINAL REVIEW (opus): clean tranne 1 Important (unguarded it.slot -> table-index throw fuori dal pcall, abbatteva ready()). FIXED in 553c549 (+ case-insensitive amulet, commento gold). Verificato sul diff.
- Task 4: COMPLETE + HUMAN-VERIFIED @ checkpoint in-game. Due difetti trovati e corretti:
  (1) BUG bloccante: la '}' di chiusura di CLASS_SND stava isolata a colonna 0 -> DCSS
      la trattava come terminatore del blocco Lua e troncava il chunk a riga 72
      ("unexpected symbol near <eof>"). ready() non partiva: niente pickup, niente switch
      musica-per-branch (restava la musica del menu). FIX: brace attaccata alla riga
      precedente, unico '}' a colonna 0 = terminatore r182.
  (2) TUNING: pickup arma indistinguibile dall'oro (timbro metallico brillante sovrapposto
      ~1900-2600 Hz). FIX: arma ridisegnata come shing con ring GRAVE e sostenuto
      (sweep tetto 1700, metal(440) coda lunga) vs jingle acuto rapido dell'oro.
      Utente: "ora e' distinto". Tutte le 13 categorie confermate live.
