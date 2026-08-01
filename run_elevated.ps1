<#
.SYNOPSIS
mapscan을 관리자 권한으로 실행한다 (게임이 elevated인 환경에서 필요, ADR-002).

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\run_elevated.ps1 -Cmd "probe --hwnd 0x503dc"
#>
# 주의: 파라미터명에 Args를 쓰면 PowerShell 자동 변수 $Args와 충돌해 값이 비워진다.
param([string]$Cmd = "windows", [string]$LogDir = "$PSScriptRoot\output")

New-Item -ItemType Directory -Force $LogDir | Out-Null
$log = Join-Path $LogDir "mapscan_run.log"
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# mapscan은 UTF-8로 출력하므로 콘솔·로그 인코딩을 맞춰야 한글이 깨지지 않는다.
$inner = @"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
`$env:PYTHONPATH = '$PSScriptRoot\src'
& '$py' -m mapscan.cli $Cmd 2>&1 | Out-File -FilePath '$log' -Encoding utf8
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
Start-Process -Verb RunAs powershell -ArgumentList "-NoProfile -EncodedCommand $encoded" -Wait
Write-Host "--- log: $log ---"
Get-Content $log -Encoding utf8 -ErrorAction SilentlyContinue
