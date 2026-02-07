<#
uv.ps1 - 在 Windows PowerShell 中一行启动指定的虚拟环境

用法示例：
  .\uv.ps1 myenv       # 激活 D:\uv_venv\myenv 下的虚拟环境
  .\uv.ps1 -List       # 列出 D:\uv_venv 下所有环境
  .\uv.ps1 -Help       # 显示帮助

说明：请在 PowerShell 中运行此脚本（当前会话内激活环境）。
如果脚本被阻止，请运行：
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
#>
param(
    [Parameter(Position=0, ValueFromPipeline=$true)]
    [string]$Name,

    [switch]$List,
    [switch]$Help
)

$UvRoot = 'D:\uv_venv'

function Show-Help {
    Write-Host "uv.ps1 - 在 D:\uv_venv 中激活指定的虚拟环境" -ForegroundColor Cyan
    Write-Host "" 
    Write-Host "用法：" -ForegroundColor Yellow
    Write-Host "  .\uv.ps1 <环境名>        - 激活 D:\uv_venv\\<环境名>" 
    Write-Host "  .\uv.ps1 -List           - 列出所有可用环境" 
    Write-Host "  .\uv.ps1 -Help           - 显示本帮助信息" 
}

if ($Help) {
    Show-Help
    return
}

if ($List) {
    if (-not (Test-Path $UvRoot)) {
        Write-Error "未找到目录： $UvRoot"
        return 1
    }
    Get-ChildItem -Path $UvRoot -Directory | ForEach-Object { $_.Name }
    return
}

if (-not $Name) {
    Show-Help
    return 1
}

$envPath = Join-Path $UvRoot $Name
if (-not (Test-Path $envPath)) {
    Write-Error "未找到虚拟环境： '$Name'（在 $UvRoot 中）"
    return 1
}

$activate = Join-Path $envPath 'Scripts\Activate.ps1'
if (-not (Test-Path $activate)) {
    Write-Error "找不到激活脚本： $activate`n请确认该环境是使用 venv/virtualenv 创建的，且路径正确。"
    return 1
}

Write-Host "正在激活虚拟环境： $Name ✅" -ForegroundColor Green

# 运行激活脚本
& $activate

Write-Host "激活完成。可运行 'python --version' 或 'pip list' 确认。" -ForegroundColor Green

