# S-3/S-4 에이전트를 관리자 권한으로 실행한다 (UAC 1회).
param([string]$Hwnd = "0x40148")
$d = "C:\src\git\map_search\spikes\s3_nav_ui"
New-Item -ItemType Directory -Force "$d\work" | Out-Null
$py = "C:\src\git\map_search\.venv\Scripts\python.exe"
$inner = "& '$py' '$d\agent.py' --hwnd $Hwnd --dir '$d\work' 2>&1 | Out-File '$d\work\agent_run.log' -Encoding utf8"
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
Start-Process -Verb RunAs powershell -ArgumentList "-NoProfile -EncodedCommand $encoded"
Write-Host "agent launch requested (UAC)"
