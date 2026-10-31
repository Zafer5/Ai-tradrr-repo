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
echo En son surum kontrol ediliyor...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $t=Join-Path $env:TEMP 'akt-update'; if(Test-Path $t){Remove-Item $t -Recurse -Force}; New-Item -ItemType Directory $t | Out-Null; Invoke-WebRequest 'https://github.com/Zafer5/Ai-tradrr-repo/archive/refs/heads/main.zip' -OutFile (Join-Path $t 'u.zip') -TimeoutSec 30; Expand-Archive (Join-Path $t 'u.zip') -DestinationPath $t -Force" >nul 2>&1 && (
  robocopy "%TEMP%\akt-update\Ai-tradrr-repo-main\backend" "%~dp0backend" /E /NFL /NDL /NJH /NJS >nul
  echo Guncel surum uygulandi.
) || echo Guncelleme yapilamadi, mevcut surumle devam ediliyor.
if not exist .venv (
  echo Ilk kurulum yapiliyor, birkac dakika surebilir...
  python -m venv .venv || (echo Python bulunamadi. python.org adresinden kurun ve "Add to PATH" kutusunu isaretleyin. & pause & exit /b 1)
)
.venv\Scripts\pip install -q -r backend\requirements.txt || (echo Kurulum hatasi & pause & exit /b 1)
echo.
echo Panel: http://localhost:8000   (kapatmak icin bu pencereyi kapatin)
start "" http://localhost:8000
cd backend
set DATABASE_URL=sqlite+aiosqlite:///../data/trader.db
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
