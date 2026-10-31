"""Portföy, bildirim, coin listeleri ve rapor uçları."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

import math

from ..analysis.engine import TIMEFRAMES
from ..analysis.indicators import compute_indicators
from ..exchange.binance import ExchangeError
from ..logging_setup import register_secret
from ..models import ApiCredential, Notification, PortfolioAction, utcnow
from ..report import build_daily_report
from ..security import mask
from ..trading_settings import PROFILE_LABELS, PROFILES
from .routes import ctx, iso, require_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


# ---------------------------------------------------------------------- portföy
@router.get("/portfolio")
async def portfolio(request: Request):
    c = ctx(request)
    s = await c.store.get()
    views = c.bot.market_views()
    prices = dict(c.feed.prices)
    rows = []
    for h in await c.portfolio.holdings():
        a = c.bot.analyses.get(h.symbol)
        px = prices.get(h.symbol) or (a.price if a and a.price else None)  # canlı akış yoksa son analiz fiyatı
        v = c.portfolio.valuation(h, px, s, views.get(h.symbol))
        v["ai"] = {"score": a.score, "label": a.label, "trend": a.trend, "sell_fit": a.sell_fit, "downside_risk": a.downside_risk} if a and a.eligible else None
        rows.append(v)
    total_value = sum(r["value"] for r in rows)
    known = [r for r in rows if r["invested"] is not None and r["unrealized_pnl"] is not None]
    async with c.db.session() as ses:
        acts = list((await ses.execute(select(PortfolioAction).order_by(PortfolioAction.id.desc()).limit(20))).scalars())
    return {
        "mode": s.portfolio_mode, "items": rows,
        "totals": {"value": total_value, "invested": sum(r["invested"] for r in known), "unrealized_pnl": sum(r["unrealized_pnl"] for r in known),
                   "realized_pnl": sum(r["realized_pnl"] for r in rows), "unknown_cost": sum(1 for r in rows if not r["cost_known"])},
        "actions": [{"id": a.id, "ts": iso(a.ts), "asset": a.asset, "action": a.action, "mode": a.mode, "quantity": a.quantity,
                     "price": a.price, "net_pnl": a.net_pnl, "reason": a.reason} for a in acts],
        "note": "Mevcut coinleriniz paper hesabından ayrı izlenir. Gerçek hesabınızda hiçbir emir gönderilmez; 'yönet' modu gölge (sanal) uygulama yapar.",
    }


class HoldingBody(BaseModel):
    asset: str = Field(min_length=2, max_length=12, pattern=r"^[A-Za-z0-9]+$")
    quantity: float = Field(gt=0)
    avg_cost: float = Field(ge=0, description="USDT cinsinden ortalama alış maliyeti; 0 = bilinmiyor")
    note: str = Field(default="", max_length=200)


@router.post("/portfolio/holdings")
async def add_holding(body: HoldingBody, request: Request):
    c = ctx(request)
    sym = body.asset.upper() + "USDT"
    if c.bot.symbols and sym not in c.bot.symbols:
        raise HTTPException(422, f"{sym} Binance'te bulunamadı (yalnızca USDT pariteleri desteklenir).")
    h = await c.portfolio.upsert_manual(body.asset, body.quantity, body.avg_cost, body.note)
    return {"ok": True, "asset": h.asset}


class ManagedBody(BaseModel):
    managed: bool


@router.patch("/portfolio/holdings/{asset}")
async def set_managed(asset: str, body: ManagedBody, request: Request):
    if not await ctx(request).portfolio.set_managed(asset, body.managed):
        raise HTTPException(404, "Coin bulunamadı.")
    return {"ok": True}


@router.delete("/portfolio/holdings/{asset}")
async def delete_holding(asset: str, request: Request):
    await ctx(request).portfolio.delete(asset)
    return {"ok": True}


@router.post("/portfolio/sync")
async def sync_portfolio(request: Request):
    """Binance hesabını SALT OKUNUR anahtarla okur (bakiyeler + geçmiş alımlar). Emir göndermez."""
    c = ctx(request)
    async with c.db.session() as ses:
        row = await ses.get(ApiCredential, "readonly")
    if not row:
        raise HTTPException(404, "Önce 'API Bağlantıları' ekranından salt okunur Binance anahtarını kaydedin.")
    client = c.make_client(c.auth.vault.decrypt(row.api_key_enc), c.auth.vault.decrypt(row.api_secret_enc))
    try:
        symbols = c.bot.symbols or await c.client.exchange_info()
        prices = await c.client.prices()
        return await c.portfolio.sync_from_binance(client, symbols, prices)
    except ExchangeError as e:
        raise HTTPException(502, f"Binance hesabı okunamadı: {e}")
    finally:
        await client.aclose()


# ---------------------------------------------------------------------- salt okunur anahtar
class KeyBody(BaseModel):
    api_key: str
    api_secret: str


@router.put("/connections/readonly")
async def save_readonly(body: KeyBody, request: Request):
    c = ctx(request)
    key, secret = body.api_key.strip(), body.api_secret.strip()
    if len(key) < 16 or len(secret) < 16 or " " in key or " " in secret:
        raise HTTPException(422, "Anahtar biçimi geçersiz görünüyor.")
    register_secret(key)
    register_secret(secret)
    async with c.db.session() as ses:
        row = await ses.get(ApiCredential, "readonly")
        ek, es = c.auth.vault.encrypt(key), c.auth.vault.encrypt(secret)
        if row:
            row.api_key_enc, row.api_secret_enc, row.key_hint, row.updated_at = ek, es, mask(key), utcnow()
        else:
            ses.add(ApiCredential(env="readonly", api_key_enc=ek, api_secret_enc=es, key_hint=mask(key)))
        await ses.commit()
    return {"ok": True, "key_hint": mask(key)}


@router.delete("/connections/readonly")
async def delete_readonly(request: Request):
    async with ctx(request).db.session() as ses:
        row = await ses.get(ApiCredential, "readonly")
        if row:
            await ses.delete(row)
            await ses.commit()
    return {"ok": True}


@router.post("/connections/readonly/test")
async def test_readonly(request: Request):
    c = ctx(request)
    async with c.db.session() as ses:
        row = await ses.get(ApiCredential, "readonly")
    if not row:
        raise HTTPException(404, "Önce anahtarı kaydedin.")
    client = c.make_client(c.auth.vault.decrypt(row.api_key_enc), c.auth.vault.decrypt(row.api_secret_enc))
    try:
        acc = await client.account()
    except ExchangeError as e:
        raise HTTPException(502, f"Binance bağlantısı başarısız: {e}")
    finally:
        await client.aclose()
    can_withdraw, can_trade = bool(acc.get("canWithdraw")), bool(acc.get("canTrade"))
    warnings = []
    if can_withdraw:
        warnings.append("Bu anahtarda PARA ÇEKME yetkisi açık! Sistem buna ihtiyaç duymaz; Binance'ten kapatın.")
    if can_trade:
        warnings.append("Bu anahtarda alım-satım yetkisi açık. Salt okunur (yalnızca 'Enable Reading') anahtar kullanmanız önerilir.")
    return {"ok": True, "can_withdraw": can_withdraw, "can_trade": can_trade, "permissions": acc.get("permissions", []), "warnings": warnings}


# ---------------------------------------------------------------------- bildirimler
@router.get("/notifications")
async def notifications(request: Request, limit: int = 60):
    c = ctx(request)
    async with c.db.session() as ses:
        rows = list((await ses.execute(select(Notification).order_by(Notification.id.desc()).limit(max(1, min(limit, 300))))).scalars())
        unread = (await ses.execute(select(func.count(Notification.id)).where(Notification.read.is_(False)))).scalar_one()
    return {"unread": unread, "telegram": c.notifier.telegram_enabled,
            "items": [{"id": n.id, "ts": iso(n.ts), "kind": n.kind, "level": n.level, "title": n.title, "body": n.body, "read": n.read} for n in rows]}


@router.post("/notifications/read-all")
async def read_all(request: Request):
    async with ctx(request).db.session() as ses:
        await ses.execute(update(Notification).values(read=True))
        await ses.commit()
    return {"ok": True}


# ---------------------------------------------------------------------- takip / hariç listesi
class ListsBody(BaseModel):
    watch: list[str] = []
    exclude: list[str] = []


@router.get("/coin-lists")
async def get_lists(request: Request):
    return await ctx(request).bot.coin_lists()


@router.put("/coin-lists")
async def put_lists(body: ListsBody, request: Request):
    return await ctx(request).bot.save_coin_lists(body.watch, body.exclude)


# ---------------------------------------------------------------------- risk profili / rapor / rejim
class ProfileBody(BaseModel):
    profile: str


@router.get("/settings/profiles")
async def profiles():
    return {"profiles": [{"id": k, "label": PROFILE_LABELS[k], "values": v} for k, v in PROFILES.items()]}


@router.post("/settings/profile")
async def apply_profile(body: ProfileBody, request: Request):
    try:
        s = await ctx(request).store.apply_profile(body.profile)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"values": s.model_dump()}


@router.get("/reports/daily")
async def daily_report(request: Request):
    c = ctx(request)
    title, body = await build_daily_report(c.db, c.service, c.bot.price_map())
    return {"title": title, "body": body}


@router.get("/market/regime")
async def regime(request: Request):
    b = ctx(request).bot
    return {"regime": b.regime.to_dict() if b.regime else None, "shock_active": b.shock_active}


# ---------------------------------------------------------------------- fiyat grafiği
def _clean(arr) -> list:
    return [None if (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else float(x) for x in arr]


@router.get("/market/{symbol}/chart")
async def chart(symbol: str, request: Request, tf: str = "1h", limit: int = 120):
    """Mum + EMA/Bollinger verisi ve AI plan seviyeleri (grafik ekranı için). Oluşmakta olan son mum dahildir."""
    c = ctx(request)
    sym = symbol.upper()
    if tf not in TIMEFRAMES:
        raise HTTPException(422, f"Zaman dilimi şunlardan biri olmalı: {', '.join(TIMEFRAMES)}")
    if c.bot.symbols and sym not in c.bot.symbols:
        raise HTTPException(404, "Coin bulunamadı.")
    try:
        candles = (await c.bot.get_candles(sym))[tf]
    except ExchangeError as e:
        raise HTTPException(502, f"Mum verisi alınamadı: {e}")
    ind = compute_indicators(candles)
    n = max(20, min(limit, len(candles), 300))
    sl = slice(len(candles) - n, None)
    a = c.bot.analyses.get(sym)
    levels = {}
    if a and a.eligible:
        levels = {"entry": a.entry, "stop": a.stop, "tp1": a.tp1, "tp2": a.tp2}
        s1h = a.tf.get("1h", {})
        levels["support"], levels["resistance"] = s1h.get("support"), s1h.get("resistance")
    return {
        "symbol": sym, "tf": tf,
        "t": [int(x) for x in candles.open_time[sl]],
        "o": _clean(candles.open[sl]), "h": _clean(candles.high[sl]), "l": _clean(candles.low[sl]), "c": _clean(candles.close[sl]),
        "v": _clean(candles.volume[sl]),
        "ema21": _clean(ind.ema21[sl]), "ema50": _clean(ind.ema50[sl]), "bb_up": _clean(ind.bb_up[sl]), "bb_low": _clean(ind.bb_low[sl]),
        "levels": levels,
    }
