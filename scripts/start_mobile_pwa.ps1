param(
    [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
    [string]$Venue = "東京",
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$SkipBuild,
    [switch]$NoTunnel
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$TmpDir = Join-Path $Root "tmp"
$CloudflaredPath = Join-Path $TmpDir "cloudflared.exe"

New-Item -ItemType Directory -Force -Path $TmpDir | Out-Null

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
                break
            }
        }
    }
}

function Get-ListeningOwner {
    param([int]$Port)
    return (
        Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique |
            Select-Object -First 1
    )
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 45
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 8
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for $Url. Last error: $lastError"
}

function Get-TunnelUrlFromLog {
    param(
        [string]$LogPath,
        [int]$TimeoutSeconds = 60
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $LogPath) {
            $text = Get-Content $LogPath -Raw -ErrorAction SilentlyContinue
            $match = [regex]::Match($text, "https://[a-zA-Z0-9-]+\.trycloudflare\.com")
            if ($match.Success) {
                return $match.Value
            }
        }
        Start-Sleep -Seconds 1
    }
    if (Test-Path $LogPath) {
        Get-Content $LogPath -Tail 80
    }
    throw "Cloudflare tunnel URL was not found in $LogPath"
}

Write-Host "== Keiba mobile PWA startup ==" -ForegroundColor Cyan
Write-Host "Date : $Date"
Write-Host "Venue: $Venue"

Write-Host "`n[1/5] Stopping stale app processes..." -ForegroundColor Cyan
Stop-KeibaProcessFromPid -PidFile (Join-Path $TmpDir "backend_8000.pid") -CommandHints @("uvicorn app.main:app", "\backend")
Stop-KeibaProcessFromPid -PidFile (Join-Path $TmpDir "frontend_3000.pid") -CommandHints @("next-server", "next start", "\frontend")
Stop-KeibaProcessFromPid -PidFile (Join-Path $TmpDir "cloudflared_3000.pid") -CommandHints @("cloudflared", "--url http://127.0.0.1:$FrontendPort")
Stop-KeibaProcessesByPort -Port $BackendPort -CommandHints @("uvicorn app.main:app")
Stop-KeibaProcessesByPort -Port $FrontendPort -CommandHints @("next\dist\bin\next", "next start")

if (-not $SkipBuild) {
    Write-Host "`n[2/5] Building frontend production bundle..." -ForegroundColor Cyan
    Push-Location $FrontendDir
    try {
        npm run build
    } finally {
        Pop-Location
    }
} else {
    Write-Host "`n[2/5] Skipping frontend build (-SkipBuild)." -ForegroundColor Yellow
}

Write-Host "`n[3/5] Starting FastAPI backend..." -ForegroundColor Cyan
$backendCmd = @"
`$env:PYTHONPATH='.';
`$env:FRONTEND_ORIGINS='http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort';
Set-Location '$BackendDir';
python -m uvicorn app.main:app --host 0.0.0.0 --port $BackendPort
"@
$backendProc = Start-Process powershell -ArgumentList @("-NoProfile", "-Command", $backendCmd) -PassThru -WindowStyle Minimized
$backendProc.Id | Set-Content (Join-Path $TmpDir "backend_8000.pid")
Wait-HttpOk -Url "http://127.0.0.1:$BackendPort/health" -TimeoutSeconds 60 | Out-Null
$backendOwner = Get-ListeningOwner -Port $BackendPort
if ($backendOwner) {
    $backendOwner | Set-Content (Join-Path $TmpDir "backend_8000.pid")
}

Write-Host "`n[4/5] Starting Next.js frontend..." -ForegroundColor Cyan
$frontendCmd = @"
`$env:BACKEND_INTERNAL_URL='http://127.0.0.1:$BackendPort';
Set-Location '$FrontendDir';
npm run start -- -H 0.0.0.0 -p $FrontendPort
"@
$frontendProc = Start-Process powershell -ArgumentList @("-NoProfile", "-Command", $frontendCmd) -PassThru -WindowStyle Minimized
$frontendProc.Id | Set-Content (Join-Path $TmpDir "frontend_3000.pid")
Wait-HttpOk -Url "http://127.0.0.1:$FrontendPort/health" -TimeoutSeconds 60 | Out-Null
$frontendOwner = Get-ListeningOwner -Port $FrontendPort
if ($frontendOwner) {
    $frontendOwner | Set-Content (Join-Path $TmpDir "frontend_3000.pid")
}

$encodedVenue = [System.Uri]::EscapeDataString($Venue)
$localSheetUrl = "http://127.0.0.1:$FrontendPort/same-day-sheet?date=$Date&venue=$encodedVenue"
$publicSheetUrl = $localSheetUrl

if (-not $NoTunnel) {
    Write-Host "`n[5/5] Starting Cloudflare quick tunnel..." -ForegroundColor Cyan
    if (-not (Test-Path $CloudflaredPath)) {
        Write-Host "Downloading cloudflared..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $CloudflaredPath -TimeoutSec 180
    }
    $tunnelLog = Join-Path $TmpDir "cloudflared_3000.log"
    Remove-Item $tunnelLog -Force -ErrorAction SilentlyContinue
    $cloudflaredProc = Start-Process -FilePath $CloudflaredPath -ArgumentList @(
        "tunnel",
        "--url",
        "http://127.0.0.1:$FrontendPort",
        "--logfile",
        $tunnelLog,
        "--loglevel",
        "info"
    ) -PassThru -WindowStyle Minimized
    $cloudflaredProc.Id | Set-Content (Join-Path $TmpDir "cloudflared_3000.pid")
    $tunnelUrl = Get-TunnelUrlFromLog -LogPath $tunnelLog -TimeoutSeconds 70
    $tunnelUrl | Set-Content (Join-Path $TmpDir "cloudflared_3000.url")
    $publicSheetUrl = "$tunnelUrl/same-day-sheet?date=$Date&venue=$encodedVenue"
    Wait-HttpOk -Url "$tunnelUrl/health" -TimeoutSeconds 60 | Out-Null
} else {
    Write-Host "`n[5/5] Skipping tunnel (-NoTunnel)." -ForegroundColor Yellow
}

Write-Host "`nReady." -ForegroundColor Green
Write-Host "Local URL:" -ForegroundColor Cyan
Write-Host "  $localSheetUrl"
if (-not $NoTunnel) {
    Write-Host "iPhone URL:" -ForegroundColor Cyan
    Write-Host "  $publicSheetUrl" -ForegroundColor Green
    Write-Host "`nThis public URL is temporary. Stop it after use:" -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\stop_mobile_pwa.ps1"
}
