import numpy as np
import pytest

import app.backtest.engine as bt
from app.analysis.engine import Composite
from app.backtest.engine import simulate, walk_forward
from app.exchange.types import Candles
from app.trading_settings import TradingSettings
from tests.synth import make_multi_tf


@pytest.fixture(scope="module")
def data():
    return make_multi_tf(days=75, drift_per_hour=0.0002, vol_per_sqrt_hour=0.006, seed=21)


def cut(candles: dict[str, Candles], t: int) -> dict[str, Candles]:
    out = {}
    for tf, c in candles.items():
        m = c.close_time <= t
        out[tf] = Candles(*(getattr(c, n)[m] for n in ("open_time", "open", "high", "low", "close", "volume", "close_time")))
    return out


S = TradingSettings(buy_score_threshold=60)


def test_backtest_accounting_identity(data):
    r = simulate(data, S)
    assert r.metrics["trades"] >= 0
    total = sum(t.pnl for t in r.trades)
    assert r.equity[-1] - r.initial == pytest.approx(total, abs=1e-6)
    assert r.metrics["net_pnl"] == pytest.approx(total, abs=1e-6)


def test_no_lookahead_decisions_do_not_depend_on_future_data(data):
    """Veriyi T anında kesince, T'ye kadarki equity eğrisi AYNI kalmalı (gelecek bilgisi kullanılmıyor)."""
    base = data["15m"]
    T = int(base.close_time[int(len(base) * 0.8)])
    full = simulate(data, S, end_ms=T)
    short = simulate(cut(data, T), S)
    k = len(short.equity) - 1  # son eleman zorunlu kapanıştan etkilenir
    assert k > 100
    assert np.allclose(full.equity[:k], short.equity[:k], rtol=0, atol=1e-9)
    assert [t.entry_time for t in full.trades if t.exit_time <= short.times[k - 1]] == [t.entry_time for t in short.trades if t.exit_time <= short.times[k - 1]]


def force_signal(monkeypatch):
    def fake_compose(signals, spread_pct=None):
        return Composite(100.0, "Çok güçlü fırsat", "Yükseliş", "Düşük", [], [])

    monkeypatch.setattr(bt, "compose", fake_compose)


def test_exit_mechanics_with_forced_entries(monkeypatch):
    """Giriş sinyali zorlanır; stop/hedef/trailing mekaniği ve maliyetli muhasebe doğrulanır."""
    force_signal(monkeypatch)
    d = make_multi_tf(days=75, drift_per_hour=0.0, vol_per_sqrt_hour=0.012, seed=5)
    s = TradingSettings(buy_score_threshold=50, cooldown_minutes=0, max_trades_per_day=500)
    r = simulate(d, s)
    assert r.metrics["trades"] > 15
    reasons = {t.reason for t in r.trades}
    assert reasons <= {"STOP_LOSS", "TAKE_PROFIT_2", "TAKE_PROFIT_1", "TRAILING_STOP", "BREAKEVEN_STOP", "BACKTEST_END"}
    stops = [t for t in r.trades if t.reason == "STOP_LOSS"]
    assert stops and all(t.pnl < 0 for t in stops)
    # işlem başına risk bütçesi (%1) gap payıyla aşılmaz
    assert min(t.pnl for t in r.trades) >= -r.initial * 0.01 * 2.0
    # tek coine %5 sınırı: hiçbir işlemin maliyeti %5 sermayeyi aşamaz
    assert all(t.qty * t.entry <= r.initial * 3 * 0.05 + 1 for t in r.trades)  # bileşik büyüme payı
    wins = [t for t in r.trades if t.reason in ("TAKE_PROFIT_2", "TRAILING_STOP")]
    assert all(t.pnl > 0 for t in wins), [(t.reason, t.pnl) for t in wins if t.pnl <= 0]


def test_costs_reduce_results(monkeypatch):
    force_signal(monkeypatch)
    d = make_multi_tf(days=60, drift_per_hour=0.0, vol_per_sqrt_hour=0.01, seed=8)
    free = simulate(d, TradingSettings(buy_score_threshold=50, cooldown_minutes=0, fee_rate_pct=0, slippage_pct=0, min_net_profit_pct=0.05, min_risk_reward=0.3))
    costly = simulate(d, TradingSettings(buy_score_threshold=50, cooldown_minutes=0, fee_rate_pct=0.5, slippage_pct=0.3, min_net_profit_pct=0.05, min_risk_reward=0.3))
    assert free.metrics["net_return_pct"] > costly.metrics["net_return_pct"]


def test_walk_forward_selects_threshold_on_train_only(data):
    wf = walk_forward(data, TradingSettings(), split=0.6, thresholds=(55, 60, 65))
    assert wf.chosen_threshold in (55, 60, 65)
    assert set(wf.train_grid) == {55, 60, 65}
    # test dilimi eğitim bitiminden SONRA başlar
    assert wf.test.times[0] > wf.train.times[-1]
    for m in (wf.train.metrics, wf.test.metrics):
        assert {"net_return_pct", "max_drawdown_pct", "profit_factor", "win_rate", "buy_and_hold_pct"} <= set(m)
        assert m["max_drawdown_pct"] >= 0
