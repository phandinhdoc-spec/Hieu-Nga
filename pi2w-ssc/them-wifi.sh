#!/usr/bin/env bash
# ===========================================================================
# THÊM MỘT MẠNG WI-FI MỚI CHO PI  (dành cho thầy cô; chạy TRÊN Pi, cần sudo)
#
# Vì sao cần? Pi chỉ nối được những Wi-Fi nó đã "nhớ". Khi mang Pi tới nơi mới
# (lớp học, phòng thi...) phải dạy nó tên và mật khẩu Wi-Fi ở đó.
#
# Cách dùng:
#       sudo bash them-wifi.sh "TênWiFi" "MậtKhẩuWiFi"
# Ví dụ:
#       sudo bash them-wifi.sh "LopHoc6A" "12345678"
# Mạng không có mật khẩu:  sudo bash them-wifi.sh "TênWiFi" ""
#
# Sau khi chạy, Pi tự thử nối mạng mới (nếu mạng đó đang ở gần).
# Thử xem trước mà không ghi gì:  DRY=1 sudo bash them-wifi.sh "TênWiFi" "MậtKhẩu"
# ===========================================================================
set -Eeuo pipefail

CONF="/etc/wpa_supplicant/wpa_supplicant.conf"   # file DietPi lưu các Wi-Fi đã nhớ

[[ ${EUID} -eq 0 ]] || { echo "Hãy chạy bằng sudo." >&2; exit 1; }
[[ $# -eq 2 ]] || { echo "Cách dùng: sudo bash them-wifi.sh \"TênWiFi\" \"MậtKhẩu\"" >&2; exit 1; }
SSID="$1"
PASS="$2"

# Mật khẩu WPA phải dài 8-63 ký tự (quy định của Wi-Fi).
if [[ -n "${PASS}" && ( ${#PASS} -lt 8 || ${#PASS} -gt 63 ) ]]; then
    echo "Mật khẩu Wi-Fi phải dài từ 8 đến 63 ký tự." >&2
    exit 1
fi

# Tạo khối cấu hình cho mạng mới.
if [[ -n "${PASS}" ]]; then
    # wpa_passphrase tính sẵn "mật khẩu đã băm" -> không phải lưu mật khẩu gốc dạng chữ.
    BLOCK="$(wpa_passphrase "${SSID}" "${PASS}" | grep -v '^[[:space:]]*#psk=')"
else
    BLOCK=$'network={\n\tssid="'"${SSID}"$'"\n\tkey_mgmt=NONE\n}'
fi
# scan_ssid=1 giúp nối được cả mạng ẩn tên.
BLOCK="$(printf '%s\n' "${BLOCK}" | sed 's/^network={/network={\n\tscan_ssid=1/')"

if [[ "${DRY:-0}" == "1" ]]; then
    echo "[THỬ] Sẽ thêm vào ${CONF}:"
    echo "${BLOCK}" | sed 's/psk=.*/psk=***/'
    exit 0
fi

cp "${CONF}" "${CONF}.bak"            # sao lưu trước khi sửa, lỡ hỏng còn khôi phục
printf '\n%s\n' "${BLOCK}" >> "${CONF}"
wpa_cli -i wlan0 reconfigure || true  # bảo Pi đọc lại danh sách Wi-Fi
echo "Đã thêm Wi-Fi \"${SSID}\". Nếu mạng đó đang ở gần, Pi sẽ tự nối trong vài giây."
echo "(Bản sao lưu cấu hình cũ: ${CONF}.bak)"
