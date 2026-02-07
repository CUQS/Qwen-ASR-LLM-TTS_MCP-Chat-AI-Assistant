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
uv pip install einops
uv pip install onnxruntime
uv pip install torchaudio
cd ./Qwen3-TTS/
uv pip install -e .

# ai assistant
uv pip install PyQt6 ollama keyboard mcp
uv pip install flask_socketio
```