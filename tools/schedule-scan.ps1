<#
.SYNOPSIS
전체 스캔 예약 운용 — Windows 작업 스케줄러 등록/해제/상태 (DCR-005 2계정 병렬).

.DESCRIPTION
매일 -StartTime에 파트(계정)별 청크 스캔을 자동 시작하고, 스캔은
`--until <StopTime>`으로 행 경계에서 체크포인트를 저장한 뒤 스스로 정지한다
(paused). 다음 날 실행이 체크포인트에서 재개하므로 며칠에 걸친 완주가
무인으로 굴러간다. 청크 완주(체크포인트가 end-row 도달) 후의 일일 실행은
0행 처리로 무해하며, 태스크 해제는 수동이다(-Unregister — 사용자 결정).

태스크는 반드시 **로그온한 사용자 세션에서 실행**된다(LogonType Interactive —
PostMessage·WGC가 세션을 요구한다). 일반 권한으로 등록·실행하며 UAC가 필요
없다(MuMu는 비관리자). 로그아웃·시스템 절전·MuMu 창 최소화는 금지 전제
그대로이고, 전원 설정(절전 해제)은 스케줄러가 관리하지 않으므로 직접 확인한다.

운용 파라미터(파트 구성·맵 크기)는 스크립트 상단 $Parts 표에서 수정한다.

.PARAMETER Register
파트별 태스크(MapScan-part1..N)를 등록한다. 이미 있으면 갱신한다.

.PARAMETER Unregister
등록된 태스크를 해제한다.

.PARAMETER Status
태스크 상태·다음/마지막 실행·파트별 체크포인트(완주 여부)를 출력한다(기본 동작).

.PARAMETER Run
태스크가 호출하는 실행 래퍼. 첫 실행(--new --start-row)과 재개를 파트 DB의
재개 가능 스캔 유무로 판별해 스캔을 실행하고 output\schedule_part<N>.log에
추가 기록한다. 수동 점검에도 쓸 수 있다.

.PARAMETER Part
-Run 대상 파트 번호(1부터).

.PARAMETER StartTime
매일 자동 시작 시각(HH:mm). 기본 22:00. -Register에서 사용.

.PARAMETER StopTime
자기 정지 시각(HH:mm) — scan --until로 전달된다. 기본 08:00.

.EXAMPLE
.\schedule-scan.ps1 -Register
   확정값(22:00 시작, 08:00 정지)으로 2개 태스크 등록

.EXAMPLE
.\schedule-scan.ps1 -Register -StartTime 21:30 -StopTime 07:00

.EXAMPLE
.\schedule-scan.ps1 -Status

.EXAMPLE
.\schedule-scan.ps1 -Run -Part 1 -StopTime 08:00
   1번 파트를 지금 수동 실행(등록 없이 래퍼 점검)

.EXAMPLE
.\schedule-scan.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [switch]$Register,
    [switch]$Unregister,
    [switch]$Status,
    [switch]$Run,
    [int]$Part,
    [string]$StartTime = '22:00',
    [string]$StopTime = '08:00'
)

# ---- 운용 파라미터 (확정값 — 변경은 여기서) --------------------------------
$Parts = @(
    @{ Instance = '용스'; Db = 'output\part1.db'; StartRow = 0;   EndRow = 272 },
    @{ Instance = '실버'; Db = 'output\part2.db'; StartRow = 272; EndRow = 544 }
)
$MapSize = @(1619, 1619)
$TaskPrefix = 'MapScan-part'
# ---------------------------------------------------------------------------

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'

function Get-TaskName([int]$i) { return "$TaskPrefix$i" }

function Get-WindowLimit([string]$Start, [string]$Stop) {
    # 시작→정지 창 + 1시간을 태스크 실행 시간 상한으로 둔다.
    # 정지는 --until이 담당하고, 이 상한은 프로세스가 매달렸을 때의 안전망이다.
    $s = [datetime]::ParseExact($Start, 'HH:mm', $null)
    $e = [datetime]::ParseExact($Stop, 'HH:mm', $null)
    $span = $e - $s
    if ($span -le [TimeSpan]::Zero) { $span = $span + (New-TimeSpan -Days 1) }
    return $span + (New-TimeSpan -Hours 1)
}

function Invoke-PartQuery([string]$Db, [string]$Code) {
    # 파트 DB에 대해 mapscan.store 로직 그대로 질의한다(별도 SQL 중복 없음)
    $out = & $Python -c $Code $Db 2>&1 | ForEach-Object { "$_" } | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { return $null }
    return $out
}

# 재개 가능 스캔(running/paused)이 있으면 'resume', 없으면 'new' — CLI의
# latest_resumable_scan과 같은 판별이라 첫 실행 실패(창 미발견 등) 후에도
# 다음 날 엉뚱한 행(0행)에서 새 스캔을 시작하지 않는다.
$FormQuery = "import sys; from mapscan.store import DataStore; s = DataStore(sys.argv[1]); print('resume' if s.latest_resumable_scan('A2') else 'new'); s.close()"
$CheckpointQuery = "import sys; from mapscan.store import DataStore; s = DataStore(sys.argv[1]); r = s.latest_resumable_scan('A2'); print(-1 if r is None else r['checkpoint']); s.close()"

function Invoke-Run {
    if ($Part -lt 1 -or $Part -gt $Parts.Count) {
        throw "-Run에는 -Part 1..$($Parts.Count)가 필요합니다"
    }
    $p = $Parts[$Part - 1]
    Set-Location $RepoRoot
    if (-not (Test-Path 'output')) { New-Item -ItemType Directory 'output' | Out-Null }
    $log = "output\schedule_part$Part.log"
    try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

    $form = Invoke-PartQuery $p.Db $FormQuery
    if ($null -eq $form -or ($form -ne 'new' -and $form -ne 'resume')) {
        Add-Content -Encoding UTF8 $log ("=== {0} DB 상태 판별 실패: {1} ===" -f
            (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $form)
        exit 1
    }
    $scanArgs = @('scan', '--mumu', $p.Instance, '--db', $p.Db,
                  '--map-size', $MapSize[0], $MapSize[1],
                  '--until', $StopTime, '--end-row', $p.EndRow)
    if ($form -eq 'new') {
        $scanArgs += @('--new', '--start-row', $p.StartRow)
    }
    Add-Content -Encoding UTF8 $log ("=== {0} 시작 (파트 {1} '{2}', {3}, 정지 {4}) ===" -f
        (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Part, $p.Instance, $form, $StopTime)
    # 행 단위로 열고 닫는다 — 스트리밍 Add-Content는 파일을 독점 점유해
    # 실행 중(최대 10h+) 로그 열람·상태 확인이 막힌다(실측)
    & $Python -u -m mapscan.cli @scanArgs 2>&1 |
        ForEach-Object { Add-Content -Encoding UTF8 $log "$_" }
    $code = $LASTEXITCODE
    Add-Content -Encoding UTF8 $log ("=== {0} 종료 (exit {1}) ===" -f
        (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $code)
    exit $code
}

function Invoke-Register {
    if (-not (Test-Path $Python)) { throw ".venv 파이썬이 없습니다: $Python" }
    $limit = Get-WindowLimit $StartTime $StopTime
    # 로그온 세션 필수(Interactive) + 일반 권한(Limited) — SYSTEM·세션 없는 실행 금지
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive -RunLevel Limited
    $trigger = New-ScheduledTaskTrigger -Daily -At $StartTime
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit $limit
    $script = Join-Path $PSScriptRoot 'schedule-scan.ps1'
    for ($i = 1; $i -le $Parts.Count; $i++) {
        $p = $Parts[$i - 1]
        $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden " +
               "-File `"$script`" -Run -Part $i -StopTime $StopTime"
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
            -Argument $arg -WorkingDirectory $RepoRoot
        Register-ScheduledTask -TaskName (Get-TaskName $i) -Action $action `
            -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
        Write-Host ("등록: {0} — 매일 {1} 시작, {2} 정지 ('{3}' 행 {4}~{5}, {6})" -f
            (Get-TaskName $i), $StartTime, $StopTime, $p.Instance,
            $p.StartRow, $p.EndRow, $p.Db)
    }
    Write-Host ""
    Write-Host "전제 확인(스케줄러가 관리하지 않음):"
    Write-Host "  - 사용자 로그온 세션 유지(로그아웃 금지 — 잠금·RDP 연결 해제·모니터 off는 무해)"
    Write-Host "  - 전원 옵션에서 시스템 절전 해제"
    Write-Host "  - MuMu 인스턴스($(($Parts | ForEach-Object { $_.Instance }) -join '·')) 실행 + 게임 접속 상태, 창 최소화 금지"
    Write-Host "  - 완주 후 해제는 수동: .\schedule-scan.ps1 -Unregister"
}

function Invoke-Unregister {
    for ($i = 1; $i -le $Parts.Count; $i++) {
        $name = Get-TaskName $i
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($null -ne $task) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "해제: $name"
        } else {
            Write-Host "없음: $name"
        }
    }
}

function Show-Status {
    $allDone = $true
    for ($i = 1; $i -le $Parts.Count; $i++) {
        $p = $Parts[$i - 1]
        $name = Get-TaskName $i
        Write-Host ("파트 {0} — '{1}' 행 {2}~{3} ({4})" -f
            $i, $p.Instance, $p.StartRow, $p.EndRow, $p.Db)
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            Write-Host "  태스크: 미등록"
        } else {
            $info = Get-ScheduledTaskInfo -TaskName $name
            $last = '-'
            if ($info.LastRunTime -and $info.LastRunTime.Year -gt 2000) {
                $last = '{0:yyyy-MM-dd HH:mm} (결과 {1})' -f $info.LastRunTime, $info.LastTaskResult
            }
            Write-Host ("  태스크: {0} {1}, 다음 실행 {2:yyyy-MM-dd HH:mm}, 마지막 {3}" -f
                $name, $task.State, $info.NextRunTime, $last)
        }
        $dbPath = Join-Path $RepoRoot $p.Db
        if (-not (Test-Path $dbPath)) {
            Write-Host "  진행: 미시작 (DB 없음)"
            $allDone = $false
        } else {
            $cp = Invoke-PartQuery $dbPath $CheckpointQuery
            if ($null -eq $cp -or $cp -eq '-1') {
                Write-Host "  진행: 스캔 기록 없음"
                $allDone = $false
            } elseif ([int]$cp -ge $p.EndRow) {
                Write-Host ("  진행: 체크포인트 {0}/{1}행 — 완주" -f $cp, $p.EndRow)
            } else {
                Write-Host ("  진행: 체크포인트 {0}/{1}행" -f $cp, $p.EndRow)
                $allDone = $false
            }
        }
        $logPath = Join-Path $RepoRoot "output\schedule_part$i.log"
        if (Test-Path $logPath) {
            Write-Host ("  로그: {0} (마지막 기록 {1:yyyy-MM-dd HH:mm})" -f
                "output\schedule_part$i.log", (Get-Item $logPath).LastWriteTime)
        }
    }
    if ($allDone) {
        Write-Host ""
        Write-Host "전 파트 완주 — 태스크 해제(-Unregister) 후 merge → 보충·CSV 절차로 진행하세요(README 참조)"
    }
}

$chosen = @($Register, $Unregister, $Run, $Status) | Where-Object { $_ }
if ($chosen.Count -gt 1) {
    throw "-Register / -Unregister / -Status / -Run 중 하나만 지정하세요"
}
if ($Run) { Invoke-Run }
elseif ($Register) { Invoke-Register }
elseif ($Unregister) { Invoke-Unregister }
else { Show-Status }
