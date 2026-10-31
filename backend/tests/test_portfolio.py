import pytest

from app.portfolio.costbasis import compute_cost_basis, history_matches
from app.portfolio.manager import HoldingState, MarketView, decide
from app.trading_settings import TradingSettings

S = TradingSettings()


def tr(buy, price, qty, t, comm=0.0, asset="USDT"):
    return {"isBuyer": buy, "price": str(price), "qty": str(qty), "quoteQty": str(price * qty), "commission": str(comm), "commissionAsset": asset, "time": t}


def test_cost_basis_weighted_average_and_realized():
    cb = compute_cost_basis([tr(True, 100, 1, 1, 0.1), tr(True, 200, 1, 2, 0.2), tr(False, 300, 1, 3, 0.3)], "ABC")
    # alım maliyeti: (100+0.1)+(200+0.2)=300.3 ; ort 150.15 ; satış geliri 300-0.3=299.7 -> kâr 149.55
    assert cb.quantity == pytest.approx(1.0) and cb.avg_cost == pytest.approx(150.15)
    assert cb.realized_pnl == pytest.approx(299.7 - 150.15) and cb.fees_usdt == pytest.approx(0.6) and not cb.approx


def test_cost_basis_base_asset_commission_reduces_quantity_and_bnb_is_approx():
    cb = compute_cost_basis([tr(True, 100, 1, 1, 0.001, "ABC")], "ABC")
    assert cb.quantity == pytest.approx(0.999) and cb.avg_cost == pytest.approx(100 / 0.999)
    assert compute_cost_basis([tr(True, 100, 1, 1, 0.01, "BNB")], "ABC").approx


def test_history_matches_detects_missing_history():
    assert history_matches(1.0, 1.01) and not history_matches(0.5, 1.0)


def hs(**kw):
    d = dict(quantity=10, avg_cost=100.0, peak=100.0, trailing_active=False)
    d.update(kw)
    return HoldingState(**d)


def test_underwater_holding_is_never_sold_automatically_by_default():
    d = decide(hs(), 80.0, MarketView(score=20, trend="Düşüş", downside_risk=90), S)
    assert d.action == "HOLD" and d.fraction == 0
    d2 = decide(hs(), 80.0, MarketView(shock=True), S)
    assert d2.action == "HOLD"


def test_user_defined_stop_limit_triggers():
    d = decide(hs(), 85.0, MarketView(), TradingSettings(holding_stop_pct=10))
    assert d.action == "STOP" and d.fraction == 1.0


def test_take_profit_when_target_reached_and_weak_momentum():
    d = decide(hs(), 106.0, MarketView(score=55, sell_fit=60, trend="Yatay"), S)
    assert d.action == "TAKE_PROFIT" and d.fraction == 0.5 and d.net_pct > 0


def test_strong_trend_defers_profit_taking():
    d = decide(hs(), 106.0, MarketView(score=82, sell_fit=10, trend="Yükseliş"), S)
    assert d.action == "HOLD" and "trailing" in d.reason.lower()


def test_trailing_exit_never_below_breakeven():
    h = hs(peak=110.0, trailing_active=True)
    d = decide(h, 108.0, MarketView(score=50, sell_fit=20), S)  # zirvenin %1.5'i = 108.35 -> tetiklenir
    assert d.action == "TRAIL_EXIT" and d.net_pct > 0
    d2 = decide(hs(peak=104.5, trailing_active=True), 103.0, MarketView(), S)
    assert d2.trail_stop >= 100 * 1.001 / 0.999  # başa baş altında stop yok


def test_market_shock_reduces_risk_only_when_in_profit():
    assert decide(hs(), 110.0, MarketView(shock=True), S).action == "REDUCE_RISK"
    assert decide(hs(), 99.0, MarketView(shock=True), S).action == "HOLD"


def test_unknown_cost_asks_for_manual_entry():
    d = decide(hs(cost_known=False, avg_cost=0), 50.0, MarketView(), S)
    assert d.action == "NO_COST" and "elle" in d.reason
