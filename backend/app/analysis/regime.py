"""Genel piyasa rejimi: BTC yönü ve ani düşüş (şok) koruması. Saf fonksiyon - emir göndermez."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..exchange.types import Candles
from .engine import TIMEFRAMES, evaluate_tf
from .indicators import compute_indicators


@dataclass
class Regime:
    direction: str  # Yükseliş | Yatay | Düşüş | Bilinmiyor
    shock: bool
    shock_reason: str | None
    btc_1h_change_pct: float | None
    summary: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def evaluate_regime(btc: dict[str, Candles], now_ms: int, shock_pct: float = 2.5) -> Regime:
    """BTC kapanmış mumlarından yön ve şok tespiti.
    Şok: son 1 saatte (12x5dk) BTC düşüşü >= shock_pct VEYA son 15 dakikada >= shock_pct/2."""
    closed = {tf: c.closed(now_ms) for tf, c in btc.items()}
    trends = {}
    for tf in ("4h", "1d", "1h"):
        c = closed.get(tf)
        if c is not None and len(c) >= 60:
            sig = evaluate_tf(compute_indicators(c), len(c) - 1, tf)
            if sig:
                trends[tf] = sig.trend
    up = lambda t: t in ("Yükseliş", "Zayıf yükseliş")  # noqa: E731
    if not trends:
        direction = "Bilinmiyor"
    elif trends.get("4h") == "Düşüş" or (trends.get("1d") == "Düşüş" and not up(trends.get("1h", ""))):
        direction = "Düşüş"
    elif up(trends.get("4h", "")) and up(trends.get("1h", "")):
        direction = "Yükseliş"
    else:
        direction = "Yatay"

    shock, reason, chg1h = False, None, None
    c5 = closed.get("5m")
    if c5 is not None and len(c5) > 13:
        px = c5.close
        chg1h = float((px[-1] / px[-13] - 1) * 100)
        chg15 = float((px[-1] / px[-4] - 1) * 100)
        if chg1h <= -shock_pct:
            shock, reason = True, f"BTC son 1 saatte %{chg1h:.2f} düştü (ani düşüş koruması)"
        elif chg15 <= -shock_pct / 2:
            shock, reason = True, f"BTC son 15 dakikada %{chg15:.2f} düştü (ani düşüş koruması)"
    summary = f"BTC yönü: {direction}" + (f" · 1sa değişim %{chg1h:+.2f}" if chg1h is not None else "")
    return Regime(direction, shock, reason, chg1h, summary)
