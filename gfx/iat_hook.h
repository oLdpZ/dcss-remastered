#pragma once
/* Sostituisce nella Import Address Table del modulo principale la voce
   dll!func con `replacement`. Ritorna il puntatore originale, o NULL. */
void *iat_hook(const char *dll, const char *func, void *replacement);
