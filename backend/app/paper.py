"""Emir yürütücüleri.

PaperExecutor : sanal emir; komisyon ve fiyat kayması simüle edilir, borsaya HİÇBİR ŞEY gönderilmez.
LiveExecutor  : Binance'e (Testnet veya gerçek) piyasa emri gönderir.
İkisi de aynı arayüzü kullanır; motor hangisinin çalıştığını bilmez.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Fill:
    side: str
    price: float
    quantity: float
    notional: float
    fee: float                 # toplam komisyonun USDT değeri (raporlama ve kâr hesabı)
    fee_cash: float | None = None  # bunun USDT bakiyesinden fiilen düşen kısmı (BNB/base ile ödenen hariç)

    def __post_init__(self):
        if self.fee_cash is None:
            self.fee_cash = self.fee


def fmt_qty(q: float, step: float) -> str:
    """Miktarı adım boyutuna göre aşağı yuvarlayıp üstel gösterimsiz metne çevirir."""
    d = Decimal(str(q))
    if step > 0:
        s = Decimal(str(step))
        d = (d / s).to_integral_value(rounding="ROUND_DOWN") * s
    return format(d.normalize(), "f")


class PaperExecutor:
    mode = "paper"

    def __init__(self, fee_pct: float, slippage_pct: float):
        self.fee = fee_pct / 100
        self.slip = slippage_pct / 100

    async def buy(self, symbol: str, ask: float, quantity: float, info=None) -> Fill:
        px = ask * (1 + self.slip)
        notional = px * quantity
        return Fill("BUY", px, quantity, notional, notional * self.fee)

    async def sell(self, symbol: str, bid: float, quantity: float, info=None) -> Fill:
        px = bid * (1 - self.slip)
        notional = px * quantity
        return Fill("SELL", px, quantity, notional, notional * self.fee)

    def net_if_sold(self, bid: float, quantity: float, cost_basis: float) -> float:
        """Şimdi satılırsa komisyon ve kayma sonrası tahmini net kâr."""
        px = bid * (1 - self.slip)
        n = px * quantity
        return n - n * self.fee - cost_basis
