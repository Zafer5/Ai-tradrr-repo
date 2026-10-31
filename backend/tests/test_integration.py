import json

import pytest
from sqlalchemy import select, text

from app.kv import kv_set
from app.models import ApiCredential, LogEntry
from tests.conftest import PASSWORD


async def scan(env):
    s = await env.ctx.store.get()
    await env.ctx.bot.scan_cycle(s)
    return s


# ----------------------------------------------------------------------- kimlik doğrulama
async def test_auth_required_and_login_flow(env):
    assert (await env.api.get("/api/status")).status_code == 401
    assert (await env.api.get("/api/health")).status_code == 200
    assert (await env.api.post("/api/auth/login", json={"password": "yanlis"})).status_code == 401
    r = await env.api.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    assert (await env.api.get("/api/status")).status_code == 200
    await env.api.post("/api/auth/logout")
    assert (await env.api.get("/api/auth/me")).json() == {"authenticated": False}


async def test_login_lockout_after_repeated_failures(env):
    for _ in range(5):
        assert (await env.api.post("/api/auth/login", json={"password": "x"})).status_code == 401
    r = await env.api.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 429


# ----------------------------------------------------------------------- tarayıcı + analiz
async def test_scanner_and_analyses_endpoints(authed):
    await scan(authed)
    d = (await authed.api.get("/api/scanner")).json()
    syms = {c["symbol"] for c in d["candidates"]}
    assert {"AAAUSDT", "BBBUSDT", "CCCUSDT", "YOUNGUSDT"} <= syms
    assert not syms & {"USDCUSDT", "WIDEUSDT", "LOWUSDT"}  # stablecoin, geniş spread, düşük hacim elendi
    assert d["rejected"]["Stablecoin"] == 1 and d["rejected"]["Spread yüksek"] == 1 and d["rejected"]["24s hacim düşük"] == 1
    young = next(c for c in d["candidates"] if c["symbol"] == "YOUNGUSDT")
    assert young["score"] is None and "yetersiz geçmiş" in young["skip_reason"]

    a = (await authed.api.get("/api/analyses")).json()
    by = {x["symbol"]: x for x in a["items"]}
    assert by["AAAUSDT"]["eligible"] and by["AAAUSDT"]["rationale"]
    assert by["AAAUSDT"]["score"] > by["BBBUSDT"]["score"]
    assert by["BBBUSDT"]["score"] <= 55
    one = (await authed.api.get("/api/analyses/aaausdt")).json()
    assert one["symbol"] == "AAAUSDT" and set(one["tf"]) == {"5m", "15m", "1h", "4h"}


# ----------------------------------------------------------------------- paper alım-satım
async def force_good_signal(env, symbol="AAAUSDT"):
    a = env.ctx.bot.analyses[symbol]
    a.score, a.risk, a.label = 90.0, "Düşük", "Çok güçlü fırsat"
    return a


async def test_paper_trade_lifecycle_through_risk_manager(authed):
    env = authed
    bot = env.ctx.bot
    s = await scan(env)
    await force_good_signal(env)
    await bot.set_enabled(True)
    await bot.try_entries(s)

    pos = (await env.api.get("/api/positions")).json()["items"]
    assert len(pos) == 1 and pos[0]["symbol"] == "AAAUSDT"
    p = pos[0]
    assert p["stop_price"] < p["entry_price"] < p["tp1_price"] < p["tp2_price"]
    assert p["quantity"] * p["entry_price"] <= 1000 * 0.05 + 0.5  # tek coin %5 sınırı

    # mükerrer emir engeli: aynı coine ikinci alım yapılmaz
    await bot.try_entries(s)
    assert len((await env.api.get("/api/positions")).json()["items"]) == 1
    assert any(d["symbol"] == "AAAUSDT" and not d["approved"] and any("mükerrer" in r for r in d["reasons"]) for d in bot.decisions)

    # fiyat 1. hedefe ulaşır -> kademeli satış
    env.ctx.feed.update("AAAUSDT", p["tp1_price"] * 1.001)
    await bot.monitor_once()
    p2 = (await env.api.get("/api/positions")).json()["items"][0]
    assert p2["tp1_done"] and p2["quantity"] == pytest.approx(p["quantity"] * 0.5)

    # fiyat girişe geri düşer -> başa baş/trailing stop; net sonuç kâr olmalı
    env.ctx.feed.update("AAAUSDT", p["entry_price"] * 1.0005)
    await bot.monitor_once()
    assert (await env.api.get("/api/positions")).json()["items"] == []
    tr = (await env.api.get("/api/trades?status=CLOSED")).json()["items"][0]
    assert tr["status"] == "CLOSED" and tr["close_reason"] in ("BREAKEVEN_STOP", "TRAILING_STOP")
    assert tr["realized_pnl"] > 0, "1. hedeften sonra stop başa baş üstünde olmalı"

    rep = (await env.api.get("/api/reports/pnl")).json()
    assert rep["summary"]["trades"] == 1 and rep["summary"]["net_pnl"] == pytest.approx(tr["realized_pnl"])
    orders = (await env.api.get("/api/orders")).json()["items"]
    assert [o["side"] for o in reversed(orders)] == ["BUY", "SELL", "SELL"]
    dash = (await env.api.get("/api/dashboard")).json()
    assert dash["fees_total"] == pytest.approx(sum(o["fee"] for o in orders)) and dash["trades_today"] == 1


async def test_stop_loss_exit_and_daily_loss_limit_blocks_new_buys(authed):
    env = authed
    bot = env.ctx.bot
    s = await scan(env)
    await force_good_signal(env)
    await bot.set_enabled(True)
    await bot.try_entries(s)
    p = (await env.api.get("/api/positions")).json()["items"][0]
    env.ctx.feed.update("AAAUSDT", p["stop_price"] * 0.999)
    await bot.monitor_once()
    tr = (await env.api.get("/api/trades?status=CLOSED")).json()["items"][0]
    assert tr["close_reason"] == "STOP_LOSS" and tr["realized_pnl"] < 0
    # stop kaybı risk bütçesini (%1) aşmamalı
    assert -tr["realized_pnl"] <= 1000 * 0.01 * 1.05

    # Günlük kayıp limiti: gün başı bakiyesini %3 yüksek göster -> yeni alım reddedilmeli
    async with env.ctx.db.session() as ses:
        acc = await env.ctx.service.account()
        from app.trading.service import DAY_KEY, today_str

        await kv_set(ses, DAY_KEY, {"date": today_str(), "start_equity": (acc["cash"]) * 1.03})
        await ses.commit()
    await force_good_signal(env, "CCCUSDT")
    await bot.try_entries(s)
    assert (await env.api.get("/api/positions")).json()["items"] == []
    assert any("Günlük zarar limiti" in " ".join(d["reasons"]) for d in bot.decisions)
    risk = (await env.api.get("/api/risk")).json()
    assert risk["halted_buys"] is True and "Kaldıraç kapalı" in risk["fixed_rules"]


async def test_api_failure_means_no_order(authed):
    env = authed
    s = await scan(env)
    await force_good_signal(env)
    await env.ctx.bot.set_enabled(True)
    env.fake.state.fail_book_ticker = True  # güncel fiyat alınamıyor => belirsiz durum => emir YOK
    env.ctx.client.http  # noqa
    await env.ctx.bot.try_entries(s)
    assert (await env.api.get("/api/positions")).json()["items"] == []
    assert any("Güncel fiyat alınamadı" in " ".join(d["reasons"]) for d in env.ctx.bot.decisions)


async def test_safe_mode_blocks_entries_when_market_data_fails(authed):
    env = authed
    s = await scan(env)
    await force_good_signal(env)
    await env.ctx.bot.set_enabled(True)
    env.ctx.bot.scan_errors = 3
    env.ctx.bot.last_scan_error = "ağ hatası"
    env.ctx.bot._update_safe_mode(False)
    assert env.ctx.bot.safe_reason
    await env.ctx.bot.try_entries(s)
    assert (await env.api.get("/api/positions")).json()["items"] == []
    st = (await env.api.get("/api/status")).json()
    assert st["bot"]["safe_mode"]


async def test_emergency_stop_closes_positions_and_blocks_restart(authed):
    env = authed
    s = await scan(env)
    await force_good_signal(env)
    await env.ctx.bot.set_enabled(True)
    await env.ctx.bot.try_entries(s)
    env.ctx.feed.update("AAAUSDT", (await env.api.get("/api/positions")).json()["items"][0]["entry_price"])
    r = await env.api.post("/api/bot/emergency-stop", json={"close_positions": True})
    assert r.status_code == 200 and r.json()["closed_positions"] == 1 and r.json()["emergency"] and not r.json()["enabled"]
    assert (await env.api.get("/api/positions")).json()["items"] == []
    assert (await env.api.post("/api/bot/start")).status_code == 409
    await env.ctx.bot.try_entries(s)
    assert (await env.api.get("/api/positions")).json()["items"] == []
    assert (await env.api.post("/api/bot/clear-emergency")).status_code == 200
    assert (await env.api.post("/api/bot/start")).status_code == 200


async def test_manual_close_and_position_patch_validation(authed):
    env = authed
    s = await scan(env)
    await force_good_signal(env)
    await env.ctx.bot.set_enabled(True)
    await env.ctx.bot.try_entries(s)
    p = (await env.api.get("/api/positions")).json()["items"][0]
    env.ctx.feed.update("AAAUSDT", p["entry_price"])
    bad = await env.api.patch(f"/api/positions/{p['id']}", json={"stop_price": p["entry_price"] * 1.1})
    assert bad.status_code == 422
    ok = await env.api.patch(f"/api/positions/{p['id']}", json={"tp1_price": p["entry_price"] * 1.02, "tp2_price": p["entry_price"] * 1.05})
    assert ok.status_code == 200
    assert (await env.api.post(f"/api/positions/{p['id']}/close")).status_code == 200
    assert (await env.api.get("/api/trades?status=CLOSED")).json()["items"][0]["close_reason"] == "MANUAL"


# ----------------------------------------------------------------------- ayarlar
async def test_settings_roundtrip_and_validation(authed):
    api = authed.api
    d = (await api.get("/api/settings")).json()
    assert d["values"]["risk_per_trade_pct"] == 1.0 and d["values"]["daily_loss_limit_pct"] == 2.0
    assert d["values"]["max_open_positions"] == 5 and d["values"]["max_symbol_alloc_pct"] == 5.0 and d["values"]["max_total_exposure_pct"] == 20.0
    keys = {m["key"] for m in d["meta"]}
    assert {"risk_per_trade_pct", "tp1_pct", "trailing_enabled", "target_mode"} <= keys
    assert (await api.put("/api/settings", json={"values": {"daily_loss_limit_pct": 1.5}})).status_code == 200
    assert (await api.get("/api/settings")).json()["values"]["daily_loss_limit_pct"] == 1.5
    assert (await api.put("/api/settings", json={"values": {"risk_per_trade_pct": 99}})).status_code == 422
    assert (await api.put("/api/settings", json={"values": {"tp1_rr": 5, "tp2_rr": 2}})).status_code == 422
    assert (await api.post("/api/settings/reset")).json()["values"]["daily_loss_limit_pct"] == 2.0


async def test_paper_reset_requires_confirmation_and_stopped_bot(authed):
    env = authed
    assert (await env.api.post("/api/paper/reset", json={"confirm": False})).status_code == 422
    await env.ctx.bot.set_enabled(True)
    assert (await env.api.post("/api/paper/reset", json={"confirm": True})).status_code == 409
    await env.ctx.bot.set_enabled(False)
    assert (await env.api.post("/api/paper/reset", json={"confirm": True})).status_code == 200


# ----------------------------------------------------------------------- güvenlik: API anahtarları
async def test_api_keys_are_encrypted_masked_and_never_returned_or_logged(authed):
    env = authed
    key, secret = "AKIAFAKEKEY1234567890ABCD", "s3cr3tVALUE-9876543210-zyxwvutsrq"
    r = await env.api.put("/api/connections/testnet", json={"api_key": key, "api_secret": secret})
    assert r.status_code == 200 and secret not in r.text and key not in r.text
    conns = (await env.api.get("/api/connections")).text
    assert secret not in conns and key not in conns and "…" in conns
    j = (await env.api.get("/api/connections")).json()
    assert j["live"]["locked"] is True and j["live"]["configured"] is False and j["market_data"]["needs_key"] is False

    async with env.ctx.db.session() as ses:
        row = await ses.get(ApiCredential, "testnet")
        assert key not in row.api_key_enc and secret not in row.api_secret_enc  # diskte şifreli
        raw = (await ses.execute(text("select api_key_enc || api_secret_enc from api_credentials"))).scalar_one()
        assert secret not in raw
    assert env.ctx.auth.vault.decrypt(row.api_secret_enc) == secret

    import logging

    logging.getLogger("app.test").error("hata: api_secret=%s signature=%s" % (secret, "a" * 64))
    import asyncio

    await asyncio.sleep(1.6)  # günlük yazıcısı
    logs = (await env.api.get("/api/logs?limit=500")).text
    assert secret not in logs and ("a" * 64) not in logs

    assert (await env.api.delete("/api/connections/testnet")).status_code == 200
    assert (await env.api.get("/api/connections")).json()["testnet"]["configured"] is False
    assert (await env.api.put("/api/connections/live", json={"api_key": key, "api_secret": secret})).status_code in (404, 405)


async def test_frontend_never_receives_secret_key_or_password_hash(authed):
    for path in ("/api/status", "/api/dashboard", "/api/settings", "/api/connections"):
        body = (await authed.api.get(path)).text
        assert PASSWORD not in body
        assert authed.ctx.auth.secret not in body
