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

from .config import settings
from .db import AnalysisRecord, Database, LogEntry, Position, Trade
from .engine import Engine
from .exchanges.binance import BinanceClient, BinancePriceStream

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).parent / "static"


def build_engine() -> Engine:
    db = Database(settings.database_url)
    client = BinanceClient(settings.binance_rest_url)
    engine = Engine(client, db, settings.starting_balance)
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
    await engine.log("INFO", "AI KRİPTO TRADER başladı (mod: PAPER - sanal işlem)")
    yield
    await engine.shutdown()
    await engine.client.close()
    await engine.db.dispose()


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


@app.get("/api/connections", dependencies=[Depends(auth)])
async def connections():
    e = eng()
    return {
        "exchange": "Binance Spot",
        "mode": "paper",
        "market_data": "Herkese açık piyasa verisi (API anahtarı gerekmez)",
        "websocket_connected": bool(e.stream and e.stream.connected),
        "api_key_configured": False,
        "live_trading": "Kapalı - bu sürümde gerçek emir gönderme kodu yoktur",
    }


class RunBody(BaseModel):
    running: bool


class EmergencyBody(BaseModel):
    active: bool
    close_positions: bool = False


@app.post("/api/bot/run", dependencies=[Depends(auth)])
async def bot_run(b: RunBody):
    try:
        await eng().set_running(b.running)
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
