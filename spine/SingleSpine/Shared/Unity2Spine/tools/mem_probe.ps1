# Measure the PEAK memory of a whole process tree (on Windows the real worker
# is usually a CHILD process; watching only the launcher gives fake numbers).
#
# Usage:
#   powershell -NoProfile -File tools\mem_probe.ps1 -Exe <exe> ^
#       -ArgList "arg1|arg2|arg3" -LimitMB 8000
#
# Kill the tree when the peak exceeds -LimitMB so one heavy job can never take
# the whole machine down again (2026-09-16 incident).
param(
  [Parameter(Mandatory=$true)][string]$Exe,
  [Parameter(Mandatory=$true)][string]$ArgList,
  [int]$LimitMB = 8000,
  [int]$TimeoutSec = 2400,
  [string]$WorkDir = "D:\VB\Unity2Spine"
)
$argsArray = $ArgList.Split("|")
$p = Start-Process -FilePath $Exe -ArgumentList $argsArray -PassThru -WindowStyle Hidden -WorkingDirectory $WorkDir
$peak = 0
$killed = $false
$sw = [Diagnostics.Stopwatch]::StartNew()
while (-not $p.HasExited) {
    $sum = $p.WorkingSet64
    foreach ($k in (Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)" -ErrorAction SilentlyContinue)) {
        $kp = Get-Process -Id $k.ProcessId -ErrorAction SilentlyContinue
        if ($kp) { $sum += $kp.WorkingSet64 }
    }
    if ($sum -gt $peak) { $peak = $sum }
    if (($peak / 1MB) -gt $LimitMB) {
        $killed = $true
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        break
    }
    if ($sw.Elapsed.TotalSeconds -gt $TimeoutSec) { break }
    Start-Sleep -Milliseconds 400
    $p.Refresh()
}
$sw.Stop()
$name = [IO.Path]::GetFileName($Exe)
"{0} | peak={1:N0} MB | {2:N1} s | killed={3} | exit={4}" -f $name, ($peak / 1MB), $sw.Elapsed.TotalSeconds, $killed, $p.ExitCode
