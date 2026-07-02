param(
    [Parameter(Mandatory = $true)]
    [string]$TargetRoot,

    [string]$SystemFolderName = "日程管理系统",

    [switch]$Force
)

$ErrorActionPreference = "Stop"

$skillRoot = Split-Path -Parent $PSScriptRoot
$templateRoot = Join-Path -Path $skillRoot -ChildPath "assets\calendar-system"
if (-not (Test-Path -LiteralPath $templateRoot)) {
    throw "Template not found: $templateRoot"
}

if (-not (Test-Path -LiteralPath $TargetRoot)) {
    New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
}

$systemRoot = Join-Path -Path $TargetRoot -ChildPath $SystemFolderName
if ((Test-Path -LiteralPath $systemRoot) -and -not $Force) {
    throw "Target system folder already exists: $systemRoot. Re-run with -Force to overwrite scripts."
}

$folders = @(
    "01-待识别传票",
    "02-识别文本",
    "03-待确认日程",
    "04-日历导出",
    "05-已处理传票",
    "06-识别失败",
    "07-同步日志",
    "08-同步失败",
    "90-脚本",
    "99-说明"
)

foreach ($folder in $folders) {
    New-Item -ItemType Directory -Force -Path (Join-Path -Path $systemRoot -ChildPath $folder) | Out-Null
}

Copy-Item -LiteralPath (Join-Path -Path $templateRoot -ChildPath "90-脚本\*") `
    -Destination (Join-Path -Path $systemRoot -ChildPath "90-脚本") `
    -Recurse `
    -Force

Write-Host "Installed calendar summons system: $systemRoot"
Write-Host "Next: create local iCloud config, check connection, then register listener."
