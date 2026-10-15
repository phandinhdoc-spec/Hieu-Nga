@echo off
REM ===========================================================================
REM CHAY SERVER AI GREEN EYE - Windows.
REM Lan dau: tu tao moi truong Python rieng (.venv) va tai thu vien (can Internet).
REM Nhung lan sau: chay luon, rat nhanh.
REM (Viet khong dau vi cua so den cua Windows hay loi font tieng Viet.)
REM ===========================================================================
cd /d "%~dp0"

REM --- 1. Tim Python: thu "py" (bo cai python.org), roi "python" ---
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo [LOI] May chua cai Python.
  echo   Cach 1: vao https://www.python.org/downloads/ tai ban moi nhat, cai dat,
  echo           NHO TICH vao o "Add python.exe to PATH" o man hinh dau tien.
  echo   Cach 2: dang thu cai tu dong bang winget...
  where winget >nul 2>nul && winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Cai xong thi DONG cua so nay va bam dup lai file CHAY-SERVER-WINDOWS.bat.
  pause
  exit /b 1
)

REM --- 2. Co file .env (chua chia khoa Gemini) chua? ---
if not exist .env (
  copy .env.example .env >nul
  echo.
  echo [!] Chua co file .env nen da tao moi.
  echo     Hay mo file server\.env bang Notepad, dien chia khoa Gemini vao dong GEMINI_API_KEY=...
  echo     roi chay lai. ^(Xem HUONG-DAN.md, muc "Chia khoa Gemini"^)
  pause
  exit /b 1
)

REM --- 3. Tao moi truong rieng (.venv) neu chua co hoac bi hong ---
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import sys" >nul 2>nul || rmdir /s /q .venv
)
if not exist .venv\Scripts\python.exe (
  echo [1/2] Tao moi truong Python ^(chi lan dau^)...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [LOI] Khong tao duoc moi truong Python.
    pause
    exit /b 1
  )
)

REM --- 4. Cai thu vien can thiet (edge-tts) ---
echo [2/2] Kiem tra thu vien...
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo [LOI] Khong cai duoc thu vien. Kiem tra may co Internet khong.
  pause
  exit /b 1
)

REM --- 5. Chay server ---
.venv\Scripts\python.exe server.py
echo.
echo Server da dung. Bam phim bat ky de dong cua so.
pause
