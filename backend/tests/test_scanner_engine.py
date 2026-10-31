import time

import numpy as np

from app.analysis.engine import MIN_4H_BARS, PlanParams, analyze_symbol, build_plan, label_for
from app.exchange.types import INTERVAL_MS, SymbolInfo, Ticker
from app.market.scanner import is_leveraged, scan
from app.trading_settings import TradingSettings
from tests.synth import make_candles


def sym(base, status="TRADING", spot=True):
    return SymbolInfo(f"{base}USDT", base, "USDT", status, spot)


def tick(base, vol=50e6, bid=100.0, ask=100.05, trades=100000, chg=2.0, last=100.0):
    return Ticker(f"{base}USDT", last, bid, ask, vol, chg, trades)


def test_scanner_filters_and_ranking():
    symbols = {s.symbol: s for s in [sym("BTC"), sym("ETH"), sym("USDC"), sym("BTCUP"), sym("JUP"), sym("HALT", "BREAK"),
                                     sym("THIN"), sym("WIDE"), sym("PUMP"), sym("NOQ"), sym("FEW")]}
    tickers = {
        "BTCUSDT": tick("BTC", vol=900e6), "ETHUSDT": tick("ETH", vol=400e6), "USDCUSDT": tick("USDC", vol=800e6),
        "BTCUPUSDT": tick("BTCUP"), "JUPUSDT": tick("JUP", vol=60e6), "HALTUSDT": tick("HALT"),
        "THINUSDT": tick("THIN", vol=100_000), "WIDEUSDT": tick("WIDE", bid=100, ask=101),
        "PUMPUSDT": tick("PUMP", chg=80.0), "NOQUSDT": tick("NOQ", bid=0, ask=0), "FEWUSDT": tick("FEW", trades=10),
    }
    res = scan(symbols, tickers, TradingSettings())
    assert [c.symbol for c in res.candidates] == ["BTCUSDT", "ETHUSDT", "JUPUSDT"]  # hacme göre sıralı; JUP kaldıraçlı sanılmadı
    r = res.rejected
    assert r["stable"] == 1 and r["leveraged"] == 1 and r["not_trading"] == 1 and r["low_volume"] == 1
    assert r["wide_spread"] == 1 and r["extreme_move"] == 1 and r["no_quote"] == 1 and r["low_trades"] == 1


def test_scanner_top_n_limit():
    symbols = {s.symbol: s for s in [sym(f"C{i}") for i in range(10)]}
    tickers = {f"C{i}USDT": tick(f"C{i}", vol=(10 + i) * 1e6) for i in range(10)}
    res = scan(symbols, tickers, TradingSettings(scan_top_n=5))
    assert len(res.candidates) == 5 and res.candidates[0].symbol == "C9USDT" and res.passed_filters == 10


def test_leveraged_detection_does_not_flag_real_coins():
    known = {"BTC", "ETH", "JUP", "SUP"}
    assert is_leveraged("BTCUP", known) and is_leveraged("ETHDOWN", known)
    assert not is_leveraged("JUP", known) and not is_leveraged("SUP", known)


def _candles(now_ms, drift, seed, n=300, vol=0.003):
    out = {}
    for tf in ("5m", "15m", "1h", "4h"):
        step = INTERVAL_MS[tf]
        last_closed = (now_ms // step) * step - 1
        c = make_candles(n, tf, drift=drift * step / 3_600_000, vol=vol * (step / 3_600_000) ** 0.5, seed=seed, end_ms=last_closed + step)
        out[tf] = c  # son mum 'oluşmakta olan' mum olacak (close_time > now)
    return out


def test_uptrend_scores_higher_than_downtrend_and_downtrend_is_capped():
    now = int(time.time() * 1000)
    up = analyze_symbol("UPUSDT", _candles(now, 0.004, 1), now, spread_pct=0.02)
    down = analyze_symbol("DNUSDT", _candles(now, -0.004, 2), now, spread_pct=0.02)
    assert up.eligible and down.eligible
    assert up.trend == "Yükseliş" and down.trend == "Düşüş"
    assert up.score > down.score
    assert down.score <= 55 and down.label in ("Bekle", "İşlem yapma")
    assert any("düşüş" in w.lower() for w in down.warnings)
    assert 0 <= up.score <= 100 and up.rationale


def test_plan_geometry_is_valid_long():
    now = int(time.time() * 1000)
    a = analyze_symbol("UPUSDT", _candles(now, 0.004, 1), now)
    assert a.stop < a.entry < a.tp1 < a.tp2
    stop, tp1, tp2 = build_plan(100.0, 1.0, PlanParams())
    assert abs((100 - stop) - 1.5) < 1e-9 and abs((tp1 - 100) - 3.0) < 1e-9 and abs((tp2 - 100) - 5.25) < 1e-9
    s2, t1, t2 = build_plan(100.0, 1.0, PlanParams(stop_mode="percent", target_mode="percent", stop_pct=2, tp1_pct=3, tp2_pct=6))
    assert (round(s2, 6), round(t1, 6), round(t2, 6)) == (98.0, 103.0, 106.0)


def test_young_coin_is_rejected_for_insufficient_history():
    now = int(time.time() * 1000)
    c = _candles(now, 0.002, 3)
    c["4h"] = make_candles(50, "4h", seed=3, end_ms=c["4h"].close_time[-1])
    a = analyze_symbol("NEWUSDT", c, now)
    assert not a.eligible and "yetersiz geçmiş" in a.skip_reason and MIN_4H_BARS == 200


def test_forming_candle_is_never_used():
    """Oluşmakta olan (kapanmamış) mum analiz sonucunu DEĞİŞTİRMEMELİ."""
    now = int(time.time() * 1000)
    base = _candles(now, 0.003, 4)
    a1 = analyze_symbol("XUSDT", base, now)
    tampered = {tf: c for tf, c in base.items()}
    for c in tampered.values():  # son (açık) mumu uçuk bir değere çek
        c.close = c.close.copy()
        c.close[-1] *= 3
        c.high = c.high.copy()
        c.high[-1] *= 3
    a2 = analyze_symbol("XUSDT", tampered, now)
    assert a1.score == a2.score and a1.entry == a2.entry


def test_labels_follow_spec_bands():
    assert label_for(90) == "Çok güçlü fırsat" and label_for(85) == "Çok güçlü fırsat"
    assert label_for(70) == "Değerlendirilebilir fırsat" and label_for(84.9) == "Değerlendirilebilir fırsat"
    assert label_for(50) == "Bekle" and label_for(69.9) == "Bekle"
    assert label_for(49.9) == "İşlem yapma"


def test_scores_are_finite():
    now = int(time.time() * 1000)
    for seed in range(5):
        a = analyze_symbol("ZUSDT", _candles(now, np.random.default_rng(seed).normal(0, 0.003), seed), now)
        assert a.eligible and np.isfinite(a.score) and 0 <= a.score <= 100
