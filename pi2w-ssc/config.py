"""CẤU HÌNH (các con số và lựa chọn) của thiết bị AI Green Eye.

NGUYÊN TẮC: mọi thứ đã được CHỌN SẴN và GHI CỨNG ngay trong file này, nên học
sinh KHÔNG cần tạo hay sửa file cấu hình nào. File ".env" (nếu có) chỉ dùng khi
muốn đổi một giá trị nào đó – xem bảng "CÁC GIÁ TRỊ MẶC ĐỊNH" bên dưới.

Thứ tự ưu tiên khi một giá trị được khai báo ở nhiều nơi (cao -> thấp):
    biến môi trường  >  file .env  >  giá trị mặc định ghi cứng ở đây
"""

from __future__ import annotations

import os                                  # đọc biến môi trường
import re                                  # xử lý chuỗi (cắt chú thích cuối dòng)
from dataclasses import dataclass          # tạo "hộp đựng" dữ liệu gọn gàng
from pathlib import Path                   # làm việc với đường dẫn file


# ===========================================================================
# CÁC GIÁ TRỊ MẶC ĐỊNH (đã chọn sẵn – thường không cần đổi)
# ===========================================================================

# Mật khẩu chung giữa Pi và server. PHẢI GIỐNG với DEFAULT_TOKEN trong server/server.py.
DEFAULT_SERVER_TOKEN = "d26a5af4e93257eda0aeb44d0db6da1f"

# Địa chỉ server. "auto" = Pi tự lắng nghe và tìm server trong mạng (khuyên dùng).
# Muốn chỉ định cứng thì ghi vào .env, ví dụ MAC_SERVER_URL=http://192.168.1.50:8080
DEFAULT_SERVER_URL = "auto"

# Số chân GPIO nối nút bấm. GPIO25 chính là chân vật lí số 22 trên Pi.
# (GPIO18, 19, 21 đã bị loa MAX98357A dùng nên không dùng cho nút.)
DEFAULT_TOUCH_GPIO = 25

# Nút bấm của nhóm nối chân GPIO25 xuống GND (đất): ấn nút thì chân bị kéo xuống 0V.
# Vì vậy "ấn nút" ứng với mức THẤP => TOUCH_ACTIVE_HIGH = False.
# (Nếu dùng cảm biến chạm TTP223 – ngõ ra lên mức cao khi chạm – thì đổi thành true.)
DEFAULT_TOUCH_ACTIVE_HIGH = False

# Thiết bị phát âm thanh của Linux. "default" là loa MAX98357A đã cài sẵn.
DEFAULT_PLAYBACK_DEVICE = "default"

# Chờ server trả lời tối đa bao nhiêu giây (Gemini nhìn ảnh có thể mất vài giây).
DEFAULT_COMMAND_TIMEOUT_SECONDS = 60

# Gặp lỗi mạng thì thử lại thêm mấy lần trước khi báo lỗi.
DEFAULT_HTTP_RETRIES = 2

# Bật ngay "chế độ liên tục" khi khởi động xong (true), hay đợi ấn nút mới chạy (false).
DEFAULT_START_ACTIVE = True

# Nghỉ bao nhiêu giây giữa hai lần chụp trong chế độ liên tục.
DEFAULT_LOOP_INTERVAL_SECONDS = 1.0

# Vị trí lấy nét của camera. Để trống = camera tự lấy nét.
# Điền 3.5 = cố định lấy nét ở khoảng 28 cm (chưa kiểm chứng).
DEFAULT_LENS_POSITION = ""


class ConfigError(ValueError):
    """Lỗi khi giá trị cấu hình sai (ví dụ GPIO ghi chữ thay vì số)."""


@dataclass(frozen=True)
class Config:
    """Một "hộp" chứa toàn bộ cấu hình đã đọc xong. frozen=True: tạo xong không ai sửa được."""

    server_url: str               # địa chỉ server; "" nghĩa là tự tìm
    server_token: str             # mật khẩu gửi kèm mỗi yêu cầu
    playback_device: str          # thiết bị loa
    touch_gpio: int               # chân GPIO của nút bấm
    touch_active_high: bool       # nút bấm tạo mức cao (True) hay mức thấp (False)
    command_timeout_seconds: int  # thời gian chờ server
    http_retries: int             # số lần thử lại
    start_active: bool            # bật liên tục ngay khi khởi động?
    loop_interval_seconds: float  # nghỉ giữa hai lần chụp
    lens_position: str            # lấy nét camera ("" = tự động)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Đọc cấu hình: lấy mặc định, rồi chồng .env và biến môi trường lên trên."""
        values = _read_env(path or Path(__file__).with_name(".env"))
        values.update(os.environ)

        server_url = values.get("MAC_SERVER_URL", DEFAULT_SERVER_URL).strip().rstrip("/")
        if server_url.lower() in ("", "auto"):
            server_url = ""  # "" = chưa biết, sẽ tự đi tìm bằng tiếng "hét" của server
        elif not server_url.startswith(("http://", "https://")):
            raise ConfigError("MAC_SERVER_URL phải là 'auto' hoặc bắt đầu bằng http:// hoặc https://")

        return cls(
            server_url=server_url,
            server_token=values.get("SERVER_TOKEN", "").strip() or DEFAULT_SERVER_TOKEN,
            playback_device=values.get("ONBOARD_PLAYBACK_DEVICE", DEFAULT_PLAYBACK_DEVICE).strip()
            or DEFAULT_PLAYBACK_DEVICE,
            touch_gpio=_integer(values, "TOUCH_GPIO", DEFAULT_TOUCH_GPIO, minimum=0, maximum=27),
            touch_active_high=_bool(values, "TOUCH_ACTIVE_HIGH", DEFAULT_TOUCH_ACTIVE_HIGH),
            command_timeout_seconds=_integer(
                values, "COMMAND_TIMEOUT_SECONDS", DEFAULT_COMMAND_TIMEOUT_SECONDS, minimum=1
            ),
            http_retries=_integer(values, "HTTP_RETRIES", DEFAULT_HTTP_RETRIES, minimum=0),
            start_active=_bool(values, "START_ACTIVE", DEFAULT_START_ACTIVE),
            loop_interval_seconds=_number(
                values, "LOOP_INTERVAL_SECONDS", DEFAULT_LOOP_INTERVAL_SECONDS, minimum=0.0
            ),
            lens_position=values.get("LENS_POSITION", DEFAULT_LENS_POSITION).strip(),
        )


# ===========================================================================
# CÁC HÀM PHỤ: đọc file .env và đổi chữ thành số / đúng-sai
# ===========================================================================

def _read_env(path: Path) -> dict[str, str]:
    """Đọc file .env: mỗi dòng dạng TEN=giatri. Bỏ dòng trống và dòng bắt đầu bằng #.

    Không có file .env thì trả về {} (rỗng) – hoàn toàn bình thường, khi đó
    dùng toàn bộ giá trị mặc định ở trên.
    """
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key:
            raise ConfigError(f"Dòng .env không hợp lệ: {raw_line}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]  # bỏ dấu nháy bao quanh
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()  # bỏ chú thích cuối dòng
        values[key] = value
    return values


def _integer(values: dict[str, str], key: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    """Đọc một số nguyên, kiểm tra nằm trong khoảng cho phép."""
    raw = values.get(key, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{key} không phải số nguyên: {raw}") from error
    if value < minimum or (maximum is not None and value > maximum):
        limit = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise ConfigError(f"{key} phải nằm trong khoảng {limit}: {raw}")
    return value


def _number(values: dict[str, str], key: str, default: float, *, minimum: float) -> float:
    """Đọc một số thực (có thể có phần thập phân, ví dụ 1.5)."""
    raw = values.get(key, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigError(f"{key} không phải số: {raw}") from error
    if value < minimum:
        raise ConfigError(f"{key} phải >= {minimum}: {raw}")
    return value


def _bool(values: dict[str, str], key: str, default: bool) -> bool:
    """Đọc giá trị đúng/sai: true/yes/on/1 là ĐÚNG; false/no/off/0 là SAI; để trống = mặc định."""
    raw = values.get(key, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} không phải giá trị đúng/sai: {raw}")
