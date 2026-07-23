#Requires -Version 5.1
<#
.SYNOPSIS
  Detach Hermes_Zalo external module from local Hermes Agent.
  Does not delete this repo. Re-attach with install.ps1.
#>
$ErrorActionPreference = 'Stop'
$Hermes = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA 'hermes' }
$BridgeDst = Join-Path $Hermes 'scripts\zalo-bridge'
$PluginDst = Join-Path $Hermes 'plugins\zalo-platform'
$ConfigYaml = Join-Path $Hermes 'config.yaml'

Write-Host "== Hermes_Zalo uninstall ==" -ForegroundColor Cyan
Write-Host "Hermes: $Hermes"

function Remove-JunctionOrWarn($path) {
  if (-not (Test-Path $path)) {
    Write-Host "missing (ok): $path"
    return
  }
  $item = Get-Item $path -Force
  if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
    cmd /c "rmdir `"$path`"" | Out-Null
    Write-Host "removed junction: $path"
  } else {
    throw "Path exists and is not a junction (refusing delete): $path"
  }
}

Remove-JunctionOrWarn $BridgeDst
Remove-JunctionOrWarn $PluginDst

# Soft-disable in config.yaml if present (best-effort, no full YAML rewrite)
if (Test-Path $ConfigYaml) {
  $raw = Get-Content $ConfigYaml -Raw -Encoding UTF8
  $orig = $raw
  # platforms.zalo.enabled: true -> false
  $raw = [regex]::Replace($raw, '(?m)(^\s*zalo:\s*\r?\n(?:^\s+.+\r?\n)*?^\s+enabled:\s*)true', '${1}false')
  # strip zalo-platform / zalo from plugins.enabled list lines only when alone on line
  $raw = [regex]::Replace($raw, '(?m)^\s*-\s*zalo-platform\s*\r?\n', '')
  $raw = [regex]::Replace($raw, '(?m)^\s*-\s*zalo\s*\r?\n', '')
  if ($raw -ne $orig) {
    $bak = "$ConfigYaml.bak-zalo-uninstall-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Copy-Item $ConfigYaml $bak -Force
    Set-Content -Path $ConfigYaml -Value $raw -Encoding UTF8 -NoNewline
    Write-Host "config soft-disabled zalo (backup $bak)"
  } else {
    Write-Host "config.yaml: no zalo enable lines changed (check plugins/platforms manually)"
  }
}

Write-Host ""
Write-Host "OK. SoT remains at this repo. .env Zalo keys left intact." -ForegroundColor Green
Write-Host "Re-attach: powershell -File $(Join-Path (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)) 'scripts\install.ps1')"
Write-Host "Restart Hermes gateway/desktop after uninstall."
