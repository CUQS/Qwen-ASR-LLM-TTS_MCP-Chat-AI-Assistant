# run_ai_assistant.ps1 — PowerShell 版，可直接在 PowerShell 中运行并可激活仓库 venv 或 D:\uv_venv
$PythonExe = "D:\uv_venv\qwen-asr\Scripts\python.exe"

& $PythonExe .\ai_assistant_llm_streaming.py
Pause
