# FTMO bot: one-time Windows setup. Run it from the folder the repo is in:
#   powershell -ExecutionPolicy Bypass -File deploy\ftmo\setup.ps1
#   powershell -ExecutionPolicy Bypass -File deploy\ftmo\setup.ps1 -Account challenge -Force
#
# 1. finds a 64-bit Python 3.11-3.14 (the bot needs 3.11+; the MetaTrader5
#    package has no Windows build for 3.15 yet);
# 2. creates .venv (or checks the one there) and installs the bot's packages
#    (MetaTrader5, PyYAML, tzdata);
# 3. installs a config as state\ftmo_config.yaml: the free-trial config by
#    default, the challenge config with -Account challenge. An existing
#    state\ftmo_config.yaml is kept unless you add -Force;
# 4. checks that the bot and its config load.
# It never asks for or stores a password: you log MetaTrader 5 in yourself.
param(
    [ValidateSet("trial", "challenge")]
    [string]$Account = "trial",
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
Set-Location -LiteralPath $root

$probe = "import struct, sys; print('%d %d.%d' % (struct.calcsize('P') * 8, sys.version_info[0], sys.version_info[1]))"
$good = @("3.11", "3.12", "3.13", "3.14")

function Test-Python($exe, $pyArgs) {
    # The version ("3.12") of a 64-bit Python the bot can run on, else
    # $null. Native commands that write to stderr (the Microsoft
    # Store's python alias does) must not stop the search, and stdin is
    # closed so an install prompt from the py launcher cannot hang it.
    $ErrorActionPreference = "Continue"
    $out = $null | & $exe @pyArgs -c $probe 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    $bits, $ver = "$out".Trim().Split(" ")
    if ($bits -eq "64" -and $good -contains $ver) { return $ver }
    return $null
}

function Find-Python {
    # @{ Exe = ...; Args = @(...) } or $null. A hashtable, because
    # PowerShell unrolls a one-element array returned from a function into
    # a plain string.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("3.12", "3.13", "3.11", "3.14")) {
            if ((Test-Python "py" @("-$v")) -eq $v) { return @{ Exe = "py"; Args = @("-$v") } }
        }
    }
    if ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-Python "python" @())) {
        return @{ Exe = "python"; Args = @() }
    }
    return $null
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $ver = Test-Python $venvPython @()
    if (-not $ver) {
        throw (".venv was made with a Python the bot cannot use (it needs 64-bit " +
               "Python 3.11 to 3.14). Delete the .venv folder and run this again.")
    }
    Write-Host "using the existing .venv (Python $ver)"
} else {
    $py = Find-Python
    if (-not $py) {
        throw ("No 64-bit Python 3.11 to 3.14 found (the bot and its MetaTrader5 package need one). " +
               "Install Python 3.12 (64-bit) from python.org, tick 'Add python.exe to PATH', " +
               "open a new PowerShell window and run this again.")
    }
    $pyArgs = @($py.Args)
    Write-Host ("using Python: " + ((@($py.Exe) + $pyArgs) -join " "))
    Write-Host "creating .venv"
    $ErrorActionPreference = "Continue"
    & $py.Exe @pyArgs -m venv .venv
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -ne 0) { throw "could not create .venv" }
}

# From here on, native commands run with "Continue": Windows PowerShell 5.1
# turns their stderr (pip's warnings) into errors when output is redirected
# (ISE, a log file), and "Stop" would end the script there. Their exit codes
# are checked instead, and cmdlets stop on errors through -ErrorAction Stop.
$ErrorActionPreference = "Continue"
& $venvPython -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip could not be upgraded" }
& $venvPython -m pip install --disable-pip-version-check -r deploy\ftmo\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "the bot's packages did not install; see the error above" }

New-Item -ItemType Directory -Force -Path "state" -ErrorAction Stop | Out-Null
if ($Account -eq "trial") { $source = "deploy\ftmo\config.trial.yaml" }
else { $source = "deploy\ftmo\config.example.yaml" }
$target = "state\ftmo_config.yaml"
if ((Test-Path -LiteralPath $target) -and -not $Force) {
    Write-Host "kept your existing $target (add -Force to replace it with $source)"
} else {
    Copy-Item -Force -LiteralPath $source -Destination $target -ErrorAction Stop
    Write-Host "installed $target from $source"
}

$check = "import MetaTrader5, yaml; import ftmo_bot.runner; from ftmo_bot.config import load; " +
         "c = load('state/ftmo_config.yaml'); " +
         "print('packages OK: MetaTrader5 ' + str(MetaTrader5.__version__)); " +
         "print('config OK: risk %.1f%%, target %s, minimum days %d, dry_run %s, server clock %s, login %s' % " +
         "(c.risk_per_trade * 100, c.profit_target, c.min_trading_days, c.dry_run, c.server_clock, c.login))"
& $venvPython -c $check
if ($LASTEXITCODE -ne 0) { throw "the bot did not load; see the error above" }

Write-Host ""
Write-Host "Setup done. Next:"
Write-Host "  1. Open FTMO's MetaTrader 5 and log in to the account (you type the password)."
Write-Host "     Tools > Options > Expert Advisors: tick 'Allow algorithmic trading',"
Write-Host "     press the Algo Trading button (green), and add US30.cash, US100.cash,"
Write-Host "     US500.cash and US2000.cash to Market Watch."
Write-Host "  2. Check everything (reads only, sends nothing):"
Write-Host "     powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -Preflight"
Write-Host "  3. Before run.ps1 -Live: in state\ftmo_config.yaml replace 'login: null'"
Write-Host "     with the account's login number (login: 1234567). Orders go only there."
