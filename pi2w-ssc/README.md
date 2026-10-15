# AI Green Eye – Pi Zero 2 W (SSC 2026)

Chạy **liên tục**: camera chụp ảnh liên tục → **server** (chạy trên máy tính) gọi **Gemini** phân loại → loa MAX98357A đọc kết quả.
Không dùng AI cục bộ, không mic, không Groq, không Bluetooth, không cảm biến GY25/GY63.

## Thông báo (chỉ hai loại)

1. **Hệ thống:** Wi-Fi đã kết nối, camera sẵn sàng, hệ thống sẵn sàng (`system-ready`), đang phân tích, lỗi thao tác, và "Chưa thấy vật. Hãy đưa vật vào trước camera."
2. **Kết quả:** "Rác vô cơ." / "Rác hữu cơ." / "Rác khác." Nếu là vật sắc nhọn (xác định theo hình dạng: lưỡi/cạnh bén, đầu nhọn, mảnh vỡ; không theo chất liệu) thì đọc trước: "Cảnh báo, đây là vật sắc nhọn." rồi đến tên nhóm.

## Chế độ liên tục

- Khởi động xong là tự chụp → phân loại → đọc kết quả, lặp lại (`START_ACTIVE=true`). Chạm cảm biến GPIO25 để **tắt** ("Đã tắt phân tích."), chạm lần nữa để **mở** ("Đã bật phân tích liên tục.").
- Mỗi vòng đều đọc kết quả (kể cả "Chưa thấy vật"), không lọc lặp. Ấn nút tắt thì dừng ngay: kết quả đang chờ bị bỏ, không đọc thêm.
- `LOOP_INTERVAL_SECONDS` là thời gian nghỉ giữa hai lần chụp. Mỗi lần phân tích tốn một lượt gọi Gemini nên cân nhắc hạn mức API.
- Lỗi liên tiếp chỉ báo âm thanh một lần, rồi thử lại sau 3 giây.
- Câu "bật/tắt" cũng lấy từ `/tts` và lưu cache như các câu kết quả.

## Cách hoạt động

- `app.py` gửi ảnh JPEG + prompt tới `POST /command` (`mode=observe`) của server đã có.
- Prompt nằm trong `classifier.py` (`PROMPT`). Gemini chỉ được trả mã: `VO_CO`, `HUU_CO`, `KHAC`, `KHONG_THAY`, có thể kèm `SAC_NHON`.
- Quy tắc túi bóng trong prompt: rác trong túi bóng → chỉ phân loại theo vật bên trong, không nhắc túi; túi nilon rỗng hoặc không thấy vật bên trong → vô cơ.
- Pi đọc mã rồi tự chọn câu thông báo. Các câu kết quả được tải một lần từ `/tts` rồi lưu ở `cache/` (lần khởi động sau không cần tải lại và đọc ngay). MP3 kèm theo `/command` bị bỏ.
- Gemini trả sai định dạng → đọc thông báo lỗi hệ thống, không đoán kết quả.

## Đấu nối

| Linh kiện | Chân |
|---|---|
| MAX98357A | 5V → pin 2, GND → pin 6, BCLK → GPIO18 (pin 12), LRC → GPIO19 (pin 35), DIN → GPIO21 (pin 40) |
| Cảm biến chạm (TTP223…) | VCC → 3V3, GND, OUT → **GPIO25 (pin 22)** — đổi bằng `TOUCH_GPIO` |
| Camera Module 3 | cổng CSI |

## Cài đặt

Mọi cấu hình đã ghi sẵn trong `config.py` (mật khẩu, nút GPIO25, chế độ liên tục). Pi **tự tìm server** trong mạng nhờ tiếng báo hiệu UDP của server, nên không cần địa chỉ. `.env` chỉ là tùy chọn để ghi đè (xem `.env.example`). Hướng dẫn đầy đủ cho học sinh: `../HUONG-DAN.html`.

```sh
sudo bash install.sh                   # cài gói, tạo service ai-green-eye; KHÔNG cần file .env
sudo journalctl -u ai-green-eye -f
```

Thử nhanh không cần cảm biến: `python3 app.py --once` (chụp + phân loại 1 lần), hoặc `python3 app.py --image anh.jpg`.

## Kiểm thử

```sh
python3 -m unittest discover -s tests -v
```

Các test chạy trên máy bình thường (giả lập server/loa). **Chưa chạy thử trên Pi thật**: cảm biến chạm, camera, loa và kết quả Gemini thực tế cần kiểm tra khi có thiết bị.
