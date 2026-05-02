$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
$TmpDir = Join-Path $Root "tmp"

function Stop-KeibaProcessFromPid {
    param(
        [string]$PidFile,
        [string[]]$CommandHints
    )
    if (-not (Test-Path $PidFile)) {
        return
    }
    $raw = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    $procId = 0
    if (-not [int]::TryParse([string]$raw, [ref]$procId)) {
        return
    }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $procId" -ErrorAction SilentlyContinue
    if (-not $proc) {
        return
    }
    $cmd = [string]$proc.CommandLine
    $matches = $false
    foreach ($hint in $CommandHints) {
        if ($cmd -like "*$hint*") {
            $matches = $true
            break
        }
    }
    if ($matches) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped $procId ($PidFile)"
    }
}

function Stop-KeibaProcessesByPort {
    param(
        [int]$Port,
        [string[]]$CommandHints
    )
    $owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($owner in $owners) {
        if (-not $owner) {
            continue
        }
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $owner" -ErrorAction SilentlyContinue
        if (-not $proc) {
            continue
        }
        $cmd = [string]$proc.CommandLine
        foreach ($hint in $CommandHints) {
            if ($cmd -like "*$hint*") {
                Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
                Write-Host "Stopped $owner (port $Port)"
                break
            }
        }
    }
}

Write-Host "Stopping Keiba mobile PWA processes..." -ForegroundColor Cyan
Stop-KeibaProcessFromPid -PidFile (Join-Path $TmpDir "cloudflared_3000.pid") -CommandHints @("cloudflared", "--url http://127.0.0.1:3000")
Stop-KeibaProcessFromPid -PidFile (Join-Path $TmpDir "frontend_3000.pid") -CommandHints @("next-server", "next start", "\frontend")
Stop-KeibaProcessFromPid -PidFile (Join-Path $TmpDir "backend_8000.pid") -CommandHints @("uvicorn app.main:app", "\backend")
Stop-KeibaProcessesByPort -Port 3000 -CommandHints @("next\dist\bin\next", "next start")
Stop-KeibaProcessesByPort -Port 8000 -CommandHints @("uvicorn app.main:app")

@(
    "cloudflared_3000.pid",
    "frontend_3000.pid",
    "backend_8000.pid",
    "cloudflared_3000.url"
) | ForEach-Object {
    Remove-Item (Join-Path $TmpDir $_) -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopped. Public tunnel is closed if it was running." -ForegroundColor Green
