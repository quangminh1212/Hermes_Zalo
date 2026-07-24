#Requires -Version 5.1
<#
.SYNOPSIS
  Phase B live capture: ZaloCall process + voip/call logs while receiving a call.

.DESCRIPTION
  Run BEFORE calling the PC Zalo account from another phone.
  Snapshots logs and watches for ZaloCall.exe / voip.log growth.
  Output: captures/<yyyyMMdd-HHmmss>/

  Acc phụ only. Research — does not answer the call.
#>
param(
  [int]$PollMs = 500,
  [string]$ZaloData = "$env:APPDATA\ZaloData"
)

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Out = Join-Path $Root "captures\$Stamp"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

function Log($m) {
  $line = "[{0}] {1}" -f (Get-Date -Format 'o'), $m
  Add-Content -Path (Join-Path $Out 'monitor.log') -Value $line -Encoding utf8
  Write-Host $line
}

Log "capture dir: $Out"
Log "ZaloData: $ZaloData"

# baseline copies
foreach ($rel in @('call.log', 'cal\voip.log', 'cal\login.zlog', 'log.log')) {
  $src = Join-Path $ZaloData $rel
  if (Test-Path $src) {
    try {
      $dst = Join-Path $Out ("baseline_" + ($rel -replace '[\\/]', '_'))
      Copy-Item $src $dst -Force -ErrorAction Stop
      Log "baseline ok $rel size=$((Get-Item $dst).Length)"
    } catch {
      Log "baseline skip $rel : $_"
    }
  } else {
    Log "missing $rel"
  }
}

# process snapshot
Get-CimInstance Win32_Process | Where-Object {
  $_.Name -match 'Zalo|zcall' -or ($_.CommandLine -and $_.CommandLine -match 'Zalo|zcall')
} | ForEach-Object {
  $cmd = if ($_.CommandLine) { $_.CommandLine } else { '' }
  $cmdShort = if ($cmd.Length -gt 120) { $cmd.Substring(0, 120) } else { $cmd }
  Log ("proc baseline PID={0} Name={1} Cmd={2}" -f $_.ProcessId, $_.Name, $cmdShort)
} | Out-Null

$voip = Join-Path $ZaloData 'cal\voip.log'
$callLog = Join-Path $ZaloData 'call.log'
$lastVoipLen = if (Test-Path $voip) { (Get-Item $voip).Length } else { 0 }
$lastCallLen = if (Test-Path $callLog) { (Get-Item $callLog).Length } else { 0 }
$seenZaloCall = @{}

Log "Watching... Call this PC Zalo from another phone. Ctrl+C to stop & finalize."

try {
  while ($true) {
    Start-Sleep -Milliseconds $PollMs

    # ZaloCall process
    Get-Process -Name 'ZaloCall' -ErrorAction SilentlyContinue | ForEach-Object {
      if (-not $seenZaloCall.ContainsKey($_.Id)) {
        $seenZaloCall[$_.Id] = $true
        Log "ZaloCall STARTED pid=$($_.Id) path=$($_.Path)"
        try {
          $_.Modules | Select-Object -First 30 ModuleName, FileName |
            Export-Csv (Join-Path $Out "zalo_call_$($_.Id)_modules.csv") -NoTypeInformation
        } catch {
          Log "module list fail: $_"
        }
      }
    }

    # log growth
    if (Test-Path $voip) {
      $n = (Get-Item $voip).Length
      if ($n -ne $lastVoipLen) {
        Log "voip.log size $lastVoipLen -> $n"
        try {
          Copy-Item $voip (Join-Path $Out ("voip_" + (Get-Date -Format 'HHmmss') + ".log")) -Force
        } catch { Log "voip copy: $_" }
        $lastVoipLen = $n
      }
    }
    if (Test-Path $callLog) {
      $n = (Get-Item $callLog).Length
      if ($n -ne $lastCallLen) {
        Log "call.log size $lastCallLen -> $n"
        try {
          Copy-Item $callLog (Join-Path $Out ("call_" + (Get-Date -Format 'HHmmss') + ".log")) -Force
        } catch { Log "call copy: $_" }
        $lastCallLen = $n
      }
    }
  }
} finally {
  Log "finalize"
  foreach ($rel in @('call.log', 'cal\voip.log')) {
    $src = Join-Path $ZaloData $rel
    if (Test-Path $src) {
      try {
        Copy-Item $src (Join-Path $Out ("final_" + ($rel -replace '[\\/]', '_'))) -Force
      } catch { Log "final copy $rel : $_" }
    }
  }
  # summary
  $summary = @{
    stamp     = $Stamp
    zaloCallPids = @($seenZaloCall.Keys)
    out       = $Out
    note      = 'Research capture only — call was NOT auto-answered'
  } | ConvertTo-Json
  Set-Content (Join-Path $Out 'summary.json') $summary -Encoding utf8
  Log "done → $Out"
}
