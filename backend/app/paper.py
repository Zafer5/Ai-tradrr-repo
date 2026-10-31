"""Paper Trading (sanal işlem) yürütücüsü.

Gerçek piyasa fiyatlarını kullanır; emir borsaya GÖNDERİLMEZ. Komisyon ve
fiyat kayması simüle edilir.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Fill:
    side: str
    price: float
    quantity: float
    notional: float
    fee: float


class PaperExecutor:
    mode = "paper"

    def __init__(self, fee_pct: float, slippage_pct: float):
        self.fee = fee_pct / 100
        self.slip = slippage_pct / 100

    def market_buy(self, ask: float, quantity: float) -> Fill:
        px = ask * (1 + self.slip)
        notional = px * quantity
        return Fill("BUY", px, quantity, notional, notional * self.fee)

    def market_sell(self, bid: float, quantity: float) -> Fill:
        px = bid * (1 - self.slip)
        notional = px * quantity
        return Fill("SELL", px, quantity, notional, notional * self.fee)

    def net_if_sold(self, bid: float, quantity: float, cost_basis: float) -> float:
        """Şimdi satılırsa komisyon ve kayma sonrası net kâr (cost_basis alış ücretini içerir)."""
        f = self.market_sell(bid, quantity)
        return f.notional - f.fee - cost_basis
