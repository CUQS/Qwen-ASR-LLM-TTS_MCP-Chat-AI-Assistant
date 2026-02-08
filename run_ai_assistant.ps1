Param(
    [string]$EnvName = ""
)

# run_ai_assistant.ps1 — PowerShell 版，可直接在 PowerShell 中运行并可激活仓库 venv 或 D:\uv_venv
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)
Write-Host "🚀 启动 ai_assistant.py （路径：$(Get-Location)）"

if (Test-Path .\.venv\Scripts\Activate.ps1) {
    Write-Host "🔧 激活 .venv..."
    & .\.venv\Scripts\Activate.ps1
} elseif (Test-Path .\venv\Scripts\Activate.ps1) {
    Write-Host "🔧 激活 venv..."
    & .\venv\Scripts\Activate.ps1
} elseif ($EnvName -and (Test-Path .\uv.ps1)) {
    Write-Host "🔧 通过 uv.ps1 激活 D:\uv_venv\$EnvName"
    & .\uv.ps1 $EnvName
} else {
    Write-Host "⚠️ 未发现本地 venv，直接使用当前 Python 环境。"
}

python .\ai_assistant.py
Write-Host "✅ AI Assistant 已退出。"
Pause
