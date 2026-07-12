# DCSS Remastered — launcher one-click.
# Avvia il Director (audio+grafica), lancia il gioco, chiude il Director all'uscita.
$ErrorActionPreference = "SilentlyContinue"
$game   = Split-Path $PSScriptRoot          # ...\stone_soup-tiles-0.34
$dirDir = "$PSScriptRoot\director"
# Save-Guard: tell the Director where the game's saves folder is.
$env:DCSS_SAVES_DIR = "$game\saves"

# 1) Primo avvio: crea le copie _orig dei DLL di sistema dal SysWOW64 DELL'UTENTE
#    (non ridistribuiamo DLL Microsoft). I proxy winmm/opengl32 le inoltrano.
$sys = "$env:WINDIR\SysWOW64"
if ((-not (Test-Path "$game\winmm_orig.dll"))    -and (Test-Path "$sys\winmm.dll"))    { Copy-Item "$sys\winmm.dll"    "$game\winmm_orig.dll"    -Force }
if ((-not (Test-Path "$game\opengl32_orig.dll")) -and (Test-Path "$sys\opengl32.dll")) { Copy-Item "$sys\opengl32.dll" "$game\opengl32_orig.dll" -Force }

# 2) Chiudi Director rimasti da sessioni precedenti (sia .exe sia sorgente)
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='director.exe'" |
    Where-Object { $_.CommandLine -like '*director*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 3) Avvia il Director: preferisci director.exe (congelato); fallback a python (dev).
if (Test-Path "$dirDir\director.exe") {
    $dir = Start-Process "$dirDir\director.exe" -WorkingDirectory $dirDir -WindowStyle Hidden -PassThru
} else {
    $dir = Start-Process python -ArgumentList "`"$dirDir\director.py`"" -WorkingDirectory $dirDir -WindowStyle Hidden -PassThru
}

# 4) Attendi che la named pipe sia pronta (max ~15s) invece di uno sleep fisso.
#    Test-Path non e' affidabile sui named pipe -> enumeriamo i pipe di sistema.
#    Se non rilevabile, si procede comunque dopo il timeout (il gioco tollera un
#    Director che parte con lieve ritardo).
for ($i = 0; $i -lt 150; $i++) {
    try { if ([System.IO.Directory]::GetFiles('\\.\pipe\') -match 'dcss_audio') { break } } catch {}
    Start-Sleep -Milliseconds 100
}

# 5) Lancia il gioco e attendi la chiusura.
Start-Process "$game\crawl.exe" -WorkingDirectory $game -Wait

# 6) Spegni il Director.
if ($dir -and -not $dir.HasExited) { Stop-Process -Id $dir.Id -Force }
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='director.exe'" |
    Where-Object { $_.CommandLine -like '*director*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Output "Sessione DCSS Remastered terminata."
