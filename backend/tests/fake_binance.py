"""YALNIZCA TEST İÇİN: Binance Spot genel uçlarının biçimini taklit eden yerel sunucu.

Bu, gerçek Binance DEĞİLDİR ve ürün kodunun parçası değildir. Bulut test ortamında Binance'e erişim olmadığında
uçtan uca akışın (tarama -> analiz -> risk -> paper emir) çalıştığını doğrulamak için kullanılır.
Gerçek Binance ile doğrulama, kullanıcının kendi sunucusunda yapılmalıdır.
"""
from __future__ import annotations

import time

import hashlib
import hmac

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.exchange.types import INTERVAL_MS
from tests.synth import make_candles

# sembol -> (drift/saat, oynaklık/√saat, fiyat, 24s hacim, spread %, mum sınırı)
PROFILES = {
    "BTCUSDT": dict(drift=0.0003, vol=0.002, price=60000.0, qv=900e6, spread=0.01, seed=8),
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

    @app.exception_handler(HTTPException)
    async def binance_style_errors(_, exc: HTTPException):
        """Gerçek Binance hata gövdesi: {"code": -2013, "msg": "..."} (FastAPI'nin {"detail": ...} biçimi DEĞİL)."""
        body = exc.detail if isinstance(exc.detail, dict) else {"code": -1000, "msg": str(exc.detail)}
        return JSONResponse(body, status_code=exc.status_code)

    app.state.fail_book_ticker = False
    app.state.request_log = []
    app.state.price_override = {}
    app.state.balances = {"USDT": 500.0, "AAA": 100.0, "BBB": 50.0, "NOPAIR": 3.0}
    app.state.can_trade, app.state.can_withdraw = True, False
    app.state.commission = "base"  # base | usdt | bnb
    app.state.fail_mode = None  # None | timeout_after_fill | timeout_no_fill | timeout_and_query_fails
    app.state.open_orders = []
    app.state.orders = {}  # clientOrderId -> emir
    app.state.order_seq = 1000

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
        if symbol in app.state.price_override:
            return app.state.price_override[symbol]
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

    FAKE_KEY, FAKE_SECRET = "FAKEKEY1234567890ABCDEF", "FAKESECRET1234567890ABCDEFGH"
    app.state.keys = (FAKE_KEY, FAKE_SECRET)

    def check_signed(request: Request):
        """Binance kuralı: X-MBX-APIKEY başlığı + imza = HMAC-SHA256(sorgu dizesi, secret)."""
        if request.headers.get("x-mbx-apikey") != FAKE_KEY:
            raise HTTPException(401, {"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."})
        qs = request.url.query
        if "&signature=" not in qs:
            raise HTTPException(400, {"code": -1102, "msg": "Mandatory parameter 'signature' was not sent."})
        body, sig = qs.rsplit("&signature=", 1)
        if not hmac.compare_digest(sig, hmac.new(FAKE_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()):
            raise HTTPException(400, {"code": -1022, "msg": "Signature for this request is not valid."})

    @app.get("/api/v3/account")
    def account(request: Request):
        check_signed(request)
        st = app.state
        return {"canTrade": st.can_trade, "canWithdraw": st.can_withdraw, "permissions": ["SPOT"],
                "balances": [{"asset": a, "free": f"{v:.8f}", "locked": "0.00000000"} for a, v in st.balances.items()]}

    def book_prices(symbol):
        last, p = _last(symbol), PROFILES[symbol]
        half = last * p["spread"] / 200
        return last - half, last + half

    def validate_order(q):
        st = app.state
        symbol, side, typ, qty = q["symbol"], q["side"], q["type"], float(q["quantity"])
        if symbol not in PROFILES:
            raise HTTPException(400, {"code": -1121, "msg": "Invalid symbol."})
        if typ != "MARKET":
            raise HTTPException(400, {"code": -1116, "msg": "Invalid orderType."})
        if abs(round(qty / 0.001) * 0.001 - qty) > 1e-9:
            raise HTTPException(400, {"code": -1013, "msg": "Filter failure: LOT_SIZE"})
        bid, ask = book_prices(symbol)
        px = ask if side == "BUY" else bid
        if qty * px < 5.0:
            raise HTTPException(400, {"code": -1013, "msg": "Filter failure: NOTIONAL"})
        base = symbol[:-4]
        if side == "BUY" and st.balances.get("USDT", 0) < qty * px:
            raise HTTPException(400, {"code": -2010, "msg": "Account has insufficient balance for requested action."})
        if side == "SELL" and st.balances.get(base, 0) < qty - 1e-12:
            raise HTTPException(400, {"code": -2010, "msg": "Account has insufficient balance for requested action."})
        return symbol, side, qty, px, base

    @app.post("/api/v3/order/test")
    def order_test(request: Request):
        check_signed(request)
        validate_order(dict(request.query_params))
        return {}

    @app.post("/api/v3/order")
    def new_order(request: Request):
        check_signed(request)
        st = app.state
        q = dict(request.query_params)
        cid = q.get("newClientOrderId", f"auto{st.order_seq}")
        if cid in st.orders:
            raise HTTPException(400, {"code": -2010, "msg": "Duplicate order sent."})
        if st.fail_mode == "timeout_no_fill":
            raise HTTPException(503, "service unavailable")
        symbol, side, qty, px, base = validate_order(q)
        st.order_seq += 1
        fee_rate = 0.001
        if side == "BUY":
            if st.commission == "base":
                fee, asset = qty * fee_rate, base
                st.balances["USDT"] -= qty * px
                st.balances[base] = st.balances.get(base, 0) + qty - fee
            elif st.commission == "usdt":
                fee, asset = qty * px * fee_rate, "USDT"
                st.balances["USDT"] -= qty * px + fee
                st.balances[base] = st.balances.get(base, 0) + qty
            else:
                fee, asset = qty * px * fee_rate * 0.75 / 600, "BNB"
                st.balances["USDT"] -= qty * px
                st.balances[base] = st.balances.get(base, 0) + qty
        else:
            fee, asset = qty * px * fee_rate, "USDT"
            st.balances[base] -= qty
            st.balances["USDT"] += qty * px - fee
        order = {"symbol": symbol, "orderId": st.order_seq, "clientOrderId": cid, "transactTime": 0, "price": "0.00000000",
                 "origQty": f"{qty:.8f}", "executedQty": f"{qty:.8f}", "cummulativeQuoteQty": f"{qty * px:.8f}", "status": "FILLED",
                 "type": "MARKET", "side": side,
                 "fills": [{"price": f"{px:.8f}", "qty": f"{qty:.8f}", "commission": f"{fee:.8f}", "commissionAsset": asset, "tradeId": st.order_seq}]}
        st.orders[cid] = order
        if st.fail_mode in ("timeout_after_fill", "timeout_and_query_fails"):
            raise HTTPException(503, "gateway timeout")  # emir GERÇEKLEŞTİ ama yanıt gelmedi
        return order

    @app.get("/api/v3/order")
    def get_order(request: Request, symbol: str, origClientOrderId: str):
        check_signed(request)
        if app.state.fail_mode == "timeout_and_query_fails":
            raise HTTPException(503, "down")
        o = app.state.orders.get(origClientOrderId)
        if not o:
            raise HTTPException(400, {"code": -2013, "msg": "Order does not exist."})
        return {k: v for k, v in o.items() if k != "fills"}

    @app.get("/api/v3/openOrders")
    def open_orders(request: Request, symbol: str | None = None):
        check_signed(request)
        return app.state.open_orders

    @app.get("/api/v3/myTrades")
    def my_trades(request: Request, symbol: str):
        check_signed(request)
        def t(i, buyer, price, qty):
            return {"id": i, "isBuyer": buyer, "price": str(price), "qty": str(qty), "quoteQty": str(price * qty), "commission": "0", "commissionAsset": "USDT", "time": 1_700_000_000_000 + i}
        if symbol == "AAAUSDT":
            return [t(1, True, 38, 60), t(2, True, 43, 40)]  # miktar 100 = bakiye, ort. maliyet 40
        if symbol == "BBBUSDT":
            return [t(1, True, 20, 20)]  # miktar 20 != bakiye 50 => geçmiş eksik
        return []

    return app
