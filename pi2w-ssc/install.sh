#!/usr/bin/env bash
# ===========================================================================
# CÀI AI GREEN EYE LÊN RASPBERRY PI ZERO 2 W  (DietPi / Raspberry Pi OS)
#
# Cách dùng (chạy TRÊN Pi, trong thư mục chứa file này):
#       sudo bash install.sh
#
# Script làm lần lượt:
#   1. Cài các gói cần thiết (camera, loa, phát MP3, đọc nút bấm).
#   2. Tạo một "người dùng" riêng tên aigreeneye để chạy chương trình cho an toàn.
#   3. Chép chương trình vào /opt/ai-green-eye.
#   4. Đăng ký "service" để chương trình TỰ CHẠY mỗi khi Pi bật nguồn.
#
# KHÔNG cần file .env: mọi cấu hình đã ghi sẵn trong config.py.
# (Nếu có file .env cạnh script này thì nó vẫn được chép sang để ghi đè cấu hình.)
# ===========================================================================

# -E, -e, -u, pipefail: dừng ngay khi có lỗi, để không cài dở dang.
set -Eeuo pipefail

INSTALL_DIR="/opt/ai-green-eye"          # nơi đặt chương trình trên Pi
SERVICE="ai-green-eye.service"           # tên service
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # thư mục chứa script này
USER_NAME="aigreeneye"                   # người dùng riêng chạy chương trình

# Phải chạy bằng sudo (quyền quản trị) mới cài được.
[[ ${EUID} -eq 0 ]] || { echo "Hãy chạy bằng sudo:  sudo bash install.sh" >&2; exit 1; }

# 1. Cài gói. rpicam-apps = camera; alsa-utils + mpg123 = loa; gpiozero + lgpio = nút bấm.
apt update
apt install -y --no-install-recommends \
    rpicam-apps alsa-utils mpg123 python3 python3-gpiozero python3-lgpio

# Kiểm tra loa MAX98357A đã được bật trong cấu hình khởi động chưa (chỉ nhắc, không tự sửa).
BOOT_CONFIG="/boot/firmware/config.txt"
if [[ -f "${BOOT_CONFIG}" ]] && ! grep -Eq '^[[:space:]]*dtoverlay=max98357a' "${BOOT_CONFIG}"; then
    echo "CẢNH BÁO: ${BOOT_CONFIG} chưa có dòng dtoverlay=max98357a; loa sẽ không có tiếng." >&2
fi

# 2. Tạo người dùng riêng và cho phép dùng loa (audio), camera (video), chân GPIO (gpio).
id -u "${USER_NAME}" >/dev/null 2>&1 \
    || useradd --system --user-group --home-dir "${INSTALL_DIR}" --shell /usr/sbin/nologin "${USER_NAME}"
for group in audio video gpio; do
    getent group "${group}" >/dev/null && usermod -aG "${group}" "${USER_NAME}"
done

# 3. Chép chương trình sang /opt/ai-green-eye.
install -d -o "${USER_NAME}" -g "${USER_NAME}" -m 0750 "${INSTALL_DIR}" "${INSTALL_DIR}/cache"
install -d -o "${USER_NAME}" -g "${USER_NAME}" -m 0755 "${INSTALL_DIR}/sounds"
for file in app.py classifier.py config.py hardware.py server_client.py; do
    install -o "${USER_NAME}" -g "${USER_NAME}" -m 0644 "${SCRIPT_DIR}/${file}" "${INSTALL_DIR}/${file}"
done
install -o "${USER_NAME}" -g "${USER_NAME}" -m 0644 "${SCRIPT_DIR}"/sounds/*.mp3 "${INSTALL_DIR}/sounds/"
# .env là TÙY CHỌN: chỉ chép nếu có (không có thì dùng cấu hình mặc định trong config.py).
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    install -o "${USER_NAME}" -g "${USER_NAME}" -m 0600 "${SCRIPT_DIR}/.env" "${INSTALL_DIR}/.env"
else
    # Pi từng cài bản cũ có .env riêng -> giữ nguyên, không xóa.
    echo "(Không có .env: dùng cấu hình mặc định.)"
fi

# 4. Đăng ký service để tự chạy khi bật nguồn.
install -o root -g root -m 0644 "${SCRIPT_DIR}/${SERVICE}" "/etc/systemd/system/${SERVICE}"

# Tắt bản "Thiên Nhãn" cũ (nếu còn) để hai chương trình không giành camera/loa/nút nhau.
systemctl disable --now thiennhan.service 2>/dev/null || true

systemctl daemon-reload
systemctl enable "${SERVICE}"
systemctl restart "${SERVICE}"    # restart (không phải start) để luôn nạp bản mới nhất
echo "Xong! Xem nhật ký trực tiếp:  sudo journalctl -u ${SERVICE} -f"
