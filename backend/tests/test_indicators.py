import math

from app import indicators as ind


def test_ema_constant_series():
    assert ind.ema([5.0] * 30, 9)[-1] == 5.0


def test_ema_known_values():
    vals = [1, 2, 3, 4, 5, 6]
    e = ind.ema(vals, 3)
    assert math.isnan(e[1])
    assert e[2] == 2.0            # (1+2+3)/3
    assert e[3] == 3.0            # 4*0.5 + 2*0.5
    assert e[5] == 5.0


def test_rsi_extremes():
    up = [float(i) for i in range(1, 40)]
    down = list(reversed(up))
    assert ind.rsi(up)[-1] == 100.0
    assert ind.rsi(down)[-1] == 0.0


def test_rsi_known_wilder_example():
    # Wilder'in klasik örnek verisi; ilk RSI ~70.53
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
    assert abs(ind.rsi(closes)[14] - 70.53) < 0.1


def test_bollinger_constant():
    up, mid, lo = ind.bollinger([10.0] * 25)
    assert up[-1] == mid[-1] == lo[-1] == 10.0


def test_atr_constant_range():
    n = 30
    a = ind.atr([11.0] * n, [9.0] * n, [10.0] * n)
    assert abs(a[-1] - 2.0) < 1e-9


def test_macd_sign_in_uptrend():
    closes = [100 * 1.01 ** i for i in range(100)]
    line, sig, hist = ind.macd(closes)
    assert line[-1] > 0


def test_support_resistance():
    highs = [10, 11, 12, 11, 10, 11, 13, 11, 10, 11, 12, 11, 10]
    lows = [h - 2 for h in highs]
    sup, res = ind.support_resistance(highs, lows, 11.5, wing=2)
    assert res == 12 or res == 13
    assert sup < 11.5
