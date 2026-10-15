"""MÁY CHỦ (SERVER) CỦA "AI GREEN EYE" – chạy trên máy tính của học sinh.

┌──────────────────────────────────────────────────────────────────────────┐
│ CÂU CHUYỆN CẢ HỆ THỐNG (đọc đoạn này trước cho dễ hiểu)                 │
│                                                                          │
│  1. Con Raspberry Pi Zero 2 W có camera nhưng RẤT YẾU, không tự "hiểu"  │
│     được ảnh là rác gì.                                                  │
│  2. Nên Pi chụp ảnh rồi gửi qua Wi-Fi cho MÁY TÍNH này.                  │
│  3. Máy tính này (chương trình server.py) nhờ "bộ não" Gemini của Google │
│     xem ảnh và trả lời: rác vô cơ / hữu cơ / khác.                       │
│  4. Server gửi câu trả lời về cho Pi, Pi đọc to qua loa.                 │
│                                                                          │
│  Pi  --(ảnh)-->  server.py  --(ảnh)-->  Gemini                           │
│  Pi  <--(chữ)--  server.py  <--(chữ)--  Gemini                           │
└──────────────────────────────────────────────────────────────────────────┘

Để Pi tự tìm thấy máy tính này mà không cần gõ địa chỉ, server cứ vài giây lại
"hét to" lên mạng một câu: "Tôi là server đây, ở cổng 8080!" (gọi là tín hiệu
báo hiệu – beacon). Pi nghe thấy là biết đường gọi tới.

Các "cửa" (đường dẫn) mà server mở cho Pi gọi vào (khớp pi2w-ssc/server_client.py):
  GET  /health   -> hỏi "bạn còn sống không?"  -> trả {"status":"ok"}   (không cần mật khẩu)
  POST /command  -> gửi ảnh + câu hỏi, nhờ Gemini phân loại.
                    Trả về: một file âm thanh MP3 + chữ của Gemini giấu trong
                    header "X-ThienNhan-Text-Base64" (đã mã hóa base64 cho an toàn).
  POST /tts      -> gửi một câu chữ, nhận lại file MP3 giọng đọc câu đó.
Nếu có lỗi, server trả JSON dạng {"error":{"code":"...","message":"..."}}.
Mật khẩu (gọi là token) nằm trong header:  Authorization: Bearer <SERVER_TOKEN>

Chương trình này chỉ dùng thư viện có sẵn của Python, cộng thêm 1 thư viện
tên edge-tts (để biến chữ thành giọng nói tiếng Việt).
"""

# "from __future__ import annotations" giúp Python cũ (3.9) hiểu cách viết kiểu dữ liệu mới.
from __future__ import annotations

import asyncio          # chạy các hàm "async" (edge-tts cần cái này)
import base64           # mã hóa/giải mã ảnh và chữ thành dạng chữ-số an toàn để gửi qua mạng
import binascii         # bắt lỗi khi giải mã base64 sai
import hmac             # so sánh mật khẩu một cách an toàn
import json             # đọc/ghi dữ liệu dạng JSON
import logging          # in ra màn hình những dòng "nhật ký" (log) cho dễ theo dõi
import os               # đọc biến môi trường
import re               # xử lý chuỗi bằng biểu thức chính quy
import socket           # nói chuyện qua mạng ở mức thấp (dùng cho beacon, tìm địa chỉ IP)
import sys              # thoát chương trình, biết Python đang chạy là bản nào
import tempfile         # tạo thư mục tạm
import threading        # chạy việc phát beacon song song ở "luồng" riêng
import time             # tạm dừng giữa các lần phát beacon
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # máy chủ web có sẵn của Python
from pathlib import Path                                               # làm việc với đường dẫn file
from urllib.error import HTTPError, URLError                           # các loại lỗi khi gọi mạng
from urllib.request import Request, urlopen                            # gọi sang Gemini

log = logging.getLogger("ageye-server")

# ---------------------------------------------------------------------------
# CÁC HẰNG SỐ CỐ ĐỊNH (đã chọn sẵn, học sinh không cần sửa)
# ---------------------------------------------------------------------------

# MẬT KHẨU chung giữa Pi và server. Hai bên PHẢI giống nhau, nên đã ghi cứng ở
# cả hai nơi (ở Pi là pi2w-ssc/config.py). Nhờ vậy học sinh không phải gõ gì.
# Nếu muốn đổi thì đổi ở CẢ HAI NƠI.
DEFAULT_TOKEN = "d26a5af4e93257eda0aeb44d0db6da1f"

MAX_TEXT = 2000                  # câu hỏi tối đa 2000 ký tự (Pi gửi ngắn hơn 1800)
MAX_BODY = 12 * 1024 * 1024      # một lần gửi tối đa 12 MB
MAX_IMAGE = 8 * 1024 * 1024      # ảnh tối đa 8 MB sau khi giải mã
ALLOWED_IMAGES = {"image/jpeg", "image/png", "image/webp"}  # các loại ảnh chấp nhận

# Một file MP3 "im lặng" cực ngắn. Khi Pi gửi ảnh, Pi chỉ cần CHỮ của Gemini,
# không cần giọng đọc. Nhưng giao thức vẫn yêu cầu trả về âm thanh, nên ta trả
# MP3 im lặng này cho nhanh (đỡ mất vài giây tạo giọng đọc).
SILENT_MP3 = bytes([0xFF, 0xFB, 0x90, 0x04]) + bytes(413)

# Cổng UDP dùng để "hét" beacon. Pi cũng nghe đúng cổng này (xem server_client.py).
BEACON_PORT = 8081
BEACON_INTERVAL_SECONDS = 2      # cứ 2 giây hét một lần
BEACON_PREFIX = "AGEYE"          # mở đầu câu hét, để Pi nhận ra đúng là server của mình


class ApiError(Exception):
    """Một lỗi mà ta muốn báo lại cho Pi: gồm mã HTTP, mã ngắn (code) và lời giải thích."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---------------------------------------------------------------------------
# CẤU HÌNH
# ---------------------------------------------------------------------------
class Settings:
    """Gom mọi thông số cấu hình vào một chỗ. Đọc từ file .env (và biến môi trường)."""

    def __init__(self, env: dict[str, str]) -> None:
        # Mật khẩu: nếu .env không ghi thì dùng mật khẩu cố định ở trên.
        self.token = env.get("SERVER_TOKEN", "").strip() or DEFAULT_TOKEN
        # Chìa khóa để gọi Gemini (lấy ở https://aistudio.google.com/apikey). BẮT BUỘC có.
        self.api_key = env.get("GEMINI_API_KEY", "").strip()
        # Tên mô hình Gemini dùng để nhìn ảnh.
        self.model = env.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
        # "Ngân sách suy nghĩ" của Gemini. 0 = không suy nghĩ lâu -> trả lời NHANH hơn.
        self.thinking_budget = env.get("GEMINI_THINKING_BUDGET", "0").strip()
        # Chờ Gemini tối đa bao nhiêu giây thì bỏ cuộc.
        self.gemini_timeout = int(env.get("GEMINI_TIMEOUT_SECONDS", "40"))
        # Giọng đọc tiếng Việt: HoaiMy (nữ) hoặc NamMinh (nam).
        self.voice = env.get("TTS_VOICE", "vi-VN-HoaiMyNeural").strip()
        # Có tạo giọng đọc khi Pi gửi ảnh không? Pi bỏ qua giọng đó nên mặc định TẮT cho nhanh.
        self.tts_on_observe = env.get("TTS_ON_OBSERVE", "false").strip().lower() in ("1", "true", "yes", "on")
        # 0.0.0.0 nghĩa là "nhận kết nối từ mọi máy trong mạng" (để Pi gọi vào được).
        self.host = env.get("HOST", "0.0.0.0").strip()
        # Số cổng (giống như số phòng trong một tòa nhà). Pi gọi tới cổng này.
        self.port = int(env.get("PORT", "8080"))

    def validate(self) -> None:
        """Kiểm tra đã có chìa khóa Gemini chưa; thiếu thì dừng và nói rõ cách sửa."""
        if not self.api_key:
            raise SystemExit(
                "\n[LỖI] Chưa có GEMINI_API_KEY.\n"
                "  1) Mở file  server/.env  bằng Notepad (Windows) hoặc TextEdit (Mac).\n"
                "  2) Điền chìa khóa Gemini vào dòng  GEMINI_API_KEY=...\n"
                "  3) Lưu file rồi chạy lại. (Xem mục 'Chìa khóa Gemini' trong HUONG-DAN.md)\n"
            )


def read_env_file(path: Path) -> dict[str, str]:
    """Đọc file .env: mỗi dòng dạng  TEN=giatri . Bỏ dòng trống và dòng bắt đầu bằng #."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            raise SystemExit(f"Dòng .env không hợp lệ: {raw}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]  # bỏ dấu ngoặc kép bao quanh
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()  # bỏ chú thích cuối dòng
        values[key] = value
    return values


# ---------------------------------------------------------------------------
# GỌI GEMINI VÀ TẠO GIỌNG ĐỌC
# ---------------------------------------------------------------------------
def call_gemini(settings: Settings, text: str, image: bytes | None, mime: str) -> str:
    """Gửi câu hỏi (text) + ảnh (nếu có) cho Gemini, nhận lại câu trả lời bằng chữ."""
    # "parts" là các phần của tin nhắn: phần chữ, và (nếu có) phần ảnh.
    parts: list[dict] = [{"text": text}]
    if image is not None:
        # Ảnh phải đổi sang base64 (một dạng chữ) để nhét vào JSON.
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(image).decode("ascii")}})
    # temperature=0: trả lời ổn định, không "sáng tạo lung tung". Tối đa 512 từ-khúc.
    generation: dict = {"temperature": 0, "maxOutputTokens": 512}
    if settings.thinking_budget:
        generation["thinkingConfig"] = {"thinkingBudget": int(settings.thinking_budget)}
    body = json.dumps({"contents": [{"role": "user", "parts": parts}], "generationConfig": generation}).encode()
    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.model}:generateContent",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": settings.api_key},
    )
    try:
        with urlopen(request, timeout=settings.gemini_timeout) as response:
            data = json.loads(response.read())
    except HTTPError as error:
        # Gemini trả lỗi (sai chìa khóa, hết hạn mức, sai tên model...).
        detail = error.read(4096).decode("utf-8", "replace")
        log.error("Gemini HTTP %s: %s", error.code, detail)
        raise ApiError(502, "gemini_error", f"Gemini trả HTTP {error.code}.") from error
    except (URLError, TimeoutError, OSError, ValueError) as error:
        # Không gọi được Gemini: thường do máy tính này mất Internet.
        log.error("Gemini lỗi kết nối: %s", error)
        raise ApiError(504, "gemini_unreachable", "Không gọi được Gemini.") from error

    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "không rõ")
        raise ApiError(502, "gemini_blocked", f"Gemini không trả kết quả (lý do: {reason}).")
    # Ghép các mẩu chữ Gemini trả về thành một câu.
    texts = [p["text"] for p in (candidates[0].get("content") or {}).get("parts", []) if p.get("text")]
    answer = "".join(texts).strip()
    if not answer:
        raise ApiError(502, "gemini_empty", "Gemini trả nội dung rỗng.")
    return answer


def tts_available() -> bool:
    """Thư viện edge-tts (đọc chữ thành tiếng) đã được cài chưa?"""
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return False
    return True


def synthesize(settings: Settings, text: str) -> bytes:
    """Biến một câu chữ thành file MP3 giọng đọc (cần Internet, dùng giọng của Microsoft Edge)."""
    try:
        import edge_tts
    except ImportError as error:
        raise ApiError(500, "tts_unavailable", "Chưa cài edge-tts (pip install edge-tts).") from error

    async def run() -> bytes:
        # Ghi tạm ra file rồi đọc lại, vì edge-tts chỉ biết "lưu thành file".
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "out.mp3"
            await edge_tts.Communicate(text, settings.voice).save(str(target))
            return target.read_bytes()

    try:
        audio = asyncio.run(run())
    except Exception as error:  # edge-tts có thể ném nhiều loại lỗi mạng khác nhau
        log.error("TTS lỗi: %s", error)
        raise ApiError(502, "tts_error", "Không tạo được giọng đọc.") from error
    if not audio:
        raise ApiError(502, "tts_empty", "TTS trả âm thanh rỗng.")
    return audio


# ---------------------------------------------------------------------------
# MÁY CHỦ WEB: nhận yêu cầu từ Pi
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    """Mỗi lần Pi gọi vào, một đối tượng Handler được tạo ra để xử lý yêu cầu đó."""

    server_version = "AGEyeServer/1.0"
    settings: Settings  # được gắn vào ở hàm make_server bên dưới
    # Hai "móc" này để lúc kiểm thử có thể thay bằng hàm giả (không gọi Gemini thật).
    gemini = staticmethod(call_gemini)
    tts = staticmethod(synthesize)

    def log_message(self, fmt: str, *args) -> None:
        """Ghi mỗi yêu cầu vào nhật ký (ví dụ: Pi 100.x.x.x gọi POST /command)."""
        log.info("%s %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        """Xử lý yêu cầu kiểu GET: chỉ có /health."""
        if self.path.split("?")[0] == "/health":
            self._json(200, {"status": "ok", "tts": tts_available()})
        else:
            self._error(ApiError(404, "not_found", "Không có đường dẫn này."))

    def do_POST(self) -> None:
        """Xử lý yêu cầu kiểu POST: /command và /tts."""
        try:
            path = self.path.split("?")[0]
            if path not in ("/command", "/tts"):
                raise ApiError(404, "not_found", "Không có đường dẫn này.")
            self._authorize()                 # 1) kiểm tra mật khẩu
            payload = self._read_json()       # 2) đọc dữ liệu Pi gửi
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ApiError(400, "bad_request", "Thiếu trường text.")
            if len(text) > MAX_TEXT:
                raise ApiError(400, "text_too_long", f"text vượt quá {MAX_TEXT} ký tự.")
            if path == "/tts":
                self._audio(self.tts(self.settings, text.strip()))
            else:
                self._command(payload, text.strip())
        except ApiError as error:
            self._error(error)
        except Exception:
            # Lỗi bất ngờ: ghi đầy đủ vào nhật ký nhưng chỉ báo Pi "lỗi nội bộ".
            log.exception("Lỗi không lường trước")
            self._error(ApiError(500, "server_error", "Server gặp lỗi nội bộ."))

    # -- /command: phần quan trọng nhất ---------------------------------------
    def _command(self, payload: dict, text: str) -> None:
        mode = payload.get("mode", "chat")
        image, mime = None, ""
        if payload.get("image"):
            mime = str(payload.get("imageContentType", "image/jpeg")).lower()
            if mime not in ALLOWED_IMAGES:
                raise ApiError(400, "bad_image", "imageContentType không được hỗ trợ.")
            try:
                image = base64.b64decode(payload["image"], validate=True)  # đổi chữ base64 về ảnh thật
            except (binascii.Error, ValueError, TypeError) as error:
                raise ApiError(400, "bad_image", "Ảnh base64 không hợp lệ.") from error
            if not image or len(image) > MAX_IMAGE:
                raise ApiError(400, "bad_image", "Ảnh rỗng hoặc quá lớn.")
        elif mode == "observe":
            raise ApiError(400, "bad_request", "mode=observe cần có ảnh.")

        # Nhờ Gemini xem ảnh và trả lời.
        answer = self.gemini(self.settings, text, image, mime)
        log.info("Gemini (%s): %s", mode, answer[:200].replace("\n", " "))
        if mode == "observe" and not self.settings.tts_on_observe:
            audio = SILENT_MP3                       # Pi không cần tiếng -> trả MP3 im lặng
        else:
            audio = self.tts(self.settings, answer)  # còn lại thì đọc câu trả lời thành tiếng
        self._audio(audio, answer)

    # -- các hàm tiện ích -----------------------------------------------------
    def _authorize(self) -> None:
        """Kiểm tra Pi có gửi đúng mật khẩu không. Sai thì báo lỗi 401."""
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        # hmac.compare_digest so sánh an toàn (không để lộ mật khẩu qua thời gian xử lý).
        if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), self.settings.token.encode()):
            raise ApiError(401, "unauthorized", "Token không hợp lệ.")

    def _read_json(self) -> dict:
        """Đọc phần thân yêu cầu (dữ liệu JSON) Pi gửi lên."""
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as error:
            raise ApiError(411, "length_required", "Thiếu Content-Length.") from error
        if length <= 0 or length > MAX_BODY:
            raise ApiError(413, "body_too_large", "Thân request rỗng hoặc quá lớn.")
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError) as error:
            raise ApiError(400, "bad_json", "JSON không hợp lệ.") from error
        if not isinstance(payload, dict):
            raise ApiError(400, "bad_json", "JSON phải là một đối tượng.")
        return payload

    def _json(self, status: int, data: dict) -> None:
        """Trả một câu trả lời dạng JSON."""
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, error: ApiError) -> None:
        """Trả lỗi theo đúng khuôn {"error": {"code": ..., "message": ...}}."""
        self._json(error.status, {"error": {"code": error.code, "message": error.message}})

    def _audio(self, audio: bytes, text: str | None = None) -> None:
        """Trả file MP3. Nếu có `text` (câu trả lời Gemini) thì giấu vào header dạng base64."""
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        if text is not None:
            self.send_header("X-ThienNhan-Text-Base64", base64.b64encode(text.encode("utf-8")).decode("ascii"))
        self.end_headers()
        self.wfile.write(audio)


def make_server(settings: Settings) -> ThreadingHTTPServer:
    """Tạo máy chủ web gắn với cấu hình. ThreadingHTTPServer = xử lý nhiều yêu cầu cùng lúc."""
    handler = type("BoundHandler", (Handler,), {"settings": settings})
    httpd = ThreadingHTTPServer((settings.host, settings.port), handler)
    httpd.daemon_threads = True
    return httpd


# ---------------------------------------------------------------------------
# BEACON: "hét" lên mạng để Pi tự tìm thấy server
# ---------------------------------------------------------------------------
def local_addresses() -> list[str]:
    """Liệt kê địa chỉ IP của máy tính này trong mạng (để in ra cho học sinh xem)."""
    found: list[str] = []
    try:
        # Mẹo: "kết nối" UDP tới một địa chỉ ngoài không gửi gói nào cả, nhưng hệ điều hành
        # sẽ cho ta biết nó định dùng địa chỉ IP nào của máy mình để đi ra ngoài.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in found and not address.startswith("127."):
                found.append(address)
    except OSError:
        pass
    return found


def beacon_loop(port: int) -> None:
    """Chạy mãi mãi: cứ 2 giây phát một gói UDP "AGEYE|8080" tới toàn mạng.

    Pi lắng nghe cổng 8081, nhận được gói này là biết server ở địa chỉ nào
    (địa chỉ người gửi) và cổng nào (số 8080 ghi trong gói).
    """
    message = f"{BEACON_PREFIX}|{port}".encode("ascii")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # cho phép phát tới cả mạng
        while True:
            try:
                sender.sendto(message, ("255.255.255.255", BEACON_PORT))
            except OSError:
                pass  # chưa có mạng thì thôi, 2 giây sau thử lại
            time.sleep(BEACON_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# HÀM CHẠY CHÍNH
# ---------------------------------------------------------------------------
def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Đọc file .env cạnh server.py; biến môi trường (nếu có) được ưu tiên hơn.
    env = read_env_file(Path(__file__).with_name(".env"))
    env.update(os.environ)
    settings = Settings(env)
    settings.validate()
    if not tts_available():
        log.error("CHƯA CÀI edge-tts: /tts sẽ lỗi 500 và Pi không khởi động được. "
                  "Chạy: %s -m pip install -r requirements.txt", sys.executable)

    try:
        httpd = make_server(settings)
    except OSError as error:
        # Lỗi hay gặp nhất: cổng 8080 đã có chương trình khác dùng (thường là server cũ chưa tắt).
        raise SystemExit(
            f"\n[LỖI] Không mở được cổng {settings.port}: {error}\n"
            "  Có thể server đã được bật ở một cửa sổ khác. Hãy đóng cửa sổ đó rồi chạy lại.\n"
        ) from error
    # Bật beacon ở luồng riêng (daemon=True: tự tắt khi chương trình chính tắt).
    threading.Thread(target=beacon_loop, args=(settings.port,), daemon=True).start()

    # In một bảng thông báo to rõ để học sinh biết server đã chạy.
    addresses = local_addresses() or ["(không rõ)"]
    print("\n" + "=" * 62)
    print("  SERVER AI GREEN EYE ĐANG CHẠY  –  ĐỪNG ĐÓNG CỬA SỔ NÀY!")
    print("  Địa chỉ máy tính này (Pi sẽ tự tìm, không cần gõ):")
    for address in addresses:
        print(f"      http://{address}:{settings.port}")
    print("  Muốn tắt server: bấm Ctrl + C (hoặc đóng cửa sổ).")
    print("=" * 62 + "\n", flush=True)
    log.info("Lắng nghe %s:%s (model %s)", settings.host, settings.port, settings.model)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
