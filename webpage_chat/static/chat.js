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
