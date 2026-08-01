# S-1b elevated runner: logs all output so failures are visible.
$d = "C:\src\git\map_search\spikes\s1_background_io"
$log = "$d\evidence\elev_log.txt"
"start $(Get-Date -Format o) elevated=$([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole('Administrators'))" | Out-File $log -Encoding utf8
& "C:\src\git\map_search\.venv\Scripts\python.exe" "$d\s1b_elevated.py" --hwnd 328668 --dir "$d\evidence" 2>&1 | Out-File $log -Append -Encoding utf8
"exit code $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
