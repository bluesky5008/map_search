# S-4 팝업 닫기 실험을 관리자 권한으로 실행한다 (UAC 1회).
param([string]$Hwnd = "0x40148")
$d = "C:\src\git\map_search\spikes\s3_nav_ui"
$log = "$d\work\popup_check.log"
$py = "C:\src\git\map_search\.venv\Scripts\python.exe"
$inner = @"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
& '$py' '$d\popup_check.py' --hwnd $Hwnd 2>&1 | Out-File '$log' -Encoding utf8
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
Start-Process -Verb RunAs powershell -ArgumentList "-NoProfile -EncodedCommand $encoded" -Wait
Get-Content $log -Encoding utf8
