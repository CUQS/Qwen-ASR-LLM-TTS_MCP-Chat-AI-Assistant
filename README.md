# Qwen3-ASR-LLM-TTS_MCP-Chat-AI-Assistant

![Demo](demo.png)

# ENV

```bash
uv venv qwen-asr --python 3.12
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
uv pip install --no-deps https://github.com/mjun0812/flash-attention-prebuild-wheels/releases/download/v0.7.13/flash_attn-2.8.3+cu128torch2.10-cp312-cp312-win_amd64.whl

uv pip install transformers==4.57.
uv pip install nagisa==0.2.11 
uv pip install soynlp==0.0.493
uv pip install qwen-omni-utils

uv pip install sox
uv pip install flask
uv pip install pytz

uv pip install accelerate==1.12.0

cd ./Qwen3-ASR
uv pip install -e .

# for tts
uv pip install einops onnxruntime torchaudio
cd ./Qwen3-TTS/
uv pip install -e .

# kokoro
uv pip install pip  # !!
uv pip install loguru
uv pip install misaki[zh]>=0.9.4
uv pip install num2words spacy phonemizer espeakng_loader
cd ./kokoro
uv pip install -e .

# ai assistant
uv pip install requests beautifulsoup4
uv pip install sounddevice
uv pip install PyQt6 ollama keyboard mcp
uv pip install flask_socketio
```