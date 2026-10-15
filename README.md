# AI Green Eye – Pi Zero 2 W (SSC 2026)

Chạm cảm biến → camera chụp ảnh → **Mac server hiện có** gọi **Gemini** phân loại → loa MAX98357A đọc kết quả.
Không dùng AI cục bộ, không mic, không Groq, không Bluetooth, không cảm biến GY25/GY63.

## Thông báo (chỉ hai loại)

1. **Hệ thống:** Wi-Fi đã kết nối, camera sẵn sàng, hệ thống sẵn sàng (`system-ready`), đang phân tích, lỗi thao tác, và "Chưa thấy vật. Hãy đưa vật vào trước camera."
2. **Kết quả:** "Rác vô cơ." / "Rác hữu cơ." / "Rác khác." Nếu là vật sắc nhọn (xác định theo hình dạng: lưỡi/cạnh bén, đầu nhọn, mảnh vỡ; không theo chất liệu) thì đọc trước: "Cảnh báo, đây là vật sắc nhọn." rồi đến tên nhóm.

## Cách hoạt động

- `app.py` gửi ảnh JPEG + prompt tới `POST /command` (`mode=observe`) của server đã có; **không sửa server**.
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

```sh
cp .env.example .env && nano .env     # điền MAC_SERVER_URL, SERVER_TOKEN
sudo bash install.sh                   # cài gói, tạo service ai-green-eye, tắt thiennhan.service cũ
sudo journalctl -u ai-green-eye -f
```

Thử nhanh không cần cảm biến: `python3 app.py --once` (chụp + phân loại 1 lần), hoặc `python3 app.py --image anh.jpg`.

## Kiểm thử

```sh
python3 -m unittest discover -s tests -v
```

Các test chạy trên máy bình thường (giả lập server/loa). **Chưa chạy thử trên Pi thật**: cảm biến chạm, camera, loa và kết quả Gemini thực tế cần kiểm tra khi có thiết bị.
