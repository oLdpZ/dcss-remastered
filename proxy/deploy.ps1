$ErrorActionPreference = "Stop"
$game = Split-Path (Split-Path $PSScriptRoot)   # ...\stone_soup-tiles-0.34
Copy-Item "$PSScriptRoot\winmm.dll" "$game\winmm.dll" -Force
Copy-Item "C:\Windows\SysWOW64\winmm.dll" "$game\winmm_orig.dll" -Force
Write-Output "deploy ok in $game"
