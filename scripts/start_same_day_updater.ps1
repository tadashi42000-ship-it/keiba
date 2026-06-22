param(
    [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
    [string]$Venue = "tokyo",
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$BudgetYen = 3000,
    [int]$LookaheadMin = 30,
    [int]$PostStartMin = 1,
    [int]$FullRefreshEveryMin = 30,
    [string]$PythonExe = "python",
    [switch]$Once
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
$TmpDir = Join-Path $Root "tmp"
$PidFile = Join-Path $TmpDir "same_day_updater.pid"
$LogFile = Join-Path $TmpDir "same_day_updater.log"
$ErrFile = Join-Path $TmpDir "same_day_updater.err.log"
$StatusFile = Join-Path $TmpDir "same_day_updater.status.json"

New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null

function Stop-ExistingUpdater {
    if (-not (Test-Path $PidFile)) {
        return
    }
    $raw = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $procId = 0
    if (-not [int]::TryParse([string]$raw, [ref]$procId)) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return
    }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $procId" -ErrorAction SilentlyContinue
    if (-not $proc) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return
    }
    $cmd = [string]$proc.CommandLine
    if ($cmd -like "*run_same_day_updater.py*") {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 20
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 2
    }
    throw "Backend is not reachable at $Url. Last error: $lastError"
}

Write-Host "== Keiba same-day updater startup ==" -ForegroundColor Cyan
Write-Host "Date    : $Date"
Write-Host "Venue   : $Venue"
Write-Host "Base URL: $BaseUrl"
Write-Host "Full refresh every min: $FullRefreshEveryMin"

Wait-HttpOk -Url "$($BaseUrl.TrimEnd('/'))/health" -TimeoutSeconds 20 | Out-Null
Stop-ExistingUpdater

Remove-Item $ErrFile -Force -ErrorAction SilentlyContinue
if (-not (Test-Path $LogFile)) {
    New-Item -ItemType File -Path $LogFile -Force | Out-Null
}

$mode = if ($Once) { "--once" } else { "--loop" }
$command = @"
Set-Location '$Root'
`$env:PYTHONIOENCODING='utf-8'
& '$PythonExe' 'scripts/run_same_day_updater.py' --date '$Date' --venue '$Venue' --base-url '$BaseUrl' --budget-yen '$BudgetYen' --lookahead-min '$LookaheadMin' --post-start-min '$PostStartMin' --full-refresh-every-min '$FullRefreshEveryMin' --status-file '$StatusFile' $mode
if (`$null -ne `$LASTEXITCODE) { exit `$LASTEXITCODE }
exit 0
"@

$proc = Start-Process powershell -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $command) -PassThru -WindowStyle Minimized -RedirectStandardOutput $LogFile -RedirectStandardError $ErrFile
$proc.Id | Set-Content $PidFile

if ($Once) {
    $proc.WaitForExit()
    $proc.Refresh()
    $exitCode = $proc.ExitCode
    if ($null -eq $exitCode) {
        $exitCode = 0
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    if ($exitCode -ne 0) {
        Write-Host "Updater once run failed. ExitCode=$exitCode" -ForegroundColor Red
        if (Test-Path $ErrFile) { Get-Content $ErrFile -Tail 80 }
        if (Test-Path $LogFile) { Get-Content $LogFile -Tail 80 }
        exit $exitCode
    }
    Write-Host "Updater once run completed." -ForegroundColor Green
    Write-Host "Log   : $LogFile"
    Write-Host "Status: $StatusFile"
    exit 0
}

Start-Sleep -Seconds 2
if ($proc.HasExited) {
    Write-Host "Updater exited immediately." -ForegroundColor Red
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    if (Test-Path $ErrFile) { Get-Content $ErrFile -Tail 80 }
    if (Test-Path $LogFile) { Get-Content $LogFile -Tail 80 }
    exit 1
}

Write-Host "Updater started." -ForegroundColor Green
Write-Host "PID   : $($proc.Id)"
Write-Host "Log   : $LogFile"
Write-Host "Status: $StatusFile"
Write-Host ""
Write-Host "Stop command:" -ForegroundColor Yellow
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\stop_same_day_updater.ps1"
