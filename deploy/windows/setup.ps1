# Mini-Prop OS — one-time Windows setup (run from the repo root):
#   powershell -ExecutionPolicy Bypass -File deploy\windows\setup.ps1
#
# Creates .venv, installs the runtime dependencies, and installs the PAPER
# config (deploy\config.tfsa-paper.yaml -> state\config.yaml). It never
# writes credentials: Telegram token / chat id come from environment
# variables or a git-ignored .env you fill in yourself.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $root

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw "python not found on PATH (install Python 3.11+ from python.org)" }

if (-not (Test-Path ".venv")) {
    Write-Host "creating .venv"
    python -m venv .venv
}
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r deploy\requirements.txt

New-Item -ItemType Directory -Force -Path "state" | Out-Null

# PAPER config for the TFSA-permissioned paper account: SPY, port 4002.
# Deliberately NOT mini_prop_os\config.yaml (that one is the MES futures
# reference config, which this account cannot trade).
$source = Join-Path $root "deploy\config.tfsa-paper.yaml"
$target = Join-Path $root "state\config.yaml"
Copy-Item -Force $source $target
Write-Host "installed paper config: $target (from deploy\config.tfsa-paper.yaml)"

if (-not (Test-Path ".env")) {
    Copy-Item "deploy\.env.example" ".env"
    Write-Host "created .env from deploy\.env.example — fill in TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID yourself (never commit it)"
}

& $venvPython -c "from mini_prop_os.core.config import load_config; c = load_config('state/config.yaml'); assert c.connection.port in (4002, 7497), 'not a paper port'; print('config OK: port', c.connection.port, c.contract.symbol, c.contract.sec_type, 'market data', c.connection.market_data_type)"
Write-Host ""
Write-Host "next: start IB Gateway (paper, API port 4002), then .\deploy\windows\run.ps1 -Preflight"
