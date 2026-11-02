# FTMO bot: run it on Windows, from the folder the repo is in. Pick one:
#   powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -Preflight  checks only, sends nothing
#   powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -Plan       what it does at the next open
#   powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -DryRun     the bot, orders only logged
#   powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -Live       the bot with real orders
#   powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -Flat       close every bot position
# -Live and -Flat send orders only if state\ftmo_config.yaml says dry_run: false
# (the trial config does; the challenge config starts in dry-run, where they
# only log) and names the terminal's account in login: (the bot refuses
# otherwise and prints the line to add). -Flat needs the -Live window stopped
# first (Ctrl+C), e.g. before a payout request.
# Keep the window open while the bot runs; Ctrl+C stops it. Log: state\ftmo_bot.log
param(
    [switch]$Preflight,
    [switch]$Plan,
    [switch]$DryRun,
    [switch]$Live,
    [switch]$Flat,
    [string]$Config = "state\ftmo_config.yaml"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) { throw "run deploy\ftmo\setup.ps1 first" }
if (-not (Test-Path -LiteralPath $Config)) { throw "config not found: $Config (run deploy\ftmo\setup.ps1)" }

$picked = @($Preflight.IsPresent, $Plan.IsPresent, $DryRun.IsPresent,
            $Live.IsPresent, $Flat.IsPresent) | Where-Object { $_ }
if (@($picked).Count -gt 1) { throw "pick one of -Preflight, -Plan, -DryRun, -Live, -Flat" }

if ($Plan) { $cmd = @("plan", "--config", $Config) }
elseif ($DryRun) { $cmd = @("run", "--config", $Config) }
elseif ($Live) { $cmd = @("run", "--config", $Config, "--execute") }
elseif ($Flat) { $cmd = @("flat", "--config", $Config, "--execute") }
else { $cmd = @("preflight", "--config", $Config) }

# The bot logs to stderr. Windows PowerShell 5.1 turns a native command's
# stderr into errors when output is redirected (ISE, a log file), and "Stop"
# would end this script at the first log line. The exit code is passed on.
$ErrorActionPreference = "Continue"
& $venvPython -m ftmo_bot @cmd
exit $LASTEXITCODE
