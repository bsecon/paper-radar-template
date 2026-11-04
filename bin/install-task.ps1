# Windows counterpart of install-launchd.sh: two Task Scheduler entries that run bin/daily.sh in
# Git Bash, daily at HOUR:MINUTE and a retry at RETRY_HOUR:00 that only does work if pending.
# From Git Bash or PowerShell, in the repository folder:
#   powershell -ExecutionPolicy Bypass -File bin/install-task.ps1 7 30
param([int]$Hour = 7, [int]$Minute = 30, [int]$RetryHour = 13)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
# Git Bash: next to git.exe on PATH (system or per-user install), then the usual folders.
# Never C:\Windows\System32\bash.exe, which is WSL.
$candidates = @()
$git = Get-Command git.exe -ErrorAction SilentlyContinue
if ($git) { $candidates += (Join-Path (Split-Path (Split-Path $git.Source)) "bin\bash.exe") }
$candidates += @(
    (Join-Path $env:LOCALAPPDATA "Programs\Git\bin\bash.exe"),
    (Join-Path $env:ProgramFiles "Git\bin\bash.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Git\bin\bash.exe")
)
$bash = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $bash) { throw "Git Bash not found (looked in: $($candidates -join '; ')). Install Git for Windows: winget install Git.Git" }
$script = ($root -replace '\\', '/') + "/bin/daily.sh"
$logDir = Join-Path $env:USERPROFILE ".local\state\paper-radar"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = ($logDir -replace '\\', '/') + "/daily.log"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)
function Install-RadarTask([string]$name, [string]$extra, [string]$at) {
    $cmd = "'$script' $extra >> '$log' 2>&1"
    $action = New-ScheduledTaskAction -Execute $bash -Argument ('-lc "' + $cmd + '"') -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Daily -At $at
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
}
Install-RadarTask "paper-radar" "" ("{0:D2}:{1:D2}" -f $Hour, $Minute)
Install-RadarTask "paper-radar retry" "--if-pending" ("{0:D2}:00" -f $RetryHour)
Write-Host ("installed: daily at {0:D2}:{1:D2}, retry at {2:D2}:00 if work is pending; log: {3}" -f $Hour, $Minute, $RetryHour, $log)
Write-Host "run now:   Start-ScheduledTask paper-radar     (or bin/daily.sh in Git Bash)"
Write-Host "remove:    Unregister-ScheduledTask paper-radar; Unregister-ScheduledTask 'paper-radar retry'"
