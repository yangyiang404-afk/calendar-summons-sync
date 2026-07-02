$ErrorActionPreference = "Stop"

$taskName = "IntelFlowCalendarListener"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Scheduled task not found: $taskName"
    exit 0
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Unregistered scheduled task: $taskName"
