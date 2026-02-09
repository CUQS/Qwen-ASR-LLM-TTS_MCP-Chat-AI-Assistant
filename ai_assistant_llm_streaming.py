import sys
import os
import re
import threading
import queue
import keyboard
import ollama
import subprocess
import asyncio  # MCP 是异步的
import tempfile
import numpy as np
import sounddevice as sd
import soundfile as sf
import torch
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QTextEdit, 
                             QLineEdit, QPushButton, QHBoxLayout, QLabel, QCheckBox)
from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtGui import QTextDocument
import html

# --- ASR / TTS ---
from qwen_asr import Qwen3ASRModel
from qwen_tts import Qwen3TTSModel
from kokoro import KModel, KPipeline

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# --- Web Chat 集成 ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'webpage_chat'))
from server import set_assistant, start_server as start_web_server, broadcast_message as web_broadcast

# --- 配置区 ---
REMOTE_OLLAMA_HOST = "http://192.168.40.12:11434" 
MODEL_NAME = "dengcao/Qwen3-30B-A3B-Instruct-2507"

# TTS 引擎选择: "qwen" 或 "kokoro"
TTS_ENGINE = "kokoro"  # 设为 "kokoro" 可使用 Kokoro TTS

# ASR / TTS 模型配置
ASR_MODEL_ID = "Qwen/Qwen3-ASR-0.6B"
TTS_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
TTS_SPEAKER = "Serena"
TTS_LANGUAGE = "Chinese"
TTS_TOKEN_MAX_NUM = 100  # TTS 单句最大字符数，超过则继续拆分
RECORD_SAMPLE_RATE = 16000  # ASR 要求 16kHz

# Kokoro TTS 配置
KOKORO_REPO_ID = 'hexgrad/Kokoro-82M-v1.1-zh'
KOKORO_SAMPLE_RATE = 24000
KOKORO_VOICE = 'zf_001'  # zf_001 女声, zm_010 男声

# --- 句子拆分工具 ---
_PUNCT_PATTERN = re.compile(r'(?<=[。！？；\n!\?;])')
_SUB_PUNCT_PATTERN = re.compile(r'(?<=[，,、：:\-—])')

def split_sentences_for_tts(text: str, max_len: int = TTS_TOKEN_MAX_NUM) -> list[str]:
    """按标点将文本拆分为适合 TTS 的短句列表。

    1. 先按句末标点（。！？；!?;\n）拆分。
    2. 若某段仍超过 max_len，则按次级标点（，,、：:—）继续拆分。
    3. 若仍超过 max_len，则对半切割，直到每段 <= max_len。
    """
    if not text or not text.strip():
        return []

    # 第一轮：按主要句末标点拆分
    chunks = _PUNCT_PATTERN.split(text)
    chunks = [c.strip() for c in chunks if c.strip()]

    # 第二轮：对超长段按次级标点拆分
    result = []
    for chunk in chunks:
        if len(chunk) <= max_len:
            result.append(chunk)
        else:
            sub_chunks = _SUB_PUNCT_PATTERN.split(chunk)
            sub_chunks = [s.strip() for s in sub_chunks if s.strip()]
            for sc in sub_chunks:
                if len(sc) <= max_len:
                    result.append(sc)
                else:
                    # 递归对半拆分
                    result.extend(_force_split(sc, max_len))
    return result

def _force_split(text: str, max_len: int) -> list[str]:
    """无合适标点时，对半拆分直到每段 <= max_len"""
    if len(text) <= max_len:
        return [text]
    mid = len(text) // 2
    # 尽量在中间附近的空格或标点处切割
    best = mid
    for offset in range(min(20, mid)):
        for pos in (mid + offset, mid - offset):
            if 0 < pos < len(text) and text[pos] in ' ，,。！？；、：!?; \n':
                best = pos + 1
                break
        else:
            continue
        break
    left = text[:best].strip()
    right = text[best:].strip()
    parts = []
    if left:
        parts.extend(_force_split(left, max_len))
    if right:
        parts.extend(_force_split(right, max_len))
    return parts

class Communicator(QObject):
    trigger_show = pyqtSignal()
    append_chat = pyqtSignal(str, str) # 发送者, 内容
    request_exit = pyqtSignal()
    voice_status = pyqtSignal(str)  # 语音状态提示

class AIAssistant(QWidget):
    def __init__(self):
        super().__init__()
        self.comm = Communicator()
        self.client = ollama.Client(host=REMOTE_OLLAMA_HOST)
        self.model_name = MODEL_NAME
        
        # --- 对话上下文管理 ---
        self.chat_history = []

        # --- 语音录制状态 ---
        self._recording = False
        self._recorded_frames = []

        # --- ASR / TTS 模型（延迟加载） ---
        self.asr_model = None
        self.tts_model = None
        self.kokoro_model = None
        self.kokoro_pipeline = None
        self._models_loaded = False
        self._models_loading = False

        # --- MCP 配置 ---
        self.server_params = StdioServerParameters(
            command="python",
            args=["local_tools.py"], # 确保路径正确
        )

        # --- UI 初始化 ---
        self.init_ui()

        # 初始时尝试同步一次工具列表
        self.sync_tools_from_mcp()
        
        # --- 信号绑定 ---
        self.comm.trigger_show.connect(self.show_and_focus)
        self.comm.append_chat.connect(self.update_chat_display)
        self.comm.request_exit.connect(self.handle_exit)
        self.comm.voice_status.connect(lambda msg: self.update_chat_display("System", msg))

        # MCP 工具定义：由 local_tools.py 提供，运行时通过 sync_tools_from_mcp() 动态获取。
        # 初始留空，若同步失败会回退为最小的 `run_command` 工具。
        self.tools = []

        # --- 初始化 ASR 和 TTS 模型 ---
        print("正在后台加载 ASR 和 TTS 模型...")
        self._load_voice_models()
        
        print("AI Assistant 初始化完成。")
    
    def sync_tools_from_mcp(self):
        """从 MCP Server 动态获取工具定义，同步给 Ollama"""
        async def fetch():
            async with stdio_client(self.server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    try:
                        await session.initialize()
                        tools = await session.list_tools()
                        # 将 MCP 的工具格式转换为 Ollama 需要的格式
                        self.tools = []
                        for t in tools.tools:
                            self.tools.append({
                                'type': 'function',
                                'function': {
                                    'name': t.name,
                                    'description': t.description,
                                    'parameters': t.inputSchema
                                }
                            })
                        print(f"成功同步工具: {[t['function']['name'] for t in self.tools]}")
                    except Exception as e:
                        print(f"同步工具失败，使用回退 run_command：{e}")
                        # 设置最小回退工具（与 local_tools.py 中的 run_command 对应）
                        self.tools = [{
                            'type': 'function',
                            'function': {
                                'name': 'run_command',
                                'description': '在本地电脑执行终端命令',
                                'parameters': {
                                    'type': 'object',
                                    'properties': {
                                        'command': {'type': 'string', 'description': '要执行的 CMD 命令'},
                                    },
                                    'required': ['command'],
                                },
                            },
                        }]

        threading.Thread(target=lambda: asyncio.run(fetch()), daemon=True).start()

    # --- 核心逻辑：调用 MCP 工具 ---
    async def call_mcp_tool(self, tool_name, arguments):
        """通过 MCP 标准接口调用本地工具"""
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                # result.content 通常是一个 list，里面有 text 字段
                return result.content[0].text if result.content else "No output"

    def init_ui(self):
        self.setWindowTitle("AI Research Assistant (Multi-turn)")
        self.setFixedSize(500, 600)
        # 窗口置顶，方便随时唤起
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout()

        # 1. 聊天记录显示区
        self.display = QTextEdit()
        self.display.setReadOnly(True)
        layout.addWidget(QLabel("Chat History:"))
        layout.addWidget(self.display)

        # 2. 输入区
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("输入消息... (输入'结束对话'清空记录)")
        self.input_field.returnPressed.connect(self.handle_send)
        
        # 3. 按钮区
        btn_layout = QHBoxLayout()
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.handle_send)
        self.clear_btn = QPushButton("结束当前对话")
        self.clear_btn.clicked.connect(self.reset_chat)
        self.md_checkbox = QCheckBox("渲染 Markdown")
        self.md_checkbox.setChecked(True)
        
        btn_layout.addWidget(self.send_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addWidget(self.md_checkbox)
        
        layout.addWidget(self.input_field)
        layout.addLayout(btn_layout)
        
        self.setLayout(layout)

    # --- 逻辑处理 ---
    def show_and_focus(self):
        self.show()
        self.activateWindow()
        self.input_field.setFocus()

    def update_chat_display(self, sender, content):
        # 拦截来自 Web 端的清空信号
        if sender == "__CLEAR__":
            self.reset_chat()
            return

        color = "#2c3e50" if sender == "AI" else "#2980b9"
        # 根据复选框决定是否渲染 Markdown
        if getattr(self, 'md_checkbox', None) and self.md_checkbox.isChecked():
            doc = QTextDocument()
            doc.setMarkdown(content)
            content_html = doc.toHtml()
        else:
            content_html = html.escape(content).replace('\n', '<br>')
        self.display.append(f"<b style='color:{color}'>{sender}:</b> {content_html}<br>")
        # 自动滚动到底部
        self.display.verticalScrollBar().setValue(self.display.verticalScrollBar().maximum())

    def reset_chat(self):
        self.chat_history = []
        self.display.clear()
        self.update_chat_display("System", "对话上下文已清空。")

    def handle_send(self):
        user_text = self.input_field.text().strip()
        if not user_text:
            return
        
        if user_text in ["结束对话", "exit", "clear", "quit"]:
            self.reset_chat()
            self.input_field.clear()
            return

        self.update_chat_display("Me", user_text)
        self.input_field.clear()
        self.input_field.setEnabled(False) # 防止重复发送
        
        # 开启后台线程处理 AI 逻辑
        threading.Thread(target=self.process_ai_logic, args=(user_text,), daemon=True).start()

    def process_ai_logic(self, user_input, from_web=False):
        try:
            # 加入上下文
            self.chat_history.append({'role': 'user', 'content': user_input})

            # 如果来自 PyQt 端，同步用户消息到 Web
            if not from_web:
                try:
                    web_broadcast("Me", user_input)
                except Exception:
                    pass
            
            # 1. 第一轮请求 (含 Tool 调用判断)
            response = self.client.chat(
                model=MODEL_NAME,
                messages=self.chat_history,
                tools=self.tools,
                keep_alive=-1
            )

            message = response.get('message', {})
            
            # 2. 处理工具链式调用
            if message.get('tool_calls'):
                self.chat_history.append(message) # 记录模型的 tool_call 请求
                
                for tool_call in message['tool_calls']:
                    t_name = tool_call['function']['name']
                    t_args = tool_call['function']['arguments']

                    print(f"[MCP Action] 正在调用工具: {t_name} 参数: {t_args}")

                    output = asyncio.run(self.call_mcp_tool(t_name, t_args))

                    self.chat_history.append({
                        'role': 'tool', 
                        'content': str(output), 
                        'name': t_name
                    })

                # 3. 再次请求获取最终回复
                final_response = self.client.chat(model=MODEL_NAME, messages=self.chat_history)
                final_content = final_response['message']['content']
                self.chat_history.append(final_response['message'])
                self.comm.append_chat.emit("AI", final_content)
                # 同步 AI 回复到 Web
                if not from_web:
                    try:
                        web_broadcast("AI", final_content)
                    except Exception:
                        pass
            else:
                # 普通对话
                self.chat_history.append(message)
                ai_content = message.get('content', '')
                self.comm.append_chat.emit("AI", ai_content)
                # 同步 AI 回复到 Web
                if not from_web:
                    try:
                        web_broadcast("AI", ai_content)
                    except Exception:
                        pass

        except Exception as e:
            self.comm.append_chat.emit("System Error", str(e))
        finally:
            self.input_field.setEnabled(True)
            self.input_field.setFocus()

    # ==================== 语音交互功能 ====================

    def _load_voice_models(self):
        """后台加载 ASR 和 TTS 模型（首次使用时触发）"""
        if self._models_loaded or self._models_loading:
            return
        self._models_loading = True
        self.comm.voice_status.emit("正在加载 ASR 和 TTS 模型，请稍候...")

        def _load():
            try:
                print("[Voice] 开始加载 ASR 模型...")
                self.asr_model = Qwen3ASRModel.from_pretrained(
                    ASR_MODEL_ID,
                    dtype=torch.bfloat16,
                    device_map="cuda:0",
                    max_inference_batch_size=32,
                    max_new_tokens=256,
                )
                print("[Voice] ASR 模型加载完成")

                if TTS_ENGINE == "kokoro":
                    print("[Voice] 开始加载 Kokoro TTS 模型...")
                    device = 'cuda' if torch.cuda.is_available() else 'cpu'
                    self.kokoro_model = KModel(repo_id=KOKORO_REPO_ID).to(device).eval()
                    en_pipeline = KPipeline(lang_code='a', repo_id=KOKORO_REPO_ID, model=False)
                    def en_callable(text):
                        return next(en_pipeline(text)).phonemes
                    self.kokoro_pipeline = KPipeline(
                        lang_code='z', repo_id=KOKORO_REPO_ID,
                        model=self.kokoro_model, en_callable=en_callable,
                    )
                    print("[Voice] Kokoro TTS 模型加载完成")
                else:
                    print("[Voice] 开始加载 Qwen TTS 模型...")
                    self.tts_model = Qwen3TTSModel.from_pretrained(
                        TTS_MODEL_ID,
                        device_map="cuda:0",
                        dtype=torch.bfloat16,
                    )
                    print("[Voice] Qwen TTS 模型加载完成")

                self._models_loaded = True
                self.comm.voice_status.emit("ASR / TTS 模型加载完毕，可以使用语音对话了。")
            except Exception as e:
                self.comm.voice_status.emit(f"模型加载失败: {e}")
                print(f"[Voice] 模型加载异常: {e}")
            finally:
                self._models_loading = False

        threading.Thread(target=_load, daemon=True).start()

    def _on_voice_key_press(self):
        """Ctrl+Alt+A 按下 → 开始录音"""
        if self._recording:
            return
        self._recording = True
        self._recorded_frames = []
        self.comm.voice_status.emit("🎙️ 正在录音... 松开 Ctrl+Alt+A 停止")
        print("[Voice] 开始录音")

        def _record_callback(indata, frames, time_info, status):
            if self._recording:
                self._recorded_frames.append(indata.copy())

        self._audio_stream = sd.InputStream(
            samplerate=RECORD_SAMPLE_RATE,
            channels=1,
            dtype='float32',
            callback=_record_callback,
        )
        self._audio_stream.start()

    def _on_voice_key_release(self):
        """Ctrl+Alt+A 松开 → 停止录音，启动 ASR→LLM→TTS 流水线"""
        if not self._recording:
            return
        self._recording = False
        print("[Voice] 停止录音")

        try:
            self._audio_stream.stop()
            self._audio_stream.close()
        except Exception:
            pass

        if not self._recorded_frames:
            self.comm.voice_status.emit("未检测到音频输入。")
            return

        audio_data = np.concatenate(self._recorded_frames, axis=0).flatten()
        self._recorded_frames = []

        # 后台执行 ASR → LLM → TTS
        threading.Thread(target=self._voice_pipeline, args=(audio_data,), daemon=True).start()

    def _voice_pipeline(self, audio_data: np.ndarray):
        """语音对话全流程: ASR → LLM(Streaming) → TTS → 播放
        
        三级流水线架构:
          Thread-1: LLM streaming，遇到标点就拆句推入 sentence_queue
          Thread-2: 从 sentence_queue 取句子，合成 TTS 音频推入 audio_chunk_queue
          Thread-3: 从 audio_chunk_queue 取音频块，OutputStream 实时播放
        """
        try:
            # --- 1) ASR: 语音转文字 ---
            self.comm.voice_status.emit("正在识别语音...")
            tmp_wav = os.path.join(tempfile.gettempdir(), "_voice_input.wav")
            sf.write(tmp_wav, audio_data, RECORD_SAMPLE_RATE)

            results = self.asr_model.transcribe(
                audio=tmp_wav,
                language=None,
            )
            user_text = results[0].text.strip()
            detected_lang = results[0].language
            print(f"[Voice ASR] 语言={detected_lang}, 文字={user_text}")

            if not user_text:
                self.comm.voice_status.emit("未识别到有效语音。")
                return

            # 显示识别结果
            self.comm.append_chat.emit("Me 🎤", user_text)

            # --- 2) LLM ---
            llm_input = user_text + "\n（回复中尽量不要出现特殊符号，用文字表述便于朗读）"
            self.chat_history.append({'role': 'user', 'content': llm_input})
            try:
                web_broadcast("Me 🎤", user_text)
            except Exception:
                pass

            # --- 2-b) LLM Streaming + 3) TTS 流式合成播放 ---
            # 三级流水线: LLM streaming → sentence_queue → TTS → audio_chunk_queue → 播放
            # 遇到标点就把已累积文本发给 TTS，无需等 LLM 生成完毕

            _split_punct = set('。！？；!?;\n，,、：:')

            sentence_queue = queue.Queue()          # LLM → TTS
            audio_chunk_queue = queue.Queue(maxsize=64)  # TTS → Player
            SENTINEL = None
            sr_holder = [None]
            sr_ready = threading.Event()
            full_content_holder = [""]              # 收集完整回复

            # ---------- Thread-1: LLM Streaming → sentence_queue ----------
            def _flush_buffer(buf):
                """将 buffer 中的文本拆句后推入 sentence_queue，返回空串"""
                if buf.strip():
                    for s in split_sentences_for_tts(buf.strip(), TTS_TOKEN_MAX_NUM):
                        sentence_queue.put(s)
                        print(f"[LLM Stream] → TTS: {s}")
                return ""

            def _stream_response(stream_iter):
                """从 streaming iterator 中读取 delta，遇到标点就拆句推入队列。
                返回 (full_content, tool_calls_list)"""
                buf = ""
                full = ""
                tc_list = []
                for chunk in stream_iter:
                    msg = chunk.get('message', {})
                    # 收集 tool_calls
                    if msg.get('tool_calls'):
                        tc_list.extend(msg['tool_calls'])
                    delta = msg.get('content', '')
                    if not delta:
                        continue
                    buf += delta
                    full += delta
                    # 找 buffer 中最后一个标点位置
                    last_punct = -1
                    for i, ch in enumerate(buf):
                        if ch in _split_punct:
                            last_punct = i
                    if last_punct >= 0:
                        sentence = buf[:last_punct + 1].strip()
                        buf = buf[last_punct + 1:]
                        if sentence:
                            for s in split_sentences_for_tts(sentence, TTS_TOKEN_MAX_NUM):
                                sentence_queue.put(s)
                                print(f"[LLM Stream] → TTS: {s}")
                # 剩余 buffer
                buf = _flush_buffer(buf)
                return full, tc_list

            def llm_streaming_producer():
                try:
                    # 第一轮 streaming（含 Tool 调用检测）
                    stream1 = self.client.chat(
                        model=MODEL_NAME,
                        messages=self.chat_history,
                        tools=self.tools,
                        stream=True,
                        keep_alive=-1,
                    )
                    content1, tool_calls = _stream_response(stream1)

                    if tool_calls:
                        # 记录模型的 tool_call 请求
                        self.chat_history.append({
                            'role': 'assistant',
                            'content': content1,
                            'tool_calls': tool_calls,
                        })
                        for tc in tool_calls:
                            t_name = tc['function']['name']
                            t_args = tc['function']['arguments']
                            print(f"[MCP Action] 调用工具: {t_name} 参数: {t_args}")
                            output = asyncio.run(self.call_mcp_tool(t_name, t_args))
                            self.chat_history.append({
                                'role': 'tool', 'content': str(output), 'name': t_name
                            })

                        # 第二轮 streaming（获取最终回复）
                        stream2 = self.client.chat(
                            model=MODEL_NAME,
                            messages=self.chat_history,
                            stream=True,
                        )
                        content2, _ = _stream_response(stream2)
                        self.chat_history.append({'role': 'assistant', 'content': content2})
                        full_content_holder[0] = content2
                    else:
                        # 普通对话，内容已在 streaming 过程中推入队列
                        self.chat_history.append({'role': 'assistant', 'content': content1})
                        full_content_holder[0] = content1
                except Exception as e:
                    print(f"[LLM Stream] 异常: {e}")
                finally:
                    sentence_queue.put(SENTINEL)  # 通知 TTS 生产者结束

            # ---------- Thread-2: sentence_queue → TTS → audio_chunk_queue ----------
            def tts_producer():
                """从 sentence_queue 读取句子，合成 TTS，推入 audio_chunk_queue"""
                CHUNK_SAMPLES = 4800  # 约 200ms @24kHz
                tts_lang = TTS_LANGUAGE
                i = 0
                while True:
                    sentence = sentence_queue.get()
                    if sentence is SENTINEL:
                        break
                    i += 1
                    try:
                        self.comm.voice_status.emit(f"正在合成语音 ({i})...")
                        if TTS_ENGINE == "kokoro":
                            def speed_callable(len_ps):
                                speed = 0.8
                                if len_ps <= 83:
                                    speed = 1
                                elif len_ps < 183:
                                    speed = 1 - (len_ps - 83) / 500
                                return speed * 1.5
                            generator = self.kokoro_pipeline(
                                sentence, voice=KOKORO_VOICE, speed=speed_callable,
                            )
                            result = next(generator)
                            wav = result.audio
                            if isinstance(wav, torch.Tensor):
                                wav = wav.cpu().numpy()
                            sr = KOKORO_SAMPLE_RATE
                        else:
                            wavs, sr = self.tts_model.generate_custom_voice(
                                text=sentence,
                                language=tts_lang,
                                speaker=TTS_SPEAKER,
                            )
                            wav = wavs[0]
                        # 首次拿到 sr 后通知播放线程
                        if sr_holder[0] is None:
                            sr_holder[0] = sr
                            sr_ready.set()
                        # 将整段音频切成小块推入队列
                        offset = 0
                        while offset < len(wav):
                            chunk = wav[offset:offset + CHUNK_SAMPLES]
                            audio_chunk_queue.put(chunk)
                            offset += CHUNK_SAMPLES
                        print(f"[Voice TTS] 合成完成 ({i}): {sentence}")
                    except Exception as e:
                        print(f"[Voice TTS] 合成第 {i} 段失败: {e}")
                audio_chunk_queue.put(SENTINEL)

            # ---------- Thread-3: audio_chunk_queue → OutputStream 播放 ----------
            def audio_player():
                """使用 sd.OutputStream 从队列流式播放音频"""
                sr_ready.wait()
                sr = sr_holder[0]
                PLAYBACK_BLOCK = 1024

                buffer = np.array([], dtype=np.float32)
                finished = False

                def callback(outdata, frames, time_info, status):
                    nonlocal buffer, finished
                    needed = frames
                    while len(buffer) < needed and not finished:
                        try:
                            chunk = audio_chunk_queue.get_nowait()
                            if chunk is SENTINEL:
                                finished = True
                                break
                            buffer = np.concatenate([buffer, chunk.astype(np.float32)])
                        except queue.Empty:
                            break

                    if len(buffer) >= needed:
                        outdata[:, 0] = buffer[:needed]
                        buffer = buffer[needed:]
                    else:
                        avail = len(buffer)
                        outdata[:avail, 0] = buffer[:avail]
                        outdata[avail:, 0] = 0.0
                        buffer = np.array([], dtype=np.float32)
                        if finished:
                            raise sd.CallbackStop()

                with sd.OutputStream(
                    samplerate=sr, channels=1, dtype='float32',
                    blocksize=PLAYBACK_BLOCK, callback=callback,
                ) as stream:
                    while stream.active:
                        if not finished:
                            try:
                                chunk = audio_chunk_queue.get(timeout=0.05)
                                if chunk is SENTINEL:
                                    finished = True
                                else:
                                    buffer = np.concatenate([buffer, chunk.astype(np.float32)])
                            except queue.Empty:
                                pass
                        else:
                            sd.sleep(50)
                print("[Voice TTS] OutputStream 播放结束")

            # 启动三级流水线
            llm_thread = threading.Thread(target=llm_streaming_producer, daemon=True)
            tts_thread = threading.Thread(target=tts_producer, daemon=True)
            player_thread = threading.Thread(target=audio_player, daemon=True)
            llm_thread.start()
            tts_thread.start()
            player_thread.start()

            llm_thread.join()
            # LLM 完毕，更新 UI 和 Web
            ai_content = full_content_holder[0]
            if ai_content:
                self.comm.append_chat.emit("AI", ai_content)
                try:
                    web_broadcast("AI", ai_content)
                except Exception:
                    pass

            tts_thread.join()
            player_thread.join()
            self.comm.voice_status.emit("语音播放完毕。")

        except Exception as e:
            self.comm.voice_status.emit(f"语音处理异常: {e}")
            print(f"[Voice] 异常: {e}")

    # ==================== Web 端语音对话 ====================

    def web_voice_pipeline(self, audio_bytes, emit_fn):
        """Web 端语音对话全流程: ASR → LLM(Streaming) → TTS → 流式推送音频到浏览器

        emit_fn(event, data): 向指定 Web 客户端发送 Socket.IO 事件
        Events:
            voice_status:      {"status": str, "message": str}
            voice_asr_result:  {"text": str}
            voice_audio_start: {"sampleRate": int}
            voice_audio_chunk: bytes (PCM float32)
            voice_audio_end:   {}
        """
        try:
            if not self._models_loaded:
                emit_fn("voice_status", {"status": "error", "message": "语音模型尚未加载完成，请稍后再试"})
                return

            # --- 1) 解码 PCM → ASR ---
            audio_data = np.frombuffer(audio_bytes, dtype=np.float32)
            if len(audio_data) < RECORD_SAMPLE_RATE * 0.3:  # 不足 0.3 秒
                emit_fn("voice_status", {"status": "done", "message": "录音时间太短"})
                return

            emit_fn("voice_status", {"status": "asr", "message": "正在识别语音..."})

            tmp_wav = os.path.join(tempfile.gettempdir(), "_web_voice_input.wav")
            sf.write(tmp_wav, audio_data, RECORD_SAMPLE_RATE)

            results = self.asr_model.transcribe(audio=tmp_wav, language=None)
            user_text = results[0].text.strip()
            print(f"[Web Voice ASR] 文字={user_text}")

            if not user_text:
                emit_fn("voice_status", {"status": "done", "message": "未识别到有效语音"})
                return

            emit_fn("voice_asr_result", {"text": user_text})

            # 广播用户消息到 PyQt 和 Web
            self.comm.append_chat.emit("Me 🎤", user_text)
            try:
                web_broadcast("Me 🎤", user_text)
            except Exception:
                pass

            # --- 2) LLM Streaming + TTS → 流式推送音频 ---
            emit_fn("voice_status", {"status": "llm", "message": "AI 思考中..."})

            llm_input = user_text + "\n（回复中尽量不要出现特殊符号，用文字表述便于朗读）"
            self.chat_history.append({'role': 'user', 'content': llm_input})

            _split_punct = set('。！？；!?;\n，,、：:')
            sentence_queue = queue.Queue()
            SENTINEL = None
            full_content_holder = [""]
            sr_sent = [False]

            # --- Thread-1: LLM Streaming → sentence_queue ---
            def _flush_buffer(buf):
                if buf.strip():
                    for s in split_sentences_for_tts(buf.strip(), TTS_TOKEN_MAX_NUM):
                        sentence_queue.put(s)
                        print(f"[Web LLM Stream] → TTS: {s}")
                return ""

            def _stream_response(stream_iter):
                buf = ""
                full = ""
                tc_list = []
                for chunk in stream_iter:
                    msg = chunk.get('message', {})
                    if msg.get('tool_calls'):
                        tc_list.extend(msg['tool_calls'])
                    delta = msg.get('content', '')
                    if not delta:
                        continue
                    buf += delta
                    full += delta
                    last_punct = -1
                    for i, ch in enumerate(buf):
                        if ch in _split_punct:
                            last_punct = i
                    if last_punct >= 0:
                        sentence = buf[:last_punct + 1].strip()
                        buf = buf[last_punct + 1:]
                        if sentence:
                            for s in split_sentences_for_tts(sentence, TTS_TOKEN_MAX_NUM):
                                sentence_queue.put(s)
                                print(f"[Web LLM Stream] → TTS: {s}")
                buf = _flush_buffer(buf)
                return full, tc_list

            def llm_streaming_producer():
                try:
                    stream1 = self.client.chat(
                        model=MODEL_NAME,
                        messages=self.chat_history,
                        tools=self.tools,
                        stream=True,
                        keep_alive=-1,
                    )
                    content1, tool_calls = _stream_response(stream1)

                    if tool_calls:
                        self.chat_history.append({
                            'role': 'assistant',
                            'content': content1,
                            'tool_calls': tool_calls,
                        })
                        for tc in tool_calls:
                            t_name = tc['function']['name']
                            t_args = tc['function']['arguments']
                            print(f"[Web MCP Action] 调用工具: {t_name} 参数: {t_args}")
                            output = asyncio.run(self.call_mcp_tool(t_name, t_args))
                            self.chat_history.append({
                                'role': 'tool', 'content': str(output), 'name': t_name
                            })
                        stream2 = self.client.chat(
                            model=MODEL_NAME,
                            messages=self.chat_history,
                            stream=True,
                        )
                        content2, _ = _stream_response(stream2)
                        self.chat_history.append({'role': 'assistant', 'content': content2})
                        full_content_holder[0] = content2
                    else:
                        self.chat_history.append({'role': 'assistant', 'content': content1})
                        full_content_holder[0] = content1
                except Exception as e:
                    print(f"[Web LLM Stream] 异常: {e}")
                finally:
                    sentence_queue.put(SENTINEL)

            # --- Thread-2: sentence_queue → TTS → emit audio chunks ---
            def tts_web_producer():
                i = 0
                while True:
                    sentence = sentence_queue.get()
                    if sentence is SENTINEL:
                        break
                    i += 1
                    try:
                        emit_fn("voice_status", {"status": "tts", "message": f"正在合成语音 ({i})..."})

                        if TTS_ENGINE == "kokoro":
                            def speed_callable(len_ps):
                                speed = 0.8
                                if len_ps <= 83:
                                    speed = 1
                                elif len_ps < 183:
                                    speed = 1 - (len_ps - 83) / 500
                                return speed * 1.5

                            generator = self.kokoro_pipeline(
                                sentence, voice=KOKORO_VOICE, speed=speed_callable,
                            )
                            result = next(generator)
                            wav = result.audio
                            if isinstance(wav, torch.Tensor):
                                wav = wav.cpu().numpy()
                            sr = KOKORO_SAMPLE_RATE
                        else:
                            wavs, sr = self.tts_model.generate_custom_voice(
                                text=sentence,
                                language=TTS_LANGUAGE,
                                speaker=TTS_SPEAKER,
                            )
                            wav = wavs[0]

                        # 首次发送采样率
                        if not sr_sent[0]:
                            emit_fn("voice_audio_start", {"sampleRate": sr})
                            sr_sent[0] = True

                        # 发送 PCM 音频数据
                        wav_f32 = wav.astype(np.float32)
                        emit_fn("voice_audio_chunk", wav_f32.tobytes())
                        print(f"[Web Voice TTS] 合成完成 ({i}): {sentence[:30]}...")

                    except Exception as e:
                        print(f"[Web Voice TTS] 合成第 {i} 段失败: {e}")

                emit_fn("voice_audio_end", {})

            # 启动两级流水线
            llm_thread = threading.Thread(target=llm_streaming_producer, daemon=True)
            tts_thread = threading.Thread(target=tts_web_producer, daemon=True)
            llm_thread.start()
            tts_thread.start()

            llm_thread.join()
            # LLM 完毕，更新 UI
            ai_content = full_content_holder[0]
            if ai_content:
                self.comm.append_chat.emit("AI", ai_content)
                try:
                    web_broadcast("AI", ai_content)
                except Exception:
                    pass

            tts_thread.join()

        except Exception as e:
            emit_fn("voice_status", {"status": "error", "message": f"语音处理异常: {e}"})
            print(f"[Web Voice] 异常: {e}")

    def handle_exit(self):
        print("助手正在退出...")
        QApplication.quit()

    def run_hotkey_listener(self):
        keyboard.add_hotkey('ctrl+alt+q', lambda: self.comm.trigger_show.emit())
        keyboard.add_hotkey('ctrl+alt+e', lambda: self.comm.request_exit.emit())
        # 语音快捷键：按下开始录音，松开停止
        keyboard.on_press_key('a', lambda e: self._on_voice_key_press() if keyboard.is_pressed('ctrl') and keyboard.is_pressed('alt') else None)
        keyboard.on_release_key('a', lambda e: self._on_voice_key_release() if not keyboard.is_pressed('a') else None)
        print("助手已启动 (Ctrl+Alt+Q 唤起, Ctrl+Alt+E 退出, Ctrl+Alt+A 语音对话)")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    assistant = AIAssistant()
    assistant.run_hotkey_listener()

    # 启动 Web Chat 服务（局域网可访问）
    set_assistant(assistant)
    start_web_server(host="0.0.0.0", port=5100)

    sys.exit(app.exec())
