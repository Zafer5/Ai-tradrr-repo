"""Geçmiş alım-satım kayıtlarından ortalama maliyet hesabı (saf fonksiyon).

Binance /api/v3/myTrades biçimi: isBuyer, price, qty, quoteQty, commission, commissionAsset, time.
Yaklaşım: ağırlıklı ortalama maliyet. Alımda maliyet artar; satımda ortalama maliyet DEĞİŞMEZ, miktar azalır.
Komisyon: USDT ise maliyete/gelire yansır; coin cinsindense alınan miktardan düşer; BNB vb. ise değeri bilinmediği için
sıfır sayılır ve ``approx`` işaretlenir.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostBasis:
    quantity: float
    avg_cost: float
    realized_pnl: float
    fees_usdt: float
    approx: bool  # komisyon BNB vb. ile ödenmiş: maliyet yaklaşıktır


def compute_cost_basis(trades: list[dict], base_asset: str, quote_asset: str = "USDT") -> CostBasis:
    qty = cost = realized = fees = 0.0
    approx = False
    for t in sorted(trades, key=lambda x: x["time"]):
        p, q, quote_q = float(t["price"]), float(t["qty"]), float(t["quoteQty"])
        comm, comm_asset = float(t.get("commission", 0) or 0), t.get("commissionAsset", "")
        fee_usdt = 0.0
        base_fee = 0.0
        if comm > 0:
            if comm_asset == quote_asset:
                fee_usdt = comm
            elif comm_asset == base_asset:
                base_fee, fee_usdt = comm, comm * p
            else:
                approx = True
        fees += fee_usdt
        if t["isBuyer"]:
            got = q - base_fee
            cost += quote_q + (fee_usdt if comm_asset == quote_asset else 0.0)
            qty += got
        else:
            sold = q + base_fee
            avg = cost / qty if qty > 1e-12 else 0.0
            proceeds = quote_q - (fee_usdt if comm_asset == quote_asset else 0.0)
            realized += proceeds - avg * q
            if qty > 1e-12:
                cost -= avg * min(sold, qty)
            qty = max(0.0, qty - sold)
    avg_cost = cost / qty if qty > 1e-12 else 0.0
    return CostBasis(qty, avg_cost, realized, fees, approx)


def history_matches(computed_qty: float, actual_qty: float, tol: float = 0.02) -> bool:
    """Hesaplanan miktar gerçek bakiyeyle uyuşuyorsa geçmiş eksiksizdir."""
    if actual_qty <= 0:
        return computed_qty <= 0
    return abs(computed_qty - actual_qty) / actual_qty <= tol
