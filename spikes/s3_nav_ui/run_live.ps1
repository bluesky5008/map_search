# T12 실기 검증을 관리자 권한으로 실행한다 (UAC 1회).
param([string]$Hwnd = "0x40148", [string]$Extra = "")
$d = "C:\src\git\map_search\spikes\s3_nav_ui"
New-Item -ItemType Directory -Force "$d\work" | Out-Null
$log = "$d\work\live_check.log"
$py = "C:\src\git\map_search\.venv\Scripts\python.exe"
$inner = @"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
& '$py' '$d\live_check.py' --hwnd $Hwnd $Extra 2>&1 | Out-File '$log' -Encoding utf8
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
Start-Process -Verb RunAs powershell -ArgumentList "-NoProfile -EncodedCommand $encoded" -Wait
Get-Content $log -Encoding utf8
