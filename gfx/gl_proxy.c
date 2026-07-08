#include <windows.h>
#include <GL/gl.h>
#include "gl_forwarders.h"
#include "iat_hook.h"
#include "postprocess.h"

/* Sovrascriviamo glViewport per conoscere la risoluzione del framebuffer.
   Nome decorato __stdcall: 4 argomenti da 4 byte -> @16. */
#pragma comment(linker, "/EXPORT:glViewport=_glViewport@16")

static HMODULE g_real = NULL;
int g_vp_w = 0, g_vp_h = 0;   /* aggiornati da glViewport, letti dal postprocess */

typedef void (WINAPI *glViewport_t)(GLint, GLint, GLsizei, GLsizei);

typedef BOOL (WINAPI *SwapBuffers_t)(HDC);
static SwapBuffers_t g_real_swap = NULL;
static int g_hook_tried = 0;
static int g_off = -1;   /* kill-switch cache: -1 unknown, 0 on, 1 off */

static int gfx_off(void) {
    if (g_off < 0) g_off = GetEnvironmentVariableA("DCSS_GFX_OFF", NULL, 0) ? 1 : 0;
    return g_off;
}

static BOOL WINAPI hook_SwapBuffers(HDC hdc) {
    if (!gfx_off() && g_vp_w > 0 && g_vp_h > 0)
        pp_draw_overlay(g_vp_w, g_vp_h);
    return g_real_swap ? g_real_swap(hdc) : SwapBuffers(hdc);
}

static void install_hook_once(void) {
    if (g_hook_tried) return;
    g_hook_tried = 1;
    void *orig = iat_hook("gdi32.dll", "SwapBuffers", (void *)hook_SwapBuffers);
    if (orig) g_real_swap = (SwapBuffers_t)orig;
}

static HMODULE real_gl(void) {
    if (!g_real) g_real = LoadLibraryW(L"opengl32_orig.dll");
    return g_real;
}

void WINAPI glViewport(GLint x, GLint y, GLsizei w, GLsizei h) {
    install_hook_once();
    g_vp_w = (int)w; g_vp_h = (int)h;
    HMODULE hm = real_gl();
    if (hm) {
        glViewport_t real = (glViewport_t)GetProcAddress(hm, "glViewport");
        if (real) real(x, y, w, h);
    }
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID unused) {
    (void)unused;
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(h);
    return TRUE;
}
