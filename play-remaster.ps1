# DCSS Remastered Audio — launcher one-click.
# Avvia l'Audio Director, lancia il gioco, e chiude il Director all'uscita.
$ErrorActionPreference = "SilentlyContinue"
$game = Split-Path $PSScriptRoot          # ...\stone_soup-tiles-0.34
$dirScript = "$PSScriptRoot\director\director.py"

# Chiudi eventuali Director rimasti da sessioni precedenti
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*director.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Avvia il Director
$dir = Start-Process python -ArgumentList "`"$dirScript`"" `
        -WorkingDirectory "$PSScriptRoot\director" -PassThru
Start-Sleep -Milliseconds 900

# Lancia il gioco e attendi la sua chiusura
Start-Process "$game\crawl.exe" -WorkingDirectory $game -Wait

# Spegni il Director
if ($dir -and -not $dir.HasExited) { Stop-Process -Id $dir.Id -Force }
# Sicurezza: elimina qualsiasi Director residuo
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*director.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Output "Sessione DCSS Remastered terminata."
