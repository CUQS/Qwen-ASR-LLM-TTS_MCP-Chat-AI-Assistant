Param(
    [string]$ShortcutName = "AI Assistant",
    [string]$TargetScript = "run_ai_assistant.ps1",
    [switch]$UseBat = $false
)

# create_desktop_shortcut.ps1 — 在桌面创建指向本仓库启动脚本的快捷方式 (.lnk)
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop ("$ShortcutName.lnk")

if ($UseBat) {
    $target = Join-Path $repoRoot "run_ai_assistant.bat"
    $arguments = ''
} else {
    $target = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $scriptFull = Join-Path $repoRoot $TargetScript
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptFull`""
}

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $repoRoot
$shortcut.WindowStyle = 7  # 1:normal, 7:minimized
$shortcut.Description = "Launch AI Assistant (from $repoRoot)"

# Try to set a repo icon if one exists, otherwise use powershell icon
$possibleIcon = Join-Path $repoRoot 'assets\ai_icon.ico'
if (Test-Path $possibleIcon) { $shortcut.IconLocation = $possibleIcon } else { $shortcut.IconLocation = "$target,0" }

$shortcut.Save()
Write-Host "✅ 快捷方式已创建： $shortcutPath"
