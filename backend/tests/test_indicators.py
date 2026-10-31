import numpy as np

from app.analysis.engine import evaluate_tf
from app.analysis.indicators import atr, bollinger, compute_indicators, ema, macd, rsi, support_resistance, volume_ratio
from tests.synth import make_candles


def test_ema_constant_series():
    out = ema(np.full(50, 7.0), 9)
    assert np.isnan(out[7]) and np.allclose(out[8:], 7.0)


def test_ema_matches_manual_calculation():
    x = np.array([1, 2, 3, 4, 5, 6], dtype=float)
    out = ema(x, 3)  # seed = SMA(1,2,3)=2 ; alpha=0.5
    assert out[2] == 2.0
    assert out[3] == 0.5 * 4 + 0.5 * 2
    assert out[4] == 0.5 * 5 + 0.5 * 3


def test_rsi_extremes_and_range():
    up = np.arange(1, 60, dtype=float)
    assert rsi(up)[-1] == 100.0
    down = np.arange(60, 1, -1, dtype=float)
    assert rsi(down)[-1] < 1e-9
    r = rsi(make_candles(300, drift=0, seed=3).close)
    assert np.nanmin(r) >= 0 and np.nanmax(r) <= 100


def test_rsi_known_value_wilder():
    # Klasik örnek (Wilder / StockCharts): RSI(14) ilk değeri ~70.46
    close = np.array([44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28], dtype=float)
    assert abs(rsi(close)[14] - 70.46) < 0.1


def test_macd_hist_is_line_minus_signal():
    c = make_candles(200, seed=5).close
    line, sig, hist = macd(c)
    i = 150
    assert abs(hist[i] - (line[i] - sig[i])) < 1e-12
    assert np.isnan(line[24]) and not np.isnan(line[25])


def test_bollinger_bands_symmetric():
    c = make_candles(100, seed=2).close
    mid, up, low = bollinger(c)
    assert np.allclose(up[30] - mid[30], mid[30] - low[30])


def test_atr_constant_range():
    n = 60
    high, low, close = np.full(n, 11.0), np.full(n, 9.0), np.full(n, 10.0)
    assert abs(atr(high, low, close)[-1] - 2.0) < 1e-9


def test_volume_ratio_uses_only_previous_candles():
    v = np.ones(30)
    v[25] = 5.0
    vr = volume_ratio(v, 20)
    assert abs(vr[25] - 5.0) < 1e-9  # öncekilerin ortalaması 1
    assert np.isnan(vr[19])


def test_indicators_are_causal_no_lookahead():
    """KRİTİK: i. mumdaki gösterge değeri, i'den sonraki verilerden etkilenmemeli."""
    full = make_candles(400, "1h", drift=0.0005, seed=11)
    i = 300
    cut = make_candles(400, "1h", drift=0.0005, seed=11)
    for name in ("open", "high", "low", "close", "volume", "open_time", "close_time"):
        setattr(cut, name, getattr(cut, name)[: i + 1])
    a, b = compute_indicators(full), compute_indicators(cut)
    for name in ("ema9", "ema21", "ema50", "ema200", "rsi", "macd", "macd_signal", "macd_hist", "bb_mid", "bb_up", "bb_low", "atr", "vol_ratio"):
        assert np.isclose(getattr(a, name)[i], getattr(b, name)[i], equal_nan=True), name
    assert support_resistance(full.high, full.low, full.close, i) == support_resistance(cut.high, cut.low, cut.close, i)
    sa, sb = evaluate_tf(a, i, "1h"), evaluate_tf(b, i, "1h")
    assert sa.score == sb.score and sa.trend == sb.trend


def test_support_resistance_ordering():
    c = make_candles(300, seed=9, vol=0.01)
    i = 250
    sup, res = support_resistance(c.high, c.low, c.close, i)
    if sup is not None:
        assert sup < c.close[i]
    if res is not None:
        assert res > c.close[i]
