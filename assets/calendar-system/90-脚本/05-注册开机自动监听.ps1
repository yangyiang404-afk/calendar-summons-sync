$ErrorActionPreference = "Stop"

$taskName = "IntelFlowCalendarListener"
$scriptDir = $PSScriptRoot
$systemDir = Split-Path -Parent $scriptDir
$root = Split-Path -Parent $systemDir
$watchScriptItem = Get-ChildItem -LiteralPath $scriptDir -Filter "02-*.ps1" | Select-Object -First 1
if ($null -eq $watchScriptItem) {
    throw "Watch script not found in: $scriptDir"
}
$watchScript = $watchScriptItem.FullName
$workDir = $root
$powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$wscript = "$env:SystemRoot\System32\wscript.exe"
$hiddenLauncher = Join-Path -Path $scriptDir -ChildPath "calendar-listener-hidden.vbs"

$escapedPowerShell = $powershell.Replace('"', '""')
$escapedWatchScript = $watchScript.Replace('"', '""')
$escapedWorkDir = $workDir.Replace('"', '""')
$watchCommand = "`"$powershell`" -NoProfile -ExecutionPolicy Bypass -File `"$watchScript`""
$escapedWatchCommand = $watchCommand.Replace('"', '""')
$launcherContent = @"
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "$escapedWorkDir"
shell.Run "$escapedWatchCommand", 0, True
"@
Set-Content -LiteralPath $hiddenLauncher -Value $launcherContent -Encoding Unicode

$action = New-ScheduledTaskAction `
    -Execute $wscript `
    -Argument "//B //Nologo `"$hiddenLauncher`"" `
    -WorkingDirectory $workDir

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$watchdogTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger @($logonTrigger, $watchdogTrigger) `
    -Settings $settings `
    -Description "Start IntelFlow calendar summons listener at user logon." `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $taskName
$task.Settings.Hidden = $true
Set-ScheduledTask -InputObject $task | Out-Null

Write-Host "Registered scheduled task: $taskName"
Write-Host "It will start hidden at Windows user logon and self-check every 5 minutes."
