const API = "";

let ws = null;
let currentSerial = null;
let deviceW = 1080, deviceH = 1920;
let streamMode = "jpeg";
let h264Decoder = null;
let h264Configured = false;
let nalBuffer = [];
let swipeStart = null;
let currentPath = "/sdcard/";

const canvas       = document.getElementById("screen");
const ctx          = canvas.getContext("2d");
const noSignal     = document.getElementById("no-signal");
const deviceSelect = document.getElementById("device-select");
const deviceMeta   = document.getElementById("device-meta");
const streamStatus = document.getElementById("stream-status");
const fpsSlider    = document.getElementById("fps-slider");
const fpsValue     = document.getElementById("fps-value");
const breadcrumb   = document.getElementById("breadcrumb");
const fileList     = document.getElementById("file-list");
const phoneInput   = document.getElementById("phone-number");
const textInput    = document.getElementById("text-input");

(async function init() {
  await refreshDevices();
  setupCanvasEvents();
  setupNavigation();
  setupFpsSlider();
  document.getElementById("refresh-devices").addEventListener("click", refreshDevices);
  document.getElementById("nav-up-btn").addEventListener("click", navigateUp);
  document.getElementById("upload-input").addEventListener("change", handleUpload);
})();

async function refreshDevices() {
  try {
    const res = await fetch(`${API}/api/devices`);
    const data = await res.json();
    const devices = data.devices || [];
    deviceSelect.innerHTML = devices.length
      ? devices.map(d => `<option value="${d.serial}">${d.model || d.serial} (${d.state})</option>`).join("")
      : `<option value="">No devices found</option>`;
    if (devices.length > 0) selectDevice(devices[0].serial);
  } catch (e) {
    deviceSelect.innerHTML = `<option value="">ADB not found</option>`;
    showToast("Cannot reach backend — is it running?");
  }
}

deviceSelect.addEventListener("change", () => {
  if (deviceSelect.value) selectDevice(deviceSelect.value);
});

async function selectDevice(serial) {
  currentSerial = serial;
  await fetch(`${API}/api/device/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ serial })
  });
  try {
    const res = await fetch(`${API}/api/device/info?serial=${encodeURIComponent(serial)}`);
    const info = await res.json();
    deviceW = info.screen.w;
    deviceH = info.screen.h;
    const b = info.battery;
    deviceMeta.textContent = `${deviceW}×${deviceH} · 🔋${b.level}% ${b.charging ? "⚡" : ""}`;
  } catch (_) {
    deviceMeta.textContent = "";
  }
  connectWebSocket();
}

function connectWebSocket() {
  if (ws) { ws.close(); ws = null; }
  destroyDecoder();
  setStatus("connecting");
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const host = location.host || "localhost:8000";
  ws = new WebSocket(`${proto}://${host}/ws/screen`);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    setStatus("connected");
    noSignal.style.display = "none";
    ws.send(JSON.stringify({ type: "set_fps", fps: parseInt(fpsSlider.value) }));
    ws._pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
    }, 5000);
  };

  ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) {
      if (streamMode === "h264") feedH264(new Uint8Array(e.data));
      else renderJpegBinary(e.data);
    } else {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === "mode") {
          streamMode = msg.codec;
          if (msg.codec === "h264") initH264Decoder();
          showToast(msg.codec === "h264" ? "▶ H.264 stream" : "▶ JPEG stream (fallback)");
        } else if (msg.type === "frame") {
          renderJpegBase64(msg.data);
        }
      } catch (_) {}
    }
  };

  ws.onerror = () => setStatus("disconnected");

  ws.onclose = () => {
    clearInterval(ws._pingInterval);
    setStatus("disconnected");
    noSignal.style.display = "flex";
    if (currentSerial) setTimeout(connectWebSocket, 3000);
  };
}

function initH264Decoder() {
  if (!("VideoDecoder" in window)) {
    showToast("WebCodecs not supported — using JPEG fallback");
    streamMode = "jpeg";
    return;
  }
  destroyDecoder();
  h264Decoder = new VideoDecoder({
    output: (frame) => {
      canvas.width = frame.displayWidth;
      canvas.height = frame.displayHeight;
      ctx.drawImage(frame, 0, 0);
      frame.close();
    },
    error: () => {
      h264Configured = false;
      nalBuffer = [];
    }
  });
  h264Configured = false;
  nalBuffer = [];
}

function destroyDecoder() {
  if (h264Decoder) {
    try { h264Decoder.close(); } catch (_) {}
    h264Decoder = null;
  }
  h264Configured = false;
  nalBuffer = [];
}

function feedH264(nalUnit) {
  if (!h264Decoder || h264Decoder.state === "closed") return;
  let start = 0;
  if (nalUnit[0] === 0 && nalUnit[1] === 0 && nalUnit[2] === 0 && nalUnit[3] === 1) start = 4;
  else if (nalUnit[0] === 0 && nalUnit[1] === 0 && nalUnit[2] === 1) start = 3;
  if (start >= nalUnit.length) return;
  const nalType = nalUnit[start] & 0x1f;
  if (nalType === 7) {
    nalBuffer = [nalUnit];
    return;
  }
  if (nalType === 8) {
    nalBuffer.push(nalUnit);
    if (!h264Configured && nalBuffer.length >= 2) configureH264Decoder();
    return;
  }
  if (!h264Configured) return;
  const isKeyframe = nalType === 5;
  const chunk = new EncodedVideoChunk({
    type: isKeyframe ? "key" : "delta",
    timestamp: performance.now() * 1000,
    data: nalUnit,
  });
  try {
    h264Decoder.decode(chunk);
  } catch (e) {
    h264Configured = false;
  }
}

function configureH264Decoder() {
  try {
    h264Decoder.configure({
      codec: "avc1.42001f",
      optimizeForLatency: true,
    });
    h264Configured = true;
    nalBuffer = [];
  } catch (e) {
    streamMode = "jpeg";
  }
}

let _jpegPending = false;
function renderJpegBinary(arrayBuffer) {
  if (_jpegPending) return;
  _jpegPending = true;
  const blob = new Blob([arrayBuffer], { type: "image/jpeg" });
  createImageBitmap(blob).then(bitmap => {
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    ctx.drawImage(bitmap, 0, 0);
    bitmap.close();
    _jpegPending = false;
  }).catch(() => { _jpegPending = false; });
}

function renderJpegBase64(base64) {
  const img = new Image();
  img.onload = () => {
    canvas.width = img.width;
    canvas.height = img.height;
    ctx.drawImage(img, 0, 0);
  };
  img.src = `data:image/jpeg;base64,${base64}`;
}

function setStatus(state) {
  const labels = { connected: "● Live", disconnected: "● Disconnected", connecting: "● Connecting…" };
  streamStatus.className = `stream-status ${state}`;
  streamStatus.textContent = labels[state] || state;
}

function setupCanvasEvents() {
  canvas.addEventListener("mousedown", onMouseDown);
  canvas.addEventListener("mouseup", onMouseUp);
  canvas.addEventListener("mousemove", onMouseMove);
  canvas.addEventListener("wheel", onWheel, { passive: false });
  canvas.addEventListener("contextmenu", e => e.preventDefault());
}

function canvasCoords(e) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: Math.round((e.clientX - rect.left) * (canvas.width / rect.width)),
    y: Math.round((e.clientY - rect.top) * (canvas.height / rect.height)),
  };
}

function onMouseDown(e) {
  swipeStart = { ...canvasCoords(e), t: Date.now() };
}

function onMouseUp(e) {
  if (!swipeStart || !currentSerial) return;
  const end = canvasCoords(e);
  const dx = end.x - swipeStart.x;
  const dy = end.y - swipeStart.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  const dt = Date.now() - swipeStart.t;
  const cw = canvas.width, ch = canvas.height;
  if (dist < 8) {
    postInput("/api/input/tap", { x: end.x, y: end.y, canvas_w: cw, canvas_h: ch, device_w: deviceW, device_h: deviceH, serial: currentSerial });
  } else {
    const dur = Math.max(100, Math.min(600, dt));
    postInput("/api/input/swipe", { x1: swipeStart.x, y1: swipeStart.y, x2: end.x, y2: end.y, canvas_w: cw, canvas_h: ch, device_w: deviceW, device_h: deviceH, duration_ms: dur, serial: currentSerial });
  }
  swipeStart = null;
}

function onMouseMove(e) {}

function onWheel(e) {
  e.preventDefault();
  if (!currentSerial) return;
  const coords = canvasCoords(e);
  const cw = canvas.width, ch = canvas.height;
  const scrollY = e.deltaY > 0 ? 300 : -300;
  postInput("/api/input/swipe", {
    x1: coords.x, y1: coords.y,
    x2: coords.x, y2: coords.y - scrollY,
    canvas_w: cw, canvas_h: ch,
    device_w: deviceW, device_h: deviceH,
    duration_ms: 200, serial: currentSerial
  });
}

function sendKey(keycode) {
  if (!currentSerial) return showToast("No device connected");
  postInput("/api/input/key", { keycode, serial: currentSerial });
}
window.sendKey = sendKey;

function sendText() {
  const text = textInput.value.trim();
  if (!text) return;
  if (!currentSerial) return showToast("No device connected");
  postInput("/api/input/text", { text, serial: currentSerial });
  textInput.value = "";
  showToast("Text sent");
}
window.sendText = sendText;

function appendDigit(d) { phoneInput.value += d; }
function backspaceDigit() { phoneInput.value = phoneInput.value.slice(0, -1); }
window.appendDigit = appendDigit;
window.backspaceDigit = backspaceDigit;

async function startCall() {
  const number = phoneInput.value.trim();
  if (!number) return showToast("Enter a phone number");
  if (!currentSerial) return showToast("No device connected");
  await postInput("/api/call/start", { number, serial: currentSerial });
  showToast(`Calling ${number}…`);
}
async function endCall() {
  if (!currentSerial) return;
  await postInput("/api/call/end", { serial: currentSerial });
  showToast("Call ended");
}
window.startCall = startCall;
window.endCall = endCall;

async function loadFiles(path) {
  currentPath = path;
  breadcrumb.textContent = path;
  fileList.innerHTML = `<div class="loading">Loading…</div>`;
  try {
    const res = await fetch(`${API}/api/files?path=${encodeURIComponent(path)}&serial=${encodeURIComponent(currentSerial || "")}`);
    const data = await res.json();
    renderFiles(data.entries || []);
  } catch (e) {
    fileList.innerHTML = `<div class="loading">Failed to load — is a device connected?</div>`;
  }
}

function renderFiles(entries) {
  if (!entries.length) {
    fileList.innerHTML = `<div class="loading">Empty folder</div>`;
    return;
  }
  entries.sort((a, b) => (b.is_dir - a.is_dir) || a.name.localeCompare(b.name));
  fileList.innerHTML = entries.map(e => {
    const icon = e.is_dir ? "📁" : fileIcon(e.name);
    const size = e.is_dir ? "" : formatSize(e.size);
    return `
    <div class="file-item" data-path="${e.path}" data-dir="${e.is_dir}">
      <span class="file-icon">${icon}</span>
      <span class="file-name" title="${e.name}">${e.name}</span>
      <span class="file-meta">${size}</span>
      ${!e.is_dir ? `<button class="file-dl" title="Download" onclick="downloadFile('${e.path}')">⬇</button>` : ""}
      <button class="file-del" title="Delete" onclick="deleteFile('${e.path}', event)">🗑</button>
    </div>`;
  }).join("");
  fileList.querySelectorAll(".file-item[data-dir='true']").forEach(el => {
    el.addEventListener("click", () => loadFiles(el.dataset.path + "/"));
  });
}

function navigateUp() {
  const parts = currentPath.replace(/\/$/, "").split("/");
  if (parts.length <= 2) return;
  parts.pop();
  loadFiles(parts.join("/") + "/");
}

async function downloadFile(path) {
  const url = `${API}/api/files/download?path=${encodeURIComponent(path)}&serial=${encodeURIComponent(currentSerial || "")}`;
  const a = document.createElement("a");
  a.href = url;
  a.download = path.split("/").pop();
  a.click();
}
window.downloadFile = downloadFile;

async function deleteFile(path, e) {
  e.stopPropagation();
  if (!confirm(`Delete ${path.split("/").pop()}?`)) return;
  await fetch(`${API}/api/files`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, serial: currentSerial })
  });
  showToast("Deleted");
  loadFiles(currentPath);
}
window.deleteFile = deleteFile;

async function handleUpload(e) {
  const files = Array.from(e.target.files);
  if (!files.length) return;
  if (!currentSerial) return showToast("No device connected");
  for (const file of files) {
    const fd = new FormData();
    fd.append("file", file);
    await fetch(`${API}/api/files/upload?device_path=${encodeURIComponent(currentPath)}&serial=${encodeURIComponent(currentSerial)}`, {
      method: "POST", body: fd
    });
    showToast(`Uploaded ${file.name}`);
  }
  loadFiles(currentPath);
  e.target.value = "";
}

function setupFpsSlider() {
  fpsSlider.addEventListener("input", () => {
    const fps = parseInt(fpsSlider.value);
    fpsValue.textContent = fps;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "set_fps", fps }));
    }
  });
}

function setupNavigation() {
  document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const panel = btn.dataset.panel;
      document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
      document.getElementById(`panel-${panel}`).classList.add("active");
      if (panel === "files" && currentSerial) loadFiles(currentPath);
    });
  });
}

async function postInput(endpoint, body) {
  try {
    await fetch(`${API}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  } catch (e) {
    console.error("Input error:", e);
  }
}

function fileIcon(name) {
  const ext = name.split(".").pop().toLowerCase();
  const map = {
    jpg: "🖼", jpeg: "🖼", png: "🖼", gif: "🖼", webp: "🖼",
    mp4: "🎬", mkv: "🎬", avi: "🎬", mov: "🎬",
    mp3: "🎵", flac: "🎵", wav: "🎵", aac: "🎵",
    pdf: "📄", doc: "📝", docx: "📝", txt: "📝",
    zip: "🗜", rar: "🗜", tar: "🗜",
    apk: "📦",
  };
  return map[ext] || "📄";
}

function formatSize(sizeStr) {
  const n = parseInt(sizeStr);
  if (isNaN(n)) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

let toastTimer;
function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3000);
}
