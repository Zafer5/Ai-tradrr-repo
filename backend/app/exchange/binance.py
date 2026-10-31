"""Binance Spot REST istemcisi.

* Genel piyasa verisi (exchangeInfo, ticker, klines) API anahtarı GEREKTİRMEZ.
* İmzalı uçlar (hesap, emir) yalnızca Testnet aşamasında kullanılacak; para çekme yetkisi hiçbir yerde gerekmez.
* Tüm istekler yeniden deneme + hız sınırı (429/418) koruması içerir.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import httpx

from .types import Candles, SymbolInfo, Ticker

log = logging.getLogger("app.exchange")


class ExchangeError(Exception):
    def __init__(self, message: str, status: int | None = None, code: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


def sign_query(query_string: str, secret: str) -> str:
    """HMAC-SHA256 imzası (Binance belgelerindeki yönteme göre)."""
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


class BinanceClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        api_secret: str | None = None,
        http: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self._secret = api_secret
        self._own_http = http is None
        self.http = http or httpx.AsyncClient(timeout=timeout)
        self.used_weight_1m: int | None = None
        self.last_ok_at: float | None = None
        self.last_error: str | None = None
        self._ban_until = 0.0

    async def aclose(self) -> None:
        if self._own_http:
            await self.http.aclose()

    # ------------------------------------------------------------------ çekirdek
    async def _request(self, method: str, path: str, params: dict | None = None, signed: bool = False, retries: int = 3):
        params = dict(params or {})
        headers = {}
        if signed:
            if not (self._key and self._secret):
                raise ExchangeError("İmzalı istek için API anahtarı tanımlı değil.")
            params["timestamp"] = int(time.time() * 1000)
            params.setdefault("recvWindow", 5000)
            qs = urlencode(params)
            params_str = f"{qs}&signature={sign_query(qs, self._secret)}"
            headers["X-MBX-APIKEY"] = self._key
            url = f"{self.base_url}{path}?{params_str}"
            req_params = None
        else:
            url = f"{self.base_url}{path}"
            req_params = params or None

        last_exc: Exception | None = None
        for attempt in range(retries):
            wait = self._ban_until - time.time()
            if wait > 0:
                await asyncio.sleep(min(wait, 60))
            try:
                resp = await self.http.request(method, url, params=req_params, headers=headers)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_exc = e
                self.last_error = f"Bağlantı hatası: {type(e).__name__}"
                await asyncio.sleep(0.5 * 2**attempt)
                continue

            w = resp.headers.get("x-mbx-used-weight-1m")
            if w and w.isdigit():
                self.used_weight_1m = int(w)

            if resp.status_code in (429, 418):
                retry_after = float(resp.headers.get("retry-after", "10"))
                self._ban_until = time.time() + retry_after
                self.last_error = f"Hız sınırı ({resp.status_code}); {retry_after:.0f} sn beklenecek"
                log.warning(self.last_error)
                last_exc = ExchangeError(self.last_error, resp.status_code)
                continue
            if resp.status_code >= 500:
                last_exc = ExchangeError(f"Binance sunucu hatası {resp.status_code}", resp.status_code)
                self.last_error = str(last_exc)
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                except ValueError:
                    body = {}
                msg = body.get("msg") or resp.text[:200]
                self.last_error = f"Binance hatası {resp.status_code}: {msg}"
                raise ExchangeError(self.last_error, resp.status_code, body.get("code"))

            self.last_ok_at = time.time()
            self.last_error = None
            return resp.json()
        raise ExchangeError(f"İstek başarısız ({path}): {last_exc}")

    # ------------------------------------------------------------------ genel uçlar
    async def ping(self) -> bool:
        await self._request("GET", "/api/v3/ping", retries=1)
        return True

    async def server_time(self) -> int:
        return int((await self._request("GET", "/api/v3/time"))["serverTime"])

    async def exchange_info(self) -> dict[str, SymbolInfo]:
        data = await self._request("GET", "/api/v3/exchangeInfo")
        out: dict[str, SymbolInfo] = {}
        for s in data.get("symbols", []):
            flt = {f["filterType"]: f for f in s.get("filters", [])}
            notional = flt.get("NOTIONAL") or flt.get("MIN_NOTIONAL") or {}
            out[s["symbol"]] = SymbolInfo(
                symbol=s["symbol"],
                base=s.get("baseAsset", ""),
                quote=s.get("quoteAsset", ""),
                status=s.get("status", ""),
                spot_allowed=bool(s.get("isSpotTradingAllowed", True)),
                tick_size=_f(flt.get("PRICE_FILTER", {}).get("tickSize")),
                step_size=_f(flt.get("LOT_SIZE", {}).get("stepSize")),
                min_qty=_f(flt.get("LOT_SIZE", {}).get("minQty")),
                min_notional=_f(notional.get("minNotional")),
            )
        return out

    async def tickers_24h(self) -> dict[str, Ticker]:
        data = await self._request("GET", "/api/v3/ticker/24hr")
        out = {}
        for t in data:
            out[t["symbol"]] = Ticker(
                symbol=t["symbol"],
                last=_f(t.get("lastPrice")),
                bid=_f(t.get("bidPrice")),
                ask=_f(t.get("askPrice")),
                quote_volume=_f(t.get("quoteVolume")),
                change_pct=_f(t.get("priceChangePercent")),
                trades=int(_f(t.get("count"))),
            )
        return out

    async def prices(self) -> dict[str, float]:
        data = await self._request("GET", "/api/v3/ticker/price")
        return {d["symbol"]: _f(d["price"]) for d in data}

    async def book_ticker(self, symbol: str) -> tuple[float, float]:
        d = await self._request("GET", "/api/v3/ticker/bookTicker", {"symbol": symbol})
        return _f(d["bidPrice"]), _f(d["askPrice"])

    async def klines(self, symbol: str, interval: str, limit: int = 300, start: int | None = None, end: int | None = None) -> Candles:
        p: dict = {"symbol": symbol, "interval": interval, "limit": limit}
        if start is not None:
            p["startTime"] = start
        if end is not None:
            p["endTime"] = end
        return Candles.from_klines(await self._request("GET", "/api/v3/klines", p))

    # ------------------------------------------------------------------ imzalı uçlar (Testnet aşaması)
    async def account(self) -> dict:
        return await self._request("GET", "/api/v3/account", signed=True)

    async def my_trades(self, symbol: str, limit: int = 1000) -> list:
        """Geçmiş dolumlar (salt okunur yetki yeterli)."""
        return await self._request("GET", "/api/v3/myTrades", {"symbol": symbol, "limit": limit}, signed=True)

    async def new_order(self, symbol: str, side: str, order_type: str, quantity: float, price: float | None = None, client_order_id: str | None = None) -> dict:
        p: dict = {"symbol": symbol, "side": side, "type": order_type, "quantity": f"{quantity:.8f}".rstrip("0").rstrip(".")}
        if order_type == "LIMIT":
            p["timeInForce"] = "GTC"
            p["price"] = f"{price:.8f}".rstrip("0").rstrip(".")
        if client_order_id:
            p["newClientOrderId"] = client_order_id
        return await self._request("POST", "/api/v3/order", p, signed=True, retries=1)

    async def get_order(self, symbol: str, order_id: int) -> dict:
        return await self._request("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    async def cancel_order(self, symbol: str, order_id: int) -> dict:
        return await self._request("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    async def open_orders(self, symbol: str | None = None) -> list:
        return await self._request("GET", "/api/v3/openOrders", {"symbol": symbol} if symbol else None, signed=True)
