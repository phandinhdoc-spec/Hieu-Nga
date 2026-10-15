#!/usr/bin/env bash
# ===========================================================================
# CHẠY SERVER AI GREEN EYE – macOS / Linux.
# Lần đầu: tự tạo môi trường Python riêng (.venv) và tải thư viện (cần Internet).
# Những lần sau: chạy luôn, rất nhanh.
# ===========================================================================
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"   # đi vào thư mục chứa file này (thư mục server)

# --- 1. Có Python chưa? -----------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "[LỖI] Máy chưa có Python 3." >&2
    echo "  - Mac: mở Terminal gõ  xcode-select --install  (hoặc cài từ https://www.python.org/downloads/)" >&2
    echo "  - Linux: sudo apt install python3 python3-venv python3-pip" >&2
    exit 1
fi

# --- 2. Có file .env (chứa chìa khóa Gemini) chưa? --------------------------
if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "[!] Chưa có file .env nên đã tạo mới từ .env.example."
    echo "    Hãy mở file  server/.env , điền chìa khóa Gemini vào dòng GEMINI_API_KEY=..."
    echo "    rồi chạy lại. (Xem HUONG-DAN.md, mục 'Chìa khóa Gemini')"
    exit 1
fi

# --- 3. Tạo môi trường riêng (.venv) nếu chưa có ----------------------------
# Nếu .venv được chép từ máy khác sang thì sẽ không chạy được -> xóa tạo lại.
if [[ -d .venv ]] && ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    rm -rf .venv
fi
if [[ ! -d .venv ]]; then
    echo "[1/2] Tạo môi trường Python (chỉ lần đầu)..."
    python3 -m venv .venv
fi

# --- 4. Cài thư viện cần thiết (edge-tts) -----------------------------------
echo "[2/2] Kiểm tra thư viện..."
.venv/bin/python -m pip install -q -r requirements.txt

# --- 5. Chạy server ---------------------------------------------------------
exec .venv/bin/python server.py
