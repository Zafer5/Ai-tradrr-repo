"""Gerçek emir yürütücü (Binance Testnet veya GERÇEK hesap)."""
from __future__ import annotations

from .exchanges.base import ExchangeError, SymbolInfo
from .exchanges.binance_trade import BinanceTrader
from .paper import Fill, PaperExecutor, fmt_qty


class LiveExecutor(PaperExecutor):
    def __init__(self, trader: BinanceTrader, mode: str, fee_pct: float, slippage_pct: float, quote: str = "USDT"):
        super().__init__(fee_pct, slippage_pct)
        self.trader = trader
        self.mode = mode
        self.quote = quote
        self._px_cache: dict[str, float] = {}

    async def _fee_value(self, fills: list[dict], base: str) -> tuple[float, float, float]:
        """(toplam_komisyon_usdt_değeri, usdt_bakiyesinden_düşen, base_cinsinden_düşen_miktar)"""
        total = cash = base_fee = 0.0
        for f in fills:
            c = float(f.get("commission", 0))
            if c <= 0:
                continue
            asset, px = f.get("commissionAsset", ""), float(f.get("price", 0))
            if asset == self.quote:
                total += c
                cash += c
            elif asset == base:
                total += c * px
                base_fee += c
            else:  # örn. BNB ile ödenen komisyon
                try:
                    total += c * await self.trader.price(asset + self.quote)
                except ExchangeError:
                    total += float(f.get("qty", 0)) * px * 0.001  # fiyat alınamazsa %0,1 tahmin
        return total, cash, base_fee

    async def _run(self, symbol: str, side: str, quantity: float, info: SymbolInfo | None) -> Fill:
        step = info.step_size if info else 0.0
        qty_s = fmt_qty(quantity, step)
        if float(qty_s) <= 0:
            raise ExchangeError("Miktar adım boyutunun altında")
        o = await self.trader.market_order(symbol, side, qty_s)
        executed = float(o.get("executedQty", 0))
        quote_qty = float(o.get("cummulativeQuoteQty", 0))
        if executed <= 0 or quote_qty <= 0:
            raise ExchangeError(f"Emir gerçekleşmedi (durum: {o.get('status')})")
        base = info.base if info else symbol.removesuffix(self.quote)
        fee_total, fee_cash, base_fee = await self._fee_value(o.get("fills", []), base)
        net_qty = executed - base_fee if side == "BUY" else executed
        return Fill(side, quote_qty / executed, net_qty, quote_qty, fee_total, fee_cash)

    async def buy(self, symbol, ask, quantity, info=None) -> Fill:
        return await self._run(symbol, "BUY", quantity, info)

    async def sell(self, symbol, bid, quantity, info=None) -> Fill:
        return await self._run(symbol, "SELL", quantity, info)
