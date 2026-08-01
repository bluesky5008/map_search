<#
.SYNOPSIS
실행 중인 "삼국지-전략판" 클라이언트를 골라 화면(작업 영역)의 1/4 크기로 배치한다.

.DESCRIPTION
게임 창을 드래그로 조절하면 종횡비가 고정되지만, Win32 SetWindowPos로 직접 설정하면
그 제약을 우회할 수 있다. 넓고 낮은 창(사분면)일수록 한 화면에 보이는 타일이 많아진다.

게임이 관리자 권한으로 실행 중이면 UIPI 때문에 이 스크립트도 관리자 권한이 필요하다.
권한이 없으면 자동으로 UAC를 띄워 재실행한다.

변경 전 창 위치·크기는 저장되며 -Restore 로 되돌릴 수 있다.

.PARAMETER List
창 목록만 출력하고 종료한다.

.PARAMETER Index
선택 프롬프트 없이 N번 창을 사용한다.

.PARAMETER Quadrant
배치할 사분면: TL(좌상), TR(우상), BL(좌하), BR(우하). 기본값 TR.

.PARAMETER Restore
저장해 둔 원래 위치·크기로 되돌린다.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\set-client-quadrant.ps1
   대화식으로 창과 사분면을 선택

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\set-client-quadrant.ps1 -Index 2 -Quadrant TR

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\set-client-quadrant.ps1 -Restore
#>
[CmdletBinding()]
param(
    [switch]$List,
    [int]$Index = 0,
    [ValidateSet('TL', 'TR', 'BL', 'BR')][string]$Quadrant = 'TR',
    [switch]$Restore,
    [string]$TitleMatch = '삼국지-전략판'
)

$ErrorActionPreference = 'Stop'
$stateFile = Join-Path $env:LOCALAPPDATA 'mapscan\saved_window_rects.json'

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public class WinCtl {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    [StructLayout(LayoutKind.Sequential)] public struct MONITORINFO {
        public int cbSize; public RECT rcMonitor; public RECT rcWork; public uint dwFlags;
    }
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern int GetWindowTextLengthW(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern IntPtr MonitorFromWindow(IntPtr h, uint flags);
    [DllImport("user32.dll")] public static extern bool GetMonitorInfoW(IntPtr hMon, ref MONITORINFO mi);
    [DllImport("user32.dll", SetLastError = true)] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int w, int ht, uint flags);
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr ctx);

    public const uint SWP_NOZORDER = 0x0004, SWP_NOACTIVATE = 0x0010;
    public const uint MONITOR_DEFAULTTONEAREST = 2;

    public static void AwareDpi() {
        try { SetProcessDpiAwarenessContext((IntPtr)(-4)); } catch { }
    }

    public static List<IntPtr> Find(string match) {
        var list = new List<IntPtr>();
        EnumWindows((h, p) => {
            if (!IsWindowVisible(h) || IsIconic(h)) return true;
            int n = GetWindowTextLengthW(h);
            if (n == 0) return true;
            var sb = new StringBuilder(n + 1);
            GetWindowTextW(h, sb, n + 1);
            if (sb.ToString().Contains(match)) list.Add(h);
            return true;
        }, IntPtr.Zero);
        return list;
    }

    public static string Title(IntPtr h) {
        int n = GetWindowTextLengthW(h);
        var sb = new StringBuilder(n + 1);
        GetWindowTextW(h, sb, n + 1);
        return sb.ToString();
    }
}
'@

[WinCtl]::AwareDpi()

function Get-Clients {
    $result = @()
    foreach ($h in [WinCtl]::Find($TitleMatch)) {
        $wr = New-Object WinCtl+RECT; [void][WinCtl]::GetWindowRect($h, [ref]$wr)
        $cr = New-Object WinCtl+RECT; [void][WinCtl]::GetClientRect($h, [ref]$cr)
        $pid_ = 0; [void][WinCtl]::GetWindowThreadProcessId($h, [ref]$pid_)
        $result += [pscustomobject]@{
            Hwnd = $h; Pid = $pid_; Title = [WinCtl]::Title($h)
            X = $wr.L; Y = $wr.T; W = $wr.R - $wr.L; H = $wr.B - $wr.T
            ClientW = $cr.R; ClientH = $cr.B
            Aspect = if ($cr.B -gt 0) { [math]::Round($cr.R / $cr.B, 2) } else { 0 }
        }
    }
    return $result
}

function Get-WorkArea([IntPtr]$hwnd) {
    $mon = [WinCtl]::MonitorFromWindow($hwnd, [WinCtl]::MONITOR_DEFAULTTONEAREST)
    $mi = New-Object WinCtl+MONITORINFO
    $mi.cbSize = [Runtime.InteropServices.Marshal]::SizeOf($mi)
    [void][WinCtl]::GetMonitorInfoW($mon, [ref]$mi)
    return [pscustomobject]@{
        X = $mi.rcWork.L; Y = $mi.rcWork.T
        W = $mi.rcWork.R - $mi.rcWork.L; H = $mi.rcWork.B - $mi.rcWork.T
    }
}

function Show-Clients($clients) {
    for ($i = 0; $i -lt $clients.Count; $i++) {
        $c = $clients[$i]
        "  [{0}] pid={1,-6} 위치=({2},{3}) 창={4}x{5} 클라이언트={6}x{7} 종횡비={8}" -f `
            ($i + 1), $c.Pid, $c.X, $c.Y, $c.W, $c.H, $c.ClientW, $c.ClientH, $c.Aspect | Write-Host
    }
}

$clients = @(Get-Clients)
if ($clients.Count -eq 0) { Write-Host "'$TitleMatch' 창을 찾을 수 없습니다."; exit 1 }

if ($List) {
    Write-Host "실행 중인 클라이언트 $($clients.Count)개:"
    Show-Clients $clients
    exit 0
}

# 게임이 관리자 권한이면 이 스크립트도 관리자 권한이어야 창 조작이 전달된다(UIPI).
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "관리자 권한이 필요합니다. UAC 승인 창에서 '예'를 눌러 주세요..."
    $fwd = @()
    if ($Index -gt 0)  { $fwd += "-Index $Index" }
    if ($Restore)      { $fwd += "-Restore" }
    $fwd += "-Quadrant $Quadrant"
    Start-Process -Verb RunAs powershell -ArgumentList (
        "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$PSCommandPath`" " + ($fwd -join ' '))
    exit 0
}

if ($Restore) {
    if (-not (Test-Path $stateFile)) { Write-Host "저장된 창 배치가 없습니다: $stateFile"; exit 1 }
    $saved = Get-Content $stateFile -Encoding utf8 -Raw | ConvertFrom-Json
    foreach ($s in @($saved)) {
        $target = $clients | Where-Object { $_.Pid -eq $s.Pid } | Select-Object -First 1
        if (-not $target) { Write-Host "pid $($s.Pid) 창을 찾지 못해 건너뜁니다."; continue }
        $ok = [WinCtl]::SetWindowPos($target.Hwnd, [IntPtr]::Zero, $s.X, $s.Y, $s.W, $s.H,
                                     [WinCtl]::SWP_NOZORDER -bor [WinCtl]::SWP_NOACTIVATE)
        Write-Host ("pid {0}: {1} -> ({2},{3}) {4}x{5}" -f $s.Pid,
                    $(if ($ok) { '복원' } else { '복원 실패' }), $s.X, $s.Y, $s.W, $s.H)
    }
    exit 0
}

Write-Host "실행 중인 클라이언트 $($clients.Count)개:"
Show-Clients $clients

if ($Index -lt 1 -or $Index -gt $clients.Count) {
    if ($clients.Count -eq 1) {
        $Index = 1
    } else {
        $answer = Read-Host "크기를 바꿀 창 번호 (1-$($clients.Count))"
        if (-not [int]::TryParse($answer, [ref]$Index) -or $Index -lt 1 -or $Index -gt $clients.Count) {
            Write-Host "잘못된 번호입니다."; exit 1
        }
    }
}
$client = $clients[$Index - 1]

$work = Get-WorkArea $client.Hwnd
$halfW = [int]($work.W / 2)
$halfH = [int]($work.H / 2)
$x = if ($Quadrant -in 'TR', 'BR') { $work.X + $halfW } else { $work.X }
$y = if ($Quadrant -in 'BL', 'BR') { $work.Y + $halfH } else { $work.Y }

# 원래 배치를 저장해 두어야 -Restore 로 되돌릴 수 있다.
$saved = @()
if (Test-Path $stateFile) { $saved = @(Get-Content $stateFile -Encoding utf8 -Raw | ConvertFrom-Json) }
$saved = @($saved | Where-Object { $_.Pid -ne $client.Pid })
$saved += [pscustomobject]@{ Pid = $client.Pid; X = $client.X; Y = $client.Y; W = $client.W; H = $client.H }
New-Item -ItemType Directory -Force (Split-Path $stateFile) | Out-Null
$saved | ConvertTo-Json -Depth 3 | Out-File $stateFile -Encoding utf8

$ok = [WinCtl]::SetWindowPos($client.Hwnd, [IntPtr]::Zero, $x, $y, $halfW, $halfH,
                             [WinCtl]::SWP_NOZORDER -bor [WinCtl]::SWP_NOACTIVATE)
if (-not $ok) {
    Write-Host "창 크기 변경 실패 (Win32 error $([Runtime.InteropServices.Marshal]::GetLastWin32Error()))"
    exit 1
}

Start-Sleep -Milliseconds 500
$after = Get-Clients | Where-Object { $_.Pid -eq $client.Pid } | Select-Object -First 1
Write-Host ""
Write-Host ("작업 영역: ({0},{1}) {2}x{3} / 사분면 {4}" -f $work.X, $work.Y, $work.W, $work.H, $Quadrant)
Write-Host ("변경 전: 창 {0}x{1}, 클라이언트 {2}x{3}, 종횡비 {4}" -f
            $client.W, $client.H, $client.ClientW, $client.ClientH, $client.Aspect)
Write-Host ("변경 후: 창 {0}x{1}, 클라이언트 {2}x{3}, 종횡비 {4}" -f
            $after.W, $after.H, $after.ClientW, $after.ClientH, $after.Aspect)
Write-Host ""
Write-Host "원래 배치 저장 위치: $stateFile"
Write-Host "되돌리려면: .\set-client-quadrant.ps1 -Restore"
