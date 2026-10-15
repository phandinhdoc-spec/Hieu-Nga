"""NGƯỜI LIÊN LẠC giữa Pi và MÁY CHỦ (server) chạy trên máy tính.

Pi quá yếu để tự nhìn ảnh, nên mọi việc "khó" đều nhờ server làm:
  - health()   : hỏi "server ơi, bạn còn sống không?"
  - classify() : gửi ảnh nhờ Gemini phân loại rác, nhận lại chữ (ví dụ "VO_CO").
  - tts()      : gửi một câu chữ, nhận lại file MP3 giọng đọc câu đó.

TỰ ĐỘNG TÌM SERVER: học sinh mang server sang máy tính nào cũng được, địa chỉ
mạng của máy đó mỗi nơi một khác. Vì vậy server cứ vài giây lại "hét" lên mạng
"Tôi ở đây!" (gói UDP vào cổng 8081). File này lắng nghe tiếng hét đó để biết
địa chỉ, nên không ai phải gõ địa chỉ bằng tay.

Chỉ dùng thư viện có sẵn của Python (urllib), không cần cài thêm gì trên Pi.
"""

from __future__ import annotations

import base64               # đổi ảnh thành dạng chữ để gửi, và đổi chữ nhận về thành tiếng Việt
import http.client          # để bắt lỗi khi server ngắt kết nối giữa chừng
import json                 # đóng gói/mở gói dữ liệu JSON
import socket               # nghe tiếng "hét" (beacon) của server
import time                 # nghỉ giữa các lần thử lại
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Phải GIỐNG với server/server.py (BEACON_PORT, BEACON_PREFIX).
BEACON_PORT = 8081
BEACON_PREFIX = "AGEYE"


class ServerClientError(RuntimeError):
    """Mọi lỗi khi nói chuyện với server."""


class ServerUnreachableError(ServerClientError):
    """Không nối được tới server (server chưa bật, sai mạng, mất Wi-Fi...).

    Khác với việc "nối được nhưng server trả lỗi" (ví dụ sai mật khẩu, Gemini lỗi).
    Pi dựa vào sự khác nhau này để chọn câu thông báo cho đúng.
    """


def discover_server(timeout: float = 6.0) -> str | None:
    """Nghe tối đa `timeout` giây xem có server nào "hét" không. Thấy thì trả về địa chỉ.

    Ví dụ trả về "http://192.168.1.159:8080"; không thấy gì thì trả về None.
    """
    deadline = time.monotonic() + timeout
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("", BEACON_PORT))  # "" = nghe trên mọi mạng của Pi
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                listener.settimeout(remaining)
                try:
                    data, (sender_ip, _) = listener.recvfrom(256)
                except socket.timeout:
                    return None
                # Gói hợp lệ có dạng "AGEYE|8080".
                prefix, _, port = data.decode("ascii", "replace").partition("|")
                if prefix == BEACON_PREFIX and port.strip().isdigit():
                    return f"http://{sender_ip}:{int(port)}"
    except OSError:
        return None  # không mở được cổng nghe (hiếm gặp) -> coi như không tìm thấy


class ServerClient:
    def __init__(
        self,
        server_url: str,
        token: str,
        timeout: int,
        retries: int,
        auto_discover: bool = True,
    ) -> None:
        # server_url để trống ("") nghĩa là chưa biết địa chỉ, sẽ tự đi tìm.
        self.server_url = server_url
        self.token = token            # mật khẩu chung với server
        self.timeout = timeout        # chờ server trả lời tối đa bao nhiêu giây
        self.retries = retries        # lỗi mạng thì thử lại thêm mấy lần
        self.auto_discover = auto_discover

    # ------------------------------------------------------------------ tìm server
    def _rediscover(self) -> bool:
        """Đi tìm server bằng tiếng "hét". Thấy địa chỉ mới thì ghi nhớ và trả True."""
        if not self.auto_discover:
            return False
        found = discover_server()
        if found and found != self.server_url:
            print(f"[TÌM SERVER] Thấy server ở {found}", flush=True)
            self.server_url = found
            return True
        return False

    # ------------------------------------------------------------------ health
    def health(self) -> None:
        """Hỏi server còn sống không (không cần mật khẩu). Lỗi thì ném ServerClientError."""
        try:
            self._health_once()
        except ServerUnreachableError:
            # Địa chỉ cũ không dùng được -> thử tìm lại bằng tiếng "hét", rồi hỏi lần nữa.
            if not self._rediscover():
                raise
            self._health_once()

    def _health_once(self) -> None:
        if not self.server_url:
            raise ServerUnreachableError("Chưa biết địa chỉ server (chưa nghe thấy server nào trong mạng).")
        request = Request(self.server_url + "/health", method="GET")
        try:
            with urlopen(request, timeout=min(self.timeout, 10)) as response:
                if response.status != 200:
                    raise ServerClientError(f"Server /health trả HTTP {response.status}.")
        except HTTPError as error:
            raise ServerClientError(f"Server /health trả HTTP {error.code}.") from error
        except (URLError, OSError, http.client.HTTPException) as error:
            raise ServerUnreachableError(f"Không thể kết nối server {self.server_url}: {error}") from error

    # ------------------------------------------------------------------ phân loại ảnh
    def classify(self, image: bytes, prompt: str) -> str:
        """Gửi ảnh JPEG + câu hỏi (prompt) tới server; trả về chữ Gemini trả lời.

        Server cũng gửi kèm một file MP3 nhưng ta bỏ đi: Pi tự chọn câu để đọc
        dựa vào mã phân loại (ví dụ VO_CO -> "Rác vô cơ.").
        """
        payload = {
            "text": prompt,
            "mode": "observe",  # chế độ "quan sát ảnh"
            "image": base64.b64encode(image).decode("ascii"),
            "imageContentType": "image/jpeg",
        }
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        body, content_type, encoded_text = self._post("/command", data, 10 * 1024 * 1024)
        if not content_type.startswith("audio/mpeg") or not body:
            raise ServerClientError("Server trả phản hồi /command không hợp lệ.")
        try:
            # Chữ của Gemini nằm trong header, được server mã hóa base64.
            return (
                base64.b64decode(encoded_text, validate=True).decode("utf-8")
                if encoded_text
                else ""
            )
        except (ValueError, UnicodeDecodeError) as error:
            raise ServerClientError("Server trả header text Gemini không hợp lệ.") from error

    # ------------------------------------------------------------------ giọng đọc
    def tts(self, text: str) -> bytes:
        """Nhờ server đọc một câu thành file MP3 (tts = text-to-speech = chữ thành tiếng)."""
        data = json.dumps({"text": text}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        body, content_type, _ = self._post("/tts", data, 10 * 1024 * 1024)
        if not content_type.startswith("audio/mpeg") or not body:
            raise ServerClientError("Server trả phản hồi /tts không hợp lệ.")
        return body

    # ------------------------------------------------------------------ gửi yêu cầu POST
    def _post(self, path: str, data: bytes, response_limit: int) -> tuple[bytes, str, str | None]:
        """Gửi dữ liệu tới server, tự thử lại khi lỗi mạng. Trả (nội dung, loại, chữ Gemini)."""
        rediscovered = False
        attempt = 0
        while True:
            try:
                if not self.server_url:
                    raise ServerUnreachableError("Chưa biết địa chỉ server.")
                request = Request(
                    self.server_url + path,
                    data=data,
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {self.token}",  # gửi kèm mật khẩu
                        "Content-Type": "application/json",
                    },
                )
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read(response_limit + 1)
                    if len(body) > response_limit:
                        raise ServerClientError("Phản hồi từ server vượt quá giới hạn cho phép.")
                    return (
                        body,
                        response.headers.get_content_type().lower(),
                        response.headers.get("X-ThienNhan-Text-Base64"),
                    )
            except HTTPError as error:
                # Server trả lỗi (401 sai mật khẩu, 502 Gemini lỗi...) -> không thử lại.
                raise _server_error(error) from error
            except (ServerUnreachableError, URLError, OSError, http.client.HTTPException) as error:
                if attempt < self.retries:
                    attempt += 1
                    time.sleep(min(2**attempt, 3))  # nghỉ 2-3 giây rồi thử lại
                    continue
                if not rediscovered:
                    # Hết lượt thử: có thể server đã đổi sang máy khác -> đi tìm lại một lần.
                    rediscovered = True
                    if self._rediscover():
                        attempt = 0
                        continue
                if isinstance(error, ServerUnreachableError):
                    raise
                raise ServerUnreachableError(f"Không thể kết nối server {self.server_url}: {error}") from error


def _server_error(error: HTTPError) -> ServerClientError:
    """Biến câu trả lời lỗi của server thành một ServerClientError dễ đọc."""
    raw = error.read(64 * 1024)
    code, message = "server_error", str(error.reason or "Server xử lý thất bại.")
    try:
        detail = json.loads(raw).get("error", {})
        if isinstance(detail, dict):
            code = str(detail.get("code") or code)
            message = str(detail.get("message") or message)
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        pass
    return ServerClientError(f"HTTP {error.code} {code}: {message}")
