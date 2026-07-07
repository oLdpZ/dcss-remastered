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
static HANDLE  g_pipe = INVALID_HANDLE_VALUE;
typedef BOOL (WINAPI *sndPlaySoundW_t)(LPCWSTR, UINT);

static HMODULE real_winmm(void) {
    if (!g_real) g_real = LoadLibraryW(L"winmm_orig.dll");
    return g_real;
}

static BOOL passthrough(LPCWSTR s, UINT f) {
    HMODULE h = real_winmm();
    if (h) {
        sndPlaySoundW_t real = (sndPlaySoundW_t)GetProcAddress(h, "sndPlaySoundW");
        if (real) return real(s, f);
    }
    return FALSE;
}

static BOOL try_connect(void) {
    if (g_pipe != INVALID_HANDLE_VALUE) return TRUE;
    g_pipe = CreateFileW(L"\\\\.\\pipe\\dcss_audio", GENERIC_WRITE, 0, NULL,
                         OPEN_EXISTING, 0, NULL);
    return g_pipe != INVALID_HANDLE_VALUE;
}

static BOOL send_token(LPCWSTR pszSound) {
    if (!try_connect()) return FALSE;
    char buf[1024]; int n = 0;
    if (pszSound)
        n = WideCharToMultiByte(CP_UTF8, 0, pszSound, -1, buf, sizeof(buf) - 2, NULL, NULL);
    if (n <= 0) { buf[0] = 0; n = 1; }
    buf[n - 1] = '\n';                 /* sostituisce il NUL con newline */
    DWORD written = 0;
    if (!WriteFile(g_pipe, buf, (DWORD)n, &written, NULL)) {
        CloseHandle(g_pipe); g_pipe = INVALID_HANDLE_VALUE;  /* pipe rotta -> riconnetti dopo */
        return FALSE;
    }
    return TRUE;
}

BOOL WINAPI proxy_sndPlaySoundW(LPCWSTR pszSound, UINT fuSound) {
    if (send_token(pszSound)) return TRUE;   /* Director attivo: possiede l'audio */
    return passthrough(pszSound, fuSound);   /* fallback SFX nativi */
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID unused) {
    (void)unused;
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(h);
    return TRUE;
}
