# S-2b elevated agent v2 runner.
$d = "C:\src\git\map_search\spikes\s2_zoom_grid"
New-Item -ItemType Directory -Force "$d\work2" | Out-Null
$log = "$d\work2\run_log.txt"
"start $(Get-Date -Format o)" | Out-File $log -Encoding utf8
& "C:\src\git\map_search\.venv\Scripts\python.exe" "$d\agent2.py" --hwnd 328668 --dir "$d\work2" 2>&1 | Out-File $log -Append -Encoding utf8
"exit code $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
