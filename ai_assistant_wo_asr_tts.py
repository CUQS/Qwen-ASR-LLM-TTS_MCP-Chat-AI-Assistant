import sys
import os
import threading
import keyboard
import ollama
import subprocess
import asyncio  # MCP 是异步的
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QTextEdit, 
                             QLineEdit, QPushButton, QHBoxLayout, QLabel, QCheckBox)
from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtGui import QTextDocument
import html

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# --- Web Chat 集成 ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'webpage_chat'))
from server import set_assistant, start_server as start_web_server, broadcast_message as web_broadcast

# --- 配置区 ---
REMOTE_OLLAMA_HOST = "http://192.168.40.12:11434" 
MODEL_NAME = "dengcao/Qwen3-30B-A3B-Instruct-2507"

class Communicator(QObject):
    trigger_show = pyqtSignal()
    append_chat = pyqtSignal(str, str) # 发送者, 内容
    request_exit = pyqtSignal()

class AIAssistant(QWidget):
    def __init__(self):
        super().__init__()
        self.comm = Communicator()
        self.client = ollama.Client(host=REMOTE_OLLAMA_HOST)
        self.model_name = MODEL_NAME
        
        # --- 对话上下文管理 ---
        self.chat_history = [] 

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

        # MCP 工具定义：由 local_tools.py 提供，运行时通过 sync_tools_from_mcp() 动态获取。
        # 初始留空，若同步失败会回退为最小的 `run_command` 工具。
        self.tools = []
    
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

    def handle_exit(self):
        print("助手正在退出...")
        QApplication.quit()

    def run_hotkey_listener(self):
        keyboard.add_hotkey('ctrl+alt+q', lambda: self.comm.trigger_show.emit())
        keyboard.add_hotkey('ctrl+alt+e', lambda: self.comm.request_exit.emit())
        print("助手已启动 (Ctrl+Alt+Q 唤起, Ctrl+Alt+E 退出)")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    assistant = AIAssistant()
    assistant.run_hotkey_listener()

    # 启动 Web Chat 服务（局域网可访问）
    set_assistant(assistant)
    start_web_server(host="0.0.0.0", port=5100)

    sys.exit(app.exec())
