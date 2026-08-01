# S-2 elevated agent runner (logs output).
$d = "C:\src\git\map_search\spikes\s2_zoom_grid"
New-Item -ItemType Directory -Force "$d\work" | Out-Null
$log = "$d\work\run_log.txt"
"start $(Get-Date -Format o)" | Out-File $log -Encoding utf8
& "C:\src\git\map_search\.venv\Scripts\python.exe" "$d\agent.py" --hwnd 328668 --dir "$d\work" 2>&1 | Out-File $log -Append -Encoding utf8
"exit code $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
