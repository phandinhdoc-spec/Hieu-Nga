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

    def test_defaults(self) -> None:
        config = self._load("MAC_SERVER_URL=http://mac:8765/\nSERVER_TOKEN=t\n")
        self.assertEqual(config.server_url, "http://mac:8765")
        self.assertEqual(config.touch_gpio, 25)
        self.assertTrue(config.touch_active_high)
        self.assertEqual(config.lens_position, "")

    def test_requires_server(self) -> None:
        with self.assertRaises(ConfigError):
            self._load("SERVER_TOKEN=t\n")

    def test_rejects_bad_gpio(self) -> None:
        with self.assertRaises(ConfigError):
            self._load("MAC_SERVER_URL=http://m\nSERVER_TOKEN=t\nTOUCH_GPIO=99\n")


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


if __name__ == "__main__":
    unittest.main()
