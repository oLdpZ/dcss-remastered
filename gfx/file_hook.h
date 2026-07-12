#pragma once
/* Save-lock hook: DCSS mette un byte-range lock (LockFile/LockFileEx) sul contenuto
   del save mentre giochi, quindi un altro processo (il Director) non puo' leggerlo
   (ERROR_LOCK_VIOLATION). Questo hook intercetta Lock/UnlockFile[Ex] su TUTTI i moduli
   caricati e le rende no-op (ritornano TRUE) SOLO per gli handle di file *.cs, cosi' il
   Director puo' leggere il save e il SaveGuard fa i checkpoint per-piano. Il gioco
   (istanza singola) mantiene accesso di fatto esclusivo. Idempotente, mai fatale.
   Kill-switch: env var DCSS_SAVEHOOK_OFF. */
void file_hook_install(void);
