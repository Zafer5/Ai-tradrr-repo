# AI KRİPTO TRADER

Binance Spot piyasasını tarayan, teknik analizle coinleri puanlayan ve **sanal (paper) para** ile otomatik al-sat simülasyonu yapan sistem. Telefondan kullanılan Türkçe web paneli içerir.

> **Durum (v0.1):** Aşama 1 (Paper Trading) çalışır durumdadır. Aşama 2 (Testnet) için anahtar kaydı + bağlantı testi hazırdır, ancak Testnet'e otomatik emir gönderimi henüz bağlı değildir. **Aşama 3 (gerçek para) kod düzeyinde kilitlidir.**
> Bu sistem kâr garantisi vermez. Puanlama kural tabanlıdır (makine öğrenmesi değildir) ve gerçek veriyle backtest edilene kadar kanıtlanmış bir stratejisi yoktur.

## Neler var?
| Bölüm | Açıklama |
|---|---|
| Piyasa tarayıcı | Binance USDT paritelerini hacim, spread, işlem sayısı, stablecoin/kaldıraçlı token ve aşırı hareket filtreleriyle eler; en iyi 50'yi takip eder |
| Analiz motoru | RSI, MACD, EMA 9/21/50/200, Bollinger, ATR, hacim, destek/direnç, trend; 5dk/15dk/1sa/4sa; 0-100 puan, Türkçe gerekçe, stop/hedef planı |
| Risk yöneticisi | Analizden bağımsız; her alım buradan geçer (işlem başı %1 risk, günlük %2 zarar limiti, 5 pozisyon, tek coin %5, toplam %20, maliyet sonrası net kâr ve risk/getiri kontrolü, mükerrer emir engeli, acil durdurma, güvenli mod) |
| Paper trading | Gerçek piyasa fiyatı + sanal bakiye; komisyon ve kayma simülasyonu; kademeli satış, stop-loss, trailing stop |
| Backtest | Komisyon+kayma, gelecek verisi sızıntısı yok, eğitim/test ayrımı, max drawdown, profit factor, al-tut karşılaştırması |
| Panel | 10 ekran, mobil uyumlu, PWA |

## Kurulum (sunucuda, Docker ile)
1. Sunucuya [Docker](https://docs.docker.com/engine/install/) kurun ve bu depoyu indirin.
2. `./scripts/setup.sh` çalıştırın (panel şifresi sorar, `.env` oluşturur).
3. `docker compose up -d --build`
4. Sunucuda `http://127.0.0.1:8000` adresini açın, şifrenizle girin. Bot **kapalı** başlar; panelden "Botu başlat"a basın.

## Android telefondan erişim
Panel varsayılan olarak yalnızca sunucuda açılır (güvenlik). Telefon için, kolaylıktan zora:
1. **Tailscale (önerilir, ücretsiz):** sunucuya ve telefona Tailscale kurun; telefondan `http://<sunucu-tailscale-adresi>:8000` açın. `.env` içinde `BIND_ADDR=0.0.0.0` yapın (Tailscale dışına açılmaması için sunucu güvenlik duvarını kontrol edin).
2. **Cloudflare Tunnel:** HTTPS adresi verir; `.env` içinde `COOKIE_SECURE=true` yapın.
3. **Aynı Wi-Fi:** `BIND_ADDR=0.0.0.0` ve `http://<sunucu-yerel-ip>:8000`.

Chrome'da menü → "Ana ekrana ekle". (Tam PWA kurulumu için HTTPS gerekir: Tailscale HTTPS veya Cloudflare Tunnel.)
**Paneli doğrudan internete açmayın.**

> Bulut sunucunuzun bölgesinde `api.binance.com` engelliyse (ör. bazı ABD bölgeleri) `.env` içinde `BINANCE_REST_URL=https://data-api.binance.vision` deneyin.

## Geliştirme
```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                       # 75 test
ADMIN_PASSWORD=uzun-bir-sifre .venv/bin/uvicorn app.main:create_app --factory --port 8000
cd frontend && npm install && npm run dev        # http://localhost:5173
```
Backtest (gerçek Binance verisi, anahtar gerekmez):
`cd backend && .venv/bin/python -m app.backtest.cli BTCUSDT --days 120`

## Güvenlik
- API anahtarları Fernet ile şifreli saklanır, panele geri gönderilmez, loglarda maskelenir. Sistem **para çekme yetkisi istemez**; Testnet testi, yetki açıksa sizi uyarır.
- `.env` Git'e girmez. Panel girişi scrypt + 5 hatalı denemede kilit + httpOnly/SameSite=Strict çerez.
- **API Secret'ınızı sohbetlere/ekran görüntülerine koymayın.**

## Bilinen sınırlar (dürüst liste)
- Canlı Binance'e karşı doğrulama henüz yapılmadı: geliştirme ortamında Binance erişimi kapalıydı; uçtan uca testler yerel taklit sunucuyla yapıldı. İlk çalıştırmada **Sistem Günlükleri** ve **API Bağlantıları** ekranlarını kontrol edin.
- WebSocket akışı (`!miniTicker@arr`) canlıda doğrulanmadı; kopma halinde REST yedeği devreye girer.
- Paper modunda komisyon USDT olarak düşülür (Binance çoğu zaman alınan coinden keser); stop/hedef kontrolü 2 sn aralıklıdır.
- Kademeli *alım*, Testnet emir yürütme, Telegram, Bitget/Paribu henüz yok (mimari buna uygundur: `app/exchange`).
- Skor ağırlıkları sezgiseldir; gerçek veriyle backtest edilip doğrulanmadan gerçek parada kullanılmamalıdır.
