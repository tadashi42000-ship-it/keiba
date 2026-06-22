$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
$TmpDir = Join-Path $Root "tmp"
$PidFile = Join-Path $TmpDir "same_day_updater.pid"
$StatusFile = Join-Path $TmpDir "same_day_updater.status.json"

function Stop-FromPidFile {
    if (-not (Test-Path $PidFile)) {
        return $false
    }
    $raw = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $procId = 0
    if (-not [int]::TryParse([string]$raw, [ref]$procId)) {
        return $false
    }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $procId" -ErrorAction SilentlyContinue
    if (-not $proc) {
        return $false
    }
    $cmd = [string]$proc.CommandLine
    if ($cmd -notlike "*run_same_day_updater.py*") {
        return $false
    }
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped updater process $procId"
    return $true
}

Write-Host "Stopping Keiba same-day updater..." -ForegroundColor Cyan
$stopped = Stop-FromPidFile

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { [string]$_.CommandLine -like "*run_same_day_updater.py*" } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped updater process $($_.ProcessId)"
        Set-Variable -Name stopped -Value $true -Scope Script
    }

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue

if (Test-Path $StatusFile) {
    $status = @{
        status = "stopped"
        updated_at = (Get-Date).ToString("s")
    } | ConvertTo-Json -Depth 3
    Set-Content -Encoding UTF8 -Path $StatusFile -Value $status
}

if ($stopped) {
    Write-Host "Stopped." -ForegroundColor Green
} else {
    Write-Host "No updater process was running." -ForegroundColor Yellow
}
