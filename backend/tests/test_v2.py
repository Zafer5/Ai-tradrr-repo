import asyncio
import time

import pytest

from app.analysis.regime import evaluate_regime
from app.risk.manager import AccountSnapshot, EntryRequest, SystemFlags, evaluate_entry
from app.trading_settings import PROFILES, TradingSettings
from tests.conftest import FAKE_KEY, FAKE_SECRET
from tests.synth import make_multi_tf

S = TradingSettings()


def base_req(**kw):
    d = dict(symbol="ABCUSDT", score=90, risk_level="Düşük", eligible=True, spread_pct=0.02, change_pct=3.0, entry=100.0, stop=98.0, tp1=104.0, tp2=108.0)
    d.update(kw)
    return EntryRequest(**d)


ACCT = AccountSnapshot(1000.0, 1000.0, {}, 0.0, 0)


# ---------------------------------------------------------------- risk: kovalama + şok + zayıf piyasa
def test_does_not_chase_coins_that_already_pumped():
    d = evaluate_entry(base_req(change_pct=16.0), ACCT, SystemFlags(), S)
    assert not d.approved and any("peşinden koşulmaz" in r for r in d.reasons)
    assert evaluate_entry(base_req(change_pct=14.0), ACCT, SystemFlags(), S).approved


def test_market_shock_blocks_and_weak_btc_raises_threshold():
    d = evaluate_entry(base_req(), ACCT, SystemFlags(market_shock_reason="BTC -3%"), S)
    assert not d.approved and any("Ani düşüş koruması" in r for r in d.reasons)
    assert evaluate_entry(base_req(score=75), ACCT, SystemFlags(), S).approved
    d2 = evaluate_entry(base_req(score=75), ACCT, SystemFlags(extra_threshold=10), S)
    assert not d2.approved and any("zayıf piyasa" in r for r in d2.reasons)


def test_regime_detects_btc_shock_and_direction():
    now = 1_700_000_000_000 // 14_400_000 * 14_400_000
    calm = make_multi_tf(days=60, drift_per_hour=0.0003, vol_per_sqrt_hour=0.002, seed=3)
    r = evaluate_regime(calm, now + 1, 2.5)
    assert not r.shock and r.direction in ("Yükseliş", "Yatay", "Düşüş")
    crash = make_multi_tf(days=60, drift_per_hour=0.0003, vol_per_sqrt_hour=0.002, seed=3)
    c5 = crash["5m"]
    c5.close = c5.close.copy()
    c5.close[-12:] = c5.close[-13] * (1 - 0.035 * (1 + __import__("numpy").arange(12)) / 12)  # son saatte %3.5 düşüş
    r2 = evaluate_regime(crash, now + 1, 2.5)
    assert r2.shock and "BTC" in r2.shock_reason


# ---------------------------------------------------------------- profiller
def test_profiles_are_valid_and_ordered_by_risk():
    for v in PROFILES.values():
        TradingSettings(**v)
    assert PROFILES["dusuk"]["risk_per_trade_pct"] < PROFILES["dengeli"]["risk_per_trade_pct"] < PROFILES["yuksek"]["risk_per_trade_pct"]
    assert PROFILES["dengeli"]["risk_per_trade_pct"] == 1.0 and PROFILES["dengeli"]["daily_loss_limit_pct"] == 2.0 and PROFILES["dengeli"]["max_open_positions"] == 5


async def test_profile_api_and_custom_detection(authed):
    api = authed.api
    r = await api.post("/api/settings/profile", json={"profile": "dusuk"})
    assert r.json()["values"]["risk_profile"] == "dusuk" and r.json()["values"]["daily_loss_limit_pct"] == 1.0
    r = await api.put("/api/settings", json={"values": {"daily_loss_limit_pct": 1.7}})
    assert r.json()["values"]["risk_profile"] == "ozel"
    r = await api.post("/api/settings/profile", json={"profile": "dengeli"})
    assert r.json()["values"]["max_open_positions"] == 5
    assert (await api.post("/api/settings/profile", json={"profile": "kumarbaz"})).status_code == 422
    # hiçbir profil kaldıraç/vadeli açmaz: ayar alanı bile yoktur
    assert not any("leverage" in k or "futures" in k for k in r.json()["values"])


# ---------------------------------------------------------------- portföy
async def scan(env):
    s = await env.ctx.store.get()
    await env.ctx.bot.scan_cycle(s)
    return s


async def test_manual_holding_valuation_and_watch_recommendation(authed):
    env, api = authed, authed.api
    r = await api.post("/api/portfolio/holdings", json={"asset": "aaa", "quantity": 10, "avg_cost": 40.0})
    assert r.status_code == 200
    assert (await api.post("/api/portfolio/holdings", json={"asset": "NOPE", "quantity": 1, "avg_cost": 1})).status_code in (200, 422)
    await scan(env)  # portföydeki coin tarayıcı dışında kalsa da analiz edilir
    p = (await api.get("/api/portfolio")).json()
    h = next(x for x in p["items"] if x["asset"] == "AAA")
    assert h["invested"] == pytest.approx(400.0) and h["cost_known"] and h["avg_cost"] == 40.0
    # fiyat %20 yukarı: hedef kâr oluşur -> öneri (watch) + bildirim; gerçek emir yok
    env.ctx.feed.update("AAAUSDT", 48.0)
    s = await env.ctx.store.get()
    ev = await env.ctx.portfolio.evaluate_all({"AAAUSDT": 48.0}, {"AAAUSDT": __import__("app.portfolio.manager", fromlist=["MarketView"]).MarketView(score=50, sell_fit=70, trend="Yatay")}, s)
    assert ev and ev[0]["mode"] == "oneri"
    p = (await api.get("/api/portfolio")).json()
    assert p["actions"][0]["mode"] == "oneri" and p["actions"][0]["action"] == "TAKE_PROFIT"
    assert next(x for x in p["items"] if x["asset"] == "AAA")["quantity"] == 10  # öneri modunda miktar değişmez
    n = (await api.get("/api/notifications")).json()
    assert n["unread"] >= 1 and any("ÖNERİ" in x["title"] and "Gerçek hesabınızda emir gönderilmedi" in x["body"] for x in n["items"])
    assert (await api.post("/api/notifications/read-all")).status_code == 200
    assert (await api.get("/api/notifications")).json()["unread"] == 0


async def test_manage_mode_is_shadow_only_and_updates_virtual_holding(authed):
    env, api = authed, authed.api
    await api.put("/api/settings", json={"values": {"portfolio_mode": "manage"}})
    await api.post("/api/portfolio/holdings", json={"asset": "AAA", "quantity": 10, "avg_cost": 40.0})
    s = await env.ctx.store.get()
    from app.portfolio.manager import MarketView

    ev = await env.ctx.portfolio.evaluate_all({"AAAUSDT": 48.0}, {"AAAUSDT": MarketView(score=50, sell_fit=70, trend="Yatay")}, s)
    assert ev[0]["mode"] == "golge"
    h = next(x for x in (await api.get("/api/portfolio")).json()["items"] if x["asset"] == "AAA")
    assert h["quantity"] == pytest.approx(5.0) and h["realized_pnl"] > 0
    # paper nakit hesabı etkilenmedi
    assert (await env.ctx.service.account())["cash"] == 1000


async def test_excluded_holding_is_not_managed_and_held_symbols_are_not_bought(authed):
    env, api = authed, authed.api
    await api.post("/api/portfolio/holdings", json={"asset": "AAA", "quantity": 10, "avg_cost": 40.0})
    assert (await api.patch("/api/portfolio/holdings/AAA", json={"managed": False})).status_code == 200
    s = await env.ctx.store.get()
    from app.portfolio.manager import MarketView

    assert await env.ctx.portfolio.evaluate_all({"AAAUSDT": 80.0}, {"AAAUSDT": MarketView(score=50, sell_fit=70)}, s) == []
    # portföydeki coin için yeni alım yapılmaz
    await scan(env)
    a = env.ctx.bot.analyses["AAAUSDT"]
    assert a.held
    a.score, a.risk = 95.0, "Düşük"
    await env.ctx.bot.set_enabled(True)
    await env.ctx.bot.try_entries(s)
    assert (await api.get("/api/positions")).json()["items"] == []
    assert any(d["symbol"] == "AAAUSDT" and "portföyünüzde" in " ".join(d["reasons"]) for d in env.ctx.bot.decisions)


async def test_user_exclude_and_watch_lists(authed):
    env, api = authed, authed.api
    r = await api.put("/api/coin-lists", json={"watch": ["wideusdt"], "exclude": ["CCCUSDT"]})
    assert r.json() == {"watch": ["WIDEUSDT"], "exclude": ["CCCUSDT"]}
    await scan(env)
    syms = {c["symbol"] for c in (await api.get("/api/scanner")).json()["candidates"]}
    assert "CCCUSDT" not in syms
    assert "WIDEUSDT" in env.ctx.bot.analyses  # takip listesi: tarayıcı elese bile analiz edilir


async def test_readonly_sync_reads_balances_and_cost_basis_and_never_trades(authed):
    env, api = authed, authed.api
    await env.ctx.bot.scan_cycle(await env.ctx.store.get())
    assert (await api.post("/api/portfolio/sync")).status_code == 404  # anahtar yok
    assert (await api.put("/api/connections/readonly", json={"api_key": FAKE_KEY, "api_secret": FAKE_SECRET})).status_code == 200
    t = (await api.post("/api/connections/readonly/test")).json()
    assert t["ok"] and not t["can_withdraw"]
    rep = (await api.post("/api/portfolio/sync")).json()
    assert rep["found"] == 2 and rep["cost_ok"] == 1 and rep["cost_missing"] == ["BBB"] and "NOPAIR" in rep["skipped"]
    items = {x["asset"]: x for x in (await api.get("/api/portfolio")).json()["items"]}
    assert items["AAA"]["avg_cost"] == pytest.approx(40.0) and items["AAA"]["source"] == "binance"
    assert items["BBB"]["cost_known"] is False and items["BBB"]["avg_cost"] is None
    assert "elle" in items["BBB"]["decision_text"]
    # eksik maliyeti elle tamamla
    await api.post("/api/portfolio/holdings", json={"asset": "BBB", "quantity": 50, "avg_cost": 25.0})
    assert next(x for x in (await api.get("/api/portfolio")).json()["items"] if x["asset"] == "BBB")["cost_known"]
    # hiçbir emir ucu çağrılmadı
    assert not any("/order" in p for p in env.fake.state.request_log)


async def test_wrong_secret_is_rejected_by_exchange_signature_check(authed):
    api = authed.api
    await api.put("/api/connections/readonly", json={"api_key": FAKE_KEY, "api_secret": "WRONGSECRET1234567890ABCDEFG"})
    r = await api.post("/api/connections/readonly/test")
    assert r.status_code == 502 and "Signature" in r.text


async def test_buy_creates_explained_notification_and_daily_report(authed):
    env, api = authed, authed.api
    s = await scan(env)
    a = env.ctx.bot.analyses["AAAUSDT"]
    a.score, a.risk = 90.0, "Düşük"
    a.change_pct = 3.0
    await env.ctx.bot.set_enabled(True)
    await env.ctx.bot.try_entries(s)
    n = (await api.get("/api/notifications")).json()["items"]
    buy = next(x for x in n if x["kind"] == "buy")
    assert "ALIM" in buy["title"] and "Neden" in buy["body"] and "Stop" in buy["body"]
    rep = (await api.get("/api/reports/daily")).json()
    assert "Özkaynak" in rep["body"] and "Bugün açılan: 1" in rep["body"]


async def test_telegram_message_is_sent_without_leaking_token(env):
    import httpx

    sent = []

    def handler(req: httpx.Request):
        sent.append((str(req.url), req.content))
        return httpx.Response(200, json={"ok": True})

    from app.notify import Notifier

    n = Notifier(env.ctx.db, "123456:SECRETTOKEN-abcdefghij", "999", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await n.send("t", "Başlık", "Gövde", "info")
    assert len(sent) == 1 and "Gövde" in sent[0][1].decode() and "999" in sent[0][1].decode()
    # tekrar önleme
    assert await n.send("t", "x", "", dedupe_key="k", dedupe_sec=60) and not await n.send("t", "x", "", dedupe_key="k", dedupe_sec=60)
    from app.logging_setup import redact

    assert "SECRETTOKEN" not in redact("hata https://api.telegram.org/bot123456:SECRETTOKEN-abcdefghij/sendMessage")


async def test_regression_manage_mode_does_not_repeat_partial_sales(authed):
    """Canlı döngüde bulunan hata: hedefte kısmi satış her 10 sn tekrarlanıp pozisyonu eritiyordu."""
    env, api = authed, authed.api
    await api.put("/api/settings", json={"values": {"portfolio_mode": "manage"}})
    await api.post("/api/portfolio/holdings", json={"asset": "AAA", "quantity": 10, "avg_cost": 40.0})
    s = await env.ctx.store.get()
    from app.portfolio.manager import MarketView

    mv = {"AAAUSDT": MarketView(score=50, sell_fit=70, trend="Yatay")}
    env.ctx.feed.update("AAAUSDT", 48.0)
    for _ in range(5):  # 5 değerlendirme turu (her tur ~10 sn)
        await env.ctx.portfolio.evaluate_all({"AAAUSDT": 48.0}, mv, s)
    h = next(x for x in (await api.get("/api/portfolio")).json()["items"] if x["asset"] == "AAA")
    assert h["quantity"] == pytest.approx(5.0)  # yalnızca BİR kez %50 satıldı
    assert h["trailing_active"] is True
    acts = (await api.get("/api/portfolio")).json()["actions"]
    assert sum(1 for a in acts if a["action"] == "TAKE_PROFIT") == 1
    assert "kısmi satış yapıldı" in h["decision_text"]
    # fiyat zirveden geri çekilince kalan miktar trailing stop ile (kârda) çıkar
    await env.ctx.portfolio.evaluate_all({"AAAUSDT": 52.0}, mv, s)  # yeni zirve
    await env.ctx.portfolio.evaluate_all({"AAAUSDT": 50.0}, mv, s)  # %3.8 geri çekilme > %1.5 mesafe
    p = (await api.get("/api/portfolio")).json()
    assert all(x["asset"] != "AAA" for x in p["items"])  # tamamen çıkıldı: listeden kalkar
    assert p["actions"][0]["action"] == "TRAIL_EXIT" and p["actions"][0]["net_pnl"] > 0
