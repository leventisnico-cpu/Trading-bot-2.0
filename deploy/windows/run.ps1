# Mini-Prop OS — run on Windows against IB Gateway (paper).
#   .\deploy\windows\run.ps1 -Preflight     read-only go/no-go check
#   .\deploy\windows\run.ps1                run the bot
#   .\deploy\windows\run.ps1 -ResetKillSwitch <your-name>
param(
    [switch]$Preflight,
    [string]$ResetKillSwitch = "",
    [string]$Config = "state\config.yaml"
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "run deploy\windows\setup.ps1 first" }
if (-not (Test-Path $Config)) { throw "config not found: $Config (run setup.ps1)" }

# Load .env (KEY=VALUE lines) into this process only; never echoed or logged.
if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $k, $v = $line.Split("=", 2)
            [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
        }
    }
}

$args = @("-m", "mini_prop_os", "--config", $Config)
if ($Preflight) { $args += "--preflight" }
if ($ResetKillSwitch) { $args += @("--reset-kill-switch", $ResetKillSwitch) }
& $venvPython @args
exit $LASTEXITCODE
