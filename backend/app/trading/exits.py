"""Çıkış kuralları (saf fonksiyonlar - veritabanına dokunmaz, kolay test edilir).

Sıra: stop (başa baş / trailing dahil) -> 2. hedef -> 1. hedef.
"Net kâr pozitif değilse satma" kuralı: hedef ve trailing satışları başa baş fiyatının üstünde olmak
ZORUNDADIR. Yalnızca başlangıç stop-loss'u (acil risk çıkışı) zararına satış yapabilir.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..trading_settings import TradingSettings

REASON_TR = {
    "STOP_LOSS": "Stop-loss",
    "TRAILING_STOP": "Trailing stop",
    "BREAKEVEN_STOP": "Başa baş stop",
    "TAKE_PROFIT_1": "1. hedef",
    "TAKE_PROFIT_2": "2. hedef",
    "MANUAL": "Elle kapatıldı",
    "EMERGENCY": "Acil durdurma",
}


@dataclass
class PosState:
    entry: float
    qty: float
    stop: float
    tp1: float
    tp2: float
    tp1_done: bool
    peak: float
    trailing_active: bool


@dataclass
class ExitAction:
    fraction: float  # kalan miktarın oranı (1.0 = tamamı)
    reason: str
    order_type: str  # LIMIT (hedef) | MARKET (stop)
    ref_price: float


@dataclass
class ExitEval:
    peak: float
    trailing_active: bool
    effective_stop: float
    action: ExitAction | None


def breakeven_price(entry: float, fee_rate: float, slip_rate: float = 0.0) -> float:
    """Alım+satım komisyonu ve çıkış kaymasını karşılayan en düşük satış fiyatı."""
    return entry * (1 + fee_rate) / ((1 - fee_rate) * (1 - slip_rate))


def evaluate_exit(p: PosState, price: float, s: TradingSettings) -> ExitEval:
    fee, slip = s.fee_rate_pct / 100, s.slippage_pct / 100
    be = breakeven_price(p.entry, fee, slip)
    peak = max(p.peak, price)
    trailing = p.trailing_active or (s.trailing_enabled and peak >= p.entry * (1 + s.trailing_activation_pct / 100))

    eff_stop, stop_reason = p.stop, "STOP_LOSS"
    if p.tp1_done and be > eff_stop:
        eff_stop, stop_reason = be, "BREAKEVEN_STOP"
    if trailing:
        t = max(peak * (1 - s.trailing_distance_pct / 100), be)
        if t > eff_stop:
            eff_stop, stop_reason = t, "TRAILING_STOP"

    action: ExitAction | None = None
    if price <= eff_stop:
        action = ExitAction(1.0, stop_reason, "MARKET", price)
    elif price >= p.tp2 and price > be:
        action = ExitAction(1.0, "TAKE_PROFIT_2", "LIMIT", p.tp2)
    elif not p.tp1_done and price >= p.tp1 and price > be:
        frac = s.tp1_sell_fraction
        action = ExitAction(1.0 if frac >= 0.999 else frac, "TAKE_PROFIT_1", "LIMIT", p.tp1)
    return ExitEval(peak=peak, trailing_active=trailing, effective_stop=eff_stop, action=action)
