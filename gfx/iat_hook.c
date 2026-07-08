#include <windows.h>
#include "iat_hook.h"

void *iat_hook(const char *dll, const char *func, void *replacement) {
    HMODULE base = GetModuleHandleW(NULL);           /* crawl.exe */
    if (!base) return NULL;
    HMODULE target = GetModuleHandleA(dll);
    if (!target) return NULL;
    FARPROC orig_addr = GetProcAddress(target, func);
    if (!orig_addr) return NULL;

    BYTE *b = (BYTE *)base;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)b;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(b + dos->e_lfanew);
    DWORD rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!rva) return NULL;
    IMAGE_IMPORT_DESCRIPTOR *imp = (IMAGE_IMPORT_DESCRIPTOR *)(b + rva);

    for (; imp->Name; imp++) {
        const char *name = (const char *)(b + imp->Name);
        if (lstrcmpiA(name, dll) != 0) continue;
        IMAGE_THUNK_DATA *thunk = (IMAGE_THUNK_DATA *)(b + imp->FirstThunk);
        for (; thunk->u1.Function; thunk++) {
            void **slot = (void **)&thunk->u1.Function;
            if (*slot != (void *)orig_addr) continue;
            DWORD old;
            VirtualProtect(slot, sizeof(void *), PAGE_READWRITE, &old);
            void *original = *slot;
            *slot = replacement;
            VirtualProtect(slot, sizeof(void *), old, &old);
            return original;
        }
    }
    return NULL;
}
