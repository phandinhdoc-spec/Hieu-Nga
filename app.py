"""AI Green Eye (SSC 2026) - Raspberry Pi Zero 2 W.

Chạm cảm biến -> chụp ảnh -> Mac server (Gemini) phân loại -> đọc thông báo qua loa.
Chỉ có hai loại thông báo:
  1. Thông báo hệ thống (khởi động, đang phân tích, lỗi, chưa thấy vật).
  2. Kết quả: rác vô cơ / rác hữu cơ / rác khác; kèm cảnh báo nếu là vật sắc nhọn.

Chạy:  python3 app.py            vòng lặp chính (chờ chạm)
       python3 app.py --once     chụp, phân loại, đọc một lần rồi thoát
       python3 app.py --image X  phân loại ảnh JPEG có sẵn (không cần camera/cảm biến)
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from classifier import PROMPT, SPOKEN, ReplyError, Verdict, parse_reply
from config import Config, ConfigError
from hardware import DeviceError, TouchSensor, capture_jpeg, connected_wifi, play_mp3
from server_client import ServerClient, ServerClientError

_HERE = Path(__file__).resolve().parent
_SYSTEM_SOUNDS = _HERE / "sounds"
_SPEECH_CACHE = _HERE / "cache"
_STARTUP_RETRY_SECONDS = 5
_RELEASE_TIMEOUT_SECONDS = 3.0
_ERROR_PAUSE_SECONDS = 1.0


class SpeechCache:
    """Các câu thông báo kết quả: lấy từ /tts một lần, lưu trên thẻ nhớ, dùng lại mãi."""

    def __init__(self, client: ServerClient, directory: Path) -> None:
        self._client = client
        self._directory = directory

    def path_for(self, text: str) -> Path:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        return self._directory / f"{digest}.mp3"

    def get(self, text: str) -> bytes:
        path = self.path_for(text)
        try:
            return path.read_bytes()
        except OSError:
            pass
        data = self._client.tts(text)
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        except OSError as error:
            print(f"[CACHE] Không lưu được {path.name}: {error}", file=sys.stderr, flush=True)
        return data

    def prefetch(self) -> None:
        for text in SPOKEN.values():
            self.get(text)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config = Config.load()
    except ConfigError as error:
        print(f"[KHỞI ĐỘNG] Lỗi cấu hình: {error}", file=sys.stderr, flush=True)
        return 1

    client = ServerClient(
        config.server_url, config.server_token, config.command_timeout_seconds, config.http_retries
    )
    speech = SpeechCache(client, _SPEECH_CACHE)

    try:
        if args.image:
            return _classify_file(Path(args.image), config, client, speech)
        _startup(config, client, speech)
        if args.once:
            _classify_once(config, client, speech, capture_jpeg(config.lens_position))
            return 0
        return _run_loop(config, client, speech)
    except KeyboardInterrupt:
        print("\nĐã dừng.", flush=True)
        return 130


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Green Eye - Pi Zero 2 W")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="chụp và phân loại một lần rồi thoát")
    group.add_argument("--image", metavar="JPEG", help="phân loại một ảnh JPEG có sẵn")
    return parser.parse_args(argv)


def _run_loop(config: Config, client: ServerClient, speech: SpeechCache) -> int:
    sensor = TouchSensor(config.touch_gpio, config.touch_active_high)
    print(f"[CHẠM] Sẵn sàng. Chạm cảm biến (GPIO{config.touch_gpio}) để phân loại.", flush=True)
    try:
        while True:
            sensor.wait_for_touch()
            try:
                image = capture_jpeg(config.lens_position)
                _classify_once(config, client, speech, image)
            except DeviceError as error:
                _report_error(config, f"Phần cứng: {error}")
            except (ServerClientError, ReplyError) as error:
                _report_error(config, f"Phân loại: {error}")
            except Exception as error:  # noqa: BLE001 - giữ thiết bị sống cho lần chạm sau
                _report_error(config, f"Lỗi bất ngờ: {error}")
            # Chờ nhả tay để một lần giữ không kích hoạt nhiều lần.
            sensor.wait_for_release(_RELEASE_TIMEOUT_SECONDS)
    finally:
        sensor.close()


def _classify_once(config: Config, client: ServerClient, speech: SpeechCache, image: bytes) -> Verdict:
    print(f"[CAMERA] Ảnh {len(image)} byte. Gửi Gemini...", flush=True)
    # Phát "đang phân tích" trong lúc chờ server để người dùng biết đã chụp xong.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.classify, image, PROMPT)
        _announce("analyzing.mp3", config)
        reply = pending.result()
    print(f"[GEMINI] {reply!r}", flush=True)

    verdict = parse_reply(reply)
    for code in verdict.phrases():
        play_mp3(speech.get(SPOKEN[code]), config.playback_device)
    print(f"[KẾT QUẢ] nhóm={verdict.category}; sắc nhọn={'có' if verdict.sharp else 'không'}", flush=True)
    return verdict


def _classify_file(path: Path, config: Config, client: ServerClient, speech: SpeechCache) -> int:
    try:
        image = path.read_bytes()
    except OSError as error:
        print(f"Không đọc được ảnh: {error}", file=sys.stderr, flush=True)
        return 1
    if not image.startswith(b"\xff\xd8"):
        print("File không phải JPEG.", file=sys.stderr, flush=True)
        return 1
    try:
        _classify_once(config, client, speech, image)
    except (DeviceError, ServerClientError, ReplyError) as error:
        _report_error(config, str(error))
        return 1
    return 0


def _startup(config: Config, client: ServerClient, speech: SpeechCache) -> None:
    print("[KHỞI ĐỘNG] Kiểm tra hệ thống.", flush=True)

    _until_ok("Wi-Fi", lambda: connected_wifi(), config, "wifi-connected.mp3")
    _until_ok("Camera", lambda: len(capture_jpeg(config.lens_position)), config, "camera-ready.mp3")

    def server_ready() -> str:
        client.health()
        speech.prefetch()  # lần đầu: tải các câu kết quả từ /tts; những lần sau đã có cache
        return "Mac server"

    _until_ok("Server", server_ready, config, None)

    print("[KHỞI ĐỘNG] Hệ thống sẵn sàng.", flush=True)
    _announce("system-ready.mp3", config)


def _until_ok(name: str, check, config: Config, sound: str | None) -> None:
    announced_error = False
    while True:
        try:
            detail = check()
            print(f"[KHỞI ĐỘNG] {name} OK ({detail}).", flush=True)
            if sound:
                _announce(sound, config)
            return
        except (DeviceError, ServerClientError) as error:
            print(
                f"[KHỞI ĐỘNG] {name} chưa sẵn sàng: {error}. Thử lại sau {_STARTUP_RETRY_SECONDS} giây.",
                file=sys.stderr,
                flush=True,
            )
            if not announced_error:  # chỉ báo lỗi một lần, tránh lặp lại mỗi 5 giây
                _announce("operation-error.mp3", config)
                announced_error = True
            time.sleep(_STARTUP_RETRY_SECONDS)


def _report_error(config: Config, message: str) -> None:
    print(f"[LỖI] {message}", file=sys.stderr, flush=True)
    _announce("operation-error.mp3", config)
    time.sleep(_ERROR_PAUSE_SECONDS)


def _announce(filename: str, config: Config) -> None:
    """Phát một thông báo hệ thống có sẵn; lỗi phát chỉ ghi log, không dừng chương trình."""
    try:
        play_mp3((_SYSTEM_SOUNDS / filename).read_bytes(), config.playback_device, timeout=20)
    except (OSError, DeviceError) as error:
        print(f"[ÂM THANH] Không phát được {filename}: {error}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
