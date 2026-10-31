#!/usr/bin/env bash
# .env dosyasını güvenli biçimde oluşturur (şifre sorar, anahtar üretir).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then echo ".env zaten var; üzerine yazılmadı."; exit 0; fi
read -r -s -p "Panel şifresi seçin (en az 10 karakter): " PW; echo
[ "${#PW}" -ge 10 ] || { echo "Şifre çok kısa."; exit 1; }
KEY=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")
sed -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${PW}|" -e "s|^SECRET_KEY=.*|SECRET_KEY=${KEY}|" .env.example > .env
chmod 600 .env
echo ".env oluşturuldu. Sonraki adım:  docker compose up -d --build"
