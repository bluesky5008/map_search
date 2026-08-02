# Launch the resident admin agent (reused from S-3/S-4) for spike S-5, one UAC prompt.
# Default HWND targets the test client; verify with: mapscan windows --crops <dir>
param([string]$Hwnd = "0x60042")
$repo = "C:\src\git\map_search"
$work = "$repo\spikes\s5_drag_pan\work"
if (Test-Path $work) {
    # The agent consumes cmd_*.txt from #1 at startup - never reuse a work dir.
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Rename-Item $work "work_$stamp"
}
New-Item -ItemType Directory -Force $work | Out-Null
$py = "$repo\.venv\Scripts\python.exe"
$agent = "$repo\spikes\s3_nav_ui\agent.py"
$inner = "& '$py' '$agent' --hwnd $Hwnd --dir '$work' --idle-quit 1800 2>&1 | Out-File '$work\agent_run.log' -Encoding utf8"
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
Start-Process -Verb RunAs powershell -ArgumentList "-NoProfile -EncodedCommand $encoded"
Write-Host "S-5 agent launch requested (UAC) hwnd=$Hwnd dir=$work"
