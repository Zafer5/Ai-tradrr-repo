"""Binance Spot imzalı (özel) API: emir gönderme, bakiye, anahtar yetkileri.

Güvenlik:
- API secret hiçbir zaman loglanmaz, hata mesajlarına konmaz.
- İstek saati sunucuyla senkronlanır (yanlış PC saati yüzünden -1021 hatasını önler).
- Emir sonucu belirsizse (zaman aşımı) clientOrderId ile durum sorgulanır; yine belirsizse
  OrderUncertain fırlatılır ve motor yeni emirleri durdurur.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import uuid
from urllib.parse import urlencode

import httpx

from .base import ExchangeError


class OrderUncertain(ExchangeError):
    """Emrin gerçekleşip gerçekleşmediği bilinmiyor; elle kontrol gerekir."""


class BinanceTrader:
    def __init__(self, base_url: str, api_key: str, api_secret: str, timeout: float = 10.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url
        self._key = api_key
        self._secret = api_secret.encode()
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)
        self._offset_ms = 0
        self._synced = False

    async def close(self) -> None:
        await self._http.aclose()

    async def _sync_time(self) -> None:
        r = await self._http.get("/api/v3/time")
        r.raise_for_status()
        self._offset_ms = int(r.json()["serverTime"]) - int(time.time() * 1000)
        self._synced = True

    def _sign(self, params: dict) -> str:
        q = urlencode(params)
        return q + "&signature=" + hmac.new(self._secret, q.encode(), hashlib.sha256).hexdigest()

    async def _request(self, method: str, path: str, params: dict | None = None, signed: bool = True):
        params = dict(params or {})
        try:
            if signed:
                if not self._synced:
                    await self._sync_time()
                params["timestamp"] = int(time.time() * 1000) + self._offset_ms
                params["recvWindow"] = 5000
                url = path + "?" + self._sign(params)
                r = await self._http.request(method, url, headers={"X-MBX-APIKEY": self._key})
            else:
                r = await self._http.request(method, path, params=params)
        except httpx.HTTPError as e:
            raise ExchangeError(f"Bağlantı hatası ({type(e).__name__})") from e
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code != 200:
            code = data.get("code") if isinstance(data, dict) else None
            msg = data.get("msg") if isinstance(data, dict) else r.text[:100]
            err = ExchangeError(f"Binance hata {r.status_code} (kod {code}): {msg}")
            err.code = code  # type: ignore[attr-defined]
            raise err
        return data

    # ---- okuma ----
    async def account(self) -> dict:
        return await self._request("GET", "/api/v3/account")

    async def api_restrictions(self) -> dict:
        return await self._request("GET", "/sapi/v1/account/apiRestrictions")

    async def free_balance(self, asset: str) -> float:
        acc = await self.account()
        for b in acc.get("balances", []):
            if b["asset"] == asset:
                return float(b["free"])
        return 0.0

    async def price(self, symbol: str) -> float:
        d = await self._request("GET", "/api/v3/ticker/price", {"symbol": symbol}, signed=False)
        return float(d["price"])

    async def get_order(self, symbol: str, client_order_id: str) -> dict:
        return await self._request("GET", "/api/v3/order", {"symbol": symbol, "origClientOrderId": client_order_id})

    # ---- emir ----
    async def market_order(self, symbol: str, side: str, quantity: str) -> dict:
        """Piyasa emri gönderir ve sonucu (fills dahil) döndürür. Belirsizlikte OrderUncertain."""
        cid = "akt" + uuid.uuid4().hex[:24]
        params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": quantity,
                  "newClientOrderId": cid, "newOrderRespType": "FULL"}
        try:
            return await self._request("POST", "/api/v3/order", params)
        except ExchangeError as e:
            code = getattr(e, "code", None)
            if code is not None:
                raise  # Binance emri açıkça reddetti: emir yok
            # Ağ hatası: emir gitmiş olabilir. Durumu sorgula.
            await asyncio.sleep(1.0)
            try:
                o = await self.get_order(symbol, cid)
            except ExchangeError as e2:
                if getattr(e2, "code", None) == -2013:  # Order does not exist
                    raise ExchangeError("Emir borsaya ulaşmadı (güvenle iptal sayıldı)") from e
                raise OrderUncertain(f"{symbol} {side} emrinin sonucu bilinmiyor: {e2}") from e2
            if o.get("status") in ("FILLED", "PARTIALLY_FILLED", "EXPIRED") and float(o.get("executedQty", 0)) > 0:
                o.setdefault("fills", [])
                o["_recovered"] = True
                return o
            raise ExchangeError(f"Emir gerçekleşmedi (durum: {o.get('status')})")
