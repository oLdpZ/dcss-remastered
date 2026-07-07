#include <windows.h>
#include <stdio.h>

/* Il nostro export sndPlaySoundW punta a una funzione con nome diverso,
   per evitare il conflitto con la dichiarazione dllimport di windows.h. */
#pragma comment(linker, "/EXPORT:sndPlaySoundW=_proxy_sndPlaySoundW@8")

/* Forwarder: ogni altra funzione winmm importata da crawl.exe viene
   inoltrata alla winmm reale (copiata come winmm_orig.dll). */
#pragma comment(linker, "/EXPORT:timeBeginPeriod=winmm_orig.timeBeginPeriod")
#pragma comment(linker, "/EXPORT:timeEndPeriod=winmm_orig.timeEndPeriod")
#pragma comment(linker, "/EXPORT:timeGetTime=winmm_orig.timeGetTime")
#pragma comment(linker, "/EXPORT:waveInAddBuffer=winmm_orig.waveInAddBuffer")
#pragma comment(linker, "/EXPORT:waveInClose=winmm_orig.waveInClose")
#pragma comment(linker, "/EXPORT:waveInGetDevCapsW=winmm_orig.waveInGetDevCapsW")
#pragma comment(linker, "/EXPORT:waveInGetNumDevs=winmm_orig.waveInGetNumDevs")
#pragma comment(linker, "/EXPORT:waveInOpen=winmm_orig.waveInOpen")
#pragma comment(linker, "/EXPORT:waveInPrepareHeader=winmm_orig.waveInPrepareHeader")
#pragma comment(linker, "/EXPORT:waveInReset=winmm_orig.waveInReset")
#pragma comment(linker, "/EXPORT:waveInStart=winmm_orig.waveInStart")
#pragma comment(linker, "/EXPORT:waveInUnprepareHeader=winmm_orig.waveInUnprepareHeader")
#pragma comment(linker, "/EXPORT:waveOutClose=winmm_orig.waveOutClose")
#pragma comment(linker, "/EXPORT:waveOutGetDevCapsW=winmm_orig.waveOutGetDevCapsW")
#pragma comment(linker, "/EXPORT:waveOutGetErrorTextW=winmm_orig.waveOutGetErrorTextW")
#pragma comment(linker, "/EXPORT:waveOutGetNumDevs=winmm_orig.waveOutGetNumDevs")
#pragma comment(linker, "/EXPORT:waveOutOpen=winmm_orig.waveOutOpen")
#pragma comment(linker, "/EXPORT:waveOutPrepareHeader=winmm_orig.waveOutPrepareHeader")
#pragma comment(linker, "/EXPORT:waveOutReset=winmm_orig.waveOutReset")
#pragma comment(linker, "/EXPORT:waveOutUnprepareHeader=winmm_orig.waveOutUnprepareHeader")
#pragma comment(linker, "/EXPORT:waveOutWrite=winmm_orig.waveOutWrite")

static HMODULE g_real = NULL;
typedef BOOL (WINAPI *sndPlaySoundW_t)(LPCWSTR, UINT);

static HMODULE real_winmm(void) {
    if (!g_real) g_real = LoadLibraryW(L"winmm_orig.dll");
    return g_real;
}

static void log_path(LPCWSTR s) {
    FILE *f = _wfopen(L"remaster_proxy.log", L"a, ccs=UTF-8");
    if (f) { fwprintf(f, L"%s\n", s ? s : L"(null)"); fclose(f); }
}

BOOL WINAPI proxy_sndPlaySoundW(LPCWSTR pszSound, UINT fuSound) {
    log_path(pszSound);
    HMODULE h = real_winmm();
    if (h) {
        sndPlaySoundW_t real = (sndPlaySoundW_t)GetProcAddress(h, "sndPlaySoundW");
        if (real) return real(pszSound, fuSound);
    }
    return FALSE;
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID unused) {
    (void)unused;
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(h);
    return TRUE;
}
