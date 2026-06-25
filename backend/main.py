import os
import json
import logging
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import adb
from streamer import streamer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PhoneMirror", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TapRequest(BaseModel):
    x: int
    y: int
    canvas_w: int
    canvas_h: int
    device_w: int
    device_h: int
    serial: Optional[str] = None


class SwipeRequest(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    canvas_w: int
    canvas_h: int
    device_w: int
    device_h: int
    duration_ms: int = 300
    serial: Optional[str] = None


class KeyRequest(BaseModel):
    keycode: int
    serial: Optional[str] = None


class TextRequest(BaseModel):
    text: str
    serial: Optional[str] = None


class CallRequest(BaseModel):
    number: str
    serial: Optional[str] = None


class DeleteRequest(BaseModel):
    path: str
    serial: Optional[str] = None


class DeviceSelectRequest(BaseModel):
    serial: Optional[str] = None


def scale_coords(x, y, canvas_w, canvas_h, device_w, device_h):
    dx = int(x * device_w / canvas_w)
    dy = int(y * device_h / canvas_h)
    return dx, dy


@app.get("/api/devices")
def list_devices():
    try:
        devices = adb.get_devices()
        return {"devices": devices}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/device/select")
def select_device(req: DeviceSelectRequest):
    streamer.set_device(req.serial)
    return {"ok": True, "serial": req.serial}


@app.get("/api/device/info")
def device_info(serial: Optional[str] = Query(None)):
    try:
        w, h = adb.get_screen_size(serial)
        battery = adb.get_battery_info(serial)
        return {"screen": {"w": w, "h": h}, "battery": battery}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/input/tap")
def input_tap(req: TapRequest):
    dx, dy = scale_coords(req.x, req.y, req.canvas_w, req.canvas_h, req.device_w, req.device_h)
    adb.send_tap(dx, dy, req.serial)
    return {"ok": True, "device_coords": {"x": dx, "y": dy}}


@app.post("/api/input/swipe")
def input_swipe(req: SwipeRequest):
    dx1, dy1 = scale_coords(req.x1, req.y1, req.canvas_w, req.canvas_h, req.device_w, req.device_h)
    dx2, dy2 = scale_coords(req.x2, req.y2, req.canvas_w, req.canvas_h, req.device_w, req.device_h)
    adb.send_swipe(dx1, dy1, dx2, dy2, req.duration_ms, req.serial)
    return {"ok": True}


@app.post("/api/input/key")
def input_key(req: KeyRequest):
    adb.send_key(req.keycode, req.serial)
    return {"ok": True}


@app.post("/api/input/text")
def input_text(req: TextRequest):
    adb.send_text(req.text, req.serial)
    return {"ok": True}


@app.post("/api/call/start")
def call_start(req: CallRequest):
    adb.make_call(req.number, req.serial)
    return {"ok": True}


@app.post("/api/call/end")
def call_end(req: DeviceSelectRequest):
    adb.end_call(req.serial)
    return {"ok": True}


@app.get("/api/files")
def list_files(path: str = Query("/sdcard/"), serial: Optional[str] = Query(None)):
    try:
        entries = adb.list_files(path, serial)
        return {"path": path, "entries": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/files/download")
def download_file(path: str = Query(...), serial: Optional[str] = Query(None)):
    tmp = tempfile.mktemp(suffix=Path(path).suffix)
    ok = adb.pull_file(path, tmp, serial)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to pull file from device")
    filename = Path(path).name
    return FileResponse(tmp, filename=filename, media_type="application/octet-stream")


@app.post("/api/files/upload")
async def upload_file(
    device_path: str = Query(...),
    serial: Optional[str] = Query(None),
    file: UploadFile = File(...)
):
    tmp = tempfile.mktemp(suffix=Path(file.filename).suffix)
    with open(tmp, "wb") as f:
        f.write(await file.read())
    ok = adb.push_file(tmp, device_path + "/" + file.filename, serial)
    os.unlink(tmp)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to push file to device")
    return {"ok": True}


@app.delete("/api/files")
def delete_file(req: DeleteRequest):
    ok = adb.delete_file(req.path, req.serial)
    return {"ok": ok}


@app.websocket("/ws/screen")
async def screen_ws(websocket: WebSocket):
    await streamer.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif msg.get("type") == "set_fps":
                streamer.fps = max(1, min(30, int(msg.get("fps", 10))))
    except WebSocketDisconnect:
        streamer.disconnect(websocket)
    except Exception as e:
        logger.error(f"WS error: {e}")
        streamer.disconnect(websocket)


frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
