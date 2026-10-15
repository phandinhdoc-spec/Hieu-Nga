"""PHẦN CỨNG của Raspberry Pi Zero 2 W: Wi-Fi, camera, loa và nút bấm.

File này là "đôi tay đôi mắt" của thiết bị:
  - connected_wifi() : Pi đã nối Wi-Fi chưa?
  - capture_jpeg()   : chụp một tấm ảnh bằng camera.
  - play_mp3()       : phát một file âm thanh MP3 ra loa.
  - TouchSensor      : đọc nút bấm nối vào chân GPIO.

Mọi lỗi phần cứng đều được báo bằng DeviceError (kèm lời giải thích tiếng Việt)
để chương trình chính biết đường xử lý, thay vì bị "đứng hình".
"""

from __future__ import annotations

import shutil          # shutil.which: tìm xem một lệnh (ví dụ mpg123) có trên máy không
import subprocess      # chạy các lệnh bên ngoài (chụp ảnh, phát nhạc)
import tempfile        # tạo file tạm
import time            # đo thời gian, chờ
from pathlib import Path

# Ảnh chụp xong được cất tạm ở /dev/shm. Đó là bộ nhớ RAM, nên KHÔNG ghi lên thẻ nhớ
# (ghi nhiều làm hỏng thẻ nhớ nhanh). Mất điện là tự biến mất.
_CAMERA_RAM_DIR = Path("/dev/shm")
_CAMERA_WIDTH = 1280        # chiều rộng ảnh (pixel) – vừa đủ nét, gửi nhanh
_CAMERA_HEIGHT = 720        # chiều cao ảnh
_CAMERA_TIMEOUT_MS = 500    # camera "làm nóng" 0,5 giây trước khi chụp (để tự chỉnh sáng)


class DeviceError(RuntimeError):
    """Lỗi của thiết bị (camera hỏng, không có loa, mất Wi-Fi...)."""


# ===========================================================================
# WI-FI
# ===========================================================================
def connected_wifi() -> str:
    """Trả về tên card Wi-Fi đang có mạng (ví dụ "wlan0"); chưa có mạng thì ném DeviceError.

    Linux ghi trạng thái mạng thành các file nhỏ trong /sys/class/net/<tên card>/.
    Ta đọc 2 file: "carrier" (=1 là đã nối sóng) và "operstate" (="up" là đang hoạt động).
    """
    network_root = Path("/sys/class/net")
    try:
        # Card Wi-Fi là card có thư mục con tên "wireless".
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


# ===========================================================================
# CAMERA
# ===========================================================================
def capture_jpeg(lens_position: str = "") -> bytes:
    """Chụp một ảnh JPEG và trả về dữ liệu ảnh (bytes).

    Dùng lệnh `rpicam-jpeg` có sẵn của Raspberry Pi.
    lens_position: số "diop" (= 1 chia cho khoảng cách tính bằng mét). Ví dụ vật cách
    28 cm thì 1/0,28 ≈ 3,5. Để trống = camera tự lấy nét.
    """
    camera = shutil.which("rpicam-jpeg")  # tìm lệnh chụp ảnh trên máy
    if camera is None:
        raise DeviceError("Không tìm thấy lệnh rpicam-jpeg.")
    try:
        # Tạo sẵn một file tạm trong RAM để lệnh chụp ảnh ghi kết quả vào.
        handle = tempfile.NamedTemporaryFile(
            prefix="aigreeneye-camera-", suffix=".jpg", dir=_CAMERA_RAM_DIR, delete=False
        )
        path = Path(handle.name)
        handle.close()
    except OSError as error:
        raise DeviceError(f"Không tạo được vùng RAM cho camera: {error}") from error

    command = [
        camera,
        "--nopreview",                           # không hiện ảnh xem trước lên màn hình
        "--timeout", str(_CAMERA_TIMEOUT_MS),
        "--width", str(_CAMERA_WIDTH),
        "--height", str(_CAMERA_HEIGHT),
    ]
    if lens_position:
        command += ["--autofocus-mode", "manual", "--lens-position", lens_position]
    command += ["--output", str(path)]

    try:
        _run(command, timeout=10)    # chụp (tối đa chờ 10 giây)
        data = path.read_bytes()     # đọc ảnh vừa chụp từ RAM
    except OSError as error:
        raise DeviceError(f"Không đọc được ảnh camera trong RAM: {error}") from error
    finally:
        path.unlink(missing_ok=True)  # dù thành công hay lỗi cũng xóa file tạm
    if not data:
        raise DeviceError("Camera tạo file JPEG rỗng.")
    if not data.startswith(b"\xff\xd8"):  # mọi file JPEG thật đều bắt đầu bằng 2 byte FF D8
        raise DeviceError("Camera trả dữ liệu không phải JPEG.")
    return data


# ===========================================================================
# LOA
# ===========================================================================
def play_mp3(data: bytes, device: str, timeout: int = 60, cancel=None) -> None:
    """Phát file MP3 (dạng bytes) ra loa MAX98357A bằng chương trình `mpg123`; chờ phát xong.

    device : tên thiết bị âm thanh ("default" là loa đã cài).
    timeout: phát quá số giây này thì coi là lỗi.
    cancel : một hàm không tham số. Trong lúc phát, cứ 0,05 giây ta hỏi hàm này một lần;
             nếu nó trả True thì DỪNG PHÁT NGAY. Dùng để ấn nút tắt là loa im luôn.
    """
    if not data:
        raise DeviceError("Dữ liệu MP3 đang trống.")
    player = shutil.which("mpg123")
    if player is None:
        raise DeviceError("Không tìm thấy lệnh mpg123.")

    # ---- Cách 1: phát một mạch (khi không cần ngắt giữa chừng) ----
    if cancel is None:
        command = [player, "-q", "-a", device, "-"]  # "-" = đọc nhạc từ dữ liệu ta đưa vào
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
        return

    # ---- Cách 2: phát và liên tục kiểm tra xem có bị yêu cầu dừng không ----
    try:
        # Ghi MP3 ra file tạm trong RAM rồi cho mpg123 phát file đó.
        with tempfile.NamedTemporaryFile(prefix="aigreeneye-speech-", suffix=".mp3", dir=_CAMERA_RAM_DIR) as handle:
            handle.write(data)
            handle.flush()
            process = subprocess.Popen(
                [player, "-q", "-a", device, handle.name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            deadline = time.monotonic() + timeout
            while process.poll() is None:  # None = mpg123 vẫn đang phát
                if cancel():
                    process.terminate()    # bị yêu cầu dừng -> tắt tiếng ngay
                    process.wait(timeout=2)
                    return
                if time.monotonic() > deadline:
                    process.kill()
                    process.wait()
                    raise DeviceError("Phát MP3 quá thời gian cho phép.")
                time.sleep(0.05)
            if process.returncode != 0:
                raise DeviceError((process.stderr.read() or b"").decode("utf-8", "replace").strip() or "mpg123 lỗi.")
    except OSError as error:
        raise DeviceError(f"Không thể phát MP3: {error}") from error


# ===========================================================================
# NÚT BẤM
# ===========================================================================
class TouchSensor:
    """Nút bấm (hoặc cảm biến chạm) nối vào một chân GPIO.

    Dùng thư viện gpiozero (+ lgpio). Chỉ nạp thư viện khi thật sự tạo nút, để các
    phần khác vẫn chạy/kiểm thử được trên máy tính không có chân GPIO.

    active_high:
      - False (mặc định của nhóm): nút nối chân GPIO xuống GND. Bình thường chân ở mức
        CAO nhờ điện trở kéo lên bên trong Pi; ấn nút thì chân bị kéo xuống mức THẤP.
      - True: cảm biến chạm kiểu TTP223 (ngõ ra lên mức cao khi chạm).
    """

    def __init__(self, gpio: int, active_high: bool = True) -> None:
        try:
            from gpiozero import DigitalInputDevice
        except ImportError as error:
            raise DeviceError("Thiếu thư viện gpiozero (apt install python3-gpiozero python3-lgpio).") from error
        try:
            if active_high:
                # TTP223 tự kéo chân lên cao khi chạm -> không cần điện trở kéo.
                self._device = DigitalInputDevice(gpio, pull_up=None, active_state=True)
            else:
                # Nút nối GND: bật điện trở kéo lên để lúc không ấn chân đứng yên ở mức cao.
                # Nếu thiếu điện trở này, chân "lơ lửng" và tự nhảy lung tung (rất dễ hiểu nhầm
                # là có người ấn!).
                self._device = DigitalInputDevice(gpio, pull_up=True)
        except Exception as error:  # noqa: BLE001 - gpiozero có nhiều loại lỗi khác nhau
            raise DeviceError(f"Không mở được GPIO{gpio}: {error}") from error

    def on_touch(self, callback) -> None:
        """Đăng ký hàm `callback`: mỗi lần BẮT ĐẦU ấn nút, hàm này được gọi (từ luồng riêng)."""
        self._device.when_activated = callback

    def wait_for_touch(self) -> None:
        """Đứng chờ tới khi có người ấn nút."""
        self._device.wait_for_active()

    def wait_for_release(self, timeout: float | None = None) -> None:
        """Đứng chờ tới khi người ấn nhả tay ra (tối đa `timeout` giây)."""
        self._device.wait_for_inactive(timeout)

    def close(self) -> None:
        """Trả chân GPIO lại cho hệ thống khi tắt chương trình."""
        self._device.close()


# ===========================================================================
# HÀM PHỤ
# ===========================================================================
def _run(command: list[str], *, timeout: int) -> None:
    """Chạy một lệnh bên ngoài, chờ xong. Lệnh lỗi thì ném DeviceError kèm lời lỗi của lệnh."""
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
