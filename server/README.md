# AI Green Eye – Server (Python)

Nhận ảnh từ Pi Zero 2 W → gọi Gemini phân loại → trả kết quả. Khớp `pi2w-ssc/server_client.py`.

| Đường dẫn | Việc |
|---|---|
| `GET /health` | Kiểm tra sống, không cần token |
| `POST /command` | `{text, mode:"observe", image(base64), imageContentType}` → `audio/mpeg` + header `X-ThienNhan-Text-Base64` (text Gemini) |
| `POST /tts` | `{text}` → `audio/mpeg` (giọng `vi-VN-HoaiMyNeural` qua edge-tts) |

Xác thực: `Authorization: Bearer <SERVER_TOKEN>`. Lỗi trả `{"error":{"code","message"}}`.

## Chuyển sang máy khác (cần Python 3.9+)

1. Chép thư mục `server/` sang máy mới, **không cần** `.venv/` (có thể bỏ `__pycache__/`). Phải chép cả `.env` (hoặc tạo lại từ `.env.example`, giữ nguyên `SERVER_TOKEN` để Pi không phải đổi).
2. Chạy một lệnh, lần đầu tự tạo venv và cài thư viện (cần Internet):
   - macOS / Linux: `./start.sh`
   - Windows: bấm đúp `start.bat`
3. Không phải đổi gì trên Pi: Pi tự tìm server ở máy mới (cùng mạng). Chỉ khi dùng Tailscale hoặc mạng chặn gói quảng bá mới cần đặt `MAC_SERVER_URL=http://<địa-chỉ>:8080` trong `/opt/ai-green-eye/.env` trên Pi rồi `sudo systemctl restart ai-green-eye`.
4. Cho phép cổng 8080 qua tường lửa nếu bị chặn. Máy chạy server phải cùng mạng với Pi, hoặc cả hai cùng đăng nhập Tailscale. Máy ngủ thì Pi mất kết nối.

Kiểm tra: từ Pi chạy `curl http://<địa-chỉ>:8080/health`, phải thấy `{"status": "ok", "tts": true}`.

## Cách nhanh nhất

Bấm đúp `CHAY-SERVER-WINDOWS.bat` (Windows) hoặc `CHAY-SERVER-MAC.command` (Mac) ở thư mục `ssc2`. Server tự tạo môi trường, cài thư viện, chạy, và phát tín hiệu báo hiệu UDP (cổng 8081) để Pi tự tìm ra địa chỉ. Hướng dẫn cho học sinh: `../HUONG-DAN.html`.

## Chạy tay

```sh
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env      # điền SERVER_TOKEN, GEMINI_API_KEY
python3 server.py
```

Pi tự tìm server trong cùng mạng; chỉ cần đặt `MAC_SERVER_URL` trên Pi khi dùng Tailscale hoặc mạng không cho gói quảng bá. Mật khẩu `SERVER_TOKEN` mặc định đã ghi cứng ở cả hai bên.

Thử nhanh: `curl localhost:8080/health`. Kiểm thử: `python3 -m unittest discover -s tests -v`.

Lưu ý: mode `observe` mặc định trả MP3 im lặng vì Pi bỏ MP3 đó (đặt `TTS_ON_OBSERVE=true` để tạo giọng đọc). Chưa thử với Gemini và edge-tts thật, cần API key và mạng.
