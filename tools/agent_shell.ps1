# 상주 관리자 실행기 (T14 세션용) — UAC 1회로 명령 파일을 순번대로 실행한다.
# 프로토콜: cmd_NNNN.txt(PowerShell 스크립트) -> res_NNNN.log(출력) + done_NNNN.txt(종료코드)
param([string]$Dir, [double]$IdleQuitMin = 300)

Set-Location 'C:\src\git\map_search'
$env:PYTHONPATH = 'C:\src\git\map_search\src'
$env:PYTHONIOENCODING = 'utf-8'
$elev = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
"start $(Get-Date -Format o) pid=$PID elevated=$elev" | Out-File "$Dir\shell_status.txt" -Encoding utf8 -Append

$seq = 1
$last = Get-Date
while (((Get-Date) - $last).TotalMinutes -lt $IdleQuitMin) {
    $cf = Join-Path $Dir ("cmd_{0:D4}.txt" -f $seq)
    if (-not (Test-Path $cf)) { Start-Sleep -Milliseconds 300; continue }
    Start-Sleep -Milliseconds 200   # 쓰기 완료 대기
    $last = Get-Date
    $res = Join-Path $Dir ("res_{0:D4}.log" -f $seq)
    $done = Join-Path $Dir ("done_{0:D4}.txt" -f $seq)
    $body = Get-Content $cf -Raw -Encoding utf8
    "run #$seq $(Get-Date -Format o)" | Out-File "$Dir\shell_status.txt" -Encoding utf8 -Append
    if ($body.Trim() -eq 'quit') { 'quit' | Out-File $done -Encoding utf8; break }
    $tmp = Join-Path $Dir ("run_{0:D4}.ps1" -f $seq)
    $body | Out-File $tmp -Encoding utf8
    # 자식 powershell로 실행해 스트림을 통째로 로그에 담는다(관리자 권한 상속)
    & powershell -NoProfile -ExecutionPolicy Bypass -File $tmp > $res 2>&1
    "$LASTEXITCODE" | Out-File $done -Encoding utf8
    $seq += 1
}
"exit $(Get-Date -Format o)" | Out-File "$Dir\shell_status.txt" -Encoding utf8 -Append
