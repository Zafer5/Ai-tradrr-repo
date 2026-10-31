"""Bağımsız risk yöneticisi.

AI analizi TEK BAŞINA emir gönderemez: her alım bu modülden geçer ve herhangi bir kural reddederse
emir oluşmaz. Bu modül analiz motorunu import etmez; yalnızca sayısal girdilerle çalışır.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..exchange.types import SymbolInfo
from ..trading_settings import TradingSettings


@dataclass
class AccountSnapshot:
    equity: float
    cash: float
    open_positions: dict[str, float]  # sembol -> güncel pozisyon değeri (USDT)
    day_pnl_pct: float
    trades_today: int
    cooldown_symbols: set[str] = field(default_factory=set)
    in_flight: set[str] = field(default_factory=set)

    @property
    def exposure(self) -> float:
        return sum(self.open_positions.values())


@dataclass
class SystemFlags:
    emergency_stop: bool = False
    safe_mode_reason: str | None = None  # API hatası / belirsiz durum => yeni emir yok


@dataclass
class EntryRequest:
    symbol: str
    score: float
    risk_level: str
    eligible: bool
    spread_pct: float | None
    entry: float  # tahmini dolum fiyatı (ask + kayma)
    stop: float
    tp1: float
    tp2: float


@dataclass
class RiskDecision:
    approved: bool
    reasons: list[str]
    quantity: float = 0.0
    notional: float = 0.0
    risk_amount: float = 0.0
    est_fees: float = 0.0
    net_pct_tp1: float = 0.0
    risk_reward: float = 0.0

    def to_dict(self) -> dict:
        return {k: (round(v, 8) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def floor_to_step(qty: float, step: float) -> float:
    if step <= 0:
        return qty
    return math.floor(qty / step + 1e-9) * step


def evaluate_entry(req: EntryRequest, acct: AccountSnapshot, flags: SystemFlags, s: TradingSettings, info: SymbolInfo | None = None) -> RiskDecision:
    reasons: list[str] = []
    fee = s.fee_rate_pct / 100
    slip = s.slippage_pct / 100

    # ---- Sistem durumu ----
    if flags.emergency_stop:
        reasons.append("Acil durdurma aktif")
    if flags.safe_mode_reason:
        reasons.append(f"Güvenli mod: {flags.safe_mode_reason}")

    # ---- AI çıktısı kalite kapısı ----
    if not req.eligible:
        reasons.append("Analiz uygun değil")
    if req.score < s.buy_score_threshold:
        reasons.append(f"AI puanı {req.score:.0f} < eşik {s.buy_score_threshold:.0f}")
    if req.risk_level == "Yüksek" and not s.allow_high_risk:
        reasons.append("Risk seviyesi yüksek")
    if req.spread_pct is None or req.spread_pct > s.max_spread_pct:
        reasons.append(f"Spread uygun değil ({'veri yok' if req.spread_pct is None else f'%{req.spread_pct:.3f}'})")

    # ---- Hesap / limitler ----
    if acct.day_pnl_pct <= -s.daily_loss_limit_pct:
        reasons.append(f"Günlük zarar limiti aşıldı (%{acct.day_pnl_pct:.2f})")
    if acct.trades_today >= s.max_trades_per_day:
        reasons.append("Günlük azami işlem sayısına ulaşıldı")
    if req.symbol in acct.open_positions or req.symbol in acct.in_flight:
        reasons.append("Bu coinde zaten açık pozisyon / bekleyen emir var (mükerrer emir engeli)")
    if req.symbol in acct.cooldown_symbols:
        reasons.append("Coin yakın zamanda kapatıldı (bekleme süresi)")
    if len(acct.open_positions) >= s.max_open_positions:
        reasons.append(f"Azami açık pozisyon sayısına ulaşıldı ({s.max_open_positions})")

    # ---- Geometri doğrulaması ----
    if not (req.stop < req.entry < req.tp1 < req.tp2) or req.entry <= 0:
        reasons.append("Stop/hedef seviyeleri geçersiz")
        return RiskDecision(False, reasons)

    # ---- Maliyet dahil birim kazanç / kayıp (net) ----
    loss_per_unit = req.entry * (1 + fee) - req.stop * (1 - fee) * (1 - slip)  # stop piyasa emriyle çalışır
    gain_per_unit = req.tp1 * (1 - fee) - req.entry * (1 + fee)  # hedef limit emriyle çalışır
    net_pct = gain_per_unit / req.entry * 100
    rr = gain_per_unit / loss_per_unit if loss_per_unit > 0 else 0.0
    if net_pct < s.min_net_profit_pct:
        reasons.append(f"1. hedefte komisyon+kayma sonrası net kâr %{net_pct:.2f} < asgari %{s.min_net_profit_pct:.2f}")
    if rr < s.min_risk_reward:
        reasons.append(f"Net risk/getiri {rr:.2f} < asgari {s.min_risk_reward:.2f}")

    # ---- Pozisyon büyüklüğü ----
    equity = max(acct.equity, 0.0)
    risk_amount = equity * s.risk_per_trade_pct / 100
    qty_by_risk = risk_amount / loss_per_unit if loss_per_unit > 0 else 0.0
    cap_symbol = equity * s.max_symbol_alloc_pct / 100
    cap_exposure = equity * s.max_total_exposure_pct / 100 - acct.exposure
    cap_cash = acct.cash * 0.995  # komisyon payı
    notional = max(0.0, min(qty_by_risk * req.entry, cap_symbol, cap_exposure, cap_cash))
    if cap_exposure <= 0:
        reasons.append(f"Toplam maruziyet limiti dolu (%{s.max_total_exposure_pct:.0f})")

    qty = notional / req.entry if req.entry > 0 else 0.0
    if info and info.step_size > 0:
        qty = floor_to_step(qty, info.step_size)
    if info and info.min_qty > 0 and qty < info.min_qty:
        qty = 0.0
    notional = qty * req.entry
    min_notional = info.min_notional if info and info.min_notional > 0 else 5.0
    if notional < min_notional:
        reasons.append(f"Hesaplanan işlem tutarı ({notional:.2f} USDT) asgari tutarın ({min_notional:.2f}) altında")

    est_fees = notional * fee + qty * req.tp1 * fee
    approved = not reasons
    return RiskDecision(
        approved=approved, reasons=reasons if reasons else ["Tüm risk kontrolleri geçti"],
        quantity=qty if approved else 0.0, notional=notional if approved else 0.0,
        risk_amount=qty * loss_per_unit if approved else 0.0, est_fees=est_fees,
        net_pct_tp1=net_pct, risk_reward=rr,
    )
