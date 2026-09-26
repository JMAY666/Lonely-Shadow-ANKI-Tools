param(
    [ValidatePattern('^(|[a-fA-F0-9]{7,40})$')]
    [string]$Revision = '',
    [string]$Summary = '',
    [string]$UpdatedAt = ''
)

$ErrorActionPreference = 'Stop'
$ankiRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$ankiDist = Join-Path $ankiRoot 'dist'
$ankiPackage = Join-Path $ankiDist 'Anki-weak-review-tables-26.8.1'
$ankiExecutable = Join-Path $ankiPackage 'Anki.exe'
if (-not (Test-Path -LiteralPath $ankiExecutable -PathType Leaf)) {
    throw 'The fixed Anki installation is missing. Build and verify it before creating the entry.'
}

$ankiManifest = Get-Content -LiteralPath (Join-Path $ankiPackage 'INTEGRATED-BUILD.json') -Raw | ConvertFrom-Json
$ankiPackageFiles = Join-Path $ankiPackage 'app_packages'
foreach ($entry in $ankiManifest.weak_review_files.psobject.Properties) {
    $ankiFile = [IO.Path]::GetFullPath((Join-Path $ankiPackageFiles $entry.Name))
    if (-not $ankiFile.StartsWith($ankiPackageFiles + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Invalid file path in the application manifest.'
    }
    if ((Get-FileHash -LiteralPath $ankiFile -Algorithm SHA256).Hash -ne $entry.Value) {
        throw "Installed file does not match its delivery manifest: $($entry.Name)"
    }
}

$ankiStatePath = Join-Path $ankiDist 'CURRENT-APP.json'
$ankiPrevious = if (Test-Path -LiteralPath $ankiStatePath) {
    Get-Content -LiteralPath $ankiStatePath -Raw | ConvertFrom-Json
} else { $null }
if (-not $Revision) { $Revision = $ankiPrevious.revision }
if (-not $Summary) { $Summary = $ankiPrevious.summary }
if (-not $UpdatedAt) { $UpdatedAt = $ankiPrevious.updatedAt }
if (-not $Revision -or -not $Summary -or -not $UpdatedAt) {
    throw 'Provide the delivered revision, summary and timestamp when initializing the fixed entry.'
}

$ankiLinkPath = Join-Path $ankiDist '启动 Anki.lnk'
$ankiShell = New-Object -ComObject WScript.Shell
$ankiLink = $ankiShell.CreateShortcut($ankiLinkPath)
if ((Test-Path -LiteralPath $ankiLinkPath) -and $ankiLink.TargetPath -ne $ankiExecutable) {
    throw 'An existing shortcut points to another application. It has been preserved.'
}
$ankiLink.TargetPath = $ankiExecutable
$ankiLink.WorkingDirectory = $ankiPackage
$ankiLink.IconLocation = "$ankiExecutable,0"
$ankiLink.Description = 'Anki 固定启动入口；更新后继续使用此快捷方式'
$ankiLink.Save()
if ($ankiShell.CreateShortcut($ankiLinkPath).TargetPath -ne $ankiExecutable) {
    throw 'The saved shortcut did not retain the correct application target.'
}

$ankiState = [ordered]@{
    entry = '启动 Anki.lnk'
    application = 'Anki-weak-review-tables-26.8.1/Anki.exe'
    revision = $Revision
    updatedAt = $UpdatedAt
    summary = $Summary
    verifiedAt = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
}
$ankiUtf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText($ankiStatePath, ($ankiState | ConvertTo-Json), $ankiUtf8)
$ankiNotice = @"
Anki 当前使用版本

日常启动：双击本文件旁边的“启动 Anki”快捷方式。
程序位置：$ankiExecutable
功能修订：$Revision
功能交付时间：$UpdatedAt
最近更新：$Summary
入口核验时间：$($ankiState.verifiedAt)

后续更新沿用同一入口和同一使用目录。更新后完全退出 Anki（包括托盘），再重新打开。
文件夹名称和日期不代表内部功能的新旧；请以本说明及交付修订为准。

当前保留的其他目录：
- Anki-weak-insights-26.8.1：上一版总结功能的构建副本。
- Anki-weak-rounds-26.8.1：逐空评分修复的验收副本。
这些副本保留用于验收和恢复。日常学习统一使用上面的固定快捷方式。
"@
[IO.File]::WriteAllText((Join-Path $ankiDist '当前使用版本.txt'), $ankiNotice, $ankiUtf8)
[pscustomobject]@{Shortcut=$ankiLinkPath; Target=$ankiExecutable; Revision=$Revision; Verified=$true} | ConvertTo-Json -Compress
