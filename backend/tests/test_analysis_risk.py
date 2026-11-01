from app.analysis import Analysis, Analyzer, TargetSettings, label_for
from app.exchanges.base import SymbolInfo
from app.paper import PaperExecutor
from app.risk import PortfolioState, RiskSettings, evaluate_buy, round_step

from .helpers import make_candles

INFO = SymbolInfo("AAAUSDT", "AAA", "USDT", "TRADING", True, step_size=0.001, min_notional=5, min_qty=0.001)


def state(**kw):
    d = dict(equity=1000, cash=1000, day_start_equity=1000, open_symbols=set(), open_exposure=0.0)
    d.update(kw)
    return PortfolioState(**d)


def good(symbol="AAAUSDT", score=80, price=10.0):
    return Analysis(symbol, price, score, label_for(score), "yükseliş", "orta", price, price * 1.03, price * 0.98, 1.0)


def test_labels():
    assert label_for(90) == "Çok güçlü fırsat"
    assert label_for(75) == "Değerlendirilebilir fırsat"
    assert label_for(60) == "Bekle"
    assert label_for(10) == "İşlem yapma"


def test_uptrend_scores_higher_than_downtrend():
    an = Analyzer()
    up = {tf: make_candles(250, 5, 0.002, tf, vol_last=2.5) for tf in ("5m", "15m", "1h", "4h")}
    down = {tf: make_candles(250, 50, -0.002, tf) for tf in ("5m", "15m", "1h", "4h")}
    a_up = an.analyze("UP", up, TargetSettings())
    a_down = an.analyze("DN", down, TargetSettings())
    assert a_up.score > a_down.score
    assert a_up.trend == "yükseliş" and a_down.trend == "düşüş"
    assert a_up.take_profit > a_up.price > a_up.stop_loss
    assert a_up.reasons


def test_insufficient_history_not_tradable():
    data = {tf: make_candles(50, 5, 0.001, tf) for tf in ("5m", "15m", "1h", "4h")}
    a = Analyzer().analyze("NEW", data, TargetSettings())
    assert not a.tradable and a.score == 0


def test_percent_targets():
    data = {tf: make_candles(250, 5, 0.001, tf) for tf in ("5m", "15m", "1h", "4h")}
    a = Analyzer().analyze("X", data, TargetSettings(use_atr_targets=False, take_profit_pct=10, stop_loss_pct=5))
    assert abs(a.take_profit / a.price - 1.10) < 1e-9
    assert abs(a.stop_loss / a.price - 0.95) < 1e-9


def test_risk_approves_and_respects_caps():
    d = evaluate_buy(good(), state(), INFO, 10.0, RiskSettings())
    assert d.approved, d.reasons
    assert d.notional <= 1000 * 0.05 + 1e-6          # tek coin limiti %5
    assert d.expected_net_profit > 0


def test_risk_per_trade_limit():
    # stop çok uzaksa risk %1 ile sınırlanır
    a = good()
    a.stop_loss, a.take_profit = 5.0, 20.0
    d = evaluate_buy(a, state(), INFO, 10.0, RiskSettings(max_per_coin_pct=50, max_total_exposure_pct=100))
    assert d.approved
    loss_at_stop = d.quantity * (d.notional / d.quantity - 5.0)
    assert loss_at_stop <= 10.0 + 0.5   # ~ sermayenin %1'i (+komisyon payı)


def test_risk_rejections():
    s = RiskSettings()
    assert not evaluate_buy(good(score=60), state(), INFO, 10, s).approved
    assert not evaluate_buy(good(), state(open_symbols={"AAAUSDT"}), INFO, 10, s).approved
    assert not evaluate_buy(good(), state(open_symbols={f"X{i}" for i in range(5)}), INFO, 10, s).approved
    assert not evaluate_buy(good(), state(emergency_stop=True), INFO, 10, s).approved
    assert not evaluate_buy(good(), state(halted_reason="API hatası"), INFO, 10, s).approved
    assert not evaluate_buy(good(), state(equity=979, day_start_equity=1000), INFO, 10, s).approved  # %2.1 zarar
    assert not evaluate_buy(good(), state(open_exposure=200), INFO, 10, s).approved                 # %20 dolu
    assert not evaluate_buy(good(), state(), None, 10, s).approved


def test_risk_rejects_when_fees_eat_profit():
    a = good()
    a.take_profit = 10.01  # %0.1 hedef, komisyonlar (%0.2) + kayma bunu yer
    d = evaluate_buy(a, state(), INFO, 10.0, RiskSettings())
    assert not d.approved
    assert any("net kâr" in r for r in d.reasons)


def test_round_step():
    assert round_step(1.23456, 0.001) == 1.234
    assert round_step(0.3, 0.1) == 0.3


async def test_paper_fees_and_slippage():
    ex = PaperExecutor(0.1, 0.05)
    b = await ex.buy("AAAUSDT", 100.0, 1.0)
    assert abs(b.price - 100.05) < 1e-9 and abs(b.fee - 0.10005) < 1e-9 and b.fee_cash == b.fee
    s = await ex.sell("AAAUSDT", 100.0, 1.0)
    assert abs(s.price - 99.95) < 1e-9
    # aynı fiyattan al-sat zarar ettirir (komisyon + kayma)
    assert ex.net_if_sold(100.0, 1.0, b.notional + b.fee) < 0
