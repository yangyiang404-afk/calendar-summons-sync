$ErrorActionPreference = "Stop"

$localToolRoots = @(
    "E:\Codex-Local-Tools-NoSync",
    "C:\Codex-Local-Tools-NoSync"
)

foreach ($root in $localToolRoots) {
    if (-not (Test-Path -LiteralPath $root)) {
        continue
    }
    $envScript = Join-Path -Path $root -ChildPath "docflow\codex-docflow-env.ps1"
    if (Test-Path -LiteralPath $envScript) {
        . $envScript
        $env:INTELFLOW_ICLOUD_CONFIG = Join-Path -Path $root -ChildPath "calendar-sync\icloud-calendar.json"
        break
    }
}

$systemDir = Split-Path -Parent $PSScriptRoot

$scriptPath = Join-Path $PSScriptRoot "process_summons.py"
$process = Start-Process `
    -FilePath "python" `
    -ArgumentList @($scriptPath, "--watch") `
    -NoNewWindow `
    -PassThru

$process.WaitForExit()
exit $process.ExitCode
