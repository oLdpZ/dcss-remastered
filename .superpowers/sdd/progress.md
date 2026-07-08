# Graphics Remaster — SDD progress ledger

Plan: docs/superpowers/plans/2026-07-08-graphics-remaster.md
Branch: feat/graphics-remaster
Base commit: a2ea956

- Task 1: complete (commit fc9d41f, review clean). Minor(final-review): opengl32.lib omitted (ok, verified); g_vp extern decl deferred to consumers.
- Task 2: COMPLETE + HUMAN-VERIFIED @ checkpoint 1 (commit b83bb38, review clean). Red tint visible in-game, game stable, hook lands on gdi32!SwapBuffers. Milestone proven. Minor(final-review): kill-switch cached process-lifetime.
- Task 3: complete (commit 9123fba, review clean — byte layout verified field-by-field). Minor(final-review): import-shim style; C header not yet compiled (size-assert will catch drift).
- Task 4: complete (commit bc85651, review clean — shmem name match, NULL->passthrough, handle hygiene, push/pop balanced). Minor(final-review): shmem.c missing #include <string.h> (memcpy intrinsic, builds clean); redundant glBlendFunc in vignette block.
- Task 5: complete (commit bc68f0b, review clean — PP_INIT OK, shader no-leak, glUniform2f added). Minor(final-review): per-frame glTexParameteri; no GL_LINK_STATUS check; harness g_tex/u_tex naming.
- Task 6: complete (commit 09177c8, review clean — layering + event-seq verified, full suite 14/14). GAP: visualmap.json hp_low.vignette_tint + player_death.fade_black have no struct field (dropped) -> batch into Task 9 struct bump (flags + vignette_tint + fade_black).
- Task 7: COMPLETE + HUMAN-VERIFIED @ checkpoint finale (commit 051a261). Grading live. 
- Task 8: COMPLETE + HUMAN-VERIFIED @ checkpoint 3/finale (commit 7d57460 + fix ba2ef75). Juice: hit-flash + level-up gold confirmed live.
- Task 9: COMPLETE + HUMAN-VERIFIED @ checkpoint finale (commit 805d0e5) + moderato tuning (c28fdd8). Red-vignette/death-fade/unstable + zone grades now visible. User: "mi pare funzioni tutto".
- Task 10: complete (commit d1ec532, review clean — self-disable placed safely, link-status check, string.h, README accurate). ALL 10 TASKS DONE.

NOTE: executing out of plan order — Task 6 (Python) before Tasks 4/5 (C render), which are gated on human checkpoint-1 (does the SwapBuffers hook land?).

## Feedback utente (checkpoint 2/3)
- AUDIO ok, juice ok: hit->flash grigio (letto come indicatore colpi, positivo), level_up->oro ok.
- Non nota il GRADE CONTINUO (tinta zona + low-HP): tinte troppo scure/desature a bassa strength -> legge come dimming, non colore.
- Stairs = solo-audio by design; grade cambia per-branch non per-livello (ok, chiarito).
- TARGET TUNING scelto: "MODERATO / visibile" -> strength ~0.25-0.40, tinte piu' sature. Applicare in re-tune visualmap.json dopo Task 9 mechanics. Low-HP diventera' rosso pulsante (T9) => risolve il "non lo noto".
