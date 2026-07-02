$ErrorActionPreference = "Stop"

$localToolRoots = @(
    "E:\Codex-Local-Tools-NoSync",
    "C:\Codex-Local-Tools-NoSync"
)
$localToolRoot = $localToolRoots | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $localToolRoot) {
    $localToolRoot = $localToolRoots[0]
}

$configDir = Join-Path -Path $localToolRoot -ChildPath "calendar-sync"
$configPath = Join-Path -Path $configDir -ChildPath "icloud-calendar.json"

if (-not (Test-Path -LiteralPath $configDir)) {
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null
}

if (Test-Path -LiteralPath $configPath) {
    Write-Host "Config already exists: $configPath"
    Write-Host "Skip overwrite."
    exit 0
}

$config = [ordered]@{}
$config.enabled = $false
$config.apple_id = "your-apple-id@example.com"
$config.app_specific_password = "xxxx-xxxx-xxxx-xxxx"
$config.calendar_name = ""
$config.base_url = "https://caldav.icloud.com"

$template = $config | ConvertTo-Json
Set-Content -LiteralPath $configPath -Value $template -Encoding UTF8

Write-Host "Created config template: $configPath"
Write-Host "Fill Apple ID and app-specific password, then set enabled to true."
