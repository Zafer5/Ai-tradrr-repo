"""Gerçek emir yolunun testleri. Binance yerine sahte (mock) HTTP yanıtları kullanılır;
hiçbir test gerçek bir borsaya bağlanmaz."""
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from app.db import Database, Position
from app.engine import Engine
from app.exchanges.base import Candle, ExchangeError, SymbolInfo, Ticker24h
from app.exchanges.binance_trade import BinanceTrader, OrderUncertain
from app.live import LiveExecutor
from app.paper import fmt_qty
from app.radar import evaluate

from .helpers import FakeClient

INFO = SymbolInfo("AAAUSDT", "AAA", "USDT", "TRADING", True, step_size=0.001, min_notional=5, min_qty=0.001)


# ---------- imza ve bağlantı ----------
async def test_signed_request_is_correct_and_secret_not_sent():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1_000_000_000_000})
        seen["url"], seen["key"] = req.url, req.headers.get("X-MBX-APIKEY")
        return httpx.Response(200, json={"balances": []})

    t = BinanceTrader("https://x", "KEY123", "SECRET456", transport=httpx.MockTransport(handler))
    await t.account()
    q = parse_qs(urlparse(str(seen["url"])).query)
    assert seen["key"] == "KEY123" and "SECRET456" not in str(seen["url"])
    sig = q.pop("signature")[0]
    payload = "&".join(f"{k}={v[0]}" for k, v in q.items())
    assert sig == hmac.new(b"SECRET456", payload.encode(), hashlib.sha256).hexdigest()
    assert int(q["timestamp"][0]) > 900_000_000_000          # sunucu saatine göre ayarlandı
    await t.close()


async def test_error_message_never_contains_secret():
    def handler(req):
        if req.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1})
        return httpx.Response(401, json={"code": -2015, "msg": "Invalid API-key, IP, or permissions for action."})

    t = BinanceTrader("https://x", "KEY123", "SECRET456", transport=httpx.MockTransport(handler))
    with pytest.raises(ExchangeError) as e:
        await t.account()
    assert "SECRET456" not in str(e.value) and "-2015" in str(e.value)


async def test_order_recovered_after_network_error():
    calls = {"n": 0}

    def handler(req: httpx.Request):
        if req.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1})
        if req.method == "POST":
            raise httpx.ReadTimeout("zaman aşımı")
        calls["n"] += 1
        return httpx.Response(200, json={"status": "FILLED", "executedQty": "1", "cummulativeQuoteQty": "10"})

    t = BinanceTrader("https://x", "K", "S", transport=httpx.MockTransport(handler))
    o = await t.market_order("AAAUSDT", "BUY", "1")
    assert o["status"] == "FILLED" and o["_recovered"] and calls["n"] == 1


async def test_order_not_found_after_network_error_is_safe_cancel():
    def handler(req: httpx.Request):
        if req.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1})
        if req.method == "POST":
            raise httpx.ReadTimeout("zaman aşımı")
        return httpx.Response(400, json={"code": -2013, "msg": "Order does not exist."})

    t = BinanceTrader("https://x", "K", "S", transport=httpx.MockTransport(handler))
    with pytest.raises(ExchangeError) as e:
        await t.market_order("AAAUSDT", "BUY", "1")
    assert not isinstance(e.value, OrderUncertain)


async def test_order_uncertain_when_status_unknown():
    def handler(req: httpx.Request):
        if req.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1})
        raise httpx.ConnectError("kopuk")

    t = BinanceTrader("https://x", "K", "S", transport=httpx.MockTransport(handler))
    with pytest.raises(OrderUncertain):
        await t.market_order("AAAUSDT", "BUY", "1")


def test_fmt_qty():
    assert fmt_qty(1.23456, 0.001) == "1.234"
    assert fmt_qty(0.00001234, 0.00000001) == "0.00001234"
    assert "e" not in fmt_qty(1e-7, 1e-8)


# ---------- yürütücü: komisyon çözümleme ----------
class FakeTrader:
    def __init__(self, fills, executed="5", quote="50.0", withdraw=False, usdt="5000"):
        self.fills, self.executed, self.quote = fills, executed, quote
        self.withdraw, self.usdt = withdraw, usdt
        self.orders: list[tuple] = []
        self.raise_on_order: Exception | None = None

    async def market_order(self, symbol, side, qty):
        if self.raise_on_order:
            raise self.raise_on_order
        self.orders.append((symbol, side, qty))
        return {"status": "FILLED", "executedQty": self.executed, "cummulativeQuoteQty": self.quote, "fills": self.fills}

    async def price(self, symbol):
        return {"BNBUSDT": 600.0}[symbol]

    async def free_balance(self, asset):
        return float(self.usdt)

    async def account(self):
        return {"canTrade": True, "balances": [{"asset": "USDT", "free": self.usdt, "locked": "0"}]}

    async def api_restrictions(self):
        return {"enableWithdrawals": self.withdraw, "enableSpotAndMarginTrading": True, "ipRestrict": True}

    async def close(self):
        pass


async def test_executor_fee_in_base_asset_reduces_quantity():
    t = FakeTrader([{"price": "10", "qty": "5", "commission": "0.005", "commissionAsset": "AAA"}])
    f = await LiveExecutor(t, "live", 0.1, 0.05).buy("AAAUSDT", 10.0, 5.0, INFO)
    assert abs(f.quantity - 4.995) < 1e-9 and abs(f.price - 10.0) < 1e-9
    assert abs(f.fee - 0.05) < 1e-9 and f.fee_cash == 0.0           # USDT bakiyesinden düşmedi
    assert t.orders == [("AAAUSDT", "BUY", "5")]


async def test_executor_fee_in_bnb_and_usdt():
    t = FakeTrader([{"price": "10", "qty": "5", "commission": "0.0001", "commissionAsset": "BNB"}])
    f = await LiveExecutor(t, "live", 0.1, 0.05).sell("AAAUSDT", 10.0, 5.0, INFO)
    assert abs(f.fee - 0.06) < 1e-9 and f.fee_cash == 0.0 and f.quantity == 5.0
    t2 = FakeTrader([{"price": "10", "qty": "5", "commission": "0.05", "commissionAsset": "USDT"}])
    f2 = await LiveExecutor(t2, "live", 0.1, 0.05).sell("AAAUSDT", 10.0, 5.0, INFO)
    assert f2.fee == f2.fee_cash == 0.05


async def test_executor_zero_fill_is_error():
    t = FakeTrader([], executed="0", quote="0")
    with pytest.raises(ExchangeError):
        await LiveExecutor(t, "live", 0.1, 0.05).buy("AAAUSDT", 10.0, 5.0, INFO)


# ---------- motor: canlı mod güvenlik kapıları ----------
async def make_engine(trader, mode="live", budget=30.0, cap=10.0):
    db = Database("sqlite+aiosqlite:///:memory:")
    e = Engine(FakeClient(), db, budget, mode=mode, trader=trader, max_order_usdt=cap, budget=budget)
    await e.init()
    await e.refresh_universe()
    return e


async def test_live_refuses_when_withdrawal_enabled():
    e = await make_engine(FakeTrader([], withdraw=True))
    with pytest.raises(ValueError, match="PARA ÇEKME"):
        await e.set_running(True, confirmed=True)
    assert not e.running


async def test_live_requires_typed_confirmation():
    e = await make_engine(FakeTrader([]))
    with pytest.raises(ValueError, match="onay"):
        await e.set_running(True, confirmed=False)
    await e.set_running(True, confirmed=True)
    assert e.running


async def test_live_refuses_when_balance_below_budget():
    e = await make_engine(FakeTrader([], usdt="10"))
    with pytest.raises(ValueError, match="Serbest USDT"):
        await e.set_running(True, confirmed=True)


async def test_live_buy_uses_real_fill_and_respects_order_cap():
    fills = [{"price": "10.01", "qty": "1", "commission": "0.01", "commissionAsset": "USDT"}]
    t = FakeTrader(fills, executed="1", quote="10.01")
    e = await make_engine(t, budget=1000.0, cap=10.0)
    await e.set_running(True, confirmed=True)
    e.settings.risk.min_score = 0
    e.settings.risk.max_per_coin_pct = 50
    e.settings.risk.max_total_exposure_pct = 100
    await e.analysis_cycle()
    assert len(t.orders) == 1
    sym, side, qty = t.orders[0]
    assert side == "BUY" and float(qty) * 10.0 <= 10.0 + 0.05           # tek alım üst sınırı (10 USDT)
    async with e.db.session() as s:
        p = (await s.execute(select(Position))).scalars().one()
    assert p.mode == "live" and abs(p.entry_price - 10.01) < 1e-9
    assert p.take_profit > p.entry_price > p.stop_loss                    # hedef/stop gerçek dolum fiyatına göre


async def test_uncertain_order_halts_bot_and_freezes_symbol():
    t = FakeTrader([])
    t.raise_on_order = OrderUncertain("bilinmiyor")
    e = await make_engine(t, budget=1000.0)
    await e.set_running(True, confirmed=True)
    e.settings.risk.min_score = 0
    await e.analysis_cycle()
    assert not e.running and "belirsiz" in e.halted_reason
    async with e.db.session() as s:
        assert not (await s.execute(select(Position))).scalars().all()


async def test_rejected_order_does_not_halt_or_create_position():
    t = FakeTrader([])
    t.raise_on_order = ExchangeError("Binance hata 400 (kod -1013): Filter failure")
    e = await make_engine(t, budget=1000.0)
    await e.set_running(True, confirmed=True)
    e.settings.risk.min_score = 0
    await e.analysis_cycle()
    assert e.running
    async with e.db.session() as s:
        assert not (await s.execute(select(Position))).scalars().all()


async def test_testnet_without_keys_never_trades_or_fakes_fills():
    e = await make_engine(None, mode="testnet", budget=1000.0)
    with pytest.raises(ValueError, match="API anahtarı"):
        await e.set_running(True)
    e.running = True
    e.settings.risk.min_score = 0
    await e.analysis_cycle()
    async with e.db.session() as s:
        assert not (await s.execute(select(Position))).scalars().all()


async def test_config_order_cap_cannot_be_raised_from_panel():
    t = FakeTrader([{"price": "10", "qty": "1", "commission": "0", "commissionAsset": "USDT"}], executed="1", quote="10")
    e = await make_engine(t, budget=1000.0, cap=10.0)
    await e.save_settings({"risk": {"max_order_usdt": 500.0, "max_per_coin_pct": 50.0, "max_total_exposure_pct": 100.0, "min_score": 0}})
    await e.set_running(True, confirmed=True)
    await e.analysis_cycle()
    assert t.orders and float(t.orders[0][2]) * 10.0 <= 10.0 + 0.05


# ---------- radar ----------
def daily(n, start=10.0, drift=0.0, last_vol=1.0):
    out, p = [], start
    for i in range(n):
        o, p = p, p * (1 + drift)
        out.append(Candle(i * 86_400_000, o, max(o, p) * 1.01, min(o, p) * 0.99, p, 100.0, i * 86_400_000 + 86_399_999, True))
    return out


def ticker(price, chg, qv):
    return Ticker24h("XUSDT", price, chg, qv, 1000, price, price)


def test_radar_flags_new_listing_with_warnings():
    r = evaluate("XUSDT", "X", daily(10), ticker(11.0, 12.0, 5000.0), 0.1, False)
    assert r.age_days == 10 and any("yeni listelendi" in t for t in r.tags)
    assert any("Yeni listelenen" in w for w in r.warnings)


def test_radar_breakout_and_volume_spike_score_high():
    c = daily(60, drift=0.001)
    r = evaluate("XUSDT", "X", c, ticker(c[-1].close * 1.08, 8.0, 100.0 * c[-1].close * 3.0), 0.05, True)
    assert r.breakout and r.vol_ratio >= 2 and r.age_days is None and r.score >= 70


def test_radar_overheated_coin_is_warned_not_rewarded():
    c = daily(60)
    r = evaluate("XUSDT", "X", c, ticker(15.0, 60.0, 100.0 * 10 * 1.0), 0.05, False)
    assert any("geri çekilme riski" in w for w in r.warnings) and "yükseliyor" not in r.tags


def test_radar_too_little_history_is_skipped():
    assert evaluate("XUSDT", "X", daily(2), ticker(10, 1, 1), 0.1, False) is None
