$ErrorActionPreference = "Stop"
$vc = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat"
$here = $PSScriptRoot
python "$here\gen_forwarders.py"
if ($LASTEXITCODE -ne 0) { throw "gen_forwarders fallito" }
Remove-Item "$here\opengl32.dll","$here\opengl32.lib","$here\opengl32.exp","$here\*.obj" -ErrorAction SilentlyContinue
cmd /c "`"$vc`" x86 && cl /nologo /LD /O2 `"$here\gl_proxy.c`" `"$here\postprocess.c`" `"$here\iat_hook.c`" `"$here\shmem.c`" /Fe:`"$here\opengl32.dll`" /link /MACHINE:X86 gdi32.lib user32.lib opengl32.lib"
if ($LASTEXITCODE -ne 0) { throw "compilazione fallita (exit $LASTEXITCODE)" }
if (Test-Path "$here\opengl32.dll") { Write-Output "BUILD OK -> $here\opengl32.dll" } else { throw "opengl32.dll non prodotta" }
