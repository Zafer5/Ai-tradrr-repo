"""Testnet ve GERÇEK mod testleri. Borsa yerine yerel taklit sunucu kullanılır: gerçek para/ağ YOKTUR.
Amaç: emir akışı, güvenlik kilitleri ve hata senaryolarının doğru ve GÜVENLİ davrandığını kanıtlamak."""
import types

import pytest

import app.trading.live as live_mod
from app.exchange.types import SymbolInfo
from app.trading.live import ExchangeExecutor, OrderRejected
from tests.conftest import FAKE_KEY, FAKE_SECRET, PASSWORD

PHRASE = "GERÇEK PARAYLA İŞLEM YAPMAYI ONAYLIYORUM"
INFO = SymbolInfo("AAAUSDT", "AAA", "USDT", "TRADING", True, 0.0001, 0.001, 0.001, 5.0)


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    async def nosleep(_):
        return None

    monkeypatch.setattr(live_mod, "asyncio", types.SimpleNamespace(sleep=nosleep))


async def save_key(env, which):
    r = await env.api.put(f"/api/connections/{which}", json={"api_key": FAKE_KEY, "api_secret": FAKE_SECRET})
    assert r.status_code == 200


async def go_mode(env, mode, capital, usdt=5000.0):
    env.fake.state.balances["USDT"] = usdt
    env.fake.state.balances["AAA"] = 0.0  # bot kendi pozisyonunu kullanıcının coininden ayırabilsin
    await save_key(env, mode)
    body = {"mode": mode, "capital": capital}
    if mode == "live":
        body |= {"confirm_phrase": PHRASE, "password": PASSWORD}
    r = await env.api.post("/api/trading-mode", json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def scan(env):
    s = await env.ctx.store.get()
    await env.ctx.bot.scan_cycle(s)
    return s


async def buy_signal(env, symbol="AAAUSDT"):
    s = await scan(env)
    a = env.ctx.bot.analyses[symbol]
    a.score, a.risk, a.change_pct = 92.0, "Düşük", 2.0
    await env.ctx.bot.set_enabled(True)
    await env.ctx.bot.try_entries(s)
    return s


async def positions(env):
    return (await env.api.get("/api/positions")).json()["items"]


# ---------------------------------------------------------------- kilitler
async def test_live_is_blocked_when_server_flag_is_off(authed):
    env = authed
    await save_key(env, "live")
    r = await env.api.post("/api/trading-mode", json={"mode": "live", "capital": 100, "confirm_phrase": PHRASE, "password": PASSWORD})
    assert r.status_code == 403 and "ALLOW_LIVE_TRADING" in r.text
    assert (await env.api.get("/api/trading-mode")).json()["mode"] == "paper"


async def test_live_requires_capital_phrase_password_and_safe_key_permissions(authed_live):
    env, api = authed_live, authed_live.api
    st = env.fake.state
    base = {"mode": "live", "capital": 100, "confirm_phrase": PHRASE, "password": PASSWORD}
    assert (await api.post("/api/trading-mode", json=base)).status_code == 422  # anahtar yok
    await save_key(env, "live")
    st.balances["USDT"] = 500
    assert (await api.post("/api/trading-mode", json={**base, "capital": None})).status_code == 422
    assert (await api.post("/api/trading-mode", json={**base, "capital": 5})).status_code == 422
    assert (await api.post("/api/trading-mode", json={**base, "confirm_phrase": "evet"})).status_code == 422
    assert (await api.post("/api/trading-mode", json={**base, "password": "yanlis-sifre-1"})).status_code == 401
    st.can_withdraw = True
    r = await api.post("/api/trading-mode", json=base)
    assert r.status_code == 422 and "PARA ÇEKME" in r.text
    t = (await api.post("/api/connections/live/test")).json()
    assert t["ok"] is False and any("PARA ÇEKME" in p for p in t["problems"])
    st.can_withdraw, st.can_trade = False, False
    assert (await api.post("/api/trading-mode", json=base)).status_code == 422  # alım-satım yetkisi yok
    st.can_trade, st.balances["USDT"] = True, 50
    assert (await api.post("/api/trading-mode", json=base)).status_code == 422  # sermaye için bakiye yok
    st.balances["USDT"] = 500
    assert (await api.get("/api/trading-mode")).json()["mode"] == "paper"  # hiçbir ret modu değiştirmedi
    r = await api.post("/api/trading-mode", json={**base, "confirm_phrase": PHRASE.lower()})  # küçük harf kabul edilir
    assert r.status_code == 200 and r.json()["mode"] == "live" and r.json()["capital"] == 100
    await env.ctx.bot.set_enabled(True)
    assert (await api.post("/api/trading-mode", json={"mode": "paper"})).status_code == 409  # bot çalışırken değişmez
    await env.ctx.bot.set_enabled(False)
    assert (await api.post("/api/trading-mode", json={"mode": "paper"})).status_code == 200
    assert (await api.delete("/api/connections/live")).status_code == 200


async def test_live_mode_is_disabled_again_if_server_lock_is_closed_on_restart(authed_live):
    env = authed_live
    await go_mode(env, "live", 100, usdt=500)
    env.ctx.service.live_allowed = False  # sunucu sahibi kilidi kapattı, yeniden başlatma
    await env.ctx.service.load_mode()
    assert env.ctx.service.exec is None and "kilitli" in env.ctx.service.exec_error
    env.ctx.bot._update_safe_mode(False)
    assert "borsa bağlantısı yok" in env.ctx.bot.safe_reason
    await buy_signal(env)
    assert await positions(env) == [] and not env.fake.state.orders  # tek emir gitmedi


# ---------------------------------------------------------------- Testnet: alım / satım gerçek dolumlarla
async def test_testnet_buy_uses_exchange_fills_and_respects_capital(authed):
    env, st = authed, authed.fake.state
    await go_mode(env, "testnet", 1000)
    await buy_signal(env)
    pos = (await positions(env))[0]
    assert pos["mode"] == "testnet" and len(st.orders) == 1
    order = next(iter(st.orders.values()))
    assert order["side"] == "BUY" and order["clientOrderId"].startswith("aky")
    # elimizdeki miktar = borsadaki artış (komisyon coinden düşüldü)
    assert pos["quantity"] == pytest.approx(st.balances["AAA"], abs=1e-8)
    assert pos["quantity"] < float(order["executedQty"])
    assert pos["quantity"] * pos["entry_price"] <= 1000 * 0.05 * 1.01  # tek coin %5 sermaye tavanı
    assert pos["fees_total"] > 0
    async with env.ctx.db.session() as ses:
        from sqlalchemy import select

        from app.models import Order

        o = (await ses.execute(select(Order))).scalar_one()
        assert o.mode == "testnet" and o.exchange_order_id == str(order["orderId"])
    acc = (await env.api.get("/api/status")).json()["account"]
    assert acc["initial"] == 1000 and 990 < acc["equity"] < 1010
    n = (await env.api.get("/api/notifications")).json()["items"]
    assert any("ALIM (TESTNET)" in x["title"] for x in n)


async def test_testnet_exits_sell_real_balance_and_pnl_matches_exchange(authed):
    env, st = authed, authed.fake.state
    await go_mode(env, "testnet", 1000)
    s = await buy_signal(env)
    p = (await positions(env))[0]
    usdt_after_buy = st.balances["USDT"]
    assert usdt_after_buy < 5000

    st.price_override["AAAUSDT"] = p["tp1_price"] * 1.002  # 1. hedef
    await env.ctx.bot.monitor_once()
    p2 = (await positions(env))[0]
    assert p2["tp1_done"] and p2["quantity"] == pytest.approx(p["quantity"] * 0.5, rel=0.01)

    st.price_override["AAAUSDT"] = p["entry_price"] * 0.999  # geri düşüş: başa baş/trailing stop
    await env.ctx.bot.monitor_once()
    assert await positions(env) == []
    tr = (await env.api.get("/api/trades?status=CLOSED")).json()["items"][0]
    assert tr["close_reason"] in ("BREAKEVEN_STOP", "TRAILING_STOP") and tr["mode"] == "testnet"
    assert st.balances["AAA"] == pytest.approx(0.0, abs=0.01)  # bot aldığının tamamını sattı (adım tozu hariç)
    # kayıtlı net sonuç, borsadaki USDT değişimiyle birebir aynı
    assert tr["realized_pnl"] == pytest.approx(st.balances["USDT"] - 5000.0, abs=1e-6)
    sides = [o["side"] for o in reversed((await env.api.get("/api/orders")).json()["items"])]
    assert sides == ["BUY", "SELL", "SELL"]
    assert all(o["type"] == "MARKET" for o in (await env.api.get("/api/orders")).json()["items"])


async def test_small_position_partial_target_becomes_full_close_when_below_min_notional(authed):
    env, st = authed, authed.fake.state
    await go_mode(env, "testnet", 200)  # %5 = 10 USDT pozisyon; yarısı asgari tutarın (5) altında kalır
    await buy_signal(env)
    p = (await positions(env))[0]
    st.price_override["AAAUSDT"] = p["tp1_price"] * 1.002
    await env.ctx.bot.monitor_once()
    assert await positions(env) == []  # parça satış yerine tamamı satıldı
    assert (await env.api.get("/api/trades?status=CLOSED")).json()["items"][0]["close_reason"] == "TAKE_PROFIT_1"


async def test_fee_paid_in_usdt_and_bnb_are_accounted(authed):
    env, st = authed, authed.fake.state
    await go_mode(env, "testnet", 1000)
    st.commission = "usdt"
    await buy_signal(env)
    p = (await positions(env))[0]
    assert p["quantity"] == pytest.approx(st.balances["AAA"], abs=1e-8)  # coin düşmedi
    assert p["fees_total"] == pytest.approx(p["quantity"] * p["entry_price"] * 0.001, rel=0.02)
    async with env.ctx.db.session() as ses:
        from sqlalchemy import select

        from app.models import Position

        pos = (await ses.execute(select(Position))).scalar_one()
        assert pos.cost_total == pytest.approx(pos.quantity * pos.entry_price + p["fees_total"], rel=1e-6)  # maliyet = alım + USDT komisyonu


# ---------------------------------------------------------------- hata senaryoları
async def test_timeout_after_fill_is_resolved_by_client_id_without_duplicate_order(authed):
    env, st = authed, authed.fake.state
    await go_mode(env, "testnet", 1000)
    st.fail_mode = "timeout_after_fill"  # emir gerçekleşti ama yanıt gelmedi
    await buy_signal(env)
    assert len(await positions(env)) == 1 and len(st.orders) == 1  # tek emir, tek pozisyon
    assert env.ctx.bot.halt_reason is None


async def test_timeout_without_fill_is_safe_rejection_not_halt(authed):
    env, st = authed, authed.fake.state
    await go_mode(env, "testnet", 1000)
    st.fail_mode = "timeout_no_fill"
    await buy_signal(env)
    assert await positions(env) == [] and not st.orders
    assert env.ctx.bot.halt_reason is None
    assert any("oluşmadı" in " ".join(d["reasons"]) for d in env.ctx.bot.decisions)


async def test_unresolvable_order_halts_all_new_orders_until_human_clears(authed):
    env, st = authed, authed.fake.state
    await go_mode(env, "testnet", 1000)
    st.fail_mode = "timeout_and_query_fails"
    s = await buy_signal(env)
    assert env.ctx.bot.halt_reason and "doğrulanamadı" in env.ctx.bot.halt_reason
    n = len(st.orders)
    st.fail_mode = None
    env.ctx.bot._update_safe_mode(False)
    env.ctx.bot.analyses["CCCUSDT"].score = 95.0
    await env.ctx.bot.try_entries(s)
    assert len(st.orders) == n  # halt sürerken YENİ emir gitmedi
    assert (await env.api.get("/api/status")).json()["bot"]["halt"]
    assert (await env.api.post("/api/bot/clear-halt")).status_code == 200  # insan doğruladı
    assert env.ctx.bot.halt_reason is None
    assert any(x["kind"] == "halt" for x in (await env.api.get("/api/notifications")).json()["items"])


async def test_reconcile_detects_missing_coins_and_halts(authed):
    env, st = authed, authed.fake.state
    await go_mode(env, "testnet", 1000)
    await buy_signal(env)
    st.balances["AAA"] = 0.0  # kullanıcı pozisyonu borsadan elle sattı
    problem = await env.ctx.bot._reconcile(force=True)
    assert problem and "AAAUSDT" in problem and env.ctx.bot.halt_reason
    assert (await env.api.post("/api/bot/clear-halt")).status_code == 409  # uyuşmazlık sürüyor
    p = (await positions(env))[0]
    st.balances["AAA"] = p["quantity"]
    assert (await env.api.post("/api/bot/clear-halt")).status_code == 200


async def test_exchange_sell_failure_keeps_position_and_retries(authed):
    env, st = authed, authed.fake.state
    await go_mode(env, "testnet", 1000)
    await buy_signal(env)
    p = (await positions(env))[0]
    st.balances["AAA"] = 0.0  # satılacak coin yok => satış reddedilir
    st.price_override["AAAUSDT"] = p["stop_price"] * 0.99
    await env.ctx.bot.monitor_once()
    assert len(await positions(env)) == 1  # pozisyon kaydı korunur (kapanmış gibi gösterilmez)
    assert any(x["kind"] == "exit_fail" for x in (await env.api.get("/api/notifications")).json()["items"])


# ---------------------------------------------------------------- yürütücü ön doğrulamaları
async def test_executor_preflight_rejects_unsafe_orders_before_sending(authed):
    env, st = authed, authed.fake.state
    ex = ExchangeExecutor(env.ctx.make_client(FAKE_KEY, FAKE_SECRET), "testnet")
    st.balances["AAA"] = 0.0
    st.balances["USDT"] = 10.0
    with pytest.raises(OrderRejected, match="Bakiye yetersiz"):
        await ex.buy("AAAUSDT", 1.0, 50.0, INFO)
    st.balances["USDT"] = 5000.0
    with pytest.raises(OrderRejected, match="asgari tutar"):
        await ex.buy("AAAUSDT", 0.05, 50.0, INFO)  # 2.5 USDT < 5
    with pytest.raises(OrderRejected, match="adım"):
        await ex.buy("AAAUSDT", 0.0004, 50.0, INFO)  # adım büyüklüğünün altı
    with pytest.raises(OrderRejected, match="Sermaye tavanı"):
        await ex.buy("AAAUSDT", 1.0, 50.0, INFO, capital_free=20.0)
    st.open_orders = [{"orderId": 1}]
    with pytest.raises(OrderRejected, match="bekleyen emir"):
        await ex.buy("AAAUSDT", 1.0, 50.0, INFO)
    st.open_orders = []
    with pytest.raises(OrderRejected, match="zaten AAA bakiyesi"):
        st.balances["AAA"] = 10.0
        await ex.buy("AAAUSDT", 1.0, 50.0, INFO)  # kullanıcının coini var: bot dokunmaz
    st.balances["AAA"] = 0.0
    with pytest.raises(OrderRejected, match="bakiyesi yok"):
        await ex.sell("AAAUSDT", 1.0, 50.0, SymbolInfo("ZZZUSDT", "ZZZ", "USDT", "TRADING", True, 0.01, 0.001, 0.001, 5.0), True)
    assert not st.orders  # hiçbiri gerçek emir olarak gitmedi


async def test_quantity_is_formatted_without_float_noise(authed):
    from decimal import Decimal

    assert live_mod.fmt_qty(live_mod.floor_qty(0.1 + 0.2, 0.001)) == "0.3"
    assert live_mod.fmt_qty(Decimal("12.3400")) == "12.34" and live_mod.fmt_qty(live_mod.floor_qty(1.99999999, 0.01)) == "1.99"


# ---------------------------------------------------------------- mod ayrımı
async def test_modes_keep_separate_records(authed):
    env, st = authed, authed.fake.state
    s = await scan(env)
    env.ctx.bot.analyses["AAAUSDT"].score, env.ctx.bot.analyses["AAAUSDT"].risk = 92.0, "Düşük"
    await env.ctx.bot.set_enabled(True)
    await env.ctx.bot.try_entries(s)
    pid = (await positions(env))[0]["id"]
    assert (await env.api.post(f"/api/positions/{pid}/close")).status_code in (200, 409)  # paper'da fiyat akışı yoksa 409
    env.ctx.feed.update("AAAUSDT", 50.0)
    await env.api.post(f"/api/positions/{pid}/close")
    await env.ctx.bot.set_enabled(False)
    assert len((await env.api.get("/api/trades?status=CLOSED")).json()["items"]) == 1
    await go_mode(env, "testnet", 1000)
    assert (await env.api.get("/api/trades?status=CLOSED")).json()["items"] == []  # testnet'te sanal işlem görünmez
    assert (await env.api.post("/api/paper/reset", json={"confirm": True})).status_code == 409  # borsa modunda sıfırlama yok
    assert (await env.api.post("/api/trading-mode", json={"mode": "paper"})).status_code == 200
    assert len((await env.api.get("/api/trades?status=CLOSED")).json()["items"]) == 1


async def test_legacy_database_gets_new_columns_without_data_loss(tmp_path):
    """Eski sürümden kalan veritabanı yeni sütunlarla (exchange_order_id, mode...) güncellenir."""
    import sqlite3

    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("create table orders (id integer primary key, position_id integer, symbol varchar(24), mode varchar(12), side varchar(4), order_type varchar(12), quantity float, price float, fee float, reason varchar(32), created_at datetime)")
    c.execute("create table equity_snapshots (id integer primary key, ts datetime, equity float, cash float)")
    c.execute("insert into equity_snapshots (equity, cash) values (1000, 900)")
    c.commit()
    c.close()
    from app.db import Database

    db = Database(f"sqlite+aiosqlite:///{path}")
    await db.create_all()
    await db.create_all()  # tekrar çalıştırmak zararsız
    async with db.session() as ses:
        from sqlalchemy import text

        assert (await ses.execute(text("select equity, mode from equity_snapshots"))).one() == (1000.0, "paper")
        await ses.execute(text("select exchange_order_id from orders"))
    await db.dispose()


async def test_regression_testnet_without_positions_is_not_blocked_by_missing_price_feed(authed):
    """Canlı döngüde bulunan hata: testnet'te pozisyon yokken fiyat yaşı 'sonsuz' sayılıp tüm alımlar engelleniyordu."""
    env = authed
    await go_mode(env, "testnet", 1000)
    bot = env.ctx.bot
    bot.started_at -= 1000  # başlangıç tolerans süresi geçti
    await bot.set_enabled(True)
    bot._update_safe_mode(False)
    assert bot.safe_reason is None
    await bot.set_enabled(False)
    await env.api.post("/api/trading-mode", json={"mode": "paper"})
    await bot.set_enabled(True)
    bot._update_safe_mode(False)
    assert bot.safe_reason and "fiyat akışı" in bot.safe_reason  # sanal/gerçek modda akış hâlâ şart
