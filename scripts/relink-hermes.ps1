$h = Join-Path $env:LOCALAPPDATA 'hermes'
$bridgeDst = Join-Path $h 'scripts\zalo-bridge'
$pluginDst = Join-Path $h 'plugins\zalo-platform'
$bridgeSrc = 'C:\Dev\Hermes_Zalo\bridge'
$pluginSrc = 'C:\Dev\Hermes_Zalo\plugin'

foreach ($p in @($bridgeDst, $pluginDst)) {
  if (Test-Path $p) {
    cmd /c "rmdir `"$p`""
  }
}
New-Item -ItemType Directory -Force -Path (Split-Path $bridgeDst) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $pluginDst) | Out-Null
cmd /c "mklink /J `"$bridgeDst`" `"$bridgeSrc`""
cmd /c "mklink /J `"$pluginDst`" `"$pluginSrc`""
Get-Item $bridgeDst, $pluginDst | Format-List FullName, LinkType, Target
