"""Gerçek zamanlı fiyat akışı: Binance WebSocket (!miniTicker@arr) + REST yedeği.

* Bağlantı koparsa üstel bekleme ile otomatik yeniden bağlanır.
* WebSocket 10 sn'den uzun süre sessiz kalırsa REST ile fiyatlar yenilenir (yedek).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from websockets.asyncio.client import connect

from .binance import BinanceClient

log = logging.getLogger("app.stream")


class PriceFeed:
    def __init__(self, ws_url: str, client: BinanceClient, quote: str = "USDT"):
        self.ws_url = ws_url.rstrip("/")
        self.client = client
        self.quote = quote
        self.prices: dict[str, float] = {}
        self.updated_at: float = 0.0
        self.ws_connected = False
        self.ws_reconnects = 0
        self.last_error: str | None = None
        self._tasks: list[asyncio.Task] = []

    # ---- okuma ----
    def get(self, symbol: str) -> float | None:
        return self.prices.get(symbol)

    @property
    def age(self) -> float:
        return time.time() - self.updated_at if self.updated_at else float("inf")

    def update(self, symbol: str, price: float) -> None:
        if price > 0:
            self.prices[symbol] = price
            self.updated_at = time.time()

    # ---- yaşam döngüsü ----
    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._ws_loop(), name="ws"), asyncio.create_task(self._rest_fallback_loop(), name="rest-fallback")]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _ws_loop(self) -> None:
        backoff = 1.0
        url = f"{self.ws_url}/!miniTicker@arr"
        while True:
            try:
                async with connect(url, ping_interval=20, ping_timeout=20, max_size=None, open_timeout=15) as ws:
                    self.ws_connected = True
                    self.last_error = None
                    backoff = 1.0
                    log.info("WebSocket bağlandı")
                    async for raw in ws:
                        self._on_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.last_error = f"WebSocket: {type(e).__name__}: {e}"[:200]
            finally:
                if self.ws_connected:
                    log.warning("WebSocket bağlantısı koptu; yeniden denenecek")
                self.ws_connected = False
            self.ws_reconnects += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def _on_message(self, raw: str | bytes) -> None:
        try:
            data = json.loads(raw)
        except ValueError:
            return
        if isinstance(data, dict):  # birleşik akış sarmalayıcısı
            data = data.get("data", [])
        for d in data if isinstance(data, list) else []:
            sym = d.get("s", "")
            if sym.endswith(self.quote):
                try:
                    self.update(sym, float(d["c"]))
                except (KeyError, ValueError):
                    continue

    async def _rest_fallback_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            if self.age < 10:
                continue
            try:
                for sym, price in (await self.client.prices()).items():
                    if sym.endswith(self.quote):
                        self.update(sym, price)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.last_error = f"REST yedek: {e}"[:200]
