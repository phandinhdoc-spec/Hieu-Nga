"""Phần cứng Pi Zero 2 W: Wi-Fi, camera CSI, loa MAX98357A, cảm biến chạm."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

_CAMERA_RAM_DIR = Path("/dev/shm")
_CAMERA_WIDTH = 1280
_CAMERA_HEIGHT = 720
_CAMERA_TIMEOUT_MS = 500


class DeviceError(RuntimeError):
    pass


def connected_wifi() -> str:
    """Trả tên giao diện Wi-Fi đang kết nối; ném DeviceError nếu chưa có."""
    network_root = Path("/sys/class/net")
    try:
        interfaces = sorted(path.parent.name for path in network_root.glob("*/wireless"))
    except OSError as error:
        raise DeviceError(f"Không đọc được trạng thái Wi-Fi: {error}") from error
    if not interfaces:
        raise DeviceError("Không tìm thấy giao diện Wi-Fi.")
    for interface in interfaces:
        base = network_root / interface
        try:
            carrier = (base / "carrier").read_text(encoding="ascii").strip()
            state = (base / "operstate").read_text(encoding="ascii").strip()
        except OSError:
            continue
        if carrier == "1" and state == "up":
            return interface
    raise DeviceError("Wi-Fi chưa kết nối.")


def capture_jpeg(lens_position: str = "") -> bytes:
    """Chụp một ảnh JPEG vào RAM (/dev/shm) rồi trả về bytes.

    lens_position (đơn vị diop, 1/khoảng cách mét; 25-30 cm ~ 3.5): nếu có thì
    cố định lấy nét thủ công thay vì tự lấy nét.
    """
    camera = shutil.which("rpicam-jpeg")
    if camera is None:
        raise DeviceError("Không tìm thấy lệnh rpicam-jpeg.")
    try:
        handle = tempfile.NamedTemporaryFile(
            prefix="aigreeneye-camera-", suffix=".jpg", dir=_CAMERA_RAM_DIR, delete=False
        )
        path = Path(handle.name)
        handle.close()
    except OSError as error:
        raise DeviceError(f"Không tạo được vùng RAM cho camera: {error}") from error

    command = [
        camera,
        "--nopreview",
        "--timeout", str(_CAMERA_TIMEOUT_MS),
        "--width", str(_CAMERA_WIDTH),
        "--height", str(_CAMERA_HEIGHT),
    ]
    if lens_position:
        command += ["--autofocus-mode", "manual", "--lens-position", lens_position]
    command += ["--output", str(path)]

    try:
        _run(command, timeout=10)
        data = path.read_bytes()
    except OSError as error:
        raise DeviceError(f"Không đọc được ảnh camera trong RAM: {error}") from error
    finally:
        path.unlink(missing_ok=True)
    if not data:
        raise DeviceError("Camera tạo file JPEG rỗng.")
    if not data.startswith(b"\xff\xd8"):
        raise DeviceError("Camera trả dữ liệu không phải JPEG.")
    return data


def play_mp3(data: bytes, device: str, timeout: int = 60) -> None:
    """Phát MP3 qua ALSA (loa MAX98357A) bằng mpg123; chờ phát xong."""
    if not data:
        raise DeviceError("Dữ liệu MP3 đang trống.")
    player = shutil.which("mpg123")
    if player is None:
        raise DeviceError("Không tìm thấy lệnh mpg123.")
    command = [player, "-q", "-a", device, "-"]
    try:
        result = subprocess.run(
            command,
            input=data,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise DeviceError("Phát MP3 quá thời gian cho phép.") from error
    except OSError as error:
        raise DeviceError(f"Không thể chạy mpg123: {error}") from error
    if result.returncode != 0:
        raise DeviceError(result.stderr.decode("utf-8", "replace").strip() or "mpg123 lỗi.")


class TouchSensor:
    """Cảm biến chạm điện dung (ví dụ TTP223) nối một chân GPIO.

    Dùng gpiozero (+ lgpio trên Raspberry Pi OS / DietPi Trixie). Chỉ import khi
    dùng để phần còn lại chạy và kiểm thử được trên máy không có GPIO.
    """

    def __init__(self, gpio: int, active_high: bool = True) -> None:
        try:
            from gpiozero import DigitalInputDevice
        except ImportError as error:
            raise DeviceError("Thiếu thư viện gpiozero (apt install python3-gpiozero python3-lgpio).") from error
        try:
            if active_high:
                # TTP223: ngõ ra mức cao khi chạm -> không dùng điện trở kéo.
                self._device = DigitalInputDevice(gpio, pull_up=None, active_state=True)
            else:
                # Nút nhấn kéo xuống GND: dùng điện trở kéo lên nội bộ.
                self._device = DigitalInputDevice(gpio, pull_up=True)
        except Exception as error:  # noqa: BLE001 - gpiozero ném nhiều loại lỗi khác nhau
            raise DeviceError(f"Không mở được GPIO{gpio}: {error}") from error

    def wait_for_touch(self) -> None:
        self._device.wait_for_active()

    def wait_for_release(self, timeout: float | None = None) -> None:
        self._device.wait_for_inactive(timeout)

    def close(self) -> None:
        self._device.close()


def _run(command: list[str], *, timeout: int) -> None:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise DeviceError(f"{Path(command[0]).name} chạy quá thời gian cho phép.") from error
    except OSError as error:
        raise DeviceError(f"Không thể chạy {command[0]}: {error}") from error
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise DeviceError(message or f"{Path(command[0]).name} thất bại (mã {result.returncode}).")
