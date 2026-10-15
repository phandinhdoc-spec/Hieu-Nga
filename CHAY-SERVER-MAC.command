#!/usr/bin/env bash
# NHẤP ĐÚP file này trên Mac để chạy server AI Green Eye.
# (Nếu Mac báo "không mở được": bấm chuột phải vào file -> Mở -> Mở.)
cd "$(dirname "$0")/server" || exit 1
bash ./start.sh
echo
read -r -p "Server đã dừng. Bấm Enter để đóng cửa sổ..."
