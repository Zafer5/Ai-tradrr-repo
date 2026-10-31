# AI KRİPTO TRADER

Binance Spot piyasasını tarayan, teknik analizle fırsatları puanlayan, bağımsız risk
kontrolünden geçirip **sanal (paper) işlem** yapan bot ve telefondan kullanılan Türkçe panel.

> ⚠️ Bu sürüm **yalnızca sanal işlem** yapar. Gerçek para ile emir gönderen kod yoktur.
> Hiçbir strateji kâr garantisi vermez; puanlar yalnızca olasılık tahminidir.

## Mimari

```
Binance (REST + WebSocket, genel veri)
        │
        ▼
exchanges/binance.py  ── borsa bağlantısı (ileride bitget.py, paribu.py aynı arayüzle)
        │
        ▼
scanner.py   ── USDT paritelerini tarar, düşük hacim/yüksek spread/stablecoin/kaldıraçlı tokenleri eler, ilk 50'yi seçer
        │
        ▼
analysis.py  ── 5dk/15dk/1s/4s: RSI, MACD, EMA 9/21/50/200, Bollinger, ATR, hacim, destek/direnç → 0-100 puan + Türkçe gerekçe
        │       (emir gönderemez, yalnızca öneri üretir)
        ▼
risk.py      ── bağımsız risk kontrolü: %1 risk, %2 günlük zarar, 5 pozisyon, %5 coin, %20 maruziyet, komisyon sonrası net kâr
        │
        ▼
paper.py     ── sanal emir (komisyon + fiyat kayması simülasyonu)
        │
engine.py    ── döngüler: coin listesi (30 dk), analiz (5 dk), pozisyon takibi (5 sn: hedef, stop, iz süren stop, kademeli satış)
        │
db.py        ── SQLite: pozisyonlar, işlemler, analizler, günlükler, ayarlar
main.py      ── FastAPI + şifreli mobil panel (static/)
```

## Kurulum (sunucuda)

```bash
git clone https://github.com/<kullanici>/ai-kripto-trader.git
cd ai-kripto-trader
cp .env.example .env
nano .env          # PANEL_PASSWORD satırına güçlü bir şifre yazın
docker compose up -d --build
```

Panel: `http://SUNUCU_IP:8000` (kullanıcı adı ve şifre `.env` içindeki).

Canlı bağlantı testi:

```bash
docker compose run --rm trader python -m app.scan_once
```

Günlükler: `docker compose logs -f`

## Testler

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

## Yol haritası

- [x] 1. aşama: piyasa tarayıcı, analiz motoru, risk yönetimi, paper trading, temel mobil panel
- [ ] Geçmiş verilerle backtest (komisyon, kayma, eğitim/test ayrımı, max drawdown)
- [ ] React + TypeScript PWA panel
- [ ] Binance Spot Testnet entegrasyonu
- [ ] HTTPS, Telegram bildirimleri, PostgreSQL
- [ ] Gerçek hesap (yalnızca kullanıcının ayrıca onayıyla)
