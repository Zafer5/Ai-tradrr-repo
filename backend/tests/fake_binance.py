"""YALNIZCA TEST İÇİN: Binance Spot genel uçlarının biçimini taklit eden yerel sunucu.

Bu, gerçek Binance DEĞİLDİR ve ürün kodunun parçası değildir. Bulut test ortamında Binance'e erişim olmadığında
uçtan uca akışın (tarama -> analiz -> risk -> paper emir) çalıştığını doğrulamak için kullanılır.
Gerçek Binance ile doğrulama, kullanıcının kendi sunucusunda yapılmalıdır.
"""
from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException, Query

from app.exchange.types import INTERVAL_MS
from tests.synth import make_candles

# sembol -> (drift/saat, oynaklık/√saat, fiyat, 24s hacim, spread %, mum sınırı)
PROFILES = {
    "AAAUSDT": dict(drift=0.0015, vol=0.004, price=50.0, qv=90e6, spread=0.02, seed=1),
    "BBBUSDT": dict(drift=-0.0015, vol=0.004, price=30.0, qv=70e6, spread=0.02, seed=2),
    "CCCUSDT": dict(drift=0.0, vol=0.004, price=10.0, qv=60e6, spread=0.03, seed=3),
    "WIDEUSDT": dict(drift=0.001, vol=0.004, price=5.0, qv=50e6, spread=1.0, seed=4),
    "LOWUSDT": dict(drift=0.001, vol=0.004, price=2.0, qv=100_000, spread=0.02, seed=5),
    "USDCUSDT": dict(drift=0.0, vol=0.0002, price=1.0, qv=500e6, spread=0.01, seed=6),
    "YOUNGUSDT": dict(drift=0.002, vol=0.004, price=3.0, qv=40e6, spread=0.02, seed=7, max_4h=40),
}


def _series(symbol: str, interval: str, n: int):
    p = PROFILES[symbol]
    step = INTERVAL_MS[interval]
    hours = step / 3_600_000
    if interval == "4h" and p.get("max_4h"):
        n = min(n, p["max_4h"])
    now = int(time.time() * 1000)
    end = (now // step) * step + step - 1  # son mum henüz kapanmadı
    return make_candles(n, interval, drift=p["drift"] * hours, vol=p["vol"] * hours**0.5, seed=p["seed"],
                        start_price=p["price"], end_ms=end, base_volume=1000.0, vol_trend=1.0)


def build_fake_binance() -> FastAPI:
    app = FastAPI()
    app.state.fail_book_ticker = False
    app.state.request_log = []

    @app.middleware("http")
    async def log_requests(request, call_next):
        app.state.request_log.append(request.url.path)
        return await call_next(request)

    @app.get("/api/v3/ping")
    def ping():
        return {}

    @app.get("/api/v3/exchangeInfo")
    def exchange_info():
        syms = []
        for s in PROFILES:
            syms.append({"symbol": s, "status": "TRADING", "baseAsset": s[:-4], "quoteAsset": "USDT", "isSpotTradingAllowed": True,
                         "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.0001"}, {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                                     {"filterType": "NOTIONAL", "minNotional": "5.0"}]})
        syms.append({"symbol": "AAABTC", "status": "TRADING", "baseAsset": "AAA", "quoteAsset": "BTC", "isSpotTradingAllowed": True, "filters": []})
        return {"symbols": syms}

    def _last(symbol):
        return float(_series(symbol, "5m", 300).close[-1])

    @app.get("/api/v3/ticker/24hr")
    def tickers():
        out = []
        for s, p in PROFILES.items():
            last = _last(s)
            half = last * p["spread"] / 200
            out.append({"symbol": s, "lastPrice": f"{last:.8f}", "bidPrice": f"{last - half:.8f}", "askPrice": f"{last + half:.8f}",
                        "quoteVolume": f"{p['qv']:.2f}", "priceChangePercent": "2.5", "count": 120000})
        return out

    @app.get("/api/v3/ticker/price")
    def prices():
        return [{"symbol": s, "price": f"{_last(s):.8f}"} for s in PROFILES]

    @app.get("/api/v3/ticker/bookTicker")
    def book(symbol: str):
        if app.state.fail_book_ticker:
            raise HTTPException(503, "down")
        if symbol not in PROFILES:
            raise HTTPException(400, {"code": -1121, "msg": "Invalid symbol."})
        last, p = _last(symbol), PROFILES[symbol]
        half = last * p["spread"] / 200
        return {"symbol": symbol, "bidPrice": f"{last - half:.8f}", "askPrice": f"{last + half:.8f}"}

    @app.get("/api/v3/klines")
    def klines(symbol: str, interval: str, limit: int = Query(500, le=1000)):
        if symbol not in PROFILES:
            raise HTTPException(400, {"code": -1121, "msg": "Invalid symbol."})
        c = _series(symbol, interval, limit)
        return [[int(c.open_time[i]), f"{c.open[i]:.8f}", f"{c.high[i]:.8f}", f"{c.low[i]:.8f}", f"{c.close[i]:.8f}",
                 f"{c.volume[i]:.8f}", int(c.close_time[i]), "0", 100, "0", "0", "0"] for i in range(len(c))]

    return app
