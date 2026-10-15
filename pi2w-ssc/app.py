"""AI GREEN EYE (SSC 2026) – CHƯƠNG TRÌNH CHÍNH chạy trên Raspberry Pi Zero 2 W.

┌──────────────────────────────────────────────────────────────────────────┐
│ THIẾT BỊ LÀM GÌ?                                                          │
│   Giúp người khiếm thị biết một món đồ là loại rác nào.                  │
│                                                                          │
│   Cứ lặp đi lặp lại:                                                      │
│     1. Camera chụp ảnh.                                                  │
│     2. Gửi ảnh cho máy tính (server) -> nhờ Gemini xem ảnh.              │
│     3. Nhận kết quả, đọc to qua loa:                                     │
│          "Rác vô cơ." / "Rác hữu cơ." / "Rác khác."                      │
│          Nếu là vật sắc nhọn thì cảnh báo trước:                         │
│          "Cảnh báo, đây là vật sắc nhọn."                                │
│                                                                          │
│   NÚT BẤM (GPIO25): ấn một lần = TẮT, ấn lần nữa = MỞ lại.               │
└──────────────────────────────────────────────────────────────────────────┘

CÁC FILE TRONG DỰ ÁN (mỗi file một việc):
    app.py            (file này) điều khiển mọi thứ, quyết định làm gì trước, làm gì sau
    config.py         các con số cấu hình (đã chọn sẵn)
    classifier.py     câu hỏi gửi Gemini + cách "đọc hiểu" câu trả lời
    hardware.py       camera, loa, nút bấm, Wi-Fi
    server_client.py  nói chuyện với server trên máy tính
    sounds/           các câu thông báo hệ thống có sẵn (file .mp3)
    cache/            các câu kết quả (tạo tự động lần đầu, rồi dùng lại mãi)

CÁCH CHẠY (thường không cần tự chạy, vì service đã tự khởi động cùng Pi):
    python3 app.py            chạy liên tục (chế độ bình thường)
    python3 app.py --once     chụp, phân loại, đọc ĐÚNG MỘT LẦN rồi thoát (để thử)
    python3 app.py --image X  phân loại một ảnh JPEG có sẵn (không cần camera/nút bấm)
"""

from __future__ import annotations

import argparse   # đọc các tuỳ chọn dòng lệnh như --once
import hashlib    # băm tên câu thành tên file ngắn gọn cho cache
import sys        # in lỗi, thoát chương trình
import threading  # cho phép nút bấm hoạt động song song với việc phân tích
import time       # chờ, đo thời gian
from concurrent.futures import ThreadPoolExecutor  # chạy việc "đang phân tích" song song
from pathlib import Path

from classifier import BAT, PROMPT, SPOKEN, TAT, ReplyError, Verdict, parse_reply
from config import Config, ConfigError
from hardware import DeviceError, TouchSensor, capture_jpeg, connected_wifi, play_mp3
from server_client import ServerClient, ServerClientError, ServerUnreachableError

# ---------------------------------------------------------------------------
# CÁC HẰNG SỐ
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent     # thư mục chứa file app.py này
_SYSTEM_SOUNDS = _HERE / "sounds"           # nơi để các thông báo hệ thống (.mp3 làm sẵn)
_SPEECH_CACHE = _HERE / "cache"             # nơi lưu các câu kết quả lấy từ server
_STARTUP_RETRY_SECONDS = 5                  # lúc khởi động, thứ gì chưa sẵn sàng thì 5 giây thử lại
_ERROR_PAUSE_SECONDS = 3.0                  # gặp lỗi khi đang chạy: nghỉ 3 giây rồi thử lại
_TOUCH_DEBOUNCE_SECONDS = 0.5               # hai lần ấn cách nhau dưới 0,5 giây chỉ tính là một
_TOUCH_SETTLE_SECONDS = 1.0                 # bỏ qua nút trong lúc loa đọc "bật/tắt" và 1 giây sau đó


# ===========================================================================
# BỘ NHỚ ĐỆM GIỌNG ĐỌC (SpeechCache)
# ===========================================================================
class SpeechCache:
    """Các câu kết quả ("Rác vô cơ." ...) chỉ phải nhờ server đọc MỘT LẦN DUY NHẤT.

    Lần đầu: gọi server (/tts) lấy file MP3, lưu vào thư mục cache/.
    Các lần sau: lấy thẳng từ cache/, nhanh và không cần mạng.
    Nhờ vậy, khi đã chạy một lần thì Pi đọc kết quả ngay lập tức.
    """

    def __init__(self, client: ServerClient, directory: Path) -> None:
        self._client = client
        self._directory = directory

    def path_for(self, text: str) -> Path:
        """Tên file cache của một câu: băm câu đó ra một dãy ký tự ngắn (tránh dấu tiếng Việt trong tên file)."""
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        return self._directory / f"{digest}.mp3"

    def get(self, text: str) -> bytes:
        """Lấy MP3 của một câu: có trong cache thì dùng, chưa có thì hỏi server rồi lưu lại."""
        path = self.path_for(text)
        try:
            return path.read_bytes()   # đã có sẵn trong cache
        except OSError:
            pass                       # chưa có -> đi hỏi server
        data = self._client.tts(text)
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)      # ghi ra file tạm trước...
            tmp.replace(path)          # ...rồi đổi tên: lỡ mất điện cũng không để lại file hỏng
        except OSError as error:
            print(f"[CACHE] Không lưu được {path.name}: {error}", file=sys.stderr, flush=True)
        return data

    def prefetch(self) -> None:
        """Tải trước TẤT CẢ các câu có thể đọc (lúc khởi động) để về sau đọc không bị chờ."""
        for text in SPOKEN.values():
            self.get(text)


# ===========================================================================
# HÀM main: ĐIỂM BẮT ĐẦU CỦA CHƯƠNG TRÌNH
# ===========================================================================
def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config = Config.load()
    except ConfigError as error:
        print(f"[KHỞI ĐỘNG] Lỗi cấu hình: {error}", file=sys.stderr, flush=True)
        return 1

    # Người liên lạc với server. server_url "" nghĩa là sẽ tự tìm server trong mạng.
    client = ServerClient(
        config.server_url, config.server_token, config.command_timeout_seconds, config.http_retries
    )
    speech = SpeechCache(client, _SPEECH_CACHE)

    try:
        if args.image:
            return _classify_file(Path(args.image), config, client, speech)
        _startup(config, client, speech)   # kiểm tra Wi-Fi, camera, server
        if args.once:
            _classify_once(config, client, speech, capture_jpeg(config.lens_position))
            return 0
        return _run_loop(config, client, speech)   # chạy liên tục
    except KeyboardInterrupt:  # người dùng bấm Ctrl+C
        print("\nĐã dừng.", flush=True)
        return 130


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Đọc tuỳ chọn dòng lệnh: --once hoặc --image (chỉ chọn được một)."""
    parser = argparse.ArgumentParser(description="AI Green Eye - Pi Zero 2 W")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true", help="chụp và phân loại một lần rồi thoát")
    group.add_argument("--image", metavar="JPEG", help="phân loại một ảnh JPEG có sẵn")
    return parser.parse_args(argv)


# ===========================================================================
# NÚT BẤM BẬT/TẮT (Toggle)
# ===========================================================================
class Toggle:
    """Công tắc "đang chạy / đang tắt". Mỗi lần ấn nút là đảo trạng thái một lần.

    Có hai lớp bảo vệ để một lần ấn không bị tính thành nhiều lần:
      - Chống dội: hai lần ấn cách nhau dưới 0,5 giây chỉ tính một.
      - ignore(): tạm thời bỏ qua nút (dùng trong lúc loa đang đọc "bật/tắt", vì tiếng
        loa to đôi khi gây nhiễu làm nút tưởng có người ấn).
    """

    def __init__(self, active: bool) -> None:
        self.active = active                  # True = đang chạy liên tục, False = đang tắt
        self.changed = threading.Event()      # "lá cờ" được phất lên mỗi khi trạng thái đổi
        self._lock = threading.Lock()         # khóa để hai luồng không đụng nhau
        self._last_flip = 0.0                 # lần đảo gần nhất lúc mấy giờ
        self._ignore_until = 0.0              # bỏ qua nút cho tới thời điểm này

    def ignore(self, seconds: float | None = None) -> None:
        """Bỏ qua nút trong `seconds` giây. Không truyền số = bỏ qua mãi cho tới khi gọi lại có số."""
        with self._lock:
            self._ignore_until = float("inf") if seconds is None else time.monotonic() + seconds

    def flip(self) -> None:
        """Đảo trạng thái (đang chạy <-> đang tắt). Hàm này được gọi mỗi khi có người ấn nút."""
        with self._lock:
            now = time.monotonic()
            if now < self._ignore_until or now - self._last_flip < _TOUCH_DEBOUNCE_SECONDS:
                return                        # đang bị bỏ qua hoặc ấn quá nhanh -> không tính
            self._last_flip = now
            self.active = not self.active
        self.changed.set()                    # phất cờ để vòng lặp chính biết


# ===========================================================================
# VÒNG LẶP CHÍNH (chế độ liên tục)
# ===========================================================================
def _run_loop(config: Config, client: ServerClient, speech: SpeechCache) -> int:
    """Chụp -> phân tích -> đọc kết quả, lặp mãi cho tới khi tắt chương trình.

    Mỗi vòng lặp làm đúng một trong ba việc:
      (a) Trạng thái vừa đổi do ấn nút  -> đọc "Đã bật/tắt phân tích".
      (b) Đang TẮT                       -> đứng chờ tới khi có người ấn nút.
      (c) Đang MỞ                        -> chụp, phân tích, đọc kết quả.
    """
    sensor = TouchSensor(config.touch_gpio, config.touch_active_high)
    toggle = Toggle(config.start_active)
    sensor.on_touch(toggle.flip)              # mỗi lần ấn nút thì gọi toggle.flip()
    print(
        f"[LIÊN TỤC] Ấn nút (GPIO{config.touch_gpio}) để tắt/mở. "
        f"Đang {'MỞ' if toggle.active else 'TẮT'}.",
        flush=True,
    )
    shown = toggle.active    # trạng thái mà ta đã thông báo cho người dùng nghe
    error_streak = 0         # đếm số lỗi liên tiếp (để chỉ kêu báo lỗi lần đầu, đỡ ồn)
    try:
        while True:
            # (a) Người dùng vừa ấn nút -> thông báo trạng thái mới.
            if toggle.active != shown:
                shown = toggle.active
                print(f"[LIÊN TỤC] {'MỞ' if shown else 'TẮT'}.", flush=True)
                toggle.ignore()  # trong lúc loa đọc, bỏ qua nút (tránh nhiễu từ loa)
                _speak(speech, config, TAT if not shown else BAT)
                toggle.ignore(_TOUCH_SETTLE_SECONDS)  # đọc xong, chờ thêm 1 giây cho yên
                toggle.changed.clear()
                continue

            # (b) Đang tắt -> ngủ cho tới khi nút được ấn (không tốn điện, không gọi Gemini).
            if not toggle.active:
                toggle.changed.wait()
                toggle.changed.clear()
                continue

            # (c) Đang mở -> làm một vòng chụp/phân tích/đọc.
            toggle.changed.clear()
            try:
                image = capture_jpeg(config.lens_position)        # 1. chụp ảnh
                verdict = _classify_image(client, image)          # 2. nhờ Gemini phân loại
                if toggle.active:  # nếu trong lúc chờ Gemini mà bị ấn TẮT thì bỏ kết quả này
                    for code in verdict.phrases():                # 3. đọc từng câu: cảnh báo trước, nhóm sau
                        if not toggle.active:                     # bị tắt giữa chừng -> bỏ phần còn lại
                            break
                        # cancel=...: ấn tắt là loa im NGAY, không đọc nốt câu đang dở.
                        _speak(speech, config, code, cancel=lambda: not toggle.active)
                error_streak = 0
                time.sleep(config.loop_interval_seconds)          # nghỉ chút rồi chụp vòng sau
            except DeviceError as error:
                # Lỗi phần cứng: camera, loa...
                error_streak = _loop_error(config, f"Phần cứng: {error}", error_streak)
            except ServerUnreachableError as error:
                # Không nối được server -> dùng câu thông báo riêng, dễ hiểu hơn.
                error_streak = _loop_error(config, f"Mất kết nối server: {error}", error_streak, "server-error.mp3")
            except (ServerClientError, ReplyError) as error:
                # Server trả lỗi, hoặc Gemini trả lời không đọc hiểu được.
                error_streak = _loop_error(config, f"Phân loại: {error}", error_streak)
            except Exception as error:  # noqa: BLE001 - lỗi bất ngờ: vẫn giữ máy sống để thử lại
                error_streak = _loop_error(config, f"Lỗi bất ngờ: {error}", error_streak)
    finally:
        sensor.close()   # dù thoát vì lý do gì cũng trả chân GPIO lại


def _loop_error(config: Config, message: str, streak: int, sound: str = "operation-error.mp3") -> int:
    """Ghi lỗi ra nhật ký, và chỉ KÊU báo lỗi ở lỗi đầu tiên của một chuỗi lỗi liên tiếp.

    (Nếu lỗi kéo dài mà cứ 3 giây kêu một lần thì rất ồn và khó chịu.)
    Trả về số lỗi liên tiếp mới.
    """
    print(f"[LỖI] {message}", file=sys.stderr, flush=True)
    if streak == 0:
        _announce(sound, config)
    time.sleep(_ERROR_PAUSE_SECONDS)
    return streak + 1


def _speak(speech: SpeechCache, config: Config, code: str, cancel=None) -> None:
    """Đọc to câu ứng với một mã (ví dụ "VO_CO" -> "Rác vô cơ."). Lỗi chỉ ghi nhật ký, không dừng máy."""
    try:
        play_mp3(speech.get(SPOKEN[code]), config.playback_device, cancel=cancel)
    except (DeviceError, ServerClientError) as error:
        print(f"[ÂM THANH] Không đọc được {code}: {error}", file=sys.stderr, flush=True)


def _classify_image(client: ServerClient, image: bytes) -> Verdict:
    """Gửi ảnh cho server, đọc hiểu câu trả lời của Gemini thành một Verdict (phán quyết)."""
    reply = client.classify(image, PROMPT)   # ví dụ reply = "SAC_NHON VO_CO"
    print(f"[GEMINI] {reply!r}", flush=True)
    verdict = parse_reply(reply)             # biến chữ thành (nhóm rác, có sắc nhọn không)
    print(f"[KẾT QUẢ] nhóm={verdict.category}; sắc nhọn={'có' if verdict.sharp else 'không'}", flush=True)
    return verdict


# ===========================================================================
# CHẾ ĐỘ THỬ: MỘT LẦN (--once, --image)
# ===========================================================================
def _classify_once(config: Config, client: ServerClient, speech: SpeechCache, image: bytes) -> Verdict:
    """Phân loại ĐÚNG MỘT ảnh và đọc kết quả. Có phát âm thanh "đang phân tích" trong lúc chờ."""
    print(f"[CAMERA] Ảnh {len(image)} byte. Gửi Gemini...", flush=True)
    # Gửi ảnh đi ở luồng riêng, đồng thời phát tiếng "đang phân tích" để người dùng
    # biết đã chụp xong và máy đang làm việc (chứ không bị treo).
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.classify, image, PROMPT)
        _announce("analyzing.mp3", config)
        reply = pending.result()   # chờ Gemini trả lời xong
    print(f"[GEMINI] {reply!r}", flush=True)

    verdict = parse_reply(reply)
    for code in verdict.phrases():
        play_mp3(speech.get(SPOKEN[code]), config.playback_device)
    print(f"[KẾT QUẢ] nhóm={verdict.category}; sắc nhọn={'có' if verdict.sharp else 'không'}", flush=True)
    return verdict


def _classify_file(path: Path, config: Config, client: ServerClient, speech: SpeechCache) -> int:
    """Phân loại một file ảnh JPEG có sẵn (dùng với --image). Trả 0 nếu thành công, 1 nếu lỗi."""
    try:
        image = path.read_bytes()
    except OSError as error:
        print(f"Không đọc được ảnh: {error}", file=sys.stderr, flush=True)
        return 1
    if not image.startswith(b"\xff\xd8"):  # JPEG thật luôn bắt đầu bằng 2 byte FF D8
        print("File không phải JPEG.", file=sys.stderr, flush=True)
        return 1
    try:
        _classify_once(config, client, speech, image)
    except (DeviceError, ServerClientError, ReplyError) as error:
        _report_error(config, str(error))
        return 1
    return 0


# ===========================================================================
# KHỞI ĐỘNG: KIỂM TRA TỪNG BƯỚC
# ===========================================================================
def _startup(config: Config, client: ServerClient, speech: SpeechCache) -> None:
    """Kiểm tra lần lượt: Wi-Fi -> camera -> server. Bước nào chưa được thì báo bằng loa và thử lại.

    Mỗi bước có câu báo lỗi RIÊNG để người nghe biết đường sửa:
        Wi-Fi  hỏng -> "Chưa kết nối được Wi-Fi..."
        camera hỏng -> "Chưa kết nối được camera..."
        server hỏng -> "Chưa kết nối được máy chủ..."
    """
    print("[KHỞI ĐỘNG] Kiểm tra hệ thống.", flush=True)

    _until_ok("Wi-Fi", lambda: connected_wifi(), config, "wifi-connected.mp3", "wifi-error.mp3")
    _until_ok("Camera", lambda: len(capture_jpeg(config.lens_position)), config, "camera-ready.mp3", "camera-error.mp3")

    def server_ready() -> str:
        client.health()    # hỏi server có sống không (tự tìm server nếu chưa biết địa chỉ)
        speech.prefetch()  # lần đầu: tải các câu kết quả từ server; những lần sau đã có cache
        return client.server_url or "server"

    _until_ok("Server", server_ready, config, None, "server-error.mp3")

    print("[KHỞI ĐỘNG] Hệ thống sẵn sàng.", flush=True)
    _announce("system-ready.mp3", config)


def _until_ok(name: str, check, config: Config, sound: str | None, error_sound: str) -> None:
    """Gọi hàm `check` lặp đi lặp lại cho tới khi thành công.

    name       : tên bước (để in ra nhật ký), ví dụ "Wi-Fi".
    check      : hàm kiểm tra; lỗi thì ném DeviceError hoặc ServerClientError.
    sound      : âm thanh phát khi bước này thành công (None = không phát).
    error_sound: âm thanh phát khi bước này thất bại.

    Để tránh ồn, mỗi loại lỗi chỉ được báo MỘT lần (không lặp lại mỗi 5 giây).
    """
    announced_error: str | None = None
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
            # "Không nối được server" khác "nối được nhưng server báo lỗi" (sai mật khẩu, Gemini lỗi...).
            # Trường hợp sau dùng câu báo lỗi chung.
            sound_for_error = (
                error_sound
                if not isinstance(error, ServerClientError) or isinstance(error, ServerUnreachableError)
                else "operation-error.mp3"
            )
            if announced_error != sound_for_error:  # chỉ báo khi loại lỗi thay đổi
                _announce(sound_for_error, config)
                announced_error = sound_for_error
            time.sleep(_STARTUP_RETRY_SECONDS)


def _report_error(config: Config, message: str) -> None:
    """Ghi lỗi ra nhật ký + kêu báo lỗi + nghỉ một chút."""
    print(f"[LỖI] {message}", file=sys.stderr, flush=True)
    _announce("operation-error.mp3", config)
    time.sleep(_ERROR_PAUSE_SECONDS)


def _announce(filename: str, config: Config) -> None:
    """Phát một thông báo hệ thống làm sẵn trong thư mục sounds/. Lỗi phát chỉ ghi nhật ký."""
    try:
        play_mp3((_SYSTEM_SOUNDS / filename).read_bytes(), config.playback_device, timeout=20)
    except (OSError, DeviceError) as error:
        print(f"[ÂM THANH] Không phát được {filename}: {error}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
