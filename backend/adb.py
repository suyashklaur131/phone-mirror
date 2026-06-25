import subprocess
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def run_adb(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    cmd = ["adb"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return result
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ADB command timed out: {' '.join(cmd)}")
    except FileNotFoundError:
        raise RuntimeError("adb not found. Install Android SDK Platform Tools and add to PATH.")


def get_devices() -> list[dict]:
    result = run_adb(["devices", "-l"])
    lines = result.stdout.decode().strip().split("\n")[1:]
    devices = []
    for line in lines:
        if line.strip() and "device" in line:
            parts = line.split()
            serial = parts[0]
            state = parts[1]
            model = ""
            for part in parts:
                if part.startswith("model:"):
                    model = part.replace("model:", "").replace("_", " ")
            devices.append({"serial": serial, "state": state, "model": model})
    return devices


def get_screen_size(serial: Optional[str] = None) -> tuple[int, int]:
    args = ["-s", serial] if serial else []
    result = run_adb(args + ["shell", "wm", "size"])
    output = result.stdout.decode().strip()
    try:
        size_str = output.split(":")[-1].strip()
        w, h = size_str.split("x")
        return int(w), int(h)
    except Exception:
        return 1080, 1920


def screencap(serial: Optional[str] = None) -> Optional[bytes]:
    args = ["-s", serial] if serial else []
    result = run_adb(args + ["exec-out", "screencap", "-p"], timeout=5)
    if result.returncode == 0 and result.stdout:
        return result.stdout
    return None


def send_tap(x: int, y: int, serial: Optional[str] = None):
    args = ["-s", serial] if serial else []
    run_adb(args + ["shell", "input", "tap", str(x), str(y)])


def send_swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300, serial: Optional[str] = None):
    args = ["-s", serial] if serial else []
    run_adb(args + ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])


def send_key(keycode: int, serial: Optional[str] = None):
    args = ["-s", serial] if serial else []
    run_adb(args + ["shell", "input", "keyevent", str(keycode)])


def send_text(text: str, serial: Optional[str] = None):
    escaped = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')
    args = ["-s", serial] if serial else []
    run_adb(args + ["shell", "input", "text", escaped])


def make_call(phone_number: str, serial: Optional[str] = None):
    args = ["-s", serial] if serial else []
    run_adb(args + [
        "shell", "am", "start",
        "-a", "android.intent.action.CALL",
        "-d", f"tel:{phone_number}"
    ])


def end_call(serial: Optional[str] = None):
    send_key(6, serial)


def list_files(path: str = "/sdcard/", serial: Optional[str] = None) -> list[dict]:
    args = ["-s", serial] if serial else []
    result = run_adb(args + ["shell", "ls", "-lA", "--color=never", path], timeout=10)
    output = result.stdout.decode(errors="replace").strip()
    entries = []
    for line in output.split("\n"):
        line = line.strip()
        if not line or line.startswith("total"):
            continue
        parts = line.split(None, 7)
        if len(parts) < 5:
            continue
        perms = parts[0]
        is_dir = perms.startswith("d")
        is_link = perms.startswith("l")
        name = parts[-1].split(" -> ")[0] if is_link else parts[-1]
        size = parts[4] if len(parts) > 4 else "0"
        date = f"{parts[5]} {parts[6]}" if len(parts) > 6 else ""
        entries.append({
            "name": name,
            "is_dir": is_dir,
            "is_link": is_link,
            "size": size,
            "date": date,
            "path": path.rstrip("/") + "/" + name,
        })
    return entries


def pull_file(device_path: str, local_path: str, serial: Optional[str] = None) -> bool:
    args = ["-s", serial] if serial else []
    result = run_adb(args + ["pull", device_path, local_path], timeout=60)
    return result.returncode == 0


def push_file(local_path: str, device_path: str, serial: Optional[str] = None) -> bool:
    args = ["-s", serial] if serial else []
    result = run_adb(args + ["push", local_path, device_path], timeout=60)
    return result.returncode == 0


def delete_file(device_path: str, serial: Optional[str] = None) -> bool:
    args = ["-s", serial] if serial else []
    result = run_adb(args + ["shell", "rm", "-rf", device_path])
    return result.returncode == 0


def get_battery_info(serial: Optional[str] = None) -> dict:
    args = ["-s", serial] if serial else []
    result = run_adb(args + ["shell", "dumpsys", "battery"])
    info = {"level": 0, "charging": False, "temperature": 0}
    for line in result.stdout.decode().split("\n"):
        line = line.strip()
        if "level:" in line:
            info["level"] = int(line.split(":")[-1].strip())
        elif "status:" in line:
            status = int(line.split(":")[-1].strip())
            info["charging"] = status in (2, 5)
        elif "temperature:" in line:
            temp_raw = int(line.split(":")[-1].strip())
            info["temperature"] = temp_raw / 10.0
    return info
