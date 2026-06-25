import asyncio
import logging
import socket
import struct
import subprocess
import time
import threading
from typing import Optional, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)

SCRCPY_SERVER_VERSION = "3.3.4"
SCRCPY_SERVER_PATH_DEVICE = "/data/local/tmp/scrcpy-server.jar"
SCRCPY_LOCAL_PORT = 27183
SOCKET_NAME = "scrcpy"

SCRCPY_SERVER_ARGS = [
    f"CLASSPATH={SCRCPY_SERVER_PATH_DEVICE}",
    "app_process",
    "/",
    "com.genymobile.scrcpy.Server",
    SCRCPY_SERVER_VERSION,
    "tunnel_forward=true",
    "video=true",
    "audio=false",
    "control=false",
    "cleanup=true",
    "raw_stream=true",
    "send_frame_meta=false",
    "max_size=720",
    "video_bit_rate=2000000",
    "max_fps=30",
    "video_codec=h264",
    "video_source=display",
]


class ScrcpyStreamer:
    def __init__(self):
        self.clients: Set[WebSocket] = set()
        self.serial: Optional[str] = None
        self.running = False
        self._stream_task: Optional[asyncio.Task] = None
        self._server_proc: Optional[subprocess.Popen] = None
        self._sock: Optional[socket.socket] = None
        self.mode = "scrcpy"
        self.fps = 30
        self.quality = 50

    def set_device(self, serial: Optional[str]):
        self.serial = serial

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.clients.add(websocket)
        logger.info(f"WS client connected ({len(self.clients)} total)")
        if not self.running:
            self.start()

    def disconnect(self, websocket: WebSocket):
        self.clients.discard(websocket)
        logger.info(f"WS client disconnected ({len(self.clients)} total)")
        if not self.clients:
            self.stop()

    def start(self):
        if not self.running:
            self.running = True
            self._stream_task = asyncio.create_task(self._run())

    def stop(self):
        self.running = False
        self._cleanup()
        if self._stream_task:
            self._stream_task.cancel()
            self._stream_task = None

    def _adb(self, args: list, timeout=15) -> subprocess.CompletedProcess:
        prefix = ["-s", self.serial] if self.serial else []
        return subprocess.run(["adb"] + prefix + args, capture_output=True, timeout=timeout)

    def _push_server(self) -> bool:
        import os, urllib.request
        local_jar = f"scrcpy-server-v{SCRCPY_SERVER_VERSION}.jar"
        r = self._adb(["shell", "ls", SCRCPY_SERVER_PATH_DEVICE])
        if r.returncode == 0 and "No such file" not in r.stdout.decode():
            return True
        if not os.path.exists(local_jar):
            url = f"https://github.com/Genymobile/scrcpy/releases/download/v{SCRCPY_SERVER_VERSION}/scrcpy-server-v{SCRCPY_SERVER_VERSION}"
            try:
                urllib.request.urlretrieve(url, local_jar)
            except Exception as e:
                logger.error(f"Failed to download scrcpy server: {e}")
                return False
        r = self._adb(["push", local_jar, SCRCPY_SERVER_PATH_DEVICE])
        return r.returncode == 0

    def _start_server_process(self) -> bool:
        prefix = ["-s", self.serial] if self.serial else []
        cmd = ["adb"] + prefix + ["shell"] + SCRCPY_SERVER_ARGS
        try:
            self._server_proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return True
        except Exception as e:
            logger.error(f"Failed to start scrcpy server process: {e}")
            return False

    def _forward_port(self) -> bool:
        r = self._adb([
            "forward",
            f"tcp:{SCRCPY_LOCAL_PORT}",
            f"localabstract:{SOCKET_NAME}"
        ])
        return r.returncode == 0

    def _connect_socket(self) -> bool:
        for attempt in range(10):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect(("127.0.0.1", SCRCPY_LOCAL_PORT))
                s.recv(1)
                self._sock = s
                return True
            except Exception as e:
                logger.debug(f"Socket connect attempt {attempt+1}: {e}")
                time.sleep(0.3)
        return False

    def _read_codec_meta(self):
        try:
            data = self._recv_exactly(12)
            if data:
                codec_id, w, h = struct.unpack(">III", data)
                logger.info(f"scrcpy meta: codec=0x{codec_id:08x} size={w}x{h}")
        except Exception as e:
            logger.warning(f"Could not read codec meta: {e}")

    def _recv_exactly(self, n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _cleanup(self):
        if self._sock:
            try:
                self._sock.close()
            except:
                pass
            self._sock = None
        if self._server_proc:
            try:
                self._server_proc.terminate()
            except:
                pass
            self._server_proc = None
        try:
            prefix = ["-s", self.serial] if self.serial else []
            subprocess.run(
                ["adb"] + prefix + ["forward", "--remove", f"tcp:{SCRCPY_LOCAL_PORT}"],
                capture_output=True, timeout=5
            )
        except:
            pass

    async def _run(self):
        if await self._try_scrcpy():
            logger.info("Streaming via scrcpy H.264")
            await self._stream_h264()
        else:
            logger.warning("scrcpy unavailable — falling back to screencap JPEG")
            self.mode = "screencap"
            await self._stream_screencap_fallback()

    async def _try_scrcpy(self) -> bool:
        if not self.serial and not self._has_device():
            return False
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._setup_scrcpy)

    def _has_device(self) -> bool:
        r = subprocess.run(["adb", "devices"], capture_output=True, timeout=5)
        lines = r.stdout.decode().strip().split("\n")[1:]
        return any("device" in l for l in lines)

    def _setup_scrcpy(self) -> bool:
        try:
            if not self._push_server():
                return False
            if not self._start_server_process():
                return False
            time.sleep(0.5)
            if not self._forward_port():
                return False
            if not self._connect_socket():
                return False
            self._read_codec_meta()
            return True
        except Exception as e:
            logger.error(f"scrcpy setup failed: {e}")
            self._cleanup()
            return False

    async def _stream_h264(self):
        loop = asyncio.get_event_loop()
        self._sock.setblocking(False)
        reader, _ = await asyncio.open_connection(sock=self._sock)
        await self._broadcast_text({"type": "mode", "codec": "h264"})
        buf = b""
        NAL_START = b"\x00\x00\x00\x01"
        try:
            while self.running:
                chunk = await asyncio.wait_for(reader.read(65536), timeout=5.0)
                if not chunk:
                    break
                buf += chunk
                while True:
                    idx = buf.find(NAL_START, 4)
                    if idx == -1:
                        break
                    nal = buf[:idx]
                    buf = buf[idx:]
                    if len(nal) > 4 and self.clients:
                        await self._broadcast_binary(nal)
        except asyncio.TimeoutError:
            logger.warning("scrcpy stream timed out")
        except Exception as e:
            logger.error(f"H.264 stream error: {e}")
        finally:
            self._cleanup()
            if self.running:
                await asyncio.sleep(2)
                self.running = False
                self.running = True
                asyncio.create_task(self._run())

    async def _stream_screencap_fallback(self):
        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        loop = asyncio.get_event_loop()
        await self._broadcast_text({"type": "mode", "codec": "jpeg"})
        interval = 1.0 / self.fps
        while self.running:
            t0 = time.monotonic()
            if self.clients:
                frame = await loop.run_in_executor(executor, self._screencap_jpeg)
                if frame:
                    await self._broadcast_binary(frame)
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0.0, interval - elapsed))

    def _screencap_jpeg(self) -> Optional[bytes]:
        try:
            from adb import screencap
            from PIL import Image
            import io
            raw = screencap(self.serial)
            if not raw:
                return None
            img = Image.open(io.BytesIO(raw))
            if img.mode != "RGB":
                img = img.convert("RGB")
            w, h = img.size
            img = img.resize((w // 2, h // 2), Image.BILINEAR)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self.quality, optimize=False, subsampling=2)
            return buf.getvalue()
        except Exception as e:
            logger.error(f"screencap error: {e}")
            return None

    async def _broadcast_binary(self, data: bytes):
        dead = set()
        for ws in list(self.clients):
            try:
                await ws.send_bytes(data)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def _broadcast_text(self, msg: dict):
        import json
        dead = set()
        payload = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.clients.discard(ws)


streamer = ScrcpyStreamer()
