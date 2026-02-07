"""
Web Chat Server — 与 AIAssistant (PyQt) 共享对话的 WebSocket 服务
可独立运行，也可由 ai_assistant.py 集成启动。
"""

import threading, asyncio, json, time
from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO, emit

# ---------- Flask / SocketIO ----------
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = "ai-assistant-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ---------- 共享状态 ----------
_assistant_ref = None        # 指向 AIAssistant 实例
_chat_log: list[dict] = []   # [{sender, content, timestamp}, ...]


def set_assistant(assistant):
    """由 ai_assistant.py 启动时注入"""
    global _assistant_ref
    _assistant_ref = assistant


def broadcast_message(sender: str, content: str):
    """从 PyQt 端广播消息到所有 Web 客户端"""
    msg = {"sender": sender, "content": content, "timestamp": time.time()}
    _chat_log.append(msg)
    socketio.emit("chat_message", msg)


# ---------- Routes ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


# ---------- SocketIO Events ----------
@socketio.on("connect")
def handle_connect():
    # 发送历史记录给刚连接的客户端
    emit("chat_history", _chat_log)


@socketio.on("send_message")
def handle_send(data):
    user_text = data.get("message", "").strip()
    if not user_text:
        return

    if _assistant_ref is None:
        emit("chat_message", {
            "sender": "System",
            "content": "AI 助手尚未连接，请确认 ai_assistant.py 正在运行。",
            "timestamp": time.time(),
        })
        return

    # 广播用户消息
    broadcast_message("Web", user_text)
    # 通知 PyQt 端更新显示
    _assistant_ref.comm.append_chat.emit("Web", user_text)

    # 后台线程处理 AI 逻辑（复用 assistant 的方法）
    threading.Thread(
        target=_process_from_web, args=(user_text,), daemon=True
    ).start()


@socketio.on("clear_chat")
def handle_clear(_=None):
    global _chat_log
    _chat_log.clear()
    if _assistant_ref:
        # 通过信号安全地通知 PyQt 主线程清空对话，不能直接调用 Qt GUI 方法
        _assistant_ref.comm.append_chat.emit("__CLEAR__", "")
    socketio.emit("chat_cleared")


# ---------- AI 处理 ----------
def _process_from_web(user_input: str):
    """复用 AIAssistant 的 AI 逻辑，处理来自 Web 的消息"""
    a = _assistant_ref
    if a is None:
        return
    try:
        a.chat_history.append({"role": "user", "content": user_input})

        response = a.client.chat(
            model=a.model_name if hasattr(a, 'model_name') else "dengcao/Qwen3-30B-A3B-Instruct-2507",
            messages=a.chat_history,
            tools=a.tools,
            keep_alive=-1,
        )
        message = response.get("message", {})

        if message.get("tool_calls"):
            a.chat_history.append(message)
            for tool_call in message["tool_calls"]:
                t_name = tool_call["function"]["name"]
                t_args = tool_call["function"]["arguments"]
                print(f"[MCP Action via Web] 调用工具: {t_name} 参数: {t_args}")
                output = asyncio.run(a.call_mcp_tool(t_name, t_args))
                a.chat_history.append({"role": "tool", "content": str(output), "name": t_name})

            final = a.client.chat(
                model=a.model_name if hasattr(a, 'model_name') else "dengcao/Qwen3-30B-A3B-Instruct-2507",
                messages=a.chat_history,
            )
            final_content = final["message"]["content"]
            a.chat_history.append(final["message"])
        else:
            a.chat_history.append(message)
            final_content = message.get("content", "")

        # 同时广播到 Web 和 PyQt
        broadcast_message("AI", final_content)
        a.comm.append_chat.emit("AI", final_content)

    except Exception as e:
        err = f"Error: {e}"
        broadcast_message("System", err)
        a.comm.append_chat.emit("System Error", str(e))


# ---------- 启动 ----------
def start_server(host="0.0.0.0", port=5100):
    """在后台线程中启动 Flask-SocketIO 服务"""
    def _run():
        socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    print(f"🌐 Web Chat 服务已启动: http://{host}:{port}")
    return t


if __name__ == "__main__":
    # 独立调试模式
    print("⚠️  独立模式运行，AI 功能不可用。请通过 ai_assistant.py 启动以获得完整功能。")
    socketio.run(app, host="0.0.0.0", port=5100, debug=True, allow_unsafe_werkzeug=True)
