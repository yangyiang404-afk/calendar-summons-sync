$ErrorActionPreference = "Stop"

$taskName = "IntelFlowCalendarListener"
$scriptDir = $PSScriptRoot
$systemDir = Split-Path -Parent $scriptDir
$logDir = Get-ChildItem -LiteralPath $systemDir -Directory -Filter "07-*" | Select-Object -First 1
$pidPath = $null
if ($null -ne $logDir) {
    $pidPath = Join-Path -Path $logDir.FullName -ChildPath "listener.pid"
}

function Find-WatchProcess {
    try {
        return Get-CimInstance Win32_Process -ErrorAction Stop |
            Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -like "*process_summons.py*--watch*" } |
            Select-Object -First 1
    } catch {
        Write-Host "ListenerProcessCommandLineCheck: unavailable; $($_.Exception.Message)"
        return $null
    }
}

function Get-WatchProcessByPid {
    param([int]$ProcessId)
    try {
        return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop |
            Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -like "*process_summons.py*--watch*" } |
            Select-Object -First 1
    } catch {
        $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($null -ne $process -and $process.ProcessName -eq "python") {
            return [PSCustomObject]@{
                ProcessId = $process.Id
            }
        }
        return $null
    }
}

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "ScheduledTask: not registered"
} else {
    Write-Host "ScheduledTask: $($task.State)"
}

if ($pidPath -and (Test-Path -LiteralPath $pidPath)) {
    $listenerPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $process = Get-WatchProcessByPid -ProcessId $listenerPid
    if ($null -eq $process) {
        $process = Find-WatchProcess
        if ($null -eq $process) {
            Write-Host "ListenerProcess: not running or command line unavailable; last pid was $listenerPid"
        } else {
            Write-Host "ListenerProcess: running; pid=$($process.ProcessId)"
        }
    } else {
        Write-Host "ListenerProcess: running; pid=$($process.ProcessId)"
    }
} else {
    $process = Find-WatchProcess
    if ($null -eq $process) {
        Write-Host "ListenerProcess: no pid file or command line unavailable"
    } else {
        Write-Host "ListenerProcess: running; pid=$($process.ProcessId)"
    }
}
