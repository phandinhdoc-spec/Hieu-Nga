#!/usr/bin/env bash
# Cài AI Green Eye (SSC 2026) lên Raspberry Pi Zero 2 W (DietPi / Raspberry Pi OS Trixie).
# Chạy trong thư mục này:  sudo bash install.sh
# Giả định MAX98357A đã được cấu hình I2S (dtoverlay=max98357a) từ bản cài Thiên Nhãn cũ;
# script chỉ kiểm tra và nhắc, không sửa /boot.
set -Eeuo pipefail

INSTALL_DIR="/opt/ai-green-eye"
SERVICE="ai-green-eye.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="aigreeneye"

[[ ${EUID} -eq 0 ]] || { echo "Hãy chạy bằng sudo." >&2; exit 1; }
[[ -f "${SCRIPT_DIR}/.env" ]] || { echo "Thiếu ${SCRIPT_DIR}/.env (sao chép từ .env.example rồi điền)." >&2; exit 1; }

apt update
apt install -y --no-install-recommends \
    rpicam-apps alsa-utils mpg123 python3 python3-gpiozero python3-lgpio

BOOT_CONFIG="/boot/firmware/config.txt"
if [[ -f "${BOOT_CONFIG}" ]] && ! grep -Eq '^[[:space:]]*dtoverlay=max98357a' "${BOOT_CONFIG}"; then
    echo "CẢNH BÁO: ${BOOT_CONFIG} chưa có dtoverlay=max98357a; loa MAX98357A sẽ không phát tiếng." >&2
fi

id -u "${USER_NAME}" >/dev/null 2>&1 \
    || useradd --system --user-group --home-dir "${INSTALL_DIR}" --shell /usr/sbin/nologin "${USER_NAME}"
for group in audio video gpio; do
    getent group "${group}" >/dev/null && usermod -aG "${group}" "${USER_NAME}"
done

install -d -o "${USER_NAME}" -g "${USER_NAME}" -m 0750 "${INSTALL_DIR}" "${INSTALL_DIR}/cache"
install -d -o "${USER_NAME}" -g "${USER_NAME}" -m 0755 "${INSTALL_DIR}/sounds"
for file in app.py classifier.py config.py hardware.py server_client.py; do
    install -o "${USER_NAME}" -g "${USER_NAME}" -m 0644 "${SCRIPT_DIR}/${file}" "${INSTALL_DIR}/${file}"
done
install -o "${USER_NAME}" -g "${USER_NAME}" -m 0644 "${SCRIPT_DIR}"/sounds/*.mp3 "${INSTALL_DIR}/sounds/"
install -o "${USER_NAME}" -g "${USER_NAME}" -m 0600 "${SCRIPT_DIR}/.env" "${INSTALL_DIR}/.env"
install -o root -g root -m 0644 "${SCRIPT_DIR}/${SERVICE}" "/etc/systemd/system/${SERVICE}"

# Dừng bản Thiên Nhãn cũ (nếu có) để không tranh mic/loa/camera.
systemctl disable --now thiennhan.service 2>/dev/null || true

systemctl daemon-reload
systemctl enable --now "${SERVICE}"
echo "Xong. Xem log: sudo journalctl -u ${SERVICE} -f"
