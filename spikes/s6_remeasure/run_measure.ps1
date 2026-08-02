# Launch the DCR-002 option-(d) re-measurement elevated (one UAC prompt).
# Verify the target HWND first with: mapscan windows --crops <dir>
param([string]$Hwnd = "0x60042")
$repo = "C:\src\git\map_search"
$d = "$repo\spikes\s6_remeasure"
New-Item -ItemType Directory -Force "$d\work" | Out-Null
$py = "$repo\.venv\Scripts\python.exe"
$inner = "& '$py' -u '$d\measure100.py' --hwnd $Hwnd 2>&1 | Out-File '$d\work\measure_run.log' -Encoding utf8"
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
Start-Process -Verb RunAs powershell -ArgumentList "-NoProfile -EncodedCommand $encoded"
Write-Host "measure100 launch requested (UAC) hwnd=$Hwnd"
