@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo En son surum GitHub'dan indiriliyor...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $t=Join-Path $env:TEMP 'akt-update'; if(Test-Path $t){Remove-Item $t -Recurse -Force}; New-Item -ItemType Directory $t | Out-Null; Invoke-WebRequest 'https://github.com/Zafer5/Ai-tradrr-repo/archive/refs/heads/main.zip' -OutFile (Join-Path $t 'u.zip'); Expand-Archive (Join-Path $t 'u.zip') -DestinationPath $t -Force" || (echo Indirme basarisiz & pause & exit /b 1)
robocopy "%TEMP%\akt-update\Ai-tradrr-repo-main\backend" "%~dp0backend" /E /NFL /NDL /NJH /NJS >nul
copy /Y "%TEMP%\akt-update\Ai-tradrr-repo-main\README.md" "%~dp0README.md" >nul
echo.
echo Guncelleme tamam. .env, veriler ve sifren korundu.
echo Simdi baslat.bat ile botu yeniden baslatin.
pause
