<#
.SYNOPSIS
실행 중인 "삼국지-전략판" 클라이언트의 창 크기를 조절한다 (기본: 화면의 1/4).

.DESCRIPTION
게임 창을 드래그로 조절하면 종횡비가 고정되지만, Win32 SetWindowPos로 직접 설정하면
그 제약을 우회할 수 있다. 넓고 낮은 창일수록 한 화면에 보이는 타일이 많아진다.

크기 결정
  -Width/-Height 를 주면 그 크기로, 주지 않으면 모니터 작업 영역의 1/4 크기로 설정한다.

위치 결정
  -Quadrant 를 주면      그 사분면에 배치한다.
  -All 이고 -Quadrant 가 없으면  TL→TR→BL→BR 순서로 나누어 배치한다.
  둘 다 없으면            크기만 지정한 경우 현재 위치를 유지하고, 아니면 TR에 배치한다.

게임이 관리자 권한으로 실행 중이면 UIPI 때문에 이 스크립트도 관리자 권한이 필요하다.
권한이 없으면 자동으로 UAC를 띄워 재실행한다.

변경 전 창 위치·크기는 저장되며 -Restore 로 되돌릴 수 있다.

.PARAMETER List
창 목록만 출력하고 종료한다.

.PARAMETER Index
선택 프롬프트 없이 N번 창을 사용한다.

.PARAMETER All
목록의 모든 클라이언트를 일괄 변경한다.

.PARAMETER Quadrant
배치할 사분면: TL(좌상), TR(우상), BL(좌하), BR(우하).

.PARAMETER Width
창 가로 크기(픽셀). -Height 와 함께 지정한다.

.PARAMETER Height
창 세로 크기(픽셀). -Width 와 함께 지정한다.

.PARAMETER Restore
저장해 둔 원래 위치·크기로 되돌린다.

.EXAMPLE
.\set-client-quadrant.ps1
   대화식으로 창을 선택해 1/4 크기(우상단)로 설정

.EXAMPLE
.\set-client-quadrant.ps1 -All
   모든 클라이언트를 1/4 크기로, 사분면에 나누어 배치

.EXAMPLE
.\set-client-quadrant.ps1 -Index 2 -Width 2560 -Height 696
   2번 창을 지정 크기로 (위치는 그대로)

.EXAMPLE
.\set-client-quadrant.ps1 -All -Width 2560 -Height 696 -Quadrant TR
   모든 클라이언트를 지정 크기로 우상단에 배치

.EXAMPLE
.\set-client-quadrant.ps1 -Restore
#>
[CmdletBinding()]
param(
    [switch]$List,
    [int]$Index = 0,
    [switch]$All,
    [ValidateSet('TL', 'TR', 'BL', 'BR')][string]$Quadrant = 'TR',
    [int]$Width = 0,
    [int]$Height = 0,
    [switch]$Restore,
    [string]$TitleMatch = '삼국지-전략판'
)

$ErrorActionPreference = 'Stop'
$stateFile = Join-Path $env:LOCALAPPDATA 'mapscan\saved_window_rects.json'
$quadrantExplicit = $PSBoundParameters.ContainsKey('Quadrant')
$sizeExplicit = ($Width -gt 0) -or ($Height -gt 0)

if ($sizeExplicit -and (($Width -le 0) -or ($Height -le 0))) {
    Write-Host "-Width 와 -Height 는 함께 지정해야 합니다."
    exit 1
}

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
        $aspect = 0
        if ($cr.B -gt 0) { $aspect = [math]::Round($cr.R / $cr.B, 2) }
        $result += [pscustomobject]@{
            Hwnd = $h; Pid = $pid_; Title = [WinCtl]::Title($h)
            X = $wr.L; Y = $wr.T; W = $wr.R - $wr.L; H = $wr.B - $wr.T
            ClientW = $cr.R; ClientH = $cr.B; Aspect = $aspect
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

function Read-SavedRects {
    if (-not (Test-Path $stateFile)) { return @() }
    try { $raw = Get-Content $stateFile -Encoding utf8 -Raw | ConvertFrom-Json } catch { return @() }
    # 중첩 배열이 섞여 있어도(구버전이 남긴 형태) 레코드만 골라 평탄화한다.
    $flat = @()
    $stack = [System.Collections.Stack]::new()
    $stack.Push($raw)
    while ($stack.Count -gt 0) {
        $node = $stack.Pop()
        if ($null -eq $node) { continue }
        if ($node -is [System.Collections.IEnumerable] -and $node -isnot [string]) {
            foreach ($child in $node) { $stack.Push($child) }
        } elseif ($null -ne $node.Pid) {
            $flat += [pscustomobject]@{
                Pid = [int]$node.Pid; X = [int]$node.X; Y = [int]$node.Y
                W = [int]$node.W; H = [int]$node.H
            }
        }
    }
    # 쉼표 연산자로 배열을 감싸지 않으면 항목이 하나일 때 스칼라로 풀려 += 가 실패한다.
    return , $flat
}

function Write-SavedRects($rects) {
    New-Item -ItemType Directory -Force (Split-Path $stateFile) | Out-Null
    $json = ConvertTo-Json @($rects) -Depth 3
    # ConvertTo-Json은 PowerShell 버전에 따라 단일 항목을 객체로 쓰기도 하므로 배열 형태로 고정한다.
    if (-not $json.TrimStart().StartsWith('[')) { $json = "[$json]" }
    $json | Out-File $stateFile -Encoding utf8
}

function Save-OriginalRect($client) {
    $saved = Read-SavedRects
    # 같은 창을 두 번 바꿔도 최초 배치가 남도록, 이미 저장된 항목은 덮어쓰지 않는다.
    if ($saved | Where-Object { $_.Pid -eq $client.Pid }) { return }
    $saved += [pscustomobject]@{ Pid = $client.Pid; X = $client.X; Y = $client.Y; W = $client.W; H = $client.H }
    Write-SavedRects $saved
}

function Set-ClientRect($client, [string]$quadrant) {
    $work = Get-WorkArea $client.Hwnd
    if ($sizeExplicit) {
        $w = $Width; $h = $Height
    } else {
        $w = [int]($work.W / 2); $h = [int]($work.H / 2)
    }

    $placeByQuadrant = $quadrantExplicit -or $All -or (-not $sizeExplicit)
    if ($placeByQuadrant) {
        $x = $work.X; $y = $work.Y
        if ($quadrant -eq 'TR' -or $quadrant -eq 'BR') { $x = $work.X + [int]($work.W / 2) }
        if ($quadrant -eq 'BL' -or $quadrant -eq 'BR') { $y = $work.Y + [int]($work.H / 2) }
        $where = "사분면 $quadrant"
    } else {
        $x = $client.X; $y = $client.Y
        $where = "현재 위치 유지"
    }

    Save-OriginalRect $client
    $ok = [WinCtl]::SetWindowPos($client.Hwnd, [IntPtr]::Zero, $x, $y, $w, $h,
                                 [WinCtl]::SWP_NOZORDER -bor [WinCtl]::SWP_NOACTIVATE)
    if (-not $ok) {
        Write-Host ("pid {0}: 변경 실패 (Win32 error {1})" -f $client.Pid,
                    [Runtime.InteropServices.Marshal]::GetLastWin32Error())
        return $false
    }
    Start-Sleep -Milliseconds 400
    $after = Get-Clients | Where-Object { $_.Pid -eq $client.Pid } | Select-Object -First 1
    Write-Host ("pid {0}: {1}x{2}(비 {3}) -> {4}x{5}(비 {6}) @({7},{8})  [{9}]" -f
                $client.Pid, $client.ClientW, $client.ClientH, $client.Aspect,
                $after.ClientW, $after.ClientH, $after.Aspect, $after.X, $after.Y, $where)
    return $true
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
    if ($Index -gt 0)       { $fwd += "-Index $Index" }
    if ($All)               { $fwd += "-All" }
    if ($quadrantExplicit)  { $fwd += "-Quadrant $Quadrant" }
    if ($sizeExplicit)      { $fwd += "-Width $Width -Height $Height" }
    if ($Restore)           { $fwd += "-Restore" }
    Start-Process -Verb RunAs powershell -ArgumentList (
        "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$PSCommandPath`" " + ($fwd -join ' '))
    exit 0
}

if ($Restore) {
    $saved = Read-SavedRects
    if ($saved.Count -eq 0) { Write-Host "저장된 창 배치가 없습니다: $stateFile"; exit 1 }
    foreach ($s in $saved) {
        $target = $clients | Where-Object { $_.Pid -eq $s.Pid } | Select-Object -First 1
        if (-not $target) { Write-Host "pid $($s.Pid) 창을 찾지 못해 건너뜁니다."; continue }
        $ok = [WinCtl]::SetWindowPos($target.Hwnd, [IntPtr]::Zero, $s.X, $s.Y, $s.W, $s.H,
                                     [WinCtl]::SWP_NOZORDER -bor [WinCtl]::SWP_NOACTIVATE)
        $verb = '복원 실패'
        if ($ok) { $verb = '복원' }
        Write-Host ("pid {0}: {1} -> ({2},{3}) {4}x{5}" -f $s.Pid, $verb, $s.X, $s.Y, $s.W, $s.H)
    }
    Remove-Item $stateFile -ErrorAction SilentlyContinue
    exit 0
}

Write-Host "실행 중인 클라이언트 $($clients.Count)개:"
Show-Clients $clients
Write-Host ""

if ($All) {
    $targets = $clients
} else {
    if ($Index -lt 1 -or $Index -gt $clients.Count) {
        if ($clients.Count -eq 1) {
            $Index = 1
        } else {
            $answer = Read-Host "크기를 바꿀 창 번호 (1-$($clients.Count), 전체는 A)"
            if ($answer -eq 'A' -or $answer -eq 'a') {
                $All = $true
            } elseif (-not [int]::TryParse($answer, [ref]$Index) -or
                      $Index -lt 1 -or $Index -gt $clients.Count) {
                Write-Host "잘못된 번호입니다."; exit 1
            }
        }
    }
    if ($All) { $targets = $clients } else { $targets = @($clients[$Index - 1]) }
}

if ($sizeExplicit) {
    Write-Host "지정 크기 ${Width}x${Height} 로 설정합니다."
} else {
    Write-Host "작업 영역의 1/4 크기로 설정합니다."
}

$order = @('TL', 'TR', 'BL', 'BR')
$changed = 0
for ($i = 0; $i -lt $targets.Count; $i++) {
    $q = $Quadrant
    # -All 이면서 사분면을 지정하지 않았으면 서로 겹치지 않도록 나누어 배치한다.
    if ($All -and -not $quadrantExplicit) { $q = $order[$i % $order.Count] }
    # 한 창에서 실패해도 나머지 창은 계속 처리한다.
    try {
        if (Set-ClientRect $targets[$i] $q) { $changed++ }
    } catch {
        Write-Host ("pid {0}: 오류 - {1}" -f $targets[$i].Pid, $_.Exception.Message)
    }
}

Write-Host ""
Write-Host "$changed/$($targets.Count)개 창을 변경했습니다."
Write-Host "원래 배치 저장 위치: $stateFile"
Write-Host "되돌리려면: .\set-client-quadrant.ps1 -Restore"
