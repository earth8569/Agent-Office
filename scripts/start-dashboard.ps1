param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8787,
  [string]$Config = "config\agent-office.toml",
  [switch]$NoBrowser,
  [switch]$AutoStartAgents
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$ConfigPath = Join-Path $RepoRoot $Config
$Url = "http://${HostName}:${Port}/reports/grid_pixel_dashboard.html"
$AgentStartUrl = "http://${HostName}:${Port}/api/agents/start"
$StatusUrl = "http://${HostName}:${Port}/api/agents/status"

function Start-AgentLoopWhenReady {
  param(
    [string]$StatusUrl,
    [string]$AgentStartUrl
  )

  for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
      Invoke-RestMethod -Method Get -Uri $StatusUrl -TimeoutSec 3 | Out-Null
      $result = Invoke-RestMethod -Method Post -Uri $AgentStartUrl -ContentType "application/json" -Body "{}" -TimeoutSec 30
      Write-Host "Backend agents started. Phase: $($result.background_phase); running: $($result.background_running)" -ForegroundColor Green
      return
    } catch {
      Start-Sleep -Seconds 1
    }
  }

  Write-Host "Dashboard started, but backend agents did not auto-start within 30 seconds." -ForegroundColor Yellow
}

if (-not (Test-Path -LiteralPath $Python)) {
  Write-Host "Python venv not found: $Python" -ForegroundColor Red
  Write-Host "Create/install the venv first, then run this file again."
  exit 1
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
  Write-Host "Config file not found: $ConfigPath" -ForegroundColor Red
  exit 1
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
  Write-Host "Dashboard already running on port $Port." -ForegroundColor Yellow
  Write-Host $Url
  if ($AutoStartAgents) { Start-AgentLoopWhenReady -StatusUrl $StatusUrl -AgentStartUrl $AgentStartUrl }
  if (-not $NoBrowser) { Start-Process $Url }
  exit 0
}

Write-Host "Starting Agent Office dashboard..." -ForegroundColor Cyan
Write-Host "Config: $ConfigPath"
Write-Host "URL:    $Url"
Write-Host "Close this window or press Ctrl+C to stop the dashboard."
if ($AutoStartAgents) {
  Write-Host "Backend agents will auto-start after the dashboard is ready." -ForegroundColor Green
  Start-Job -ScriptBlock ${function:Start-AgentLoopWhenReady} -ArgumentList $StatusUrl, $AgentStartUrl | Out-Null
}
if (-not $NoBrowser) { Start-Process $Url }

Set-Location $RepoRoot
& $Python -m agent_office.cli web --config $Config --host $HostName --port $Port
