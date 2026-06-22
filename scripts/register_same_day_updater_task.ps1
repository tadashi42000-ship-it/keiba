param(
    [string]$Date,
    [string]$Venue = "tokyo",
    [string]$TaskName = "Keiba Same-Day Updater",
    [string]$StartTime = "09:00",
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$BudgetYen = 3000,
    [int]$LookaheadMin = 30,
    [int]$PostStartMin = 1,
    [int]$FullRefreshEveryMin = 30
)

$ErrorActionPreference = "Stop"

if (-not $Date) {
    throw "Date is required, e.g. -Date 2026-06-14"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
$StartScript = Join-Path $Root "scripts\start_same_day_updater.ps1"

$argument = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$StartScript`"",
    "-Date", "`"$Date`"",
    "-Venue", "`"$Venue`"",
    "-BaseUrl", "`"$BaseUrl`"",
    "-BudgetYen", "$BudgetYen",
    "-LookaheadMin", "$LookaheadMin",
    "-PostStartMin", "$PostStartMin",
    "-FullRefreshEveryMin", "$FullRefreshEveryMin"
) -join " "

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Once -At ([datetime]::ParseExact("$Date $StartTime", "yyyy-MM-dd HH:mm", $null))
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 12)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Registered scheduled task." -ForegroundColor Green
Write-Host "Task : $TaskName"
Write-Host "Run  : $Date $StartTime"
Write-Host "Venue: $Venue"
Write-Host "Full refresh every min: $FullRefreshEveryMin"
Write-Host ""
Write-Host "Check command:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask -TaskName `"$TaskName`""
Write-Host "Manual start:" -ForegroundColor Cyan
Write-Host "  Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host "Remove command:" -ForegroundColor Cyan
Write-Host "  Unregister-ScheduledTask -TaskName `"$TaskName`" -Confirm:`$false"
