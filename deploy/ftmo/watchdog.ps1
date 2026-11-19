# deploy\ftmo\watchdog.ps1: keeps FTMO's MetaTrader and the bot running.
# Registered by watchdog_install.ps1 as the Windows scheduled task
# "FTMO bot watchdog": at logon and every 5 minutes, on battery too.
# Without the task, -Loop does the same from its own window, every 5
# minutes, until that window is closed (no reboot survival):
#   Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File','deploy\ftmo\watchdog.ps1','-Loop'
# It changes nothing else: it starts the terminal named by mt5_path in
# state\ftmo_config.yaml when it is closed, and run.ps1 -Live in its own
# window when no ftmo_bot process runs. The bot's own state lock refuses a
# second process, so a race here cannot double the bot. Pure ASCII,
# Windows PowerShell 5.1.
# To stop the bot on purpose (run.ps1 -SelfTest or -Flat need it stopped),
# first create state\watchdog.pause (any content); the watchdog then does
# nothing until that file is deleted. The pause is logged once an hour.
param([switch]$Loop)
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
$log = Join-Path $repo 'state\watchdog.log'
function Note($m) {
    Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m)
}
function Invoke-Watch {
    $pause = Join-Path $repo 'state\watchdog.pause'
    if (Test-Path $pause) {
        if ((Get-Date).Minute -lt 5) { Note 'paused by state\watchdog.pause; nothing started' }
        return
    }
    $cfg = Join-Path $repo 'state\ftmo_config.yaml'
    if (-not (Test-Path $cfg)) { Note 'no state\ftmo_config.yaml; nothing started'; return }
    $mt5 = $null
    foreach ($line in Get-Content $cfg) {
        if ($line -match '^mt5_path:\s*(\S.*)$') {
            $v = ($Matches[1] -split '\s#')[0].Trim()          # drop a trailing comment
            $mt5 = $v.Trim('"').Trim("'").Replace('/', '\')    # and quotes
            break
        }
    }
    $openedMt5 = $false
    if ($mt5 -and (Test-Path $mt5)) {
        $up = Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $mt5 }
        if (-not $up) {
            Start-Process -FilePath $mt5
            Note "MetaTrader was closed: started $mt5"
            $openedMt5 = $true
        }
    }
    $bot = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*ftmo_bot*' }
    if ($bot) { return }                  # run, selftest, plan or preflight: leave it alone
    if ($openedMt5) { Start-Sleep -Seconds 120 }   # let the terminal log in and load its history
    Start-Process powershell -WorkingDirectory $repo -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', 'deploy\ftmo\run.ps1', '-Live'
    Note 'no bot process: started run.ps1 -Live'
}
if ($Loop) {
    Note 'watchdog loop started in its own window (every 5 minutes until this window closes)'
    while ($true) {
        try { Invoke-Watch } catch { Note ("error: " + $_.Exception.Message) }
        Start-Sleep -Seconds 300
    }
} else {
    Invoke-Watch
}
