# deploy\ftmo\watchdog_install.ps1: registers (or refreshes) the scheduled
# task "FTMO bot watchdog" for the current user: at logon and every 5
# minutes, allowed on battery, hidden window. Run once, as the user who
# runs the bot (no admin needed). -Remove deletes the task.
param([switch]$Remove)
$name = 'FTMO bot watchdog'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "removed: $name"
    exit 0
}
$script = Join-Path $PSScriptRoot 'watchdog.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $script + '"')
$atLogon = New-ScheduledTaskTrigger -AtLogOn
$every5 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $atLogon, $every5 `
    -Settings $settings -Force | Out-Null
$t = Get-ScheduledTask -TaskName $name
Write-Host ("registered: {0} ({1}); next run {2}" -f $t.TaskName, $t.State,
    (Get-ScheduledTaskInfo -TaskName $name).NextRunTime)
