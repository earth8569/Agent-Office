param(
  [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $listeners) {
  Write-Host "No dashboard server is listening on port $Port." -ForegroundColor Yellow
  exit 0
}

foreach ($listener in $listeners) {
  $processId = $listener.OwningProcess
  if ($processId -and $processId -ne 0) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -like "*agent_office.cli*web*") {
      Stop-Process -Id $processId -Force
      Write-Host "Stopped Agent Office dashboard process $processId on port $Port." -ForegroundColor Green
    } else {
      Write-Host "Port $Port is used by non-dashboard process $processId. Not stopping it." -ForegroundColor Red
      exit 1
    }
  }
}