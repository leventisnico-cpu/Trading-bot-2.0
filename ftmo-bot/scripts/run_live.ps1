<#
.SYNOPSIS
  Starts the guard (Process 1), waits for a fresh heartbeat, then the strategy
  runner (Process 2), and supervises both on the Windows VPS.

.DESCRIPTION
  Each process uses its OWN MetaTrader 5 terminal installation and login
  (MT5_GUARD_* for the guard, MT5_* for the runner). The guard is restarted if
  it dies; the runner is restarted if it crashes, but NOT if it refused to start
  (exit code 3: state\HALT exists or the guard heartbeat is stale) — that needs
  a human.

  Required environment variables:
    MT5_GUARD_LOGIN MT5_GUARD_PASSWORD MT5_GUARD_SERVER MT5_GUARD_PATH
    MT5_LOGIN       MT5_PASSWORD       MT5_SERVER       MT5_PATH
  Optional: TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID HEALTHCHECK_URL

.PARAMETER Mode
  paper (refuses non-demo accounts) or live.
#>
param(
    [ValidateSet("paper", "live")]
    [string]$Mode = "paper"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force -Path "state\logs" | Out-Null

foreach ($v in "MT5_GUARD_LOGIN", "MT5_GUARD_PASSWORD", "MT5_GUARD_SERVER", "MT5_GUARD_PATH",
               "MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER", "MT5_PATH") {
    if (-not (Test-Path "Env:$v")) { throw "missing environment variable $v" }
}
if ($env:MT5_GUARD_PATH -eq $env:MT5_PATH) {
    throw "guard and runner must use separate MT5 terminal installations (MT5_GUARD_PATH == MT5_PATH)"
}

function Start-Guard {
    Start-Process -FilePath "uv" -ArgumentList "run", "ftmo-bot", "guard" -PassThru -NoNewWindow `
        -RedirectStandardError "state\logs\guard.stderr.log"
}

function Get-HeartbeatAge {
    if (-not (Test-Path "state\heartbeat")) { return [double]::PositiveInfinity }
    try {
        $ts = [DateTimeOffset]::Parse((Get-Content "state\heartbeat" -Raw).Trim())
        return ([DateTimeOffset]::UtcNow - $ts).TotalSeconds
    } catch { return [double]::PositiveInfinity }
}

Write-Host "Starting guard..."
$guard = Start-Guard
$deadline = (Get-Date).AddSeconds(60)
while ((Get-HeartbeatAge) -gt 10) {
    if ($guard.HasExited) { throw "guard exited with code $($guard.ExitCode); see state\logs" }
    if ((Get-Date) -gt $deadline) { throw "no fresh guard heartbeat within 60 s" }
    Start-Sleep -Seconds 1
}
Write-Host "Guard heartbeat fresh. Starting runner ($Mode)..."

$runner = $null
$retryRunnerAt = Get-Date
while ($true) {
    if ($guard.HasExited) {
        Write-Warning "guard exited ($($guard.ExitCode)); restarting. Runner refuses entries meanwhile."
        $guard = Start-Guard
    }
    if ($null -eq $runner -or $runner.HasExited) {
        if ($null -ne $runner -and $runner.ExitCode -eq 3) {
            Write-Warning "runner REFUSED to start (HALT or stale heartbeat). Guard keeps running. Human action needed."
            $runner = $null
            # Retry every 5 min (starts once a human clears HALT); the guard is
            # still supervised every 10 s meanwhile.
            $retryRunnerAt = (Get-Date).AddMinutes(5)
        }
        if ((Get-Date) -ge $retryRunnerAt -and (Get-HeartbeatAge) -le 10) {
            $runner = Start-Process -FilePath "uv" -ArgumentList "run", "ftmo-bot", $Mode -PassThru `
                -NoNewWindow -RedirectStandardError "state\logs\runner.stderr.log"
        }
    }
    Start-Sleep -Seconds 10
}
