# Launch the S-3/S-4 command agent elevated (one UAC prompt).
# Default HWND targets the test client; verify with: mapscan windows --crops <dir>
param([string]$Hwnd = "0x60042")
$d = "C:\src\git\map_search\spikes\s3_nav_ui"
New-Item -ItemType Directory -Force "$d\work" | Out-Null
$py = "C:\src\git\map_search\.venv\Scripts\python.exe"
$inner = "& '$py' '$d\agent.py' --hwnd $Hwnd --dir '$d\work' 2>&1 | Out-File '$d\work\agent_run.log' -Encoding utf8"
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
Start-Process -Verb RunAs powershell -ArgumentList "-NoProfile -EncodedCommand $encoded"
Write-Host "agent launch requested (UAC)"
