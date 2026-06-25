<div align="center">

# 📱 PhoneMirror

**Stream and control your Android phone from any browser — no app required.**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat&logo=fastapi&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey?style=flat)

</div>

---

## Overview

PhoneMirror lets you see and control an Android phone screen directly from a browser tab. It uses ADB to bridge your computer and phone, scrcpy's H.264 streaming protocol for low-latency video, and the WebCodecs API for hardware-accelerated decoding in the browser.

**Latency:** ~20–50ms with scrcpy (H.264), ~300–1500ms fallback (JPEG screencap)

### Features

- 🖥 **Live screen mirror** — H.264 stream via scrcpy, GPU-decoded in browser
- 👆 **Full touch control** — tap, swipe, scroll wheel mapped to device input
- ⌨️ **Hardware keys** — Home, Back, Recents, volume, media controls
- 📂 **File browser** — browse, download, upload, and delete files on device
- 📞 **Phone calls** — dial and hang up from the browser
- ✍️ **Text input** — type text directly into any field on the phone
- 🔄 **Auto-reconnect** — reconnects automatically if device disconnects
- 📡 **Multi-client** — multiple browser tabs share one stream

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.10+ | [python.org](https://python.org) |
| ADB (Android Debug Bridge) | [Download Platform Tools](https://developer.android.com/tools/releases/platform-tools) |
| Android phone | USB Debugging enabled (see setup below) |
| USB cable | Data cable, not charge-only |

---

## Setup

### 1. Enable USB Debugging on your phone

1. Go to **Settings → About Phone**
2. Tap **Build Number** 7 times until you see *"You are now a developer"*
3. Go to **Settings → Developer Options**
4. Enable **USB Debugging**
5. Connect phone via USB and tap **Allow** on the popup

### 2. Verify ADB sees your phone

```bash
adb devices
```

Expected output:
```
List of devices attached
XXXXXXXX    device
```

If it shows `unauthorized`, check your phone screen for the Allow prompt.

### 3. Install dependencies

```bash
cd phone-mirror/backend
pip install -r requirements.txt
```

### 4. Run the server

```bash
python main.py
```

### 5. Open in browser

```
http://localhost:8000
```

Your phone will appear in the device dropdown. Click **Mirror** to start streaming.

---

## Wireless Mode

Connect over WiFi instead of USB after the initial setup:

```bash
adb tcpip 5555
adb connect <phone-ip>:5555
```

Find your phone's IP at **Settings → About Phone → Status → IP Address**.

---

## Project Structure

```
phone-mirror/
├── backend/
│   ├── main.py            FastAPI server — all HTTP endpoints + WebSocket
│   ├── adb.py             ADB command wrappers
│   ├── streamer.py        scrcpy H.264 stream engine + WebSocket broadcaster
│   └── requirements.txt
├── frontend/
│   ├── index.html         App shell
│   ├── style.css          Dark UI
│   └── app.js             WebSocket client, H.264 decoder, UI logic
└── README.md
```

---

## How It Works

```
Android Phone
  └── scrcpy-server.jar (auto-downloaded on first run)
        └── MediaCodec hardware H.264 encoder
              └── abstract socket: localabstract:scrcpy
                    └── adb forward tcp:27183
                          └── Python (streamer.py) reads NAL units
                                └── WebSocket /ws/screen
                                      └── Browser WebCodecs VideoDecoder (GPU)
                                            └── Canvas drawImage()
```

Touch control flows in reverse:

```
Mouse click on canvas → scale to device coords → POST /api/input/tap → adb shell input tap X Y
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/devices` | List connected ADB devices |
| POST | `/api/device/select` | Set active device |
| GET | `/api/device/info` | Screen resolution + battery |
| POST | `/api/input/tap` | Tap at coordinates |
| POST | `/api/input/swipe` | Swipe gesture |
| POST | `/api/input/key` | Send keycode |
| POST | `/api/input/text` | Type text |
| POST | `/api/call/start` | Start phone call |
| POST | `/api/call/end` | End call |
| GET | `/api/files` | List directory |
| GET | `/api/files/download` | Download file from device |
| POST | `/api/files/upload` | Upload file to device |
| DELETE | `/api/files` | Delete file on device |
| WS | `/ws/screen` | H.264 video stream |

---

## Configuration

Edit `backend/streamer.py` to adjust stream quality:

```python
SCRCPY_SERVER_ARGS = [
    ...
    "max_size=720",          # Resolution: 480 / 720 / 1080
    "video_bit_rate=2000000", # Bitrate: 1000000 = 1Mbps, 4000000 = 4Mbps
    "max_fps=30",            # Frame rate: 15 / 30
    "video_codec=h264",      # Codec: h264 / h265 / av1
]
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `adb: command not found` | Add Platform Tools to PATH and restart terminal |
| `No devices found` | Accept the USB Debugging prompt on your phone |
| Black screen in browser | Run `pip install Pillow` and restart server |
| `RGBA` error in logs | Already fixed — update `streamer.py` to convert image mode |
| High latency | Lower `max_size` or `video_bit_rate` in `streamer.py` |
| scrcpy download fails | Download `scrcpy-server-v3.3.4` manually from [releases](https://github.com/Genymobile/scrcpy/releases) and place in `backend/` |

---

## Limitations

- **Android only** — iOS blocks USB debugging entirely
- Requires USB Debugging enabled (developer feature)
- Some apps (banking, streaming) block screen recording
- scrcpy requires Android 5.0+ (API 21)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, uvicorn |
| Phone bridge | ADB (Android Debug Bridge) |
| Screen streaming | scrcpy-server.jar (H.264 via MediaCodec) |
| Transport | WebSocket (binary frames) |
| Browser decode | WebCodecs API (VideoDecoder) |
| Rendering | HTML5 Canvas |
| Image fallback | Pillow (JPEG screencap) |

---

## License

MIT
