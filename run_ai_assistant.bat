@echo off
REM run_ai_assistant.bat — 双击运行 ai_assistant.py（会尝试激活本地 venv）
cd /d "%~dp0"
echo 🚀 启动 AI Assistant （路径：%cd%）

REM 优先激活仓库内的 venv (.venv 或 venv)
if exist ".venv\Scripts\activate.bat" (
  call ".\.venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
  call ".\venv\Scripts\activate.bat"
) else (
  echo ⚠️ 未发现本地 venv (.venv 或 venv)。
  echo 如果要激活位于 D:\uv_venv 的虚拟环境，可在运行时传入环境名作为第一个参数（例如：run_ai_assistant.bat dev）。
)

REM 如果传入第一个参数，则尝试使用 uv.ps1 激活指定的 D:\uv_venv 环境并在同一 PowerShell 会话中运行 Python
if not "%~1"=="" if exist "uv.ps1" (
  echo 🔧 尝试通过 uv.ps1 激活虚拟环境: %~1
  powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\uv.ps1 %~1; python .\ai_assistant.py"
  goto :end
)

REM 默认直接用当前环境的 python 运行（若已在 venv 中则为激活后的环境）
python .\ai_assistant.py

:end


pausenecho ✅ AI Assistant 已退出。