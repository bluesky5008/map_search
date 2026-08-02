# Run the S-4 popup-close experiment elevated (one UAC prompt).
# Default HWND targets the test client; verify with: mapscan windows --crops <dir>
param([string]$Hwnd = "0x60042")
$d = "C:\src\git\map_search\spikes\s3_nav_ui"
New-Item -ItemType Directory -Force "$d\work" | Out-Null
$log = "$d\work\popup_check.log"
$py = "C:\src\git\map_search\.venv\Scripts\python.exe"
$inner = @"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
& '$py' '$d\popup_check.py' --hwnd $Hwnd 2>&1 | Out-File '$log' -Encoding utf8
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
Start-Process -Verb RunAs powershell -ArgumentList "-NoProfile -EncodedCommand $encoded" -Wait
Get-Content $log -Encoding utf8
