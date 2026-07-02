$ErrorActionPreference = "Stop"

$taskName = "IntelFlowCalendarListener"
$scriptDir = $PSScriptRoot
$systemDir = Split-Path -Parent $scriptDir
$logDir = Get-ChildItem -LiteralPath $systemDir -Directory -Filter "07-*" | Select-Object -First 1
$pidPath = $null
if ($null -ne $logDir) {
    $pidPath = Join-Path -Path $logDir.FullName -ChildPath "listener.pid"
}

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "ScheduledTask: not registered"
} else {
    Write-Host "ScheduledTask: $($task.State)"
}

if ($pidPath -and (Test-Path -LiteralPath $pidPath)) {
    $listenerPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $process = Get-Process -Id $listenerPid -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        $process = Get-CimInstance Win32_Process |
            Where-Object { $_.CommandLine -like "*process_summons.py*--watch*" } |
            Select-Object -First 1
        if ($null -eq $process) {
            Write-Host "ListenerProcess: not running; last pid was $listenerPid"
        } else {
            Write-Host "ListenerProcess: running; pid=$($process.ProcessId)"
        }
    } else {
        Write-Host "ListenerProcess: running; pid=$($process.Id); started=$($process.StartTime)"
    }
} else {
    $process = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like "*process_summons.py*--watch*" } |
        Select-Object -First 1
    if ($null -eq $process) {
        Write-Host "ListenerProcess: no pid file"
    } else {
        Write-Host "ListenerProcess: running; pid=$($process.ProcessId)"
    }
}
