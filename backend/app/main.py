"""AI KRİPTO TRADER - FastAPI uygulaması.

Çalıştırma (backend klasöründen):  uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from .api.routes import router
from .config import AppConfig, get_config, resolve_secret_key
from .db import Database
from .exchange.binance import BinanceClient
from .exchange.stream import PriceFeed
from .logging_setup import DBLogHandler, setup_logging
from .security import AuthState, PasswordGate
from .trading.bot import BotRunner
from .trading.service import TradingService
from .trading_settings import SettingsStore

log = logging.getLogger("app.main")


@dataclass
class AppContext:
    cfg: AppConfig
    db: Database
    auth: AuthState
    store: SettingsStore
    client: BinanceClient
    feed: PriceFeed
    service: TradingService
    bot: BotRunner
    log_handler: DBLogHandler


def create_app(cfg: AppConfig | None = None, http: httpx.AsyncClient | None = None) -> FastAPI:
    """``http``: testlerde sahte Binance sunucusuna bağlanmak için enjekte edilebilir."""
    cfg = cfg or get_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        handler = setup_logging(cfg.log_level)
        gate = PasswordGate(cfg.admin_password)  # şifre yoksa/kısaysa açık Türkçe hata ile durur
        db = Database(cfg.database_url)
        await db.create_all()
        auth = AuthState(gate, resolve_secret_key(cfg), cfg.session_hours, cfg.cookie_secure)
        store = SettingsStore(db)
        client = BinanceClient(cfg.binance_rest_url, http=http)
        feed = PriceFeed(cfg.binance_ws_url, client)
        service = TradingService(db, store)
        bot = BotRunner(db, store, client, feed, service)
        app.state.ctx = AppContext(cfg, db, auth, store, client, feed, service, bot, handler)
        writer = asyncio.create_task(handler.run_writer(db), name="log-writer")
        if cfg.enable_bot_runtime:
            await bot.start()
        else:
            await bot.load_state()
            await service.ensure_account()
        log.info("AI KRİPTO TRADER hazır. Mod: PAPER (sanal). Gerçek para: KİLİTLİ.")
        try:
            yield
        finally:
            if cfg.enable_bot_runtime:
                await bot.shutdown()
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
            await client.aclose()
            await db.dispose()

    app = FastAPI(title="AI KRİPTO TRADER", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.include_router(router)

    @app.exception_handler(Exception)
    async def unhandled(_, exc: Exception):
        log.exception("Beklenmeyen hata")
        return JSONResponse({"detail": "Sunucuda beklenmeyen bir hata oluştu. Sistem günlüklerine bakın."}, status_code=500)

    dist = Path(cfg.frontend_dist)
    if dist.is_dir() and (dist / "index.html").exists():
        index = dist / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Bulunamadı"}, status_code=404)
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(index)

    return app
