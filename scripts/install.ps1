#Requires -Version 5.1
<#
.SYNOPSIS
  Install Hermes_Zalo into local Hermes Agent (junctions + npm + env).
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Hermes = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA 'hermes' }
$BridgeSrc = Join-Path $Root 'bridge'
$PluginSrc = Join-Path $Root 'plugin'
$BridgeDst = Join-Path $Hermes 'scripts\zalo-bridge'
$PluginDst = Join-Path $Hermes 'plugins\zalo-platform'

Write-Host "== Hermes_Zalo install ==" -ForegroundColor Cyan
Write-Host "Repo:   $Root"
Write-Host "Hermes: $Hermes"

if (-not (Test-Path $Hermes)) {
  throw "Hermes home not found: $Hermes — install Hermes Agent first."
}
if (-not (Test-Path (Join-Path $BridgeSrc 'bridge.js'))) {
  throw "bridge/bridge.js missing under $Root"
}

# npm
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw "Node.js not found on PATH (need >= 18)" }
Push-Location $BridgeSrc
try {
  Write-Host "npm install (bridge)..." -ForegroundColor Yellow
  npm install
} finally {
  Pop-Location
}

function Ensure-Junction($dst, $src) {
  $parent = Split-Path $dst -Parent
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  if (Test-Path $dst) {
    $item = Get-Item $dst -Force
    $isLink = [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
    $target = $null
    if ($isLink -and $item.Target) {
      $target = @($item.Target)[0]
    }
    $want = (Resolve-Path $src).Path
    if ($isLink -and $target -and ((Resolve-Path $target -ErrorAction SilentlyContinue).Path -eq $want)) {
      Write-Host "Junction OK: $dst -> $src"
      return
    }
    if ($isLink) {
      Write-Host "Re-pointing junction: $dst"
      cmd /c "rmdir `"$dst`"" | Out-Null
    } else {
      throw "Path exists and is not a junction: $dst — remove it manually."
    }
  }
  cmd /c mklink /J "$dst" "$src" | Write-Host
}

Ensure-Junction $BridgeDst $BridgeSrc
Ensure-Junction $PluginDst $PluginSrc

# .env defaults
$envFile = Join-Path $Hermes '.env'
$defaults = @(
  'ZALO_ENABLED=true',
  'ZALO_BRIDGE_PORT=3001',
  'ZALO_ALLOWED_USERS=*',
  'ZALO_ALLOW_ALL_USERS=true',
  'ZALO_FORWARD_SELF_MESSAGES=true',
  'ZALO_SEND_SEEN=true',
  'ZALO_POLL_INTERVAL=0.4'
)
if (-not (Test-Path $envFile)) {
  Set-Content -Path $envFile -Value ($defaults -join "`r`n") -Encoding UTF8
  Write-Host "Created $envFile with Zalo defaults"
} else {
  $text = Get-Content $envFile -Raw -ErrorAction SilentlyContinue
  if ($null -eq $text) { $text = '' }
  $added = @()
  foreach ($line in $defaults) {
    $key = $line.Split('=')[0]
    if ($text -notmatch "(?m)^$([regex]::Escape($key))=") {
      $added += $line
    }
  }
  if ($added.Count -gt 0) {
    Add-Content -Path $envFile -Value ("`r`n# Hermes_Zalo`r`n" + ($added -join "`r`n"))
    Write-Host "Appended to .env: $($added -join ', ')"
  } else {
    Write-Host ".env already has Zalo keys"
  }
}

# enable plugin
$hermesCmd = Get-Command hermes -ErrorAction SilentlyContinue
if ($hermesCmd) {
  Write-Host "hermes plugins enable zalo-platform" -ForegroundColor Yellow
  & hermes plugins enable zalo-platform 2>&1 | Write-Host
} else {
  Write-Host "hermes CLI not on PATH — enable manually: hermes plugins enable zalo-platform" -ForegroundColor DarkYellow
}

New-Item -ItemType Directory -Force -Path (Join-Path $Hermes 'zalo\session') | Out-Null

Write-Host ""
Write-Host "OK. Next:" -ForegroundColor Green
Write-Host "  1) powershell -File $Root\scripts\pair.ps1"
Write-Host "  2) Scan QR (secondary Zalo)"
Write-Host "  3) Restart Hermes gateway"
Write-Host "  4) DM paired account, then tighten ZALO_ALLOWED_USERS"
Write-Host "Docs: $Root\docs\SETUP.md"
