# S-2c elevated agent v3 runner.
$d = "C:\src\git\map_search\spikes\s2_zoom_grid"
New-Item -ItemType Directory -Force "$d\work3" | Out-Null
$log = "$d\work3\run_log.txt"
"start $(Get-Date -Format o)" | Out-File $log -Encoding utf8
& "C:\src\git\map_search\.venv\Scripts\python.exe" "$d\agent3.py" --hwnd 328668 --dir "$d\work3" 2>&1 | Out-File $log -Append -Encoding utf8
"exit code $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
