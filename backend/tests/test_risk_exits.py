import pytest

from app.exchange.types import SymbolInfo
from app.risk.manager import AccountSnapshot, EntryRequest, SystemFlags, evaluate_entry
from app.trading.exits import PosState, breakeven_price, evaluate_exit
from app.trading_settings import TradingSettings

S = TradingSettings()


def acct(**kw):
    d = dict(equity=1000.0, cash=1000.0, open_positions={}, day_pnl_pct=0.0, trades_today=0)
    d.update(kw)
    return AccountSnapshot(**d)


def req(**kw):
    d = dict(symbol="ABCUSDT", score=80, risk_level="Orta", eligible=True, spread_pct=0.03, entry=100.0, stop=98.5, tp1=103.0, tp2=106.0)
    d.update(kw)
    return EntryRequest(**d)


def test_happy_path_sizing_respects_all_caps():
    d = evaluate_entry(req(), acct(), SystemFlags(), S)
    assert d.approved, d.reasons
    # %5 tek-coin limiti = 50 USDT baskın (risk limiti 1% = 10 USDT / ~1.7 = ~590 USDT notional olurdu)
    assert d.notional <= 50.0 + 1e-9 and abs(d.notional - 50.0) < 0.5
    assert d.risk_amount <= 1000 * S.risk_per_trade_pct / 100 + 1e-9
    assert d.quantity * 100 == pytest.approx(d.notional)


@pytest.mark.parametrize("kw,needle", [
    (dict(score=69), "AI puanı"),
    (dict(risk_level="Yüksek"), "Risk seviyesi yüksek"),
    (dict(spread_pct=0.5), "Spread"),
    (dict(spread_pct=None), "Spread"),
    (dict(eligible=False), "uygun değil"),
    (dict(stop=101.0), "geçersiz"),
    (dict(tp1=100.3, tp2=101), "net kâr"),
])
def test_request_level_rejections(kw, needle):
    d = evaluate_entry(req(**kw), acct(), SystemFlags(), S)
    assert not d.approved and any(needle in r for r in d.reasons), d.reasons
    assert d.quantity == 0


@pytest.mark.parametrize("a_kw,needle", [
    (dict(day_pnl_pct=-2.0), "Günlük zarar limiti"),
    (dict(trades_today=20), "Günlük azami işlem"),
    (dict(open_positions={"ABCUSDT": 40.0}), "mükerrer"),
    (dict(in_flight={"ABCUSDT"}), "mükerrer"),
    (dict(cooldown_symbols={"ABCUSDT"}), "bekleme"),
    (dict(open_positions={f"C{i}USDT": 10.0 for i in range(5)}), "Azami açık pozisyon"),
    (dict(open_positions={"X1USDT": 100.0, "X2USDT": 100.0}), "maruziyet"),
])
def test_account_level_rejections(a_kw, needle):
    d = evaluate_entry(req(), acct(**a_kw), SystemFlags(), S)
    assert not d.approved and any(needle in r for r in d.reasons), d.reasons


def test_emergency_and_safe_mode_block_everything():
    assert not evaluate_entry(req(), acct(), SystemFlags(emergency_stop=True), S).approved
    d = evaluate_entry(req(), acct(), SystemFlags(safe_mode_reason="API hatası"), S)
    assert not d.approved and "Güvenli mod" in d.reasons[0]


def test_total_exposure_cap_limits_size():
    d = evaluate_entry(req(), acct(open_positions={"A": 80.0, "B": 80.0, "C": 30.0}), SystemFlags(), S)  # %19 dolu
    assert d.approved and d.notional <= 1000 * 0.20 - 190 + 1e-6 + 1  # ~10 USDT kaldı
    assert d.notional < 15


def test_min_notional_and_step_size_from_exchange_info():
    info = SymbolInfo("ABCUSDT", "ABC", "USDT", "TRADING", True, step_size=0.1, min_qty=0.1, min_notional=100.0)
    d = evaluate_entry(req(), acct(), SystemFlags(), S, info)
    assert not d.approved and any("asgari tutarın" in r for r in d.reasons)
    info2 = SymbolInfo("ABCUSDT", "ABC", "USDT", "TRADING", True, step_size=0.1, min_qty=0.1, min_notional=5.0)
    d2 = evaluate_entry(req(), acct(), SystemFlags(), S, info2)
    assert d2.approved and abs(d2.quantity / 0.1 - round(d2.quantity / 0.1)) < 1e-6


def test_daily_loss_limit_boundary():
    assert evaluate_entry(req(), acct(day_pnl_pct=-1.99), SystemFlags(), S).approved
    assert not evaluate_entry(req(), acct(day_pnl_pct=-2.0), SystemFlags(), S).approved


def test_settings_validation():
    with pytest.raises(ValueError):
        TradingSettings(tp1_rr=3.0, tp2_rr=2.0)
    with pytest.raises(ValueError):
        TradingSettings(max_symbol_alloc_pct=30, max_total_exposure_pct=20)
    with pytest.raises(ValueError):
        TradingSettings(risk_per_trade_pct=50)


# ----------------------------------------------------------------------- çıkış kuralları
def ps(**kw):
    d = dict(entry=100.0, qty=1.0, stop=98.5, tp1=103.0, tp2=106.0, tp1_done=False, peak=100.0, trailing_active=False)
    d.update(kw)
    return PosState(**d)


def test_stop_loss_sells_everything_at_market():
    ev = evaluate_exit(ps(), 98.4, S)
    assert ev.action.reason == "STOP_LOSS" and ev.action.fraction == 1.0 and ev.action.order_type == "MARKET"
    assert evaluate_exit(ps(), 98.6, S).action is None


def test_tp1_sells_fraction_then_stop_moves_to_breakeven():
    ev = evaluate_exit(ps(), 103.2, S)
    assert ev.action.reason == "TAKE_PROFIT_1" and ev.action.fraction == 0.5 and ev.action.order_type == "LIMIT" and ev.action.ref_price == 103.0
    be = breakeven_price(100.0, 0.001, 0.0005)
    after = ps(tp1_done=True, qty=0.5, peak=103.2, trailing_active=True)
    ev2 = evaluate_exit(after, be - 0.01, S)
    assert ev2.action and ev2.action.reason in ("BREAKEVEN_STOP", "TRAILING_STOP")
    assert ev2.effective_stop >= be


def test_trailing_stop_never_sells_below_breakeven_so_net_profit_is_positive():
    be = breakeven_price(100.0, 0.001, 0.0005)
    # fiyat 101.6'ya çıktı (trailing devreye girdi), sonra düşüyor
    p = ps(peak=101.6, trailing_active=True)
    ev = evaluate_exit(p, 100.9, S)  # zirveden %0.8 = 100.787 -> be(100.25) üstünde
    assert ev.action is None or ev.action.reason == "TRAILING_STOP"
    assert ev.effective_stop >= be
    ev2 = evaluate_exit(ps(peak=101.5, trailing_active=True), 100.5, S)
    assert ev2.effective_stop >= be


def test_trailing_activates_only_after_threshold():
    ev = evaluate_exit(ps(), 101.0, S)
    assert not ev.trailing_active
    ev = evaluate_exit(ps(), 101.6, S)
    assert ev.trailing_active and ev.peak == 101.6


def test_tp2_closes_remaining_and_price_gap_over_tp2_sells_all():
    ev = evaluate_exit(ps(tp1_done=True, qty=0.5, peak=104, trailing_active=True), 106.5, S)
    assert ev.action.reason == "TAKE_PROFIT_2" and ev.action.fraction == 1.0
    ev = evaluate_exit(ps(), 107.0, S)  # TP1 işlenmeden doğrudan TP2 üstüne gap
    assert ev.action.reason == "TAKE_PROFIT_2"


def test_target_sell_requires_net_positive():
    """Hedef yanlışlıkla başa baş fiyatının altına ayarlanmışsa bile zararına satılmaz."""
    p = ps(tp1=100.05, tp2=100.1, stop=95)
    assert evaluate_exit(p, 100.2, S).action is None
    assert evaluate_exit(p, 100.5, S).action is not None


def test_breakeven_price_formula():
    assert breakeven_price(100, 0.001, 0) == pytest.approx(100 * 1.001 / 0.999)
    assert breakeven_price(100, 0, 0) == 100
