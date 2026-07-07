import pefile, sys
pe = pefile.PE(sys.argv[1] if len(sys.argv) > 1 else "../../crawl.exe", fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
print("Machine: 0x%04x" % pe.FILE_HEADER.Machine)
for e in pe.DIRECTORY_ENTRY_IMPORT:
    if e.dll.decode(errors="replace").lower().startswith("winmm"):
        for imp in e.imports:
            print(imp.name.decode() if imp.name else "ord#%d" % imp.ordinal)
