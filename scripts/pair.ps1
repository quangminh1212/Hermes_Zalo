#Requires -Version 5.1
<#
.SYNOPSIS
  Start Hermes_Zalo bridge for QR pair / normal listen.
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Hermes = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA 'hermes' }
$Bridge = Join-Path $Root 'bridge\bridge.js'
$Session = Join-Path $Hermes 'zalo\session'
$Port = if ($env:ZALO_BRIDGE_PORT) { $env:ZALO_BRIDGE_PORT } else { '3001' }

New-Item -ItemType Directory -Force -Path $Session | Out-Null
$env:HERMES_HOME = $Hermes
$env:ZALO_SESSION_DIR = $Session

Write-Host "Hermes_Zalo bridge :$Port" -ForegroundColor Cyan
Write-Host "Session: $Session"
Write-Host "QR: $Session\qr.png  or  http://127.0.0.1:$Port/qr.png"
Write-Host "Pair refresh: curl -X POST http://127.0.0.1:$Port/pair"
Write-Host ""

Set-Location (Split-Path $Bridge)
node $Bridge --port $Port --session $Session
