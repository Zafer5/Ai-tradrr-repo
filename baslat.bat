@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .env (
  copy .env.example .env >nul
  echo.
  echo .env dosyasi olusturuldu. Acilan Not Defteri'nde PANEL_PASSWORD= satirinin
  echo yanina en az 10 karakterlik bir sifre yazin, kaydedin, kapatin.
  notepad .env
)
if not exist .venv (
  echo Ilk kurulum yapiliyor, birkac dakika surebilir...
  python -m venv .venv || (echo Python bulunamadi. python.org adresinden kurun ve "Add to PATH" kutusunu isaretleyin. & pause & exit /b 1)
  .venv\Scripts\pip install -r backend\requirements.txt || (echo Kurulum hatasi & pause & exit /b 1)
)
echo.
echo Panel: http://localhost:8000   (kapatmak icin bu pencereyi kapatin)
start "" http://localhost:8000
cd backend
set DATABASE_URL=sqlite+aiosqlite:///../data/trader.db
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
