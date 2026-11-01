"""FastAPI uygulaması: REST API + mobil panel."""
from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from .config import TESTNET_REST, settings
from . import indicators as ind
from .db import AnalysisRecord, Database, LogEntry, Position, Trade
from .engine import Engine
from .exchanges.binance import BinanceClient, BinancePriceStream
from .exchanges.binance_trade import BinanceTrader
from .secrets_store import KeyStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).parent / "static"


def keystore() -> KeyStore:
    import os
    path = settings.db_url.split(":///", 1)[-1]
    return KeyStore(os.path.dirname(os.path.abspath(path)) or ".", settings.panel_password)


def make_trader() -> BinanceTrader | None:
    """Kayıtlı (şifreli) anahtarlardan işlem istemcisi üretir. Anahtar ya da mod uyuşmuyorsa None."""
    if settings.trading_mode == "paper":
        return None
    d = keystore().load()
    if not d or d.get("environment") != settings.trading_mode:
        return None
    url = TESTNET_REST if settings.trading_mode == "testnet" else settings.binance_rest_url
    return BinanceTrader(url, d["api_key"], d["api_secret"])


def build_engine() -> Engine:
    db = Database(settings.db_url)
    mode = settings.trading_mode
    rest = TESTNET_REST if mode == "testnet" else settings.binance_rest_url
    client = BinanceClient(rest)
    engine = Engine(client, db, settings.effective_starting_balance, mode=mode, trader=make_trader(),
                    max_order_usdt=settings.live_max_order_usdt if mode == "live" else 0.0,
                    budget=settings.live_budget_usdt if mode == "live" else 0.0)
    if mode == "testnet":   # Testnet'te hacim çok düşüktür; süzgeçleri gevşet (yalnızca emir akışını denemek için)
        sc = engine.settings.scan
        sc.min_quote_volume, sc.max_spread_pct, sc.min_trade_count = 0.0, 5.0, 0
    if mode != "testnet":
        engine.stream = BinancePriceStream(settings.binance_ws_url, engine.on_price)
    return engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_safety()
    engine: Engine = app.state.engine if hasattr(app.state, "engine") else build_engine()
    app.state.engine = engine
    await engine.init()
    if getattr(app.state, "background", True):
        engine.start_background()
    await engine.log("INFO", f"AI KRİPTO TRADER başladı (mod: {engine.label})")
    yield
    await engine.shutdown()
    await engine.client.close()
    await engine.db.dispose()
    if engine.trader is not None:
        await engine.trader.close()


app = FastAPI(title="AI KRİPTO TRADER", lifespan=lifespan)
security = HTTPBasic(realm="AI Kripto Trader")


def auth(c: HTTPBasicCredentials = Depends(security)) -> None:
    ok_user = secrets.compare_digest(c.username.encode(), settings.panel_username.encode())
    ok_pass = secrets.compare_digest(c.password.encode(), settings.panel_password.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Hatalı kullanıcı adı veya şifre",
                            headers={"WWW-Authenticate": 'Basic realm="AI Kripto Trader"'})


def eng() -> Engine:
    return app.state.engine


def pos_dict(p: Position, price: float | None) -> dict:
    d = {c.name: getattr(p, c.name) for c in Position.__table__.columns}
    if price is not None and p.status == "open":
        d["current_price"] = price
        d["unrealized_pnl"] = p.quantity * price * (1 - eng().settings.risk.fee_pct / 100) - p.cost_basis
    return d


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/status", dependencies=[Depends(auth)])
async def get_status():
    return await eng().status()


@app.get("/api/scanner", dependencies=[Depends(auth)])
async def get_scanner():
    e = eng()
    return {"updated_at": e.last_universe_at, "rejected": e.rejected_count,
            "filters": e.settings.to_dict()["scan"], "coins": [u.to_dict() for u in e.universe]}


@app.get("/api/analyses", dependencies=[Depends(auth)])
async def get_analyses():
    e = eng()
    items = sorted((a.to_dict() for a in e.latest.values()), key=lambda a: a["score"], reverse=True)
    return {"updated_at": e.last_analysis_at, "items": items}


@app.get("/api/analyses/{symbol}/history", dependencies=[Depends(auth)])
async def analysis_history(symbol: str):
    async with eng().db.session() as s:
        rows = (await s.execute(select(AnalysisRecord).where(AnalysisRecord.symbol == symbol.upper())
                                .order_by(AnalysisRecord.created_at.desc()).limit(100))).scalars().all()
    return [{"score": r.score, "at": r.created_at.isoformat(), "price": r.data.get("price")} for r in rows]


@app.get("/api/positions", dependencies=[Depends(auth)])
async def get_positions(state: str = "open", limit: int = 200):
    e = eng()
    async with e.db.session() as s:
        rows = (await s.execute(select(Position).where(Position.status == state)
                                .order_by(Position.opened_at.desc()).limit(limit))).scalars().all()
    return [pos_dict(p, e.prices.get(p.symbol, (None, 0))[0]) for p in rows]


@app.get("/api/trades", dependencies=[Depends(auth)])
async def get_trades(limit: int = 200):
    async with eng().db.session() as s:
        rows = (await s.execute(select(Trade).order_by(Trade.created_at.desc()).limit(limit))).scalars().all()
    return [{c.name: getattr(t, c.name) for c in Trade.__table__.columns} for t in rows]


@app.get("/api/report", dependencies=[Depends(auth)])
async def get_report():
    return await eng().report()


@app.get("/api/logs", dependencies=[Depends(auth)])
async def get_logs(limit: int = 200):
    async with eng().db.session() as s:
        rows = (await s.execute(select(LogEntry).order_by(LogEntry.id.desc()).limit(limit))).scalars().all()
    return [{"level": r.level, "message": r.message, "at": r.created_at.isoformat()} for r in rows]


@app.get("/api/settings", dependencies=[Depends(auth)])
async def get_settings():
    return eng().settings.to_dict()


@app.put("/api/settings", dependencies=[Depends(auth)])
async def put_settings(data: dict):
    try:
        await eng().save_settings(data)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    return eng().settings.to_dict()


class KeyBody(BaseModel):
    environment: str = "testnet"
    api_key: str
    api_secret: str


@app.get("/api/keys", dependencies=[Depends(auth)])
async def get_keys():
    return keystore().public_info()


@app.put("/api/keys", dependencies=[Depends(auth)])
async def put_keys(b: KeyBody):
    if settings.trading_mode == "paper":
        raise HTTPException(400, "Sanal modda API anahtarı gerekmez ve kaydedilmez. Anahtar için .env dosyasında TRADING_MODE=testnet yapın.")
    if b.environment != settings.trading_mode:
        raise HTTPException(400, f"Bot şu an '{settings.trading_mode}' modunda; yalnızca bu moda ait anahtar kaydedilebilir.")
    k, sec = b.api_key.strip(), b.api_secret.strip()
    if not (16 <= len(k) <= 128) or not (16 <= len(sec) <= 128) or " " in k or " " in sec:
        raise HTTPException(400, "Anahtar veya secret geçersiz görünüyor. Kopyalarken boşluk kalmış olabilir.")
    keystore().save(b.environment, k, sec)
    old = eng().trader
    eng().set_trader(make_trader())
    if old is not None:
        await old.close()
    await eng().log("INFO", f"{b.environment} API anahtarı kaydedildi (şifreli). Değer günlüğe yazılmadı.")
    return keystore().public_info()


@app.delete("/api/keys", dependencies=[Depends(auth)])
async def delete_keys():
    keystore().delete()
    if eng().trader is not None:
        await eng().trader.close()
    eng().set_trader(None)
    await eng().log("INFO", "Kayıtlı API anahtarı silindi")
    return {"configured": False}


_CHART_CACHE: dict = {}


def _nn(v):
    return None if v is None or v != v else round(v, 10)


@app.get("/api/chart/{symbol}", dependencies=[Depends(auth)])
async def chart(symbol: str, interval: str = "15m", limit: int = 120):
    import datetime as _dt
    import re
    e = eng()
    symbol = symbol.upper()
    if interval not in ("5m", "15m", "1h", "4h") or not re.fullmatch(r"[A-Z0-9]{5,20}", symbol):
        raise HTTPException(400, "Geçersiz coin veya zaman dilimi")
    limit = max(30, min(limit, 200))
    import time as _t
    hit = _CHART_CACHE.get((symbol, interval))
    if hit and _t.time() - hit[0] < 2.0:       # birden çok istek borsayı yormasın
        candles = hit[1]
    else:
        try:
            candles = await e.client.klines(symbol, interval, 250)
        except Exception as ex:  # noqa: BLE001
            raise HTTPException(502, f"Grafik verisi alınamadı: {ex}")
        _CHART_CACHE[(symbol, interval)] = (_t.time(), candles)
        if len(_CHART_CACHE) > 50:
            _CHART_CACHE.pop(next(iter(_CHART_CACHE)))
    closes = [c.close for c in candles]
    e21, e50 = ind.ema(closes, 21), ind.ema(closes, 50)
    cut = len(candles) - limit
    cs = candles[cut:]
    async with e.db.session() as s:
        trades = (await s.execute(select(Trade).where(Trade.symbol == symbol).order_by(Trade.created_at))).scalars().all()
        pos = (await s.execute(select(Position).where(Position.symbol == symbol, Position.status == "open"))).scalars().first()
    t0 = cs[0].open_time if cs else 0
    markers = []
    for t in trades:
        ms = int(t.created_at.replace(tzinfo=_dt.timezone.utc).timestamp() * 1000)
        if ms >= t0:
            markers.append({"time": ms, "side": t.side, "price": t.price, "note": t.note})
    return {
        "symbol": symbol, "interval": interval,
        "candles": [{"t": c.open_time, "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume} for c in cs],
        "ema21": [_nn(v) for v in e21[cut:]], "ema50": [_nn(v) for v in e50[cut:]],
        "markers": markers,
        "position": {"entry": pos.entry_price, "take_profit": pos.take_profit, "stop_loss": pos.stop_loss} if pos else None,
        "analysis": e.latest[symbol].to_dict() if symbol in e.latest else None,
        "server_time": _t.time(),
    }


@app.get("/api/activity", dependencies=[Depends(auth)])
async def activity(limit: int = 100):
    e = eng()
    import time as _t
    nxt = max(0, int(e.last_analysis_at + e.settings.trade.analysis_interval_sec - _t.time())) if e.last_analysis_at else None
    return {"progress": e.progress, "next_analysis_in": nxt, "running": e.running, "min_score": e.settings.risk.min_score,
            "tracked": len(e.universe), "items": list(e.decisions)[:limit]}


@app.get("/api/radar", dependencies=[Depends(auth)])
async def get_radar():
    e = eng()
    return {"updated_at": e.last_radar_at, "trending_source": "CoinGecko (ücretsiz)" if e.trending else "ulaşılamadı",
            "items": [r.to_dict() for r in e.radar_items[:60]],
            "note": "Radar tahmin değildir; yalnızca olağan dışı hareket eden coinleri gösterir. Yeni ve ani yükselen coinler en riskli olanlardır."}


@app.post("/api/exchange/verify", dependencies=[Depends(auth)])
async def exchange_verify():
    return await eng().verify_exchange()


@app.get("/api/connections", dependencies=[Depends(auth)])
async def connections():
    e = eng()
    return {
        "exchange": "Binance Spot",
        "mode": settings.trading_mode,
        "mode_label": eng().label,
        "exchange_check": eng().exchange_check,
        "live_limits": {"budget_usdt": settings.live_budget_usdt, "max_order_usdt": settings.live_max_order_usdt} if settings.is_live else None,
        "market_data": "Herkese açık piyasa verisi (API anahtarı gerekmez)",
        "websocket_connected": bool(e.stream and e.stream.connected),
        "api_key_configured": keystore().exists(),
        "live_trading": "AÇIK (GERÇEK PARA)" if settings.is_live else "Kapalı",
        "key_note": "Anahtar yalnızca sunucuda şifreli saklanır; tarayıcıya geri gönderilmez.",
    }


class RunBody(BaseModel):
    running: bool
    confirm: str = ""


class EmergencyBody(BaseModel):
    active: bool
    close_positions: bool = False


@app.post("/api/bot/run", dependencies=[Depends(auth)])
async def bot_run(b: RunBody):
    try:
        await eng().set_running(b.running, confirmed=(b.confirm.strip().upper() == "ONAYLIYORUM"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"running": eng().running}


@app.post("/api/bot/emergency", dependencies=[Depends(auth)])
async def bot_emergency(b: EmergencyBody):
    closed = await eng().set_emergency(b.active, b.close_positions)
    return {"emergency_stop": eng().emergency_stop, "closed": closed}


@app.post("/api/positions/{pid}/close", dependencies=[Depends(auth)])
async def close_pos(pid: int):
    if not await eng().close_position(pid):
        raise HTTPException(404, "Açık pozisyon bulunamadı")
    return {"ok": True}


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def sw():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")


@app.get("/", dependencies=[Depends(auth)])
async def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
