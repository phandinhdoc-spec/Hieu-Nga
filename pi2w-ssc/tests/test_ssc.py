"""KIỂM THỬ TỰ ĐỘNG cho chương trình trên Pi.

Chạy:  python3 -m unittest discover -s tests -v
Các test dùng loa/camera/server GIẢ nên chạy được trên máy tính thường.
Mỗi lớp test kiểm một phần: đọc hiểu câu Gemini, prompt, cấu hình, luồng phát âm,
chế độ liên tục (nút bật/tắt), tự tìm server.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402
import classifier  # noqa: E402
from classifier import ReplyError, parse_reply  # noqa: E402
from config import Config, ConfigError  # noqa: E402


class ParseReplyTests(unittest.TestCase):
    def test_plain_codes(self) -> None:
        for code in ("VO_CO", "HUU_CO", "KHAC", "KHONG_THAY"):
            verdict = parse_reply(code)
            self.assertEqual(verdict.category, code)
            self.assertFalse(verdict.sharp)

    def test_sharp_plus_category(self) -> None:
        verdict = parse_reply("SAC_NHON VO_CO\n")
        self.assertTrue(verdict.sharp)
        self.assertEqual(verdict.category, "VO_CO")
        self.assertEqual(verdict.phrases(), ["SAC_NHON", "VO_CO"])

    def test_tolerates_markdown_and_vietnamese_words(self) -> None:
        self.assertEqual(parse_reply("`HUU_CO`").category, "HUU_CO")
        self.assertEqual(parse_reply("Rác vô cơ").category, "VO_CO")
        self.assertEqual(parse_reply("rác hữu cơ.").category, "HUU_CO")
        self.assertEqual(parse_reply("Rác khác").category, "KHAC")
        verdict = parse_reply("Vật sắc nhọn, rác vô cơ")
        self.assertTrue(verdict.sharp)
        self.assertEqual(verdict.category, "VO_CO")

    def test_khac_is_whole_word(self) -> None:
        with self.assertRaises(ReplyError):
            parse_reply("KHACH")

    def test_rejects_ambiguous_or_empty(self) -> None:
        for text in ("", "xin chào", "VO_CO HUU_CO", "KHAC VO_CO"):
            with self.assertRaises(ReplyError, msg=text):
                parse_reply(text)

    def test_sharp_overrides_not_seen(self) -> None:
        verdict = parse_reply("SAC_NHON KHONG_THAY")
        self.assertTrue(verdict.sharp)
        self.assertIsNone(verdict.category)

    def test_sharp_only_still_warns(self) -> None:
        self.assertEqual(parse_reply("SAC_NHON").phrases(), ["SAC_NHON"])


class PromptTests(unittest.TestCase):
    def test_fits_server_limit(self) -> None:
        self.assertLessEqual(len(classifier.PROMPT), classifier.MAX_PROMPT_CHARACTERS)

    def test_mentions_required_rules(self) -> None:
        prompt = classifier.PROMPT
        for needle in ("túi bóng", "HÌNH DẠNG", "VO_CO", "HUU_CO", "KHAC", "SAC_NHON", "KHONG_THAY"):
            self.assertIn(needle, prompt)

    def test_does_not_trigger_server_route_guidance_filter(self) -> None:
        # Server chặn lệnh chứa cả "hướng dẫn" và "đi đường".
        folded = classifier.PROMPT.lower()
        self.assertFalse("hướng dẫn" in folded and "đi đường" in folded)

    def test_every_spoken_code_has_text(self) -> None:
        for code in (*classifier.CATEGORIES, classifier.SAC_NHON):
            self.assertTrue(classifier.SPOKEN[code])


class ConfigTests(unittest.TestCase):
    def _load(self, text: str) -> Config:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(text, encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True):
                return Config.load(path)

    def test_defaults_work_without_any_env_file(self) -> None:
        """Học sinh không tạo .env: mọi giá trị phải có sẵn mặc định."""
        config = self._load("")
        self.assertEqual(config.server_url, "")          # "" = tự tìm server
        self.assertEqual(config.server_token, "d26a5af4e93257eda0aeb44d0db6da1f")
        self.assertEqual(config.touch_gpio, 25)
        self.assertFalse(config.touch_active_high)       # nút bấm nối GND
        self.assertTrue(config.start_active)
        self.assertEqual(config.lens_position, "")

    def test_explicit_server_url(self) -> None:
        config = self._load("MAC_SERVER_URL=http://mac:8765/\nSERVER_TOKEN=t\n")
        self.assertEqual(config.server_url, "http://mac:8765")
        self.assertEqual(config.server_token, "t")

    def test_rejects_bad_server_url(self) -> None:
        with self.assertRaises(ConfigError):
            self._load("MAC_SERVER_URL=mac:8765\n")

    def test_rejects_bad_gpio(self) -> None:
        with self.assertRaises(ConfigError):
            self._load("TOUCH_GPIO=99\n")


class FlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SimpleNamespace(playback_device="default")
        self.played: list[bytes] = []
        self.client = SimpleNamespace(
            classify=lambda image, prompt: self.reply,
            tts=lambda text: f"mp3:{text}".encode(),
        )
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.speech = app.SpeechCache(self.client, Path(self.directory.name))  # type: ignore[arg-type]

    def _run(self, reply: str) -> classifier.Verdict:
        self.reply = reply
        with patch.object(app, "play_mp3", lambda data, device, timeout=60: self.played.append(data)), \
             patch.object(app, "_announce", lambda name, config: self.played.append(name.encode())):
            return app._classify_once(self.config, self.client, self.speech, b"\xff\xd8jpeg")  # type: ignore[arg-type]

    def test_plain_result_plays_analyzing_then_category(self) -> None:
        self._run("HUU_CO")
        self.assertEqual(self.played, [b"analyzing.mp3", "mp3:Rác hữu cơ.".encode()])

    def test_sharp_warning_comes_before_category(self) -> None:
        self._run("SAC_NHON VO_CO")
        self.assertEqual(
            self.played,
            [b"analyzing.mp3", "mp3:Cảnh báo, đây là vật sắc nhọn.".encode(), "mp3:Rác vô cơ.".encode()],
        )

    def test_bad_reply_raises_and_plays_no_category(self) -> None:
        with self.assertRaises(ReplyError):
            self._run("không biết")
        self.assertEqual(self.played, [b"analyzing.mp3"])

    def test_speech_cache_reuses_file(self) -> None:
        calls: list[str] = []
        client = SimpleNamespace(tts=lambda text: calls.append(text) or b"x")
        cache = app.SpeechCache(client, Path(self.directory.name))  # type: ignore[arg-type]
        cache.get("Rác khác.")
        cache.get("Rác khác.")
        self.assertEqual(calls, ["Rác khác."])


class ContinuousModeTests(unittest.TestCase):
    def test_toggle_flips_and_debounces(self) -> None:
        toggle = app.Toggle(True)
        toggle.flip()
        self.assertFalse(toggle.active)
        self.assertTrue(toggle.changed.is_set())
        toggle.flip()  # nằm trong thời gian chống dội
        self.assertFalse(toggle.active)
        toggle._last_flip -= 10
        toggle.flip()
        self.assertTrue(toggle.active)

    def test_toggle_ignores_touch_while_announcing(self) -> None:
        toggle = app.Toggle(True)
        toggle.ignore()
        toggle.flip()
        self.assertTrue(toggle.active)
        toggle.ignore(0)
        toggle.flip()
        self.assertFalse(toggle.active)

    def test_startup_announces_server_unreachable_with_own_sound(self) -> None:
        from server_client import ServerClientError, ServerUnreachableError

        played: list[str] = []
        errors = iter([ServerUnreachableError("x"), ServerUnreachableError("x"), ServerClientError("HTTP 401"), None])

        def check() -> str:
            error = next(errors)
            if error:
                raise error
            return "ok"

        with patch.object(app, "_announce", lambda name, config: played.append(name)), \
             patch.object(app.time, "sleep", lambda seconds: None):
            app._until_ok("Server", check, SimpleNamespace(), None, "server-error.mp3")  # type: ignore[arg-type]
        self.assertEqual(played, ["server-error.mp3", "operation-error.mp3"])

    def test_toggle_phrases_exist(self) -> None:
        self.assertTrue(classifier.SPOKEN[classifier.BAT])
        self.assertTrue(classifier.SPOKEN[classifier.TAT])


class DiscoveryTests(unittest.TestCase):
    """Pi tự tìm server nhờ tiếng "hét" (beacon) UDP của server."""

    def test_discover_server_from_beacon(self) -> None:
        import socket
        import threading
        import time

        import server_client

        def shout() -> None:
            time.sleep(0.3)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.sendto(b"AGEYE|8080", ("127.0.0.1", server_client.BEACON_PORT))

        threading.Thread(target=shout, daemon=True).start()
        self.assertEqual(server_client.discover_server(timeout=3), "http://127.0.0.1:8080")

    def test_discover_ignores_foreign_packets(self) -> None:
        import server_client

        self.assertIsNone(server_client.discover_server(timeout=0.3))


if __name__ == "__main__":
    unittest.main()
