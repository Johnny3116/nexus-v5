# Start / stop / status Nexus services on NexusServer.
# Only nexus-vtube + GPT-SoVITS + Nexus-Agent gateway live here (CLAUDE.md §5).

[CmdletBinding()]
param(
    [ValidateSet("start","stop","restart","status","logs")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"
$Services = @(
    @{ Name = "nexus-agent-gateway"; Cmd = "node nexus-agent.mjs gateway --port 18790 --allow-unconfigured" },
    @{ Name = "gpt-sovits";          Cmd = "python gpt-sovits/api.py --port 9880" },
    @{ Name = "nexus-vtube";         Cmd = "python -m uvicorn nexus_vtube.main:app --host 0.0.0.0 --port 8030" }
)

function Start-All {
    foreach ($s in $Services) {
        Write-Host "starting $($s.Name)"
        pm2 start $s.Cmd --name $s.Name
    }
    pm2 save
}

function Stop-All  { foreach ($s in $Services) { pm2 stop $s.Name } }
function Restart-All { foreach ($s in $Services) { pm2 restart $s.Name } }
function Show-Status { pm2 ls }
function Show-Logs { pm2 logs --lines 50 }

switch ($Action) {
    "start"   { Start-All }
    "stop"    { Stop-All }
    "restart" { Restart-All }
    "status"  { Show-Status }
    "logs"    { Show-Logs }
}
