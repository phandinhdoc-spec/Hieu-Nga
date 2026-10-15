"""Gọi Mac server đã có: /health, /command (Gemini + ảnh), /tts."""

from __future__ import annotations

import base64
import json
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ServerClientError(RuntimeError):
    pass


class ServerClient:
    def __init__(self, server_url: str, token: str, timeout: int, retries: int) -> None:
        self.server_url = server_url
        self.token = token
        self.timeout = timeout
        self.retries = retries

    def health(self) -> None:
        """Kiểm tra server sống (không cần token)."""
        request = Request(self.server_url + "/health", method="GET")
        try:
            with urlopen(request, timeout=min(self.timeout, 10)) as response:
                if response.status != 200:
                    raise ServerClientError(f"Mac /health trả HTTP {response.status}.")
        except HTTPError as error:
            raise ServerClientError(f"Mac /health trả HTTP {error.code}.") from error
        except (URLError, TimeoutError, socket.timeout) as error:
            raise ServerClientError(f"Không thể kết nối Mac: {error}") from error

    def classify(self, image: bytes, prompt: str) -> str:
        """Gửi ảnh JPEG + prompt tới /command (mode=observe); trả text Gemini.

        MP3 mà server tạo kèm theo bị bỏ: Pi tự chọn câu thông báo từ mã phân loại.
        """
        payload = {
            "text": prompt,
            "mode": "observe",
            "image": base64.b64encode(image).decode("ascii"),
            "imageContentType": "image/jpeg",
        }
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        body, content_type, encoded_text = self._post("/command", data, 10 * 1024 * 1024)
        if not content_type.startswith("audio/mpeg") or not body:
            raise ServerClientError("Mac trả phản hồi /command không hợp lệ.")
        try:
            return (
                base64.b64decode(encoded_text, validate=True).decode("utf-8")
                if encoded_text
                else ""
            )
        except (ValueError, UnicodeDecodeError) as error:
            raise ServerClientError("Mac trả header text Gemini không hợp lệ.") from error

    def tts(self, text: str) -> bytes:
        data = json.dumps({"text": text}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        body, content_type, _ = self._post("/tts", data, 10 * 1024 * 1024)
        if not content_type.startswith("audio/mpeg") or not body:
            raise ServerClientError("Mac trả phản hồi /tts không hợp lệ.")
        return body

    def _post(self, path: str, data: bytes, response_limit: int) -> tuple[bytes, str, str | None]:
        request = Request(
            self.server_url + path,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read(response_limit + 1)
                    if len(body) > response_limit:
                        raise ServerClientError("Phản hồi từ Mac vượt quá giới hạn cho phép.")
                    return (
                        body,
                        response.headers.get_content_type().lower(),
                        response.headers.get("X-ThienNhan-Text-Base64"),
                    )
            except HTTPError as error:
                raise _server_error(error) from error
            except (URLError, TimeoutError, socket.timeout) as error:
                if attempt >= self.retries:
                    raise ServerClientError(f"Không thể kết nối Mac: {error}") from error
                time.sleep(min(2**attempt, 3))
        raise AssertionError("Vòng retry kết thúc ngoài dự kiến.")


def _server_error(error: HTTPError) -> ServerClientError:
    raw = error.read(64 * 1024)
    code, message = "server_error", str(error.reason or "Mac xử lý thất bại.")
    try:
        detail = json.loads(raw).get("error", {})
        if isinstance(detail, dict):
            code = str(detail.get("code") or code)
            message = str(detail.get("message") or message)
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        pass
    return ServerClientError(f"HTTP {error.code} {code}: {message}")
