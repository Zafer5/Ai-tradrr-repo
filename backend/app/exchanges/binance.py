"""Binance Spot genel piyasa verisi (REST + WebSocket).

Yalnızca herkese açık uç noktalar kullanılır; API anahtarı gerekmez.
Resmi belge: https://developers.binance.com/docs/binance-spot-api-docs
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Awaitable, Callable, Iterable

import httpx
import websockets

from .base import (
    BookTicker,
    Candle,
    ExchangeError,
    MarketDataClient,
    PriceUpdate,
    SymbolInfo,
    Ticker24h,
)

log = logging.getLogger("binance")


def parse_symbol(raw: dict) -> SymbolInfo:
    info = SymbolInfo(
        symbol=raw["symbol"],
        base=raw["baseAsset"],
        quote=raw["quoteAsset"],
        status=raw.get("status", ""),
        spot_allowed=bool(raw.get("isSpotTradingAllowed", False)),
    )
    for f in raw.get("filters", []):
        t = f.get("filterType")
        if t == "LOT_SIZE":
            info.step_size = float(f.get("stepSize", 0))
            info.min_qty = float(f.get("minQty", 0))
        elif t == "PRICE_FILTER":
            info.tick_size = float(f.get("tickSize", 0))
        elif t in ("NOTIONAL", "MIN_NOTIONAL"):
            info.min_notional = float(f.get("minNotional", 0))
    return info


def parse_kline(row: list) -> Candle:
    return Candle(
        open_time=int(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        close_time=int(row[6]),
        closed=int(row[6]) < int(time.time() * 1000),
    )


class BinanceClient(MarketDataClient):
    name = "binance"

    def __init__(self, rest_url: str, timeout: float = 15.0, max_concurrency: int = 5):
        self._http = httpx.AsyncClient(base_url=rest_url, timeout=timeout)
        self._sem = asyncio.Semaphore(max_concurrency)
        self._banned_until = 0.0

    async def _get(self, path: str, params: dict | None = None, retries: int = 3):
        for attempt in range(retries + 1):
            wait = self._banned_until - time.time()
            if wait > 0:
                raise ExchangeError(f"Binance istek limiti: {int(wait)} sn beklenmeli")
            try:
                async with self._sem:
                    r = await self._http.get(path, params=params)
            except httpx.HTTPError as e:
                if attempt == retries:
                    raise ExchangeError(f"Bağlantı hatası: {e}") from e
                await asyncio.sleep(2 ** attempt)
                continue
            if r.status_code in (418, 429):
                retry_after = int(r.headers.get("Retry-After", "60"))
                self._banned_until = time.time() + retry_after
                raise ExchangeError(f"Binance istek limiti aşıldı ({r.status_code}), {retry_after} sn bekleniyor")
            if r.status_code >= 500 and attempt < retries:
                await asyncio.sleep(2 ** attempt)
                continue
            if r.status_code != 200:
                raise ExchangeError(f"Binance {path} hata {r.status_code}: {r.text[:200]}")
            return r.json()
        raise ExchangeError("Bilinmeyen hata")

    async def ping(self) -> bool:
        await self._get("/api/v3/ping")
        return True

    async def symbols(self) -> list[SymbolInfo]:
        data = await self._get("/api/v3/exchangeInfo", {"permissions": "SPOT"})
        return [parse_symbol(s) for s in data.get("symbols", [])]

    async def tickers_24h(self) -> list[Ticker24h]:
        data = await self._get("/api/v3/ticker/24hr")
        out = []
        for t in data:
            out.append(
                Ticker24h(
                    symbol=t["symbol"],
                    last_price=float(t["lastPrice"]),
                    price_change_pct=float(t["priceChangePercent"]),
                    quote_volume=float(t["quoteVolume"]),
                    trade_count=int(t.get("count", 0)),
                    high=float(t["highPrice"]),
                    low=float(t["lowPrice"]),
                )
            )
        return out

    async def book_tickers(self) -> list[BookTicker]:
        data = await self._get("/api/v3/ticker/bookTicker")
        return [BookTicker(t["symbol"], float(t["bidPrice"]), float(t["askPrice"])) for t in data]

    async def book_ticker(self, symbol: str) -> BookTicker:
        t = await self._get("/api/v3/ticker/bookTicker", {"symbol": symbol})
        return BookTicker(t["symbol"], float(t["bidPrice"]), float(t["askPrice"]))

    async def klines(self, symbol: str, interval: str, limit: int = 250) -> list[Candle]:
        data = await self._get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        return [parse_kline(r) for r in data]

    async def close(self) -> None:
        await self._http.aclose()


class BinancePriceStream:
    """WebSocket ile gerçek zamanlı fiyat takibi; bağlantı koparsa otomatik yeniden bağlanır."""

    def __init__(self, ws_url: str, on_price: Callable[[PriceUpdate], Awaitable[None] | None]):
        self.ws_url = ws_url.rstrip("/")
        self.on_price = on_price
        self.symbols: list[str] = []
        self.connected = False
        self.last_message_at = 0.0
        self._task: asyncio.Task | None = None
        self._restart = asyncio.Event()
        self._stopping = False

    def set_symbols(self, symbols: Iterable[str]) -> None:
        new = sorted(set(symbols))
        if new != self.symbols:
            self.symbols = new
            self._restart.set()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopping = True
        self._restart.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run(self) -> None:
        backoff = 1
        while not self._stopping:
            if not self.symbols:
                await asyncio.sleep(1)
                continue
            streams = "/".join(f"{s.lower()}@miniTicker" for s in self.symbols)
            url = f"{self.ws_url}/stream?streams={streams}"
            self._restart.clear()
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
                    self.connected = True
                    backoff = 1
                    log.info("WebSocket bağlandı (%d coin)", len(self.symbols))
                    while not self._restart.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            raise ConnectionError("30 sn veri gelmedi")
                        self.last_message_at = time.time()
                        msg = json.loads(raw)
                        d = msg.get("data", {})
                        if d.get("e") == "24hrMiniTicker":
                            res = self.on_price(PriceUpdate(d["s"], float(d["c"]), self.last_message_at))
                            if asyncio.iscoroutine(res):
                                await res
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.connected = False
                log.warning("WebSocket koptu: %s. %d sn sonra yeniden bağlanılacak", e, backoff)
                await asyncio.sleep(backoff + random.random())
                backoff = min(backoff * 2, 60)
            finally:
                self.connected = False
