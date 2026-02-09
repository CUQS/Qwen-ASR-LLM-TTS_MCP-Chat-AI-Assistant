"""
Web Chat Server — 与 AIAssistant (PyQt) 共享对话的 WebSocket 服务
可独立运行，也可由 ai_assistant.py 集成启动。
支持 HTTPS（自签名证书），使局域网 / Tailscale 手机端可使用麦克风等安全 API。
"""

import threading, asyncio, json, time, os, ssl
from flask import Flask, render_template, send_from_directory, request
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


@socketio.on("voice_input")
def handle_voice_input(data):
    """接收来自 Web 端的语音输入 (PCM float32, 16kHz)"""
    if _assistant_ref is None:
        emit("voice_status", {"status": "error", "message": "AI 助手未连接"})
        return
    if not getattr(_assistant_ref, '_models_loaded', False):
        emit("voice_status", {"status": "error", "message": "语音模型尚未加载完成，请稍后再试"})
        return

    sid = request.sid

    def emit_fn(event, evt_data):
        socketio.emit(event, evt_data, to=sid)

    threading.Thread(
        target=_assistant_ref.web_voice_pipeline,
        args=(data, emit_fn),
        daemon=True,
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


# ---------- SSL 证书自动生成 ----------
_CERT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs")
_CERT_FILE = os.path.join(_CERT_DIR, "cert.pem")
_KEY_FILE = os.path.join(_CERT_DIR, "key.pem")


def _ensure_ssl_cert():
    """如果 certs/ 下没有证书则自动生成自签名证书（有效期 10 年）。
    优先使用 cryptography 库，回退到 openssl 命令行。
    """
    if os.path.isfile(_CERT_FILE) and os.path.isfile(_KEY_FILE):
        return True

    os.makedirs(_CERT_DIR, exist_ok=True)
    print("🔐 首次运行，正在生成自签名 HTTPS 证书...")

    # 方式 1: 使用 cryptography 库
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        import datetime, ipaddress, socket

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "AI-Assistant-Local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AI Assistant"),
        ])

        # SAN: 包含 localhost、局域网 IP、Tailscale 域名模式
        san_list = [
            x509.DNSName("localhost"),
            x509.DNSName("*.local"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            x509.IPAddress(ipaddress.IPv4Address("0.0.0.0")),
        ]
        # 添加本机所有可能的 IP（局域网 + Tailscale）
        try:
            hostname = socket.gethostname()
            for addr_info in socket.getaddrinfo(hostname, None):
                ip_str = addr_info[4][0]
                try:
                    san_list.append(x509.IPAddress(ipaddress.ip_address(ip_str)))
                except ValueError:
                    pass
        except Exception:
            pass
        # 探测常见局域网和 Tailscale 段
        for target in ["192.168.0.1", "10.0.0.1", "100.100.100.100"]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(0.5)
                s.connect((target, 80))
                local_ip = s.getsockname()[0]
                s.close()
                san_list.append(x509.IPAddress(ipaddress.ip_address(local_ip)))
            except Exception:
                pass

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow())
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
            .sign(key, hashes.SHA256())
        )

        with open(_KEY_FILE, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
        with open(_CERT_FILE, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        print("✅ 自签名证书已生成")
        return True

    except ImportError:
        pass

    # 方式 2: 回退到 openssl 命令行
    try:
        import subprocess
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", _KEY_FILE, "-out", _CERT_FILE,
            "-days", "3650", "-nodes",
            "-subj", "/CN=AI-Assistant-Local",
        ], check=True, capture_output=True)
        print("✅ 自签名证书已生成 (via openssl)")
        return True
    except Exception as e:
        print(f"⚠️  无法生成 SSL 证书: {e}")
        print("   手机端将无法使用麦克风功能。如需 HTTPS，请运行: pip install cryptography")
        return False


def _get_local_ip():
    """获取本机局域网 IP"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("192.168.0.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


# ---------- 启动 ----------
def start_server(host="0.0.0.0", port=5100, use_https=True):
    """在后台线程中启动 Flask-SocketIO 服务

    Args:
        host: 监听地址
        port: 监听端口
        use_https: 是否启用 HTTPS（手机端麦克风功能需要）
    """
    ssl_ctx = None
    scheme = "http"

    if use_https and _ensure_ssl_cert():
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(_CERT_FILE, _KEY_FILE)
        scheme = "https"

    def _run():
        socketio.run(
            app, host=host, port=port,
            ssl_context=ssl_ctx,
            allow_unsafe_werkzeug=True,
        )

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    local_ip = _get_local_ip()
    print(f"🌐 Web Chat 服务已启动:")
    print(f"   本机访问: {scheme}://localhost:{port}")
    if local_ip:
        print(f"   局域网访问: {scheme}://{local_ip}:{port}")
    if scheme == "https":
        print(f"   ⚠️  首次从手机访问时，浏览器会提示证书不安全，请选择『继续访问』或『高级 → 继续』")
    return t


if __name__ == "__main__":
    # 独立调试模式
    print("⚠️  独立模式运行，AI 功能不可用。请通过 ai_assistant.py 启动以获得完整功能。")
    ssl_ctx = None
    if _ensure_ssl_cert():
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(_CERT_FILE, _KEY_FILE)
    socketio.run(app, host="0.0.0.0", port=5100, debug=True,
                 ssl_context=ssl_ctx, allow_unsafe_werkzeug=True)
