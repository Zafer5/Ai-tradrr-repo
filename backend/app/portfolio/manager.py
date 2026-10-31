"""Mevcut coin (portföy) yönetimi kararları - saf fonksiyon, emir göndermez.

Kurallar:
* Zararda olan coin, kullanıcı 'zarar sınırı' tanımlamadıkça OTOMATİK SATILMAZ; yalnızca uyarılır.
* Kâr satışları komisyon+kayma sonrası net kâr pozitifken yapılır.
* Hedef, piyasa koşuluna göre ayarlanır (trend güçlüyse uzar, zayıflıyorsa kısalır).
* Trailing stop, başa baş fiyatının altına inmez.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..trading.exits import breakeven_price
from ..trading_settings import TradingSettings


@dataclass
class HoldingState:
    quantity: float
    avg_cost: float
    peak: float
    trailing_active: bool
    cost_known: bool = True
    tp_done: bool = False


@dataclass
class MarketView:
    """Analiz motorundan özet (yoksa None alanlar)."""

    score: float | None = None
    trend: str | None = None
    sell_fit: float | None = None
    downside_risk: float | None = None
    risk: str | None = None
    shock: bool = False
    btc_direction: str | None = None


@dataclass
class HoldingDecision:
    action: str  # HOLD | TAKE_PROFIT | TRAIL_EXIT | REDUCE_RISK | STOP | NO_COST
    fraction: float
    reason: str
    target_price: float | None
    trail_stop: float | None
    net_pct: float | None
    peak: float
    trailing_active: bool


def adaptive_target_pct(base: float, mv: MarketView) -> float:
    if mv.score is not None and mv.score >= 70 and (mv.sell_fit or 0) < 40:
        return base * 1.5  # güçlü trend: hedefi uzat
    if (mv.sell_fit or 0) >= 60 or mv.trend == "Düşüş" or mv.shock:
        return max(1.5, base * 0.6)  # zayıflayan piyasa: hedefi yaklaştır
    return base


def decide(h: HoldingState, price: float, mv: MarketView, s: TradingSettings) -> HoldingDecision:
    fee, slip = s.fee_rate_pct / 100, s.slippage_pct / 100
    peak = max(h.peak, price)
    if not h.cost_known or h.avg_cost <= 0:
        return HoldingDecision("NO_COST", 0, "Ortalama maliyet bilinmiyor: kâr/zarar hesaplanamaz. Lütfen maliyeti elle girin.", None, None, None, peak, h.trailing_active)

    be = breakeven_price(h.avg_cost, fee, slip)
    net_pct = (price * (1 - fee) * (1 - slip) / h.avg_cost - 1) * 100
    tp_pct = adaptive_target_pct(s.holding_target_pct, mv)
    target = max(h.avg_cost * (1 + tp_pct / 100), be * 1.003)
    trailing = h.trailing_active or peak >= h.avg_cost * (1 + s.holding_trail_activation_pct / 100)
    trail_stop = max(peak * (1 - s.holding_trail_distance_pct / 100), be) if trailing else None

    def d(action, fraction, reason):
        return HoldingDecision(action, fraction, reason, target, trail_stop, net_pct, peak, trailing)

    # 1) Zarar sınırı (yalnızca kullanıcı tanımladıysa)
    if s.holding_stop_pct > 0 and net_pct <= -s.holding_stop_pct:
        return d("STOP", 1.0, f"Zarar sınırına ulaşıldı (net %{net_pct:.1f} ≤ -%{s.holding_stop_pct:.1f}): pozisyon kapatılıyor.")

    # 2) Trailing stop (kâr korunuyor)
    if trailing and trail_stop is not None and price <= trail_stop:
        return d("TRAIL_EXIT", 1.0, f"Fiyat zirveden ({peak:.6g}) geri çekildi; kâr korumak için trailing stop ({trail_stop:.6g}) çalıştı. Net kâr yaklaşık %{net_pct:.1f}.")

    # 3) Piyasa şoku / sert zayıflama: kâr varsa riski azalt, zarardaysa yalnızca uyar
    weak = mv.shock or ((mv.downside_risk or 0) >= 70 and mv.trend == "Düşüş")
    if weak:
        if net_pct > 0.3:
            why = "Piyasada ani düşüş alarmı var" if mv.shock else "Düşüş riski yüksek ve trend aşağı"
            return d("REDUCE_RISK", 0.5, f"{why}: kâr varken (net %{net_pct:.1f}) pozisyonun yarısı satılarak risk azaltılıyor.")
        return d("HOLD", 0, f"Piyasa zayıf ve pozisyon zararda/başa başta (net %{net_pct:.1f}). Zararına otomatik satış yapılmıyor; dikkatle izleniyor.")

    # 4) Hedef kâr (kısmi satış yalnızca BİR kez; kalan miktar trailing stop ile korunur)
    if price >= target and net_pct > 0 and h.tp_done:
        return d("HOLD", 0, f"Hedefte kısmi satış yapıldı; kalan miktar trailing stop ({trail_stop:.6g}) ile korunuyor, net kâr %{net_pct:.1f}." if trail_stop else f"Hedefte kısmi satış yapıldı; kalan miktar izleniyor (net %{net_pct:.1f}).")
    if price >= target and net_pct > 0:
        if mv.score is not None and mv.score >= 70 and (mv.sell_fit or 0) < 40:
            return d("HOLD", 0, f"Hedefe ({target:.6g}) ulaşıldı ama trend hâlâ güçlü (puan {mv.score:.0f}); satış yerine trailing stop ile kâr korunarak devam ediliyor.")
        return d("TAKE_PROFIT", s.holding_sell_fraction, f"Hedef kâr (%{tp_pct:.1f}) oluştu, net kâr %{net_pct:.1f}; satış uygunluğu {mv.sell_fit if mv.sell_fit is not None else '-'}. Pozisyonun %{s.holding_sell_fraction * 100:.0f}'i satılıyor.")

    state = "kârda" if net_pct > 0 else "zararda"
    return d("HOLD", 0, f"Pozisyon {state} (net %{net_pct:.1f}). Hedef {target:.6g}" + (f", trailing stop {trail_stop:.6g}" if trail_stop else "") + ". Beklemede.")
