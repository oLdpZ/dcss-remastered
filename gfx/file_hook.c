#include <windows.h>
#include <psapi.h>
#include "file_hook.h"

/* DCSS mette un byte-range lock (LockFile/LockFileEx) sul contenuto del save mentre
   giochi: leggere quei byte da un altro processo da' ERROR_LOCK_VIOLATION (33). Qui
   intercettiamo Lock/UnlockFile[Ex] e le rendiamo no-op (ritornano TRUE) SOLO per gli
   handle che si riferiscono a un file *.cs, cosi' il Director puo' leggere il save e
   fare i checkpoint per-piano. Il gioco (istanza singola) mantiene comunque accesso di
   fatto esclusivo. Vedi file_hook.h. [BUILD DIAGNOSTICA: logga su filehook.log.] */

typedef BOOL  (WINAPI *LockFile_t)(HANDLE, DWORD, DWORD, DWORD, DWORD);
typedef BOOL  (WINAPI *LockFileEx_t)(HANDLE, DWORD, DWORD, DWORD, DWORD, LPOVERLAPPED);
typedef BOOL  (WINAPI *UnlockFile_t)(HANDLE, DWORD, DWORD, DWORD, DWORD);
typedef BOOL  (WINAPI *UnlockFileEx_t)(HANDLE, DWORD, DWORD, DWORD, LPOVERLAPPED);
typedef DWORD (WINAPI *GFPNBH_t)(HANDLE, LPWSTR, DWORD, DWORD);
typedef HANDLE(WINAPI *CreateFileW_t)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES,
                                      DWORD, DWORD, HANDLE);

static LockFile_t     g_realLockFile     = NULL;
static LockFileEx_t   g_realLockFileEx   = NULL;
static UnlockFile_t   g_realUnlockFile   = NULL;
static UnlockFileEx_t g_realUnlockFileEx = NULL;
static GFPNBH_t       g_gfpnbh           = NULL;
static CreateFileW_t  g_realW            = NULL;  /* solo per il logger diagnostico */
static int g_off = -1;

static int save_off(void) {
    if (g_off < 0) g_off = GetEnvironmentVariableA("DCSS_SAVEHOOK_OFF", NULL, 0) ? 1 : 0;
    return g_off;
}

static int g_dbg = -1;
static int hook_debug(void) {
    if (g_dbg < 0) g_dbg = GetEnvironmentVariableA("DCSS_SAVEHOOK_DEBUG", NULL, 0) ? 1 : 0;
    return g_dbg;
}

/* Logging diagnostico su filehook.log, attivo solo con env DCSS_SAVEHOOK_DEBUG. */
static void hooklog(const char *msg) {
    HANDLE h;
    DWORD wrote;
    if (!hook_debug() || !g_realW) return;
    h = g_realW(L"filehook.log", FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    WriteFile(h, msg, (DWORD)lstrlenA(msg), &wrote, NULL);
    CloseHandle(h);
}

static int ends_cs_w(LPCWSTR s) {
    size_t n = 0;
    if (!s) return 0;
    while (s[n]) n++;
    if (n < 3) return 0;
    return s[n-3] == L'.'
        && (s[n-2] == L'c' || s[n-2] == L'C')
        && (s[n-1] == L's' || s[n-1] == L'S');
}

/* Ritorna 1 se l'handle si riferisce a un file *.cs (il save DCSS). */
static int handle_is_cs(HANDLE h) {
    WCHAR path[600];
    DWORD n;
    if (!g_gfpnbh) return 0;
    n = g_gfpnbh(h, path, 599, 0 /*FILE_NAME_NORMALIZED | VOLUME_NAME_DOS*/);
    if (n == 0 || n >= 600) return 0;
    path[n] = 0;
    return ends_cs_w(path);
}

static BOOL WINAPI hook_LockFile(HANDLE h, DWORD a, DWORD b, DWORD c, DWORD d) {
    if (!save_off() && handle_is_cs(h)) { hooklog("LockFile .cs -> no-op\r\n"); return TRUE; }
    return g_realLockFile ? g_realLockFile(h, a, b, c, d) : LockFile(h, a, b, c, d);
}

static BOOL WINAPI hook_LockFileEx(HANDLE h, DWORD fl, DWORD r, DWORD a, DWORD b,
                                   LPOVERLAPPED o) {
    if (!save_off() && handle_is_cs(h)) { hooklog("LockFileEx .cs -> no-op\r\n"); return TRUE; }
    return g_realLockFileEx ? g_realLockFileEx(h, fl, r, a, b, o)
                            : LockFileEx(h, fl, r, a, b, o);
}

static BOOL WINAPI hook_UnlockFile(HANDLE h, DWORD a, DWORD b, DWORD c, DWORD d) {
    if (!save_off() && handle_is_cs(h)) return TRUE;
    return g_realUnlockFile ? g_realUnlockFile(h, a, b, c, d) : UnlockFile(h, a, b, c, d);
}

static BOOL WINAPI hook_UnlockFileEx(HANDLE h, DWORD r, DWORD a, DWORD b, LPOVERLAPPED o) {
    if (!save_off() && handle_is_cs(h)) return TRUE;
    return g_realUnlockFileEx ? g_realUnlockFileEx(h, r, a, b, o)
                              : UnlockFileEx(h, r, a, b, o);
}

/* Patcha nell'IAT del modulo `mod` ogni thunk == origAddr con repl. Conta i patchati. */
static int patch_module(HMODULE mod, void *origAddr, void *repl) {
    BYTE *b = (BYTE *)mod;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)b;
    IMAGE_NT_HEADERS *nt;
    DWORD rva;
    IMAGE_IMPORT_DESCRIPTOR *imp;
    int count = 0;
    if (!origAddr || dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;
    nt = (IMAGE_NT_HEADERS *)(b + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return 0;
    rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!rva) return 0;
    imp = (IMAGE_IMPORT_DESCRIPTOR *)(b + rva);
    for (; imp->Name; imp++) {
        IMAGE_THUNK_DATA *thunk = (IMAGE_THUNK_DATA *)(b + imp->FirstThunk);
        for (; thunk->u1.Function; thunk++) {
            void **slot = (void **)&thunk->u1.Function;
            DWORD old;
            if (*slot != origAddr) continue;
            if (VirtualProtect(slot, sizeof(void *), PAGE_READWRITE, &old)) {
                *slot = repl;
                VirtualProtect(slot, sizeof(void *), old, &old);
                count++;
            }
        }
    }
    return count;
}

/* Patcha in tutti i moduli CHIAMANTI (salta i moduli d'implementazione) lo slot che
   punta a k32addr o kbaseaddr, sostituendolo con repl. Ritorna il totale patchato. */
static int hook_func(HMODULE *mods, DWORD n, HMODULE k32, HMODULE kbase, HMODULE ntdll,
                     void *k32addr, void *kbaddr, void *repl) {
    DWORD i;
    int tot = 0;
    for (i = 0; i < n; i++) {
        if (mods[i] == k32 || mods[i] == kbase || mods[i] == ntdll) continue;
        if (k32addr) tot += patch_module(mods[i], k32addr, repl);
        if (kbaddr && kbaddr != k32addr) tot += patch_module(mods[i], kbaddr, repl);
    }
    return tot;
}

/* Risolve func in kernel32 e kernelbase; imposta *real all'impl. reale (kernelbase,
   fallback kernel32) da chiamare DIRETTAMENTE (no ricorsione); patcha i chiamanti. */
static int install_one(HMODULE *mods, DWORD n, HMODULE k32, HMODULE kbase, HMODULE ntdll,
                       const char *name, void *repl, void **real) {
    void *ka = k32   ? (void *)GetProcAddress(k32, name)   : NULL;
    void *kb = kbase ? (void *)GetProcAddress(kbase, name) : NULL;
    *real = kb ? kb : ka;
    return hook_func(mods, n, k32, kbase, ntdll, ka, kb, repl);
}

void file_hook_install(void) {
    static int done = 0;
    HMODULE k32, kbase, ntdll;
    HMODULE mods[512];
    DWORD cb = 0, n;
    int tL = 0, tLx = 0, tU = 0, tUx = 0;
    char buf[220];
    if (done) return;
    done = 1;

    k32 = GetModuleHandleA("kernel32.dll");
    kbase = GetModuleHandleA("kernelbase.dll");
    ntdll = GetModuleHandleA("ntdll.dll");
    if (!k32) return;

    /* Per il logger e per identificare gli handle .cs. */
    g_realW = (CreateFileW_t)GetProcAddress(kbase ? kbase : k32, "CreateFileW");
    g_gfpnbh = (GFPNBH_t)GetProcAddress(k32, "GetFinalPathNameByHandleW");
    if (!g_gfpnbh && kbase) g_gfpnbh = (GFPNBH_t)GetProcAddress(kbase, "GetFinalPathNameByHandleW");

    if (!EnumProcessModules(GetCurrentProcess(), mods, sizeof(mods), &cb)) return;
    n = cb / (DWORD)sizeof(HMODULE);

    tL  = install_one(mods, n, k32, kbase, ntdll, "LockFile",     (void *)hook_LockFile,     (void **)&g_realLockFile);
    tLx = install_one(mods, n, k32, kbase, ntdll, "LockFileEx",   (void *)hook_LockFileEx,   (void **)&g_realLockFileEx);
    tU  = install_one(mods, n, k32, kbase, ntdll, "UnlockFile",   (void *)hook_UnlockFile,   (void **)&g_realUnlockFile);
    tUx = install_one(mods, n, k32, kbase, ntdll, "UnlockFileEx", (void *)hook_UnlockFileEx, (void **)&g_realUnlockFileEx);

    wsprintfA(buf, "install mods=%lu gfpnbh=%p patched L=%d Lx=%d U=%d Ux=%d\r\n",
              (unsigned long)n, g_gfpnbh, tL, tLx, tU, tUx);
    hooklog(buf);
}
