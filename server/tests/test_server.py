"""KIỂM THỬ TỰ ĐỘNG cho server.

Chạy:  python3 -m unittest discover -s tests -v
Gemini và giọng đọc được thay bằng hàm giả, nên không cần Internet hay chìa khóa thật.
"""
import base64, json, sys, threading, unittest
from http.client import HTTPConnection
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as s


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = s.Settings({"SERVER_TOKEN": "tok", "GEMINI_API_KEY": "k", "HOST": "127.0.0.1", "PORT": "0"})
        cls.calls = []
        def fake_gemini(settings, text, image, mime):
            cls.calls.append((text, image, mime))
            return "SAC_NHON VO_CO"
        s.Handler.gemini = staticmethod(fake_gemini)
        s.Handler.tts = staticmethod(lambda settings, text: b"MP3:" + text.encode())
        cls.httpd = s.make_server(cls.settings)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close()

    def req(self, method, path, body=None, token="tok"):
        c = HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Content-Type": "application/json"}
        if token: h["Authorization"] = f"Bearer {token}"
        c.request(method, path, json.dumps(body).encode() if body is not None else None, h)
        r = c.getresponse(); return r, r.read()

    def test_health_no_token(self):
        r, b = self.req("GET", "/health", token=None)
        self.assertEqual(r.status, 200)

    def test_auth(self):
        r, b = self.req("POST", "/tts", {"text": "x"}, token="bad")
        self.assertEqual(r.status, 401)
        self.assertEqual(json.loads(b)["error"]["code"], "unauthorized")

    def test_observe(self):
        img = base64.b64encode(b"\xff\xd8jpeg").decode()
        r, b = self.req("POST", "/command", {"text": "p", "mode": "observe", "image": img, "imageContentType": "image/jpeg"})
        self.assertEqual(r.status, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("audio/mpeg"))
        self.assertEqual(base64.b64decode(r.getheader("X-ThienNhan-Text-Base64")).decode(), "SAC_NHON VO_CO")
        self.assertEqual(b, s.SILENT_MP3)
        self.assertEqual(self.calls[-1][1], b"\xff\xd8jpeg")

    def test_observe_needs_image(self):
        r, b = self.req("POST", "/command", {"text": "p", "mode": "observe"})
        self.assertEqual(r.status, 400)

    def test_bad_image(self):
        r, b = self.req("POST", "/command", {"text": "p", "mode": "observe", "image": "!!!"})
        self.assertEqual(r.status, 400)

    def test_tts_and_limits(self):
        r, b = self.req("POST", "/tts", {"text": "Rác vô cơ."})
        self.assertEqual((r.status, b), (200, "MP3:Rác vô cơ.".encode()))
        r, b = self.req("POST", "/tts", {"text": "a" * 2001})
        self.assertEqual(r.status, 400)


if __name__ == "__main__":
    unittest.main()
