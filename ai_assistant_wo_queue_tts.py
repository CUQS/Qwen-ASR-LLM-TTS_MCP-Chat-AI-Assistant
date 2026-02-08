import sys
import os
import threading
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

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# --- Web Chat 集成 ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'webpage_chat'))
from server import set_assistant, start_server as start_web_server, broadcast_message as web_broadcast

# --- 配置区 ---
REMOTE_OLLAMA_HOST = "http://192.168.40.12:11434" 
MODEL_NAME = "dengcao/Qwen3-30B-A3B-Instruct-2507"

# ASR / TTS 模型配置
ASR_MODEL_ID = "Qwen/Qwen3-ASR-0.6B"
TTS_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
TTS_SPEAKER = "Serena"
TTS_LANGUAGE = "Chinese"
RECORD_SAMPLE_RATE = 16000  # ASR 要求 16kHz

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
        if not self._models_loaded:
            self._load_voice_models()
            return
    
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

                print("[Voice] 开始加载 TTS 模型...")
                self.tts_model = Qwen3TTSModel.from_pretrained(
                    TTS_MODEL_ID,
                    device_map="cuda:0",
                    dtype=torch.bfloat16,
                )
                print("[Voice] TTS 模型加载完成")

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
        """语音对话全流程: ASR → LLM → TTS → 播放"""
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
            llm_input = user_text + "\n（尽量不要出现特殊符号，便于朗读）"
            self.chat_history.append({'role': 'user', 'content': llm_input})
            try:
                web_broadcast("Me 🎤", user_text)
            except Exception:
                pass

            response = self.client.chat(
                model=MODEL_NAME,
                messages=self.chat_history,
                tools=self.tools,
                keep_alive=-1
            )
            message = response.get('message', {})

            # 处理工具调用
            if message.get('tool_calls'):
                self.chat_history.append(message)
                for tool_call in message['tool_calls']:
                    t_name = tool_call['function']['name']
                    t_args = tool_call['function']['arguments']
                    print(f"[MCP Action] 正在调用工具: {t_name} 参数: {t_args}")
                    output = asyncio.run(self.call_mcp_tool(t_name, t_args))
                    self.chat_history.append({'role': 'tool', 'content': str(output), 'name': t_name})
                final_response = self.client.chat(model=MODEL_NAME, messages=self.chat_history)
                ai_content = final_response['message']['content']
                self.chat_history.append(final_response['message'])
            else:
                self.chat_history.append(message)
                ai_content = message.get('content', '')

            self.comm.append_chat.emit("AI", ai_content)
            try:
                web_broadcast("AI", ai_content)
            except Exception:
                pass

            # --- 3) TTS: 文字转语音 ---
            if ai_content.strip():
                self.comm.voice_status.emit("正在合成语音...")
                tts_lang = TTS_LANGUAGE
                wavs, sr = self.tts_model.generate_custom_voice(
                    text=ai_content,
                    language=tts_lang,
                    speaker=TTS_SPEAKER,
                )
                # 播放音频
                print(f"[Voice TTS] 播放音频 sr={sr}, samples={len(wavs[0])}")
                sd.play(wavs[0], samplerate=sr)
                sd.wait()  # 等待播放完成

        except Exception as e:
            self.comm.voice_status.emit(f"语音处理异常: {e}")
            print(f"[Voice] 异常: {e}")

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
