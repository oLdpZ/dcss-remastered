#include <windows.h>
#include <string.h>
#include "shmem.h"

static HANDLE  g_map = NULL;
static void   *g_view = NULL;
static GfxState g_snap;
static int      g_have = 0;
static int      g_frames = 0;

static void try_open(void) {
    /* Riprova ogni ~60 frame se il Director non c'e' ancora. */
    if (g_map) return;
    if ((g_frames++ % 60) != 0) return;
    g_map = OpenFileMappingA(FILE_MAP_READ, FALSE, "dcss_gfx_state");
    if (!g_map) return;
    g_view = MapViewOfFile(g_map, FILE_MAP_READ, 0, 0, sizeof(GfxState));
    if (!g_view) { CloseHandle(g_map); g_map = NULL; }
}

void shmem_poll(void) {
    try_open();
    if (g_view) { memcpy(&g_snap, g_view, sizeof(GfxState)); g_have = 1; }
}

const GfxState *shmem_get(void) { return g_have ? &g_snap : NULL; }
