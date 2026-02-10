// ===== 自动 HTTPS 跳转（手机端需要 HTTPS 才能使用麦克风） =====
if (window.location.protocol === "http:" && window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
  // 非 localhost 且不是 HTTPS → 自动跳转
  window.location.href = window.location.href.replace(/^http:/, "https:");
}

// ===== Socket.IO 连接 =====
const socket = io();

// ===== DOM =====
const chatArea     = document.getElementById("chatArea");
const messagesDiv  = document.getElementById("messages");
const welcomeDiv   = document.getElementById("welcomeScreen");
const msgInput     = document.getElementById("msgInput");
const sendBtn      = document.getElementById("sendBtn");
const clearBtn     = document.getElementById("clearBtn");
const themeToggle  = document.getElementById("themeToggle");
const statusDot    = document.querySelector(".status-dot");
const statusText   = document.querySelector(".status-text");

// ===== Marked 配置 =====
marked.setOptions({
  highlight: (code, lang) => {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value;
    }
    return hljs.highlightAuto(code).value;
  },
  breaks: true,
  gfm: true,
});

// ===== 主题 =====
function initTheme() {
  const saved = localStorage.getItem("theme") || "light";
  document.documentElement.setAttribute("data-theme", saved);
  updateThemeIcon(saved);
}

function updateThemeIcon(theme) {
  const moonIcon = document.querySelector(".icon-moon");
  const sunIcon  = document.querySelector(".icon-sun");
  if (theme === "dark") {
    moonIcon.style.display = "none";
    sunIcon.style.display  = "block";
  } else {
    moonIcon.style.display = "block";
    sunIcon.style.display  = "none";
  }
}

themeToggle.addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("theme", next);
  updateThemeIcon(next);
});

initTheme();

// ===== 自动请求麦克风权限（页面加载时） =====
window.addEventListener('DOMContentLoaded', async () => {
  try {
    const res = await checkMicPermission();
    if (!res.ok) {
      console.warn('麦克风权限检查:', res.reason);
      // 若返回了 redirect（HTTP -> HTTPS），询问用户是否跳转
      if (res.redirect) {
        if (confirm(`${res.reason}\n\n是否现在跳转到 HTTPS？`)) {
          window.location.href = res.redirect;
        }
      } else {
        // 在右上角状态处给出提示，但不打断用户
        statusText.textContent = '麦克风未授权';
      }
    } else {
      // 已授权，更新状态以便用户能看到
      statusText.textContent = '麦克风已授权';
    }
  } catch (err) {
    console.error('麦克风权限请求失败', err);
  }
});

// ===== 连接状态 =====
socket.on("connect", () => {
  statusDot.classList.add("online");
  statusText.textContent = "已连接";
});

socket.on("disconnect", () => {
  statusDot.classList.remove("online");
  statusText.textContent = "已断开";
});

// ===== 工具函数 =====
function formatTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function getAvatarLetter(sender) {
  const map = { AI: "AI", Me: "我", Web: "W", System: "!", "System Error": "!" };
  return map[sender] || sender.charAt(0).toUpperCase();
}

function getSenderClass(sender) {
  if (sender === "AI") return "ai";
  if (sender === "Me" || sender === "Web") return "web";
  return "system";
}

function renderContent(sender, content) {
  if (sender === "AI") {
    // Render Markdown for AI responses
    return marked.parse(content);
  }
  // Escape HTML for user messages
  const div = document.createElement("div");
  div.textContent = content;
  return div.innerHTML.replace(/\n/g, "<br>");
}

let thinkingEl = null;

function showThinking() {
  if (thinkingEl) return;
  thinkingEl = document.createElement("div");
  thinkingEl.className = "message ai";
  thinkingEl.innerHTML = `
    <div class="avatar">AI</div>
    <div>
      <div class="bubble">
        <div class="thinking"><span></span><span></span><span></span></div>
      </div>
    </div>
  `;
  messagesDiv.appendChild(thinkingEl);
  scrollToBottom();
}

function hideThinking() {
  if (thinkingEl) {
    thinkingEl.remove();
    thinkingEl = null;
  }
}

function appendMessage(sender, content, timestamp) {
  // Hide welcome
  welcomeDiv.classList.add("hidden");
  hideThinking();

  const cls = getSenderClass(sender);
  const time = timestamp ? formatTime(timestamp) : formatTime(Date.now() / 1000);

  const msgEl = document.createElement("div");
  msgEl.className = `message ${cls}`;

  if (cls === "system") {
    msgEl.innerHTML = `
      <div>
        <div class="bubble">${renderContent(sender, content)}</div>
      </div>
    `;
  } else {
    msgEl.innerHTML = `
      <div class="avatar">${getAvatarLetter(sender)}</div>
      <div>
        <div class="bubble">${renderContent(sender, content)}</div>
        <div class="msg-time">${time}</div>
      </div>
    `;
  }

  messagesDiv.appendChild(msgEl);

  // Highlight code blocks
  msgEl.querySelectorAll("pre code").forEach(block => hljs.highlightElement(block));

  scrollToBottom();
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    chatArea.scrollTop = chatArea.scrollHeight;
  });
}

// ===== Socket 事件 =====
socket.on("chat_history", (history) => {
  messagesDiv.innerHTML = "";
  if (history.length > 0) {
    welcomeDiv.classList.add("hidden");
    history.forEach(m => appendMessage(m.sender, m.content, m.timestamp));
  } else {
    welcomeDiv.classList.remove("hidden");
  }
});

socket.on("chat_message", (msg) => {
  appendMessage(msg.sender, msg.content, msg.timestamp);
  // 文字聊天收到 AI 回复后重置 FAB
  if (msg.sender === 'AI' && voiceFabState === 'loading' && !isVoicePipelineActive) {
    setVoiceFabState('idle');
  }
});

socket.on("chat_cleared", () => {
  messagesDiv.innerHTML = "";
  welcomeDiv.classList.remove("hidden");
});

// ===== 发送消息 =====
function sendMessage() {
  const text = msgInput.value.trim();
  if (!text) return;

  socket.emit("send_message", { message: text });
  msgInput.value = "";
  autoResize();
  sendBtn.disabled = true;

  // Show thinking indicator
  showThinking();
  // FAB 显示加载状态
  setVoiceFabState('loading');
}

sendBtn.addEventListener("click", sendMessage);

msgInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// 输入检测
msgInput.addEventListener("input", () => {
  sendBtn.disabled = msgInput.value.trim().length === 0;
  autoResize();
});

function autoResize() {
  msgInput.style.height = "auto";
  msgInput.style.height = Math.min(msgInput.scrollHeight, 120) + "px";
}

// 清空
clearBtn.addEventListener("click", () => {
  if (confirm("确定要清空当前对话吗？")) {
    socket.emit("clear_chat");
  }
});

// 快捷操作
document.querySelectorAll(".quick-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const msg = btn.getAttribute("data-msg");
    msgInput.value = msg;
    sendBtn.disabled = false;
    sendMessage();
  });
});

// ===================================================================
// ===== 语音输入 / 输出 =====
// ===================================================================

const voiceMicBtn    = document.getElementById("voiceMicBtn");

// ---------- 录音器 ----------
class VoiceRecorder {
  constructor() {
    this.audioContext = null;
    this.stream = null;
    this.processor = null;
    this.source = null;
    this.chunks = [];
    this.isRecording = false;
    this.actualSampleRate = 16000;
  }

  async start() {
    this.chunks = [];
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1 }
    });
    // 尝试以 16kHz 创建 AudioContext（ASR 要求 16kHz）
    try {
      this.audioContext = new AudioContext({ sampleRate: 16000 });
    } catch {
      this.audioContext = new AudioContext();
    }
    this.actualSampleRate = this.audioContext.sampleRate;

    this.source = this.audioContext.createMediaStreamSource(this.stream);
    this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);

    this.processor.onaudioprocess = (e) => {
      if (this.isRecording) {
        this.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      }
    };

    this.source.connect(this.processor);
    this.processor.connect(this.audioContext.destination);
    this.isRecording = true;
  }

  stop() {
    // convenience: capture current data and then fully release resources
    const pcm = this.snapshot();
    this.release();
    return pcm;
  }

  snapshot() {
    // Capture current recorded chunks into a PCM buffer without closing stream/context
    const wasRecording = this.isRecording;
    this.isRecording = false;

    const totalLength = this.chunks.reduce((s, c) => s + c.length, 0);
    let pcm = new Float32Array(totalLength);
    let offset = 0;
    this.chunks.forEach(c => { pcm.set(c, offset); offset += c.length; });
    this.chunks = [];

    if (this.actualSampleRate !== 16000) {
      pcm = this._resample(pcm, this.actualSampleRate, 16000);
    }

    // restore recording flag
    this.isRecording = wasRecording;
    return pcm;
  }

  release() {
    // Fully release audio resources (stop tracks, disconnect nodes, close AudioContext)
    this.isRecording = false;
    try {
      if (this.source) this.source.disconnect();
      if (this.processor) this.processor.disconnect();
      if (this.stream) this.stream.getTracks().forEach(t => t.stop());
      this.stream = null;
      this.source = null;
      this.processor = null;
      this.chunks = [];
      if (this.audioContext && this.audioContext.state !== "closed") {
        this.audioContext.close().catch(() => {});
      }
      this.audioContext = null;
    } catch (e) {
      console.warn('release mic error', e);
    }
  }

  _resample(data, fromRate, toRate) {
    const ratio = fromRate / toRate;
    const newLength = Math.round(data.length / ratio);
    const result = new Float32Array(newLength);
    for (let i = 0; i < newLength; i++) {
      const srcIdx = i * ratio;
      const lo = Math.floor(srcIdx);
      const hi = Math.min(lo + 1, data.length - 1);
      const frac = srcIdx - lo;
      result[i] = data[lo] * (1 - frac) + data[hi] * frac;
    }
    return result;
  }
}

// ---------- 流式音频播放器 ----------
class AudioStreamPlayer {
  constructor(sampleRate) {
    this.sampleRate = sampleRate;
    this.ctx = null;
    this.nextStartTime = 0;
    this.lastSource = null;
    this.onEnded = null;
    this._ended = false;
  }

  init() {
    this.ctx = new AudioContext({ sampleRate: this.sampleRate });
    this.nextStartTime = this.ctx.currentTime + 0.05; // 小缓冲
  }

  playChunk(arrayBuffer) {
    if (!this.ctx) this.init();

    const float32Data = new Float32Array(arrayBuffer);
    if (float32Data.length === 0) return;

    const audioBuffer = this.ctx.createBuffer(1, float32Data.length, this.sampleRate);
    audioBuffer.getChannelData(0).set(float32Data);

    const source = this.ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(this.ctx.destination);

    const now = this.ctx.currentTime;
    const startTime = Math.max(now + 0.02, this.nextStartTime);
    source.start(startTime);
    this.nextStartTime = startTime + audioBuffer.duration;
    this.lastSource = source;
  }

  end() {
    if (this._ended) return;
    this._ended = true;
    // 等最后一个 chunk 播完再回调
    if (this.ctx) {
      const remaining = this.nextStartTime - this.ctx.currentTime;
      setTimeout(() => {
        if (this.onEnded) this.onEnded();
        this.close();
      }, Math.max(0, remaining * 1000) + 200);
    } else {
      if (this.onEnded) this.onEnded();
    }
  }

  close() {
    if (this.ctx && this.ctx.state !== "closed") {
      this.ctx.close().catch(() => {});
    }
    this.ctx = null;
  }
}

// ---------- 状态变量 ----------
let voiceRecorder = null;
let audioStreamPlayer = null;
let voiceCancelled = false;
let isVoicePipelineActive = false;  // 标记语音管线是否活跃
let micHeldForPlayback = false; // 标记是否为播放而保留麦克风

// ---------- FAB 状态管理 ----------
// States: 'idle' | 'recording' | 'loading' | 'playing'
let voiceFabState = 'idle';

function setVoiceFabState(state) {
  voiceFabState = state;
  voiceMicBtn.classList.remove('recording', 'loading', 'playing');
  if (state !== 'idle') {
    voiceMicBtn.classList.add(state);
  }
  const titles = {
    idle: '点击说话',
    recording: '点击停止录音',
    loading: '处理中…',
    playing: '点击停止播放',
  };
  voiceMicBtn.title = titles[state] || '';
}

// ---------- 麦克风权限检查 ----------
let micPermissionGranted = false;

async function checkMicPermission() {
  // 0) 检查是否在安全上下文中（HTTPS 或 localhost）
  if (!window.isSecureContext) {
    const httpsUrl = window.location.href.replace(/^http:/, "https:");
    return {
      ok: false,
      reason: `当前页面不在安全上下文中，浏览器禁止使用麦克风。\n\n解决方法：\n将地址栏中的 http:// 改为 https:// 即可。\n\n点击确定后将自动跳转到 HTTPS 版本。`,
      redirect: httpsUrl,
    };
  }

  // 1) 浏览器是否支持 mediaDevices
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return {
      ok: false,
      reason: "当前浏览器不支持麦克风访问。\n\n可能原因：\n• 浏览器版本过低\n• 浏览器限制了该功能\n\n建议使用最新版 Chrome / Edge / Safari。",
    };
  }

  // 2) 使用 Permissions API 查询当前权限状态（如果可用）
  if (navigator.permissions && navigator.permissions.query) {
    try {
      const result = await navigator.permissions.query({ name: "microphone" });
      if (result.state === "denied") {
        return {
          ok: false,
          reason: "麦克风权限已被拒绝。\n\n请在浏览器设置中重新允许本站使用麦克风：\n• Chrome: 点击地址栏左侧锁形图标 → 网站设置 → 麦克风 → 允许\n• Edge: 点击地址栏左侧锁形图标 → 权限 → 麦克风 → 允许\n• 修改后刷新页面",
        };
      }
      // "granted" 或 "prompt" 都可以继续
    } catch {
      // 某些浏览器不支持查询 microphone 权限，忽略
    }
  }

  // 3) 尝试实际获取麦克风流来确认权限
  try {
    const testStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    testStream.getTracks().forEach(t => t.stop()); // 立即释放
    micPermissionGranted = true;
    return { ok: true };
  } catch (err) {
    let reason;
    if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
      reason = "麦克风权限被拒绝。\n\n请点击浏览器地址栏左侧的图标，允许本站访问麦克风后重试。";
    } else if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
      reason = "未检测到麦克风设备。请确认麦克风已连接并被系统识别。";
    } else if (err.name === "NotReadableError" || err.name === "TrackStartError") {
      reason = "麦克风被其他应用占用，请关闭占用麦克风的程序后重试。";
    } else {
      reason = `麦克风访问失败: ${err.name}\n${err.message}`;
    }
    return { ok: false, reason };
  }
}

// ---------- 录音按钮事件 ----------
async function startVoiceRecording() {
  if (voiceFabState !== 'idle') return;
  voiceCancelled = false;

  // 先检查权限
  if (!micPermissionGranted) {
    const check = await checkMicPermission();
    if (!check.ok) {
      alert(check.reason);
      if (check.redirect) {
        window.location.href = check.redirect;
      }
      return;
    }
  }

  // 如果之前为了播放而保留了麦克风实例，尝试重用并直接进入录音
  if (voiceRecorder && voiceRecorder.stream && !voiceRecorder.isRecording) {
    voiceRecorder.isRecording = true;
    setVoiceFabState('recording');
    return;
  }

  voiceRecorder = new VoiceRecorder();
  try {
    await voiceRecorder.start();
    setVoiceFabState('recording');
  } catch (err) {
    console.error("麦克风访问失败:", err);
    micPermissionGranted = false;
    let msg;
    if (err.name === "NotAllowedError") {
      msg = "麦克风权限被拒绝，请在浏览器设置中允许后重试。";
    } else if (err.name === "NotFoundError") {
      msg = "未检测到麦克风设备。";
    } else if (err.name === "NotReadableError") {
      msg = "麦克风被其他应用占用。";
    } else {
      msg = `麦克风错误: ${err.name} - ${err.message}`;
    }
    alert(msg);
  }
}

function stopVoiceRecording() {
  if (voiceFabState !== 'recording') return;

  if (!voiceRecorder || !voiceRecorder.isRecording) {
    setVoiceFabState('idle');
    return;
  }

  // 获取当前录音数据，但保留麦克风与 AudioContext，直到播放结束再释放
  const pcm = voiceRecorder.snapshot();
  // 停止继续录制（但不释放设备）
  voiceRecorder.isRecording = false;
  micHeldForPlayback = true;

  // 太短（<0.3秒@16kHz = 4800 samples）
  if (pcm.length < 4800) {
    // 过短则立即释放麦克风
    voiceRecorder.release();
    voiceRecorder = null;
    micHeldForPlayback = false;
    setVoiceFabState('idle');
    return;
  }

  if (voiceCancelled) {
    if (voiceRecorder) {
      voiceRecorder.release();
      voiceRecorder = null;
    }
    micHeldForPlayback = false;
    setVoiceFabState('idle');
    return;
  }

  setVoiceFabState('loading');
  isVoicePipelineActive = true;
  socket.emit("voice_input", pcm.buffer);
}

function stopPlayback() {
  voiceCancelled = true;
  if (audioStreamPlayer) {
    audioStreamPlayer.close();
    audioStreamPlayer = null;
  }
  isVoicePipelineActive = false;
  setVoiceFabState('idle');
  // 若麦克风因播放被保留，则释放
  if (micHeldForPlayback && voiceRecorder) {
    voiceRecorder.release();
    voiceRecorder = null;
    micHeldForPlayback = false;
  }
}

// FAB 点击事件（桌面 + 手机统一为 click）
voiceMicBtn.addEventListener("click", async (e) => {
  e.preventDefault();
  if (voiceFabState === 'idle') {
    await startVoiceRecording();
  } else if (voiceFabState === 'recording') {
    stopVoiceRecording();
  } else if (voiceFabState === 'playing') {
    stopPlayback();
  }
  // loading 状态：不响应点击
});

// 阻止手机端长按弹出上下文菜单
voiceMicBtn.addEventListener("contextmenu", (e) => e.preventDefault());

// ---------- Socket.IO 语音事件 ----------
socket.on("voice_status", (data) => {
  if (voiceCancelled) return;
  if (data.status === "error") {
    // 出错时强制重置
    if (audioStreamPlayer) {
      audioStreamPlayer.close();
      audioStreamPlayer = null;
    }
    isVoicePipelineActive = false;
    setVoiceFabState('idle');
  } else if (data.status === "done") {
    // 正常完成：若还在 loading（未产生音频），重置
    if (voiceFabState === 'loading') {
      isVoicePipelineActive = false;
      setVoiceFabState('idle');
    }
  }
});

socket.on("voice_asr_result", (data) => {
  // ASR 文本通过 chat_message 广播显示
});

socket.on("voice_audio_start", (data) => {
  if (voiceCancelled) return;
  audioStreamPlayer = new AudioStreamPlayer(data.sampleRate);
  audioStreamPlayer.init();
  audioStreamPlayer.onEnded = () => {
    audioStreamPlayer = null;
    isVoicePipelineActive = false;
    setVoiceFabState('idle');
    // 播放结束后若麦克风被保留则释放
    if (micHeldForPlayback && voiceRecorder) {
      voiceRecorder.release();
      voiceRecorder = null;
      micHeldForPlayback = false;
    }
  };
  setVoiceFabState('playing');
});

socket.on("voice_audio_chunk", (data) => {
  if (voiceCancelled || !audioStreamPlayer) return;
  audioStreamPlayer.playChunk(data);
});

socket.on("voice_audio_end", () => {
  if (audioStreamPlayer) {
    audioStreamPlayer.end();
  }
});
