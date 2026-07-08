#pragma once
#include "shared_state.h"
/* Ritorna lo snapshot corrente, o NULL se non mappato. */
const GfxState *shmem_get(void);
/* Da chiamare una volta per frame: apre (con retry) e copia lo struct. */
void shmem_poll(void);
