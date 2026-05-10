# Start / stop / status for NexusBody services via PM2.
# All service config lives in ecosystem.config.js — this script is a thin
# wrapper so .claude/scripts/start-all.ps1 keeps the same command surface.
#
# Usage (from repo root):
#   .\orchestration\deployments\nexusbody-services.ps1 start
#   .\orchestration\deployments\nexusbody-services.ps1 restart
#   .\orchestration\deployments\nexusbody-services.ps1 stop
#   .\orchestration\deployments\nexusbody-services.ps1 status
#   .\orchestration\deployments\nexusbody-services.ps1 logs

[CmdletBinding()]
param(
    [ValidateSet("start","stop","restart","status","logs")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ecosystem = Join-Path $repoRoot "orchestration\deployments\ecosystem.config.js"

function Start-All {
    # Ollama must be up before nexus-gateway answers /health (Qwen probe).
    if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) {
        Write-Host "starting ollama..."
        Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 3
    }
    pm2 start $ecosystem
    pm2 save
}

function Stop-All     { pm2 stop $ecosystem }
function Restart-All  { pm2 restart $ecosystem }
function Show-Status  { pm2 ls }
function Show-Logs    { pm2 logs --lines 50 }

switch ($Action) {
    "start"   { Start-All }
    "stop"    { Stop-All }
    "restart" { Restart-All }
    "status"  { Show-Status }
    "logs"    { Show-Logs }
}
