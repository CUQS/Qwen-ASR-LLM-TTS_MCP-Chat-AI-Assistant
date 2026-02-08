<div align="center">

# Qwen3-ASR-LLM-TTS & MCP Chat AI Assistant

**A fully local, multilingual voice AI assistant for your Windows PC**

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/)
[![CUDA 12.8](https://img.shields.io/badge/CUDA-12.8-green?logo=nvidia&logoColor=white)](https://developer.nvidia.com/cuda-toolkit)
[![License](https://img.shields.io/badge/License-Open%20Source-brightgreen)](#)

</div>

---

> An easy-to-deploy multilingual AI assistant integrating
> [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR) for speech recognition,
> [Ollama](https://ollama.com/) + [Qwen3-30B-A3B](https://ollama.com/dengcao/Qwen3-30B-A3B-Instruct-2507) for LLM,
> [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) / [Kokoro](https://github.com/hexgrad/kokoro) for speech synthesis,
> and [MCP](https://github.com/modelcontextprotocol/python-sdk) for smart device control.

---

## ✨ Features

| Category | Highlights |
|---|---|
| **Speech Recognition** | Multilingual (Chinese / English / Japanese …) via Qwen3-ASR |
| **Language Model** | Powered by Qwen3-30B-A3B-Instruct-2507 through Ollama |
| **Speech Synthesis** | Natural & expressive TTS with Qwen3-TTS or Kokoro |
| **Smart Control** | MCP integration for IoT / smart device control |
| **Interaction** | Real-time streaming LLM + TTS voice conversation |
| **Interface** | Web UI + PyQt6 desktop debug app |
| **Hardware** | Runs on a single RTX 3090 24 GB GPU |

## 🔌 Implemented MCP Tools

| Tool | Description |
|---|---|
| [SwitchBot](https://github.com/OpenWonderLabs/SwitchBotAPI) | Smart home device control (example integration) |
| Weather | Real-time weather information query |
| Local Commands | Execute local system commands |

## 🖼️ Demo

<summary><b>Desktop Web UI</b></summary>

<img src="demo.png" alt="PC Demo" width="1080"/>

<summary><b>Mobile (via Tailscale)</b></summary>

Access the web GUI remotely from your phone using [Tailscale](https://tailscale.com/).

<img src="demo_phone.jpg" alt="Phone Demo" width="200"/>

---

## 🚀 Getting Started

### Prerequisites

- **OS:** Windows 10 / 11
- **GPU:** NVIDIA RTX 3090 (24 GB) or above
- **Python:** 3.12
- **Package Manager:** [uv](https://github.com/astral-sh/uv)

### 1. Create Environment

```bash
uv venv qwen-asr --python 3.12
```

### 2. Install Core Dependencies

```bash
# PyTorch + CUDA
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# Flash Attention (prebuilt wheel)
uv pip install --no-deps https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.7.13/flash_attn-2.8.3+cu128torch2.10-cp312-cp312-win_amd64.whl

# Transformers & utilities
uv pip install transformers==4.57. nagisa==0.2.11 soynlp==0.0.493 qwen-omni-utils
uv pip install sox flask pytz accelerate==1.12.0
```

### 3. Install ASR

```bash
cd ./Qwen3-ASR
uv pip install -e .
```

### 4. Install TTS

```bash
# Qwen3-TTS
uv pip install einops onnxruntime torchaudio
cd ./Qwen3-TTS/
uv pip install -e .

# Kokoro
uv pip install pip  # required first!
uv pip install loguru "misaki[zh]>=0.9.4"
uv pip install num2words spacy phonemizer espeakng_loader
cd ./kokoro
uv pip install -e .
```

### 5. Install AI Assistant

```bash
uv pip install requests beautifulsoup4 sounddevice
uv pip install PyQt6 ollama keyboard mcp flask_socketio
```

---

## 🎮 Usage

```bash
python ai_assistant.py
```

| Shortcut | Action |
|---|---|
| — | Open browser → `http://localhost:5100` |
| `Ctrl + Alt + Q` | Open PyQt6 debug app |
| `Ctrl + Alt + A` (hold) | Push-to-talk |
| `Ctrl + Alt + E` | Quit |

---

## 🖱️ Windows Quick Start

For convenience, two click-to-run scripts are included at the repository root: `run_ai_assistant.bat` and `run_ai_assistant.ps1`.

- `run_ai_assistant.bat`: double-click to run. It will try to activate a local `.venv`/`venv` if present, otherwise runs with system Python. You can pass an uv environment name to use `uv.ps1` (e.g. `run_ai_assistant.bat dev`) to activate `D:\uv_venv\dev`.

  - 中文：双击运行，优先激活仓库内的 `.venv` / `venv`；可在命令行传入 uv 环境名（例如 `run_ai_assistant.bat dev`）以通过 `uv.ps1` 激活 `D:\uv_venv` 下指定环境。

- `run_ai_assistant.ps1`: PowerShell launcher. Use `.
un_ai_assistant.ps1 -EnvName dev` to activate a named `D:\uv_venv` environment. Adjust execution policy if needed: `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`.

  - 中文：PowerShell 启动器，支持 `-EnvName` 参数，用于激活 `D:\uv_venv\<env>`；若受限请运行 `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`。

Note: The scripts keep the console open after exit so you can review logs.

---

## ⚠️ Notice

> Before running, update model paths and config paths in **kokoro** and **switchbot** to match your local setup.

---

## 📚 References

| Project | Link |
|---|---|
| Kokoro | <https://github.com/hexgrad/kokoro> |
| MCP Python SDK | <https://github.com/modelcontextprotocol/python-sdk> |
| Ollama | <https://ollama.com/> |
| Qwen3-ASR | <https://github.com/QwenLM/Qwen3-ASR> |
| Qwen3-TTS | <https://github.com/QwenLM/Qwen3-TTS> |
| SwitchBot API | <https://github.com/OpenWonderLabs/SwitchBotAPI> |
| Tailscale | <https://tailscale.com/> |
