param([int]$X, [int]$Y, [int]$W, [int]$H, [int]$Secs = 10, [string]$Proof = "")

# Topmost solid overlay to occlude the game window during S-1 tests.
Add-Type -Namespace W -Name U -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);'
[W.U]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$f = New-Object System.Windows.Forms.Form
$f.FormBorderStyle = 'None'
$f.TopMost = $true
$f.ShowInTaskbar = $false
$f.BackColor = [System.Drawing.Color]::FromArgb(30, 30, 30)  # 어두운 회색
$f.StartPosition = 'Manual'
$f.Bounds = New-Object System.Drawing.Rectangle($X, $Y, $W, $H)
$f.Show()

$end = (Get-Date).AddSeconds($Secs)
$shot = $false
while ((Get-Date) -lt $end) {
    [System.Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds 50
    # After 1s, save proof that the screen region really shows the overlay.
    if (-not $shot -and $Proof -ne "" -and ((Get-Date) -gt $end.AddSeconds(1 - $Secs))) {
        $bmp = New-Object System.Drawing.Bitmap($W, $H)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($X, $Y, 0, 0, $bmp.Size)
        $g.Dispose()
        $bmp.Save($Proof, [System.Drawing.Imaging.ImageFormat]::Png)
        $bmp.Dispose()
        $shot = $true
    }
}
$f.Close()
