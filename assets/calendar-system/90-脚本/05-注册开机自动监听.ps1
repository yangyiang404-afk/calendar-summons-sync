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

$action = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchScript`"" `
    -WorkingDirectory $workDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Start IntelFlow calendar summons listener at user logon." `
    -Force | Out-Null

Write-Host "Registered scheduled task: $taskName"
Write-Host "It will start at Windows user logon."
