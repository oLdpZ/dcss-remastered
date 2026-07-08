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
