"""Bağımsız risk yönetimi.

Analiz motoru ne derse desin, bir alım ancak buradaki TÜM kontrollerden
geçerse yapılır. Bu modül emir göndermez; yalnızca onay/ret ve miktar verir.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from decimal import Decimal, ROUND_DOWN

from .analysis import Analysis
from .exchanges.base import SymbolInfo


@dataclass
class RiskSettings:
    risk_per_trade_pct: float = 1.0       # işlem başına azami risk (sermayenin %)
    daily_loss_limit_pct: float = 2.0     # günlük zarar limiti (%)
    max_open_positions: int = 5
    max_per_coin_pct: float = 5.0         # tek coine ayrılabilecek azami sermaye (%)
    max_total_exposure_pct: float = 20.0  # toplam açık pozisyon büyüklüğü (%)
    min_score: int = 70                   # alım için gereken en düşük analiz puanı
    fee_pct: float = 0.1                  # işlem başına komisyon (%)
    slippage_pct: float = 0.05            # tahmini fiyat kayması (%)
    max_order_usdt: float = 0.0            # tek alımın USDT üst sınırı (0 = yok; canlı modda zorunlu uygulanır)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PortfolioState:
    equity: float
    cash: float
    day_start_equity: float
    open_symbols: set[str]
    open_exposure: float           # açık pozisyonların güncel toplam değeri
    bot_running: bool = True
    emergency_stop: bool = False
    halted_reason: str | None = None


@dataclass
class RiskDecision:
    approved: bool
    quantity: float = 0.0
    notional: float = 0.0
    expected_fee: float = 0.0
    expected_net_profit: float = 0.0
    reasons: list[str] = field(default_factory=list)


def round_step(qty: float, step: float) -> float:
    if step <= 0:
        return qty
    q = (Decimal(str(qty)) / Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN) * Decimal(str(step))
    return float(q)


def daily_loss_hit(state: PortfolioState, s: RiskSettings) -> bool:
    if state.day_start_equity <= 0:
        return False
    loss_pct = (state.day_start_equity - state.equity) / state.day_start_equity * 100
    return loss_pct >= s.daily_loss_limit_pct


def evaluate_buy(a: Analysis, state: PortfolioState, info: SymbolInfo | None, ask: float, s: RiskSettings) -> RiskDecision:
    no: list[str] = []
    if state.emergency_stop:
        no.append("Acil durdurma aktif")
    if not state.bot_running:
        no.append("Bot kapalı")
    if state.halted_reason:
        no.append(f"Sistem durduruldu: {state.halted_reason}")
    if daily_loss_hit(state, s):
        no.append(f"Günlük zarar limiti (%{s.daily_loss_limit_pct}) aşıldı")
    if not a.tradable:
        no.append("Analiz verisi yetersiz")
    if a.score < s.min_score:
        no.append(f"Puan yetersiz ({a.score} < {s.min_score})")
    if a.symbol in state.open_symbols:
        no.append("Bu coinde zaten açık pozisyon var (mükerrer emir engeli)")
    if len(state.open_symbols) >= s.max_open_positions:
        no.append(f"Azami açık pozisyon sayısına ulaşıldı ({s.max_open_positions})")
    if info is None:
        no.append("Coin işlem kuralları bilinmiyor")
    if ask <= 0 or math.isnan(ask):
        no.append("Geçerli fiyat yok")
    if a.stop_loss <= 0 or a.stop_loss >= ask:
        no.append("Stop-loss seviyesi geçersiz")
    if a.take_profit <= ask:
        no.append("Kâr hedefi mevcut fiyatın üzerinde değil")
    if no:
        return RiskDecision(False, reasons=no)

    fee = s.fee_pct / 100
    slip = s.slippage_pct / 100
    fill = ask * (1 + slip)
    per_unit_risk = (fill - a.stop_loss * (1 - slip)) + fill * fee + a.stop_loss * fee
    risk_amount = state.equity * s.risk_per_trade_pct / 100
    qty = risk_amount / per_unit_risk

    caps = {
        "tek coin limiti": state.equity * s.max_per_coin_pct / 100,
        "toplam maruziyet limiti": state.equity * s.max_total_exposure_pct / 100 - state.open_exposure,
        "nakit bakiye": state.cash / (1 + fee),
    }
    if s.max_order_usdt > 0:
        caps["emir üst sınırı"] = s.max_order_usdt
    notional = qty * fill
    limit_name = None
    for name, cap in caps.items():
        if notional > cap:
            notional, limit_name = max(cap, 0.0), name
    qty = round_step(notional / fill, info.step_size)
    notional = qty * fill
    reasons = [f"Risk tutarı {risk_amount:.2f} USDT (sermayenin %{s.risk_per_trade_pct})"]
    if limit_name:
        reasons.append(f"Miktar '{limit_name}' ile sınırlandı")

    min_notional = max(info.min_notional, 5.0)
    if qty <= 0 or qty < info.min_qty or notional < min_notional:
        return RiskDecision(False, reasons=reasons + [f"İşlem tutarı çok küçük ({notional:.2f} USDT < {min_notional})"])

    buy_fee = notional * fee
    exit_px = a.take_profit * (1 - slip)
    sell_fee = qty * exit_px * fee
    net = qty * exit_px - sell_fee - notional - buy_fee
    if net <= 0:
        return RiskDecision(False, reasons=reasons + ["Hedefte bile komisyon ve kayma sonrası net kâr pozitif değil"])

    reasons.append(f"Hedefte tahmini net kâr {net:.2f} USDT")
    return RiskDecision(True, qty, notional, buy_fee + sell_fee, net, reasons)
