"""Borsa emir yürütücüsü (Binance Spot): Testnet ve GERÇEK hesap için ortak kod yolu.

Güvenlik tasarımı:
* Her emirden önce: bakiye, miktar adımı (LOT_SIZE), asgari tutar (NOTIONAL), açık emir ve /order/test doğrulaması.
* Yalnızca MARKET emir. Emir isteği ASLA otomatik tekrar denenmez (çift emir riski).
* Her emrin benzersiz newClientOrderId'si vardır. Yanıt belirsizse (zaman aşımı/5xx) emir bu kimlikle SORGULANIR.
  Sonuç hâlâ bilinmiyorsa ``OrderUncertain`` fırlatılır => bot yeni emir göndermeyi durdurur (insan müdahalesi).
* Fiyat, komisyon ve miktar BORSANIN döndürdüğü gerçek dolumlardan (fills) hesaplanır; tahmin edilmez.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

from ..exchange.binance import BinanceClient, ExchangeError
from ..exchange.types import SymbolInfo

log = logging.getLogger("app.live")
QUOTE = "USDT"


class OrderRejected(Exception):
    """Emir KESİNLİKLE borsaya ulaşmadı / reddedildi (güvenle yeniden denenebilir)."""


class OrderUncertain(Exception):
    """Emrin gerçekleşip gerçekleşmediği bilinmiyor. Yeni emir gönderilmemeli; insan doğrulamalı."""


@dataclass
class Fill:
    price: float  # ortalama dolum fiyatı
    qty: float  # alımda: komisyon düşüldükten sonra ELİMİZDEKİ miktar; satımda: satılan miktar
    fee: float  # USDT karşılığı toplam komisyon
    cost: float  # alım: toplam çıkan USDT (komisyon dahil) | satım: net giren USDT
    order_id: str = ""
    approx_fee: bool = False  # komisyon BNB ile ödendi: USDT karşılığı tahmin


def floor_qty(qty: float, step: float) -> Decimal:
    q = Decimal(str(qty))
    st = Decimal(str(step)) if step and step > 0 else Decimal("0.00000001")
    return (q // st) * st


def fmt_qty(q: Decimal) -> str:
    s = format(q.normalize(), "f")
    return s if s else "0"


def parse_fill(resp: dict, base: str, side: str, fee_rate: float) -> Fill:
    executed = float(resp.get("executedQty", 0) or 0)
    quote_qty = float(resp.get("cummulativeQuoteQty", 0) or 0)
    if executed <= 0 or quote_qty <= 0:
        raise OrderRejected("Emir hiç dolmadı")
    avg = quote_qty / executed
    fee_quote = fee_base_usdt = fee_other = base_fee_qty = 0.0
    approx = False
    fills = resp.get("fills") or []
    for f in fills:
        c, a, px, q = float(f["commission"]), f["commissionAsset"], float(f["price"]), float(f["qty"])
        if a == QUOTE:
            fee_quote += c
        elif a == base:
            base_fee_qty += c
            fee_base_usdt += c * px
        else:  # BNB vb.: değer bilinmiyor => oran x %25 indirim ile tahmin
            fee_other += q * px * fee_rate * 0.75
            approx = True
    if not fills:
        fee_other, approx = quote_qty * fee_rate, True
    fee = fee_quote + fee_base_usdt + fee_other
    if side == "BUY":
        return Fill(avg, executed - base_fee_qty, fee, quote_qty + fee_quote + fee_other, str(resp.get("orderId", "")), approx)
    return Fill(avg, executed, fee, quote_qty - fee_quote - fee_other, str(resp.get("orderId", "")), approx)


class ExchangeExecutor:
    def __init__(self, client: BinanceClient, mode: str, fee_rate: float = 0.001):
        self.client, self.mode, self.fee_rate = client, mode, fee_rate

    # ------------------------------------------------------------------ hesap
    async def account(self) -> dict:
        return await self.client.account()

    async def balances(self) -> dict[str, tuple[float, float]]:
        """asset -> (serbest, kilitli)"""
        acc = await self.client.account()
        return {b["asset"]: (float(b["free"]), float(b["locked"])) for b in acc.get("balances", [])}

    async def check_account(self) -> dict:
        acc = await self.client.account()
        usdt = next((float(b["free"]) for b in acc.get("balances", []) if b["asset"] == QUOTE), 0.0)
        return {"can_trade": bool(acc.get("canTrade")), "can_withdraw": bool(acc.get("canWithdraw")),
                "permissions": acc.get("permissions", []), "usdt_free": usdt}

    # ------------------------------------------------------------------ doğrulama
    @staticmethod
    def _check_filters(qty: Decimal, price: float, info: SymbolInfo | None, side: str) -> None:
        if info is None:
            raise OrderRejected("Coin bilgisi (filtreler) alınamadı")
        if qty <= 0:
            raise OrderRejected("Hesaplanan miktar adım büyüklüğünün altında")
        if info.min_qty > 0 and float(qty) < info.min_qty:
            raise OrderRejected(f"Miktar asgari miktarın altında ({float(qty)} < {info.min_qty})")
        if info.min_notional > 0 and float(qty) * price < info.min_notional * 1.02:
            raise OrderRejected(f"İşlem tutarı asgari tutarın altında ({float(qty) * price:.2f} < {info.min_notional})")

    async def _resolve(self, symbol: str, cid: str) -> dict:
        """Yanıt belirsizken emri client id ile sorgular. Bulunamazsa (-2013) emir oluşmamıştır."""
        last_err = ""
        for wait in (0.6, 1.5, 3.0):
            await asyncio.sleep(wait)
            try:
                return await self.client.get_order_by_client_id(symbol, cid)
            except ExchangeError as e:
                if e.code == -2013:  # Order does not exist
                    continue
                last_err = str(e)
        if last_err:
            raise OrderUncertain(f"{symbol} emri sorgulanamadı ({last_err})")
        raise OrderRejected("Emir borsada oluşmadı (zaman aşımı sonrası doğrulandı)")

    async def _place(self, symbol: str, side: str, qty: Decimal, base: str) -> Fill:
        cid = "aky" + uuid.uuid4().hex[:28]
        qs = fmt_qty(qty)
        try:
            resp = await self.client.new_order(symbol, side, "MARKET", qs, client_order_id=cid)
        except ExchangeError as e:
            if e.status is not None and 400 <= e.status < 500:  # kesin ret (bakiye, filtre, yetki...)
                raise OrderRejected(f"Borsa emri reddetti: {e}") from e
            log.warning("%s %s emri belirsiz sonuçlandı (%s); sorgulanıyor", symbol, side, e)
            resp = await self._resolve(symbol, cid)

        status = resp.get("status")
        for _ in range(4):  # market emir normalde anında FILLED olur
            if status in ("FILLED", "EXPIRED", "CANCELED", "REJECTED") or float(resp.get("executedQty", 0) or 0) > 0 and status != "NEW":
                break
            await asyncio.sleep(0.8)
            try:
                resp = await self.client.get_order_by_client_id(symbol, cid)
            except ExchangeError as e:
                raise OrderUncertain(f"{symbol} emir durumu alınamadı ({e})") from e
            status = resp.get("status")
        if status == "NEW":
            raise OrderUncertain(f"{symbol} market emri hâlâ bekliyor (NEW)")
        if status in ("REJECTED", "CANCELED") and float(resp.get("executedQty", 0) or 0) <= 0:
            raise OrderRejected(f"Emir {status}")
        if "fills" not in resp:  # durum sorgusu fills döndürmez: yalnızca toplamlar var
            resp = {**resp, "fills": []}
        fill = parse_fill(resp, base, side, self.fee_rate)
        fill.order_id = str(resp.get("orderId", cid))
        log.info("%s %s gerçekleşti [%s]: %.8g @ %.8g (komisyon %.4f USDT%s)", self.mode.upper(), side, symbol, fill.qty, fill.price, fill.fee, " ~tahmini" if fill.approx_fee else "")
        return fill

    # ------------------------------------------------------------------ alım / satım
    async def buy(self, symbol: str, qty: float, ref_ask: float, info: SymbolInfo | None, capital_free: float | None = None) -> Fill:
        q = floor_qty(qty, info.step_size if info else 0)
        self._check_filters(q, ref_ask, info, "BUY")
        need = float(q) * ref_ask * 1.004
        bals = await self.balances()
        base = info.base if info else symbol.replace(QUOTE, "")
        floor_value = max(info.min_notional if info else 0.0, 5.0)
        if sum(bals.get(base, (0.0, 0.0))) * ref_ask >= floor_value:
            # Aynı coinden önceden bakiye varsa bot kendi pozisyonunu sizin coininizden AYIRAMAZ (satışta karışma riski)
            raise OrderRejected(f"Hesapta zaten {base} bakiyesi var; bot sizin coininize dokunmamak için bu coine alım yapmaz")
        free = bals.get(QUOTE, (0.0, 0.0))[0]
        if need > free:
            raise OrderRejected(f"Bakiye yetersiz (gerekli ~{need:.2f}, serbest {free:.2f} USDT)")
        if capital_free is not None and need > capital_free * 1.001:
            raise OrderRejected(f"Sermaye tavanı aşılırdı (gerekli ~{need:.2f}, tavandan kalan {capital_free:.2f} USDT)")
        try:
            if await self.client.open_orders(symbol):
                raise OrderRejected(f"{symbol} için borsada bekleyen emir var (mükerrer emir engeli)")
            await self.client.test_order(symbol, "BUY", "MARKET", fmt_qty(q))
        except ExchangeError as e:
            raise OrderRejected(f"Emir doğrulaması başarısız: {e}") from e
        return await self._place(symbol, "BUY", q, info.base if info else symbol.replace(QUOTE, ""))

    async def sell(self, symbol: str, qty: float, ref_price: float, info: SymbolInfo | None, full_close: bool) -> Fill:
        base = info.base if info else symbol.replace(QUOTE, "")
        free = (await self.balances()).get(base, (0.0, 0.0))[0]
        q = floor_qty(min(qty, free), info.step_size if info else 0)
        if q <= 0:
            raise OrderRejected(f"Satılacak {base} bakiyesi yok (serbest {free})")
        if info and info.min_notional > 0 and float(q) * ref_price < info.min_notional * 1.02:
            raise OrderRejected(f"Satış tutarı asgari tutarın altında ({float(q) * ref_price:.2f})")
        try:
            await self.client.test_order(symbol, "SELL", "MARKET", fmt_qty(q))
        except ExchangeError as e:
            raise OrderRejected(f"Satış doğrulaması başarısız: {e}") from e
        return await self._place(symbol, "SELL", q, base)
