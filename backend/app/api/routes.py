"""Panelin kullandığı REST uçları. Giriş hariç hepsi oturum (çerez) gerektirir."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from ..exchange.binance import BinanceClient, ExchangeError
from ..logging_setup import register_secret
from ..models import AnalysisLog, ApiCredential, EquitySnapshot, LogEntry, Order, Position, utcnow
from ..security import create_token, mask, verify_token
from ..trading.exits import REASON_TR
from ..trading.service import TZ, as_utc, day_start_utc
from ..trading_settings import settings_meta

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------- yardımcılar
def ctx(request: Request):
    return request.app.state.ctx


def require_auth(request: Request):
    c = ctx(request)
    token = request.cookies.get("session")
    if not token:
        h = request.headers.get("authorization", "")
        token = h[7:] if h.lower().startswith("bearer ") else None
    if not token or not verify_token(c.auth.secret, token):
        raise HTTPException(401, "Oturum gerekli. Lütfen giriş yapın.")


def iso(dt: datetime | None) -> str | None:
    d = as_utc(dt)
    return d.isoformat() if d else None


def pos_dict(p: Position, price: float | None, s) -> dict:
    fee, slip = s.fee_rate_pct / 100, s.slippage_pct / 100
    cur = price or p.entry_price
    unreal = unreal_pct = 0.0
    if p.status == "OPEN":
        remaining_cost = p.cost_total * (p.quantity / p.initial_quantity)
        unreal = p.quantity * cur * (1 - fee) * (1 - slip) - remaining_cost  # şimdi piyasa emriyle satılsa net
        unreal_pct = unreal / remaining_cost * 100 if remaining_cost else 0.0
    return {
        "id": p.id, "symbol": p.symbol, "mode": p.mode, "status": p.status,
        "entry_price": p.entry_price, "current_price": cur if p.status == "OPEN" else None,
        "quantity": p.quantity, "initial_quantity": p.initial_quantity,
        "stop_price": p.stop_price, "tp1_price": p.tp1_price, "tp2_price": p.tp2_price,
        "tp1_done": p.tp1_done, "trailing_active": p.trailing_active, "peak_price": p.peak_price,
        "value": p.quantity * cur if p.status == "OPEN" else 0.0,
        "unrealized_pnl": unreal, "unrealized_pct": unreal_pct,
        "realized_pnl": p.realized_pnl, "est_fees": p.est_fees, "fees_total": p.fees_total,
        "score": p.score, "risk_level": p.risk_level, "rationale": p.rationale,
        "opened_at": iso(p.opened_at), "closed_at": iso(p.closed_at),
        "close_reason": p.close_reason, "close_reason_tr": REASON_TR.get(p.close_reason or "", p.close_reason),
        "cost_total": p.cost_total, "proceeds_total": p.proceeds_total,
    }


async def account_summary(c) -> dict:
    prices = c.bot.price_map()
    equity, cash, open_value = await c.service.equity(prices)
    acc = await c.service.account()
    start = await c.service.roll_day(equity)
    return {
        "equity": equity, "cash": cash, "open_value": open_value, "initial": acc["initial"],
        "total_pnl": equity - acc["initial"], "total_pnl_pct": (equity - acc["initial"]) / acc["initial"] * 100,
        "day_start_equity": start, "day_pnl": equity - start, "day_pnl_pct": (equity - start) / start * 100 if start else 0.0,
        "currency": "USDT",
    }


# ---------------------------------------------------------------------- giriş / çıkış
class LoginBody(BaseModel):
    password: str


@router.get("/health")
async def health():
    return {"ok": True}


@router.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response):
    c = ctx(request)
    who = request.client.host if request.client else "?"
    wait = c.auth.gate.locked_for(who)
    if wait:
        raise HTTPException(429, f"Çok fazla hatalı deneme. {wait} sn sonra tekrar deneyin.")
    if not c.auth.gate.verify(body.password):
        c.auth.gate.register_failure(who)
        raise HTTPException(401, "Şifre hatalı.")
    c.auth.gate.register_success(who)
    response.set_cookie("session", create_token(c.auth.secret, c.auth.hours), httponly=True, samesite="strict",
                        secure=c.auth.cookie_secure, max_age=c.auth.hours * 3600, path="/")
    return {"ok": True}


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("session", path="/")
    return {"ok": True}


@router.get("/auth/me")
async def me(request: Request):
    try:
        require_auth(request)
        return {"authenticated": True}
    except HTTPException:
        return {"authenticated": False}


# ---------------------------------------------------------------------- durum / özet
def _bot_status(c) -> dict:
    b = c.bot
    return {
        "enabled": b.enabled, "emergency": b.emergency, "emergency_reason": b.emergency_reason,
        "safe_mode": b.safe_reason, "mode": c.service.mode, "mode_label": c.service.mode_label,
        "live_available": c.cfg.allow_live_trading, "halt": b.halt_reason,
    }


def _market_status(c) -> dict:
    b, f = c.bot, c.feed
    return {
        "ws_connected": f.ws_connected, "feed_age_sec": None if f.age == float("inf") else round(f.age, 1),
        "ws_reconnects": f.ws_reconnects, "feed_error": f.last_error,
        "last_scan_age_sec": round(time.time() - b.last_scan_ok_at, 1) if b.last_scan_ok_at else None,
        "scan_error": b.last_scan_error, "scan_errors": b.scan_errors, "scan_duration_sec": round(b.scan_duration, 1),
        "binance_error": c.client.last_error, "used_weight_1m": c.client.used_weight_1m,
        "tracked": len(b.scan_result.candidates) if b.scan_result else 0,
        "regime": b.regime.to_dict() if b.regime else None, "shock_active": b.shock_active,
    }


@router.get("/status", dependencies=[Depends(require_auth)])
async def status(request: Request):
    c = ctx(request)
    return {"bot": _bot_status(c), "market": _market_status(c), "account": await account_summary(c)}


@router.get("/dashboard", dependencies=[Depends(require_auth)])
async def dashboard(request: Request):
    c = ctx(request)
    s = await c.store.get()
    prices = c.bot.price_map()
    async with c.db.session() as ses:
        mode = c.service.mode
        open_pos = list((await ses.execute(select(Position).where(Position.status == "OPEN", Position.mode == mode).order_by(Position.id))).scalars())
        recent = list((await ses.execute(select(Position).where(Position.status == "CLOSED", Position.mode == mode).order_by(Position.closed_at.desc()).limit(8))).scalars())
        trades_today = (await ses.execute(select(func.count(Position.id)).where(Position.opened_at >= day_start_utc(), Position.mode == mode))).scalar_one()
        fees_total = (await ses.execute(select(func.coalesce(func.sum(Order.fee), 0.0)).where(Order.mode == mode))).scalar_one()
        today_pos = list((await ses.execute(select(Position).where(Position.closed_at >= day_start_utc(), Position.mode == mode))).scalars())
        snaps = list((await ses.execute(select(EquitySnapshot).where(EquitySnapshot.mode == mode).order_by(EquitySnapshot.id.desc()).limit(240))).scalars())
    realized_today = sum(p.realized_pnl for p in today_pos)
    top = sorted((a for a in c.bot.analyses.values() if a.eligible and not a.held), key=lambda a: -a.score)[:6]
    return {
        "bot": _bot_status(c), "market": _market_status(c), "account": await account_summary(c),
        "open_positions": [pos_dict(p, prices.get(p.symbol), s) for p in open_pos],
        "recent_trades": [pos_dict(p, None, s) for p in recent],
        "trades_today": trades_today, "realized_today": realized_today, "fees_total": fees_total,
        "tracked_coins": len(c.bot.scan_result.candidates) if c.bot.scan_result else 0,
        "top_opportunities": [a.to_dict() for a in top],
        "equity_curve": [{"ts": iso(x.ts), "equity": x.equity} for x in reversed(snaps)],
    }


# ---------------------------------------------------------------------- bot komutları
class EmergencyBody(BaseModel):
    close_positions: bool = False


@router.post("/bot/start", dependencies=[Depends(require_auth)])
async def bot_start(request: Request):
    try:
        await ctx(request).bot.set_enabled(True)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _bot_status(ctx(request))


@router.post("/bot/stop", dependencies=[Depends(require_auth)])
async def bot_stop(request: Request):
    await ctx(request).bot.set_enabled(False)
    return _bot_status(ctx(request))


@router.post("/bot/emergency-stop", dependencies=[Depends(require_auth)])
async def bot_emergency(body: EmergencyBody, request: Request):
    closed = await ctx(request).bot.emergency_stop(body.close_positions)
    return {**_bot_status(ctx(request)), "closed_positions": closed}


@router.post("/bot/clear-emergency", dependencies=[Depends(require_auth)])
async def bot_clear_emergency(request: Request):
    await ctx(request).bot.clear_emergency()
    return _bot_status(ctx(request))


# ---------------------------------------------------------------------- tarayıcı / analiz
@router.get("/scanner", dependencies=[Depends(require_auth)])
async def scanner(request: Request):
    b = ctx(request).bot
    if not b.scan_result:
        return {"ready": False, "error": b.last_scan_error, "candidates": [], "rejected": {}}
    d = b.scan_result.to_dict()
    for cand in d["candidates"]:
        a = b.analyses.get(cand["symbol"])
        cand["score"] = a.score if a and a.eligible else None
        cand["label"] = a.label if a and a.eligible else None
        cand["trend"] = a.trend if a and a.eligible else None
        cand["risk"] = a.risk if a and a.eligible else None
        cand["skip_reason"] = a.skip_reason if a and not a.eligible else None
        cand["tags"] = a.tags if a and a.eligible else []
    return {"ready": True, **d}


@router.get("/analyses", dependencies=[Depends(require_auth)])
async def analyses(request: Request):
    b = ctx(request).bot
    items = sorted(b.analyses.values(), key=lambda a: (not a.eligible, -a.score))
    return {"items": [a.to_dict() for a in items], "decisions": list(b.decisions)[:40],
            "scanned_at": b.last_scan_ok_at or None}


@router.get("/analyses/{symbol}", dependencies=[Depends(require_auth)])
async def analysis_one(symbol: str, request: Request):
    a = ctx(request).bot.analyses.get(symbol.upper())
    if not a:
        raise HTTPException(404, "Bu coin için güncel analiz yok.")
    return a.to_dict()


@router.get("/ai/performance", dependencies=[Depends(require_auth)])
async def ai_performance(request: Request):
    c = ctx(request)
    async with c.db.session() as ses:
        rows = list((await ses.execute(select(AnalysisLog).where(AnalysisLog.ret_1h_pct.is_not(None)))).scalars())
    bands = [("85-100", 85, 101), ("70-84", 70, 85), ("50-69", 50, 70)]
    out = []
    for name, lo, hi in bands:
        grp = [r for r in rows if lo <= r.score < hi]
        r1 = [r.ret_1h_pct for r in grp]
        r4 = [r.ret_4h_pct for r in grp if r.ret_4h_pct is not None]
        out.append({
            "band": name, "n": len(grp),
            "avg_ret_1h": sum(r1) / len(r1) if r1 else None, "hit_rate_1h": sum(1 for x in r1 if x > 0) / len(r1) * 100 if r1 else None,
            "n_4h": len(r4), "avg_ret_4h": sum(r4) / len(r4) if r4 else None,
            "hit_rate_4h": sum(1 for x in r4 if x > 0) / len(r4) * 100 if r4 else None,
        })
    return {"bands": out, "note": "Ölçüm amaçlıdır; sistem bu sonuçlara göre kendi kendine strateji DEĞİŞTİRMEZ. Komisyon dahil değildir."}


# ---------------------------------------------------------------------- pozisyonlar / işlemler
@router.get("/positions", dependencies=[Depends(require_auth)])
async def positions(request: Request):
    c = ctx(request)
    s = await c.store.get()
    prices = c.bot.price_map()
    return {"items": [pos_dict(p, prices.get(p.symbol), s) for p in await c.service.open_positions()]}


@router.post("/positions/{pid}/close", dependencies=[Depends(require_auth)])
async def close_position(pid: int, request: Request):
    try:
        ok = await ctx(request).bot.close_position_manually(pid)
    except ValueError as e:
        raise HTTPException(409, f"Pozisyon kapatılamadı: {e}")
    if not ok:
        raise HTTPException(409, "Pozisyon kapatılamadı (bulunamadı veya güncel fiyat yok).")
    return {"ok": True}


class PositionPatch(BaseModel):
    stop_price: float | None = None
    tp1_price: float | None = None
    tp2_price: float | None = None


@router.patch("/positions/{pid}", dependencies=[Depends(require_auth)])
async def patch_position(pid: int, body: PositionPatch, request: Request):
    """Sabit fiyat hedefi / elle stop güncelleme."""
    c = ctx(request)
    async with c.bot.trade_lock, c.db.session() as ses:
        p = await ses.get(Position, pid)
        if not p or p.status != "OPEN":
            raise HTTPException(404, "Açık pozisyon bulunamadı.")
        stop = body.stop_price if body.stop_price is not None else p.stop_price
        tp1 = body.tp1_price if body.tp1_price is not None else p.tp1_price
        tp2 = body.tp2_price if body.tp2_price is not None else p.tp2_price
        cur = c.feed.get(p.symbol) or p.entry_price
        if not (0 < stop < cur):
            raise HTTPException(422, "Stop fiyatı, güncel fiyatın altında olmalıdır.")
        if not (cur < tp1 < tp2):
            raise HTTPException(422, "Hedefler güncel fiyatın üstünde olmalı ve 2. hedef 1. hedeften büyük olmalıdır.")
        p.stop_price, p.tp1_price, p.tp2_price = stop, tp1, tp2
        await ses.commit()
    return {"ok": True}


@router.get("/trades", dependencies=[Depends(require_auth)])
async def trades(request: Request, limit: int = 100, offset: int = 0, status: str = "all"):
    c = ctx(request)
    s = await c.store.get()
    limit = max(1, min(limit, 500))
    q = select(Position).where(Position.mode == c.service.mode).order_by(Position.id.desc()).limit(limit).offset(offset)
    if status in ("OPEN", "CLOSED"):
        q = q.where(Position.status == status)
    async with c.db.session() as ses:
        rows = list((await ses.execute(q)).scalars())
        total = (await ses.execute(select(func.count(Position.id)).where(Position.mode == c.service.mode))).scalar_one()
    prices = c.bot.price_map()
    return {"items": [pos_dict(p, prices.get(p.symbol), s) for p in rows], "total": total}


@router.get("/orders", dependencies=[Depends(require_auth)])
async def orders(request: Request, limit: int = 100):
    async with ctx(request).db.session() as ses:
        rows = list((await ses.execute(select(Order).where(Order.mode == ctx(request).service.mode).order_by(Order.id.desc()).limit(max(1, min(limit, 500))))).scalars())
    return {"items": [{"id": o.id, "position_id": o.position_id, "symbol": o.symbol, "side": o.side, "type": o.order_type,
                       "quantity": o.quantity, "price": o.price, "fee": o.fee, "reason": o.reason,
                       "reason_tr": "Alım" if o.reason == "ENTRY" else REASON_TR.get(o.reason, o.reason),
                       "created_at": iso(o.created_at)} for o in rows]}


# ---------------------------------------------------------------------- raporlar
@router.get("/reports/pnl", dependencies=[Depends(require_auth)])
async def report_pnl(request: Request):
    c = ctx(request)
    async with c.db.session() as ses:
        closed = list((await ses.execute(select(Position).where(Position.status == "CLOSED", Position.mode == c.service.mode).order_by(Position.closed_at))).scalars())
        fees = (await ses.execute(select(func.coalesce(func.sum(Order.fee), 0.0)).where(Order.mode == c.service.mode))).scalar_one()
        snaps = list((await ses.execute(select(EquitySnapshot.equity).where(EquitySnapshot.mode == c.service.mode).order_by(EquitySnapshot.id).limit(50000))).scalars())
    pnls = [p.realized_pnl for p in closed]
    wins, losses = [x for x in pnls if x > 0], [x for x in pnls if x <= 0]
    gp, gl = sum(wins), -sum(losses)
    daily: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "trades": 0})
    by_reason: dict[str, dict] = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    for p in closed:
        d = as_utc(p.closed_at).astimezone(TZ).strftime("%Y-%m-%d")
        daily[d]["pnl"] += p.realized_pnl
        daily[d]["trades"] += 1
        r = REASON_TR.get(p.close_reason or "", p.close_reason or "?")
        by_reason[r]["n"] += 1
        by_reason[r]["pnl"] += p.realized_pnl
    peak, mdd = 0.0, 0.0
    for e in snaps:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak * 100)
    n = len(pnls)
    return {
        "summary": {
            "trades": n, "wins": len(wins), "losses": len(losses), "win_rate": len(wins) / n * 100 if n else None,
            "net_pnl": sum(pnls), "gross_profit": gp, "gross_loss": gl, "profit_factor": gp / gl if gl > 0 else None,
            "avg_win": gp / len(wins) if wins else None, "avg_loss": -gl / len(losses) if losses else None,
            "expectancy": sum(pnls) / n if n else None, "best": max(pnls) if pnls else None, "worst": min(pnls) if pnls else None,
            "fees_total": fees, "max_drawdown_pct": mdd if snaps else None,
        },
        "daily": [{"date": d, **v} for d, v in sorted(daily.items())],
        "by_reason": [{"reason": k, **v} for k, v in by_reason.items()],
        "note": "Kazanç oranı tek başına başarı göstergesi değildir; net kâr, profit factor ve maksimum düşüşe birlikte bakın.",
    }


# ---------------------------------------------------------------------- ayarlar / risk
class SettingsBody(BaseModel):
    values: dict


@router.get("/settings", dependencies=[Depends(require_auth)])
async def get_settings(request: Request):
    s = await ctx(request).store.get()
    return {"values": s.model_dump(), "meta": settings_meta()}


@router.put("/settings", dependencies=[Depends(require_auth)])
async def put_settings(body: SettingsBody, request: Request):
    try:
        s = await ctx(request).store.update(body.values)
    except ValidationError as e:
        msgs = [f"{'.'.join(map(str, err['loc'])) or 'ayar'}: {err['msg']}" for err in e.errors()]
        raise HTTPException(422, " | ".join(msgs))
    return {"values": s.model_dump()}


@router.post("/settings/reset", dependencies=[Depends(require_auth)])
async def reset_settings(request: Request):
    return {"values": (await ctx(request).store.reset()).model_dump()}


@router.get("/risk", dependencies=[Depends(require_auth)])
async def risk_state(request: Request):
    c = ctx(request)
    s = await c.store.get()
    snap = await c.service.snapshot(c.bot.price_map(), set(), s.cooldown_minutes)
    exposure_pct = snap.exposure / snap.equity * 100 if snap.equity else 0.0
    return {
        "equity": snap.equity, "exposure": snap.exposure, "exposure_pct": exposure_pct,
        "limits": {
            "max_total_exposure_pct": s.max_total_exposure_pct, "daily_loss_limit_pct": s.daily_loss_limit_pct,
            "max_open_positions": s.max_open_positions, "max_trades_per_day": s.max_trades_per_day,
            "risk_per_trade_pct": s.risk_per_trade_pct, "max_symbol_alloc_pct": s.max_symbol_alloc_pct,
        },
        "usage": {"day_pnl_pct": snap.day_pnl_pct, "open_positions": len(snap.open_positions), "trades_today": snap.trades_today},
        "halted_buys": snap.day_pnl_pct <= -s.daily_loss_limit_pct,
        "fixed_rules": ["Kaldıraç kapalı", "Vadeli işlemler kapalı", "Yalnızca Spot, yalnızca alış (long) yönlü",
                        "Gerçek emir için sunucu kilidi + panelde yazılı onay gerekir", "Para çekme yetkisi olan anahtar reddedilir",
                        "Belirsiz API/emir durumunda yeni emir gönderilmez"],
        "safe_mode": c.bot.safe_reason, "emergency": c.bot.emergency,
    }


class ResetBody(BaseModel):
    confirm: bool = False


@router.post("/paper/reset", dependencies=[Depends(require_auth)])
async def paper_reset(body: ResetBody, request: Request):
    c = ctx(request)
    if not body.confirm:
        raise HTTPException(422, "Onay gerekli.")
    if c.service.is_exchange:
        raise HTTPException(409, "Sanal hesap yalnızca SANAL modda sıfırlanabilir.")
    if c.bot.enabled:
        raise HTTPException(409, "Önce botu durdurun.")
    await c.service.reset_account(await c.store.get())
    return {"ok": True}


# ---------------------------------------------------------------------- API bağlantıları
class KeyBody(BaseModel):
    api_key: str
    api_secret: str


@router.get("/connections", dependencies=[Depends(require_auth)])
async def connections(request: Request):
    c = ctx(request)
    async with c.db.session() as ses:
        creds = {r.env: r for r in (await ses.execute(select(ApiCredential))).scalars()}
    t = creds.get("testnet")
    ro = creds.get("readonly")
    return {
        "readonly": {"configured": bool(ro), "key_hint": ro.key_hint if ro else None, "updated_at": iso(ro.updated_at) if ro else None},
        "telegram": c.notifier.telegram_enabled,
        "market_data": {"base_url": c.cfg.binance_rest_url, "ws_connected": c.feed.ws_connected,
                        "last_error": c.client.last_error, "needs_key": False},
        "testnet": {"configured": bool(t), "key_hint": t.key_hint if t else None, "updated_at": iso(t.updated_at) if t else None,
                    "stage": "Aşama 2: anahtar kaydı ve bağlantı testi hazır; Testnet ile otomatik emir bu sürümde henüz bağlı değil."},
        "live": {"configured": bool(creds.get("live")), "key_hint": creds["live"].key_hint if creds.get("live") else None,
                 "updated_at": iso(creds["live"].updated_at) if creds.get("live") else None,
                 "server_allowed": c.cfg.allow_live_trading, "active": c.service.mode == "live"},
    }


@router.put("/connections/testnet", dependencies=[Depends(require_auth)])
async def save_testnet(body: KeyBody, request: Request):
    c = ctx(request)
    key, secret = body.api_key.strip(), body.api_secret.strip()
    if len(key) < 16 or len(secret) < 16 or " " in key or " " in secret:
        raise HTTPException(422, "Anahtar biçimi geçersiz görünüyor.")
    register_secret(key)
    register_secret(secret)
    async with c.db.session() as ses:
        row = await ses.get(ApiCredential, "testnet")
        enc_k, enc_s = c.auth.vault.encrypt(key), c.auth.vault.encrypt(secret)
        if row:
            row.api_key_enc, row.api_secret_enc, row.key_hint, row.updated_at = enc_k, enc_s, mask(key), utcnow()
        else:
            ses.add(ApiCredential(env="testnet", api_key_enc=enc_k, api_secret_enc=enc_s, key_hint=mask(key)))
        await ses.commit()
    return {"ok": True, "key_hint": mask(key)}


@router.delete("/connections/testnet", dependencies=[Depends(require_auth)])
async def delete_testnet(request: Request):
    async with ctx(request).db.session() as ses:
        row = await ses.get(ApiCredential, "testnet")
        if row:
            await ses.delete(row)
            await ses.commit()
    return {"ok": True}


@router.post("/connections/testnet/test", dependencies=[Depends(require_auth)])
async def test_testnet(request: Request):
    c = ctx(request)
    async with c.db.session() as ses:
        row = await ses.get(ApiCredential, "testnet")
    if not row:
        raise HTTPException(404, "Önce Testnet anahtarlarını kaydedin.")
    try:
        client = c.make_client(c.auth.vault.decrypt(row.api_key_enc), c.auth.vault.decrypt(row.api_secret_enc), c.cfg.binance_testnet_rest_url)
    except ValueError as e:
        raise HTTPException(500, str(e))
    try:
        acc = await client.account()
    except ExchangeError as e:
        raise HTTPException(502, f"Testnet bağlantısı başarısız: {e}")
    finally:
        await client.aclose()
    can_withdraw = bool(acc.get("canWithdraw"))
    return {
        "ok": True, "can_trade": bool(acc.get("canTrade")), "can_withdraw": can_withdraw,
        "permissions": acc.get("permissions", []),
        "warning": "Bu anahtarda PARA ÇEKME yetkisi açık görünüyor. Bu sistem para çekme yetkisi gerektirmez; Binance'ten kapatın." if can_withdraw else None,
    }


# ---------------------------------------------------------------------- günlükler
@router.get("/logs", dependencies=[Depends(require_auth)])
async def logs(request: Request, level: str | None = None, limit: int = 200, q: str | None = None):
    qry = select(LogEntry).order_by(LogEntry.id.desc()).limit(max(1, min(limit, 1000)))
    if level and level.upper() in ("INFO", "WARNING", "ERROR", "CRITICAL"):
        levels = {"INFO": ["INFO", "WARNING", "ERROR", "CRITICAL"], "WARNING": ["WARNING", "ERROR", "CRITICAL"], "ERROR": ["ERROR", "CRITICAL"], "CRITICAL": ["CRITICAL"]}[level.upper()]
        qry = qry.where(LogEntry.level.in_(levels))
    if q:
        qry = qry.where(LogEntry.message.ilike(f"%{q[:80]}%"))
    async with ctx(request).db.session() as ses:
        rows = list((await ses.execute(qry)).scalars())
    return {"items": [{"id": r.id, "ts": iso(r.ts), "level": r.level, "source": r.source, "message": r.message} for r in rows]}
