$ErrorActionPreference = "Stop"
$vc = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat"
$here = $PSScriptRoot
Remove-Item "$here\winmm.dll","$here\winmm.lib","$here\winmm.exp","$here\winmm_proxy.obj" -ErrorAction SilentlyContinue
cmd /c "`"$vc`" x86 && cl /nologo /LD /O2 `"$here\winmm_proxy.c`" /Fe:`"$here\winmm.dll`" /link /MACHINE:X86"
if ($LASTEXITCODE -ne 0) { throw "compilazione fallita (exit $LASTEXITCODE)" }
if (Test-Path "$here\winmm.dll") { Write-Output "BUILD OK -> $here\winmm.dll" } else { throw "winmm.dll non prodotta" }
