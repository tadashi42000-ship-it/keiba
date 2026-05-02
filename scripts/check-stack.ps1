param(
  [string]$BackendBaseUrl = "http://localhost:8000",
  [string]$FrontendBaseUrl = "http://localhost:3000",
  [switch]$SkipFrontend,
  [switch]$IncludeExternalPosts,
  [int]$RequestTimeoutSec = 30
)

$ErrorActionPreference = "Stop"

function Invoke-Check {
  param(
    [string]$Name,
    [string]$Method,
    [string]$Url,
    [hashtable]$Body,
    [int[]]$AllowedStatus
  )

  try {
    Write-Host "[INFO] Checking $Name ($Method $Url, timeout=${RequestTimeoutSec}s)" -ForegroundColor DarkGray

    if ($Method -eq "GET") {
      $resp = Invoke-WebRequest -Uri $Url -Method GET -UseBasicParsing -TimeoutSec $RequestTimeoutSec
    }
    elseif ($Method -eq "POST") {
      $json = if ($Body) { $Body | ConvertTo-Json -Depth 10 } else { "{}" }
      $resp = Invoke-WebRequest -Uri $Url -Method POST -ContentType "application/json" -Body $json -UseBasicParsing -TimeoutSec $RequestTimeoutSec
    }
    else {
      throw "Unsupported method: $Method"
    }

    if ($AllowedStatus -contains [int]$resp.StatusCode) {
      Write-Host "[PASS] $Name -> $($resp.StatusCode) $Url" -ForegroundColor Green
      return $true
    }

    Write-Host "[FAIL] $Name -> status $($resp.StatusCode), allowed: $($AllowedStatus -join ', ')" -ForegroundColor Red
    return $false
  }
  catch {
    $status = 0
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
      $status = [int]$_.Exception.Response.StatusCode.value__
    }

    if ($AllowedStatus -contains $status) {
      Write-Host "[PASS] $Name -> expected non-200 status $status $Url" -ForegroundColor Yellow
      return $true
    }

    Write-Host "[FAIL] $Name -> $($_.Exception.Message)" -ForegroundColor Red
    return $false
  }
}

$checks = @(
  @{ Name = "Backend /health"; Method = "GET"; Url = "$BackendBaseUrl/health"; Allowed = @(200) },
  @{ Name = "Backend /api/v1/health"; Method = "GET"; Url = "$BackendBaseUrl/api/v1/health"; Allowed = @(200) },
  @{ Name = "Backend /api/v1/sample"; Method = "GET"; Url = "$BackendBaseUrl/api/v1/sample"; Allowed = @(200) },
  @{ Name = "Backend /api/v1/races/upcoming"; Method = "GET"; Url = "$BackendBaseUrl/api/v1/races/upcoming"; Allowed = @(200) },
  @{ Name = "Backend /api/v1/external/providers"; Method = "GET"; Url = "$BackendBaseUrl/api/v1/external/providers"; Allowed = @(200) },
  @{ Name = "Backend /api/v1/external/x/accounts"; Method = "GET"; Url = "$BackendBaseUrl/api/v1/external/x/accounts"; Allowed = @(200) }
)

if ($IncludeExternalPosts) {
  $checks += @(
    @{ Name = "External web-summary"; Method = "POST"; Url = "$BackendBaseUrl/api/v1/external/web-summary"; Allowed = @(200, 502, 503); Body = @{ query = "Satsuki Sho workout"; max_results = 3; include_domains = @("netkeiba.com") } },
    @{ Name = "External youtube-summary"; Method = "POST"; Url = "$BackendBaseUrl/api/v1/external/youtube/summary"; Allowed = @(200, 502, 503); Body = @{ query = "Satsuki Sho prediction"; race_name = "Satsuki Sho"; max_results = 3 } },
    @{ Name = "External x-summary"; Method = "POST"; Url = "$BackendBaseUrl/api/v1/external/x/summary"; Allowed = @(200, 502, 503); Body = @{ race_name = "Satsuki Sho"; max_tweets = 20 } }
  )
}

if (-not $SkipFrontend) {
  $checks += @(
    @{ Name = "Frontend /"; Method = "GET"; Url = "$FrontendBaseUrl/"; Allowed = @(200) }
  )
}

$failed = 0
foreach ($check in $checks) {
  $ok = Invoke-Check -Name $check.Name -Method $check.Method -Url $check.Url -AllowedStatus $check.Allowed -Body $check.Body
  if (-not $ok) {
    $failed++
  }
}

if ($failed -gt 0) {
  Write-Host "`nCompleted with $failed failure(s)." -ForegroundColor Red
  exit 1
}

Write-Host "`nAll checks passed." -ForegroundColor Green
exit 0
