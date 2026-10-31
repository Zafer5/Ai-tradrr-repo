"""Geçmiş veri (backtest) motoru.

Dürüstlük kuralları:
* Gelecek verisi sızmaz: i. mumda karar verilirken her zaman dilimi için yalnızca o ana kadar KAPANMIŞ mumlar kullanılır.
* Emir, karar mumunun ARDINDAKİ mumun açılışında doldurulur (aynı mumun kapanışında değil).
* Aynı mumda hem stop hem hedef görülürse STOP önce kabul edilir (kötümser).
* Komisyon ve kayma (slippage) her dolumda uygulanır.
* Yalnızca kazanç oranına değil; net getiri, profit factor, beklenti, maksimum düşüş ve al-tut karşılaştırmasına bakılır.
* Eğitim/test ayrımı: ``walk_forward`` parametreyi yalnızca eğitim diliminde seçer, test diliminde hiç görmeden uygular.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..analysis.engine import TIMEFRAMES, PlanParams, TFSignal, build_plan, compose, evaluate_tf
from ..analysis.indicators import IndicatorSet, compute_indicators
from ..exchange.types import Candles
from ..risk.manager import AccountSnapshot, EntryRequest, SystemFlags, evaluate_entry
from ..trading.exits import ExitAction, PosState, evaluate_exit
from ..trading_settings import TradingSettings

DAY_MS = 86_400_000
WARMUP_4H = 205  # EMA200 için 4sa mum sayısı


@dataclass
class BTTrade:
    entry_time: int
    exit_time: int
    entry: float
    qty: float
    pnl: float
    reason: str
    score: float


@dataclass
class BTResult:
    trades: list[BTTrade]
    equity: list[float]
    times: list[int]
    initial: float
    metrics: dict = field(default_factory=dict)


def _fee(s: TradingSettings) -> float:
    return s.fee_rate_pct / 100


def _slip(s: TradingSettings) -> float:
    return s.slippage_pct / 100


@dataclass
class Prepared:
    """Göstergeler ve zaman dilimi sinyalleri bir kez hesaplanır; eğitim/test koşuları arasında paylaşılır."""

    ind: dict[str, IndicatorSet]
    sig_cache: dict[tuple[str, int], TFSignal | None] = field(default_factory=dict)


def prepare(candles: dict[str, Candles]) -> Prepared:
    return Prepared({tf: compute_indicators(candles[tf]) for tf in TIMEFRAMES if tf in candles})


def simulate(
    candles: dict[str, Candles],
    s: TradingSettings,
    base_tf: str = "15m",
    start_ms: int | None = None,
    end_ms: int | None = None,
    assumed_spread_pct: float = 0.03,
    prep: Prepared | None = None,
) -> BTResult:
    prep = prep or prepare(candles)
    ind, sig_cache = prep.ind, prep.sig_cache
    base = candles[base_tf]
    n = len(base)
    fee, slip = _fee(s), _slip(s)
    plan = PlanParams.from_settings(s)

    def signals_at(t_close: int) -> dict[str, TFSignal]:
        out = {}
        for tf, iset in ind.items():
            j = int(np.searchsorted(candles[tf].close_time, t_close, side="right")) - 1  # t anında KAPANMIŞ son mum
            if j < 60:
                continue
            key = (tf, j)
            if key not in sig_cache:
                sig_cache[key] = evaluate_tf(iset, j, tf)
            if sig_cache[key]:
                out[tf] = sig_cache[key]
        return out

    # 4sa'de yeterli geçmiş olan ilk baz mum
    first_ok = int(np.searchsorted(base.close_time, candles["4h"].close_time[min(WARMUP_4H, len(candles["4h"]) - 1)], side="left"))
    lo = max(first_ok, 1)
    if start_ms is not None:
        lo = max(lo, int(np.searchsorted(base.close_time, start_ms, side="right")))  # start_ms'den SONRAKİ mumlar
    hi = n - 1 if end_ms is None else min(n - 1, int(np.searchsorted(base.close_time, end_ms, side="right")))

    initial = s.initial_balance
    cash = initial
    pos: dict | None = None
    trades: list[BTTrade] = []
    equity: list[float] = []
    times: list[int] = []
    day_start = {"day": None, "eq": initial}
    trades_today = {"day": None, "n": 0}
    last_exit_ms = -10**18

    def close_part(p: dict, fraction: float, ref: float, order_type: str, reason: str, t: int) -> None:
        nonlocal cash, pos
        qty = p["qty"] if fraction >= 0.999 else p["qty"] * fraction
        price = ref * (1 - slip) if order_type == "MARKET" else ref
        proceeds = price * qty - price * qty * fee
        cost_part = p["cost"] * qty / p["qty0"]
        cash += proceeds
        p["pnl"] += proceeds - cost_part
        p["qty"] -= qty
        if reason == "TAKE_PROFIT_1":
            p["tp1_done"] = True
        if fraction >= 0.999 or p["qty"] <= p["qty0"] * 1e-9:
            trades.append(BTTrade(p["t_entry"], t, p["entry"], p["qty0"], p["pnl"], reason, p["score"]))
            pos = None

    def state(p: dict) -> PosState:
        return PosState(p["entry"], p["qty"], p["stop"], p["tp1"], p["tp2"], p["tp1_done"], p["peak"], p["trailing"])

    for i in range(lo, hi):
        t_i = int(base.close_time[i])
        day = t_i // DAY_MS
        mark = pos["qty"] * base.close[i] if pos else 0.0
        eq_now = cash + mark
        if day_start["day"] != day:
            day_start.update(day=day, eq=eq_now)
        if trades_today["day"] != day:
            trades_today.update(day=day, n=0)

        # ---- açık pozisyonu BU muma göre yönet (giriş mumundan sonraki mumlar) ----
        if pos and i > pos["i_entry"]:
            o, h, l = float(base.open[i]), float(base.high[i]), float(base.low[i])
            ev = evaluate_exit(state(pos), l, s)  # a) stop önce (kötümser)
            if ev.action and ev.action.order_type == "MARKET":
                ref = min(o, ev.effective_stop) if o <= ev.effective_stop else ev.effective_stop  # gap varsa açılıştan
                close_part(pos, 1.0, ref, "MARKET", ev.action.reason, t_i)
            else:
                for _ in range(2):  # b) hedefler (TP1 sonra TP2 aynı mumda olabilir)
                    ev = evaluate_exit(state(pos), h, s)
                    pos["peak"], pos["trailing"] = ev.peak, ev.trailing_active
                    if ev.action and ev.action.order_type == "LIMIT":
                        a: ExitAction = ev.action
                        close_part(pos, a.fraction, a.ref_price, "LIMIT", a.reason, t_i)
                        if pos is None:
                            break
                    else:
                        break
                if pos:  # c) güncellenmiş trailing/başa-baş stop'a aynı mumun düşüğü değiyor mu
                    ev = evaluate_exit(state(pos), l, s)
                    if ev.action and ev.action.order_type == "MARKET":
                        close_part(pos, 1.0, ev.effective_stop, "MARKET", ev.action.reason, t_i)
            if pos is None:
                last_exit_ms = t_i

        # ---- giriş kararı: i. mumun KAPANIŞINDA, emir i+1 açılışında ----
        if pos is None and i + 1 < n:
            sigs = signals_at(t_i)
            if "1h" in sigs and "4h" in sigs:
                comp = compose(sigs, assumed_spread_pct)
                if comp.score >= s.buy_score_threshold:
                    o_next = float(base.open[i + 1])
                    stop, tp1, tp2 = build_plan(o_next, sigs["1h"].atr, plan)
                    eq_now = cash + (pos["qty"] * base.close[i] if pos else 0.0)
                    pnl_pct = (eq_now - day_start["eq"]) / day_start["eq"] * 100
                    cool = {"X"} if (t_i - last_exit_ms) < s.cooldown_minutes * 60_000 else set()
                    acct = AccountSnapshot(eq_now, cash, {}, pnl_pct, trades_today["n"], cool, set())
                    req = EntryRequest("X", comp.score, comp.risk, True, assumed_spread_pct, o_next * (1 + slip), stop, tp1, tp2)
                    dec = evaluate_entry(req, acct, SystemFlags(), s)
                    if dec.approved:
                        fill = o_next * (1 + slip)
                        cost = fill * dec.quantity * (1 + fee)
                        if cost <= cash:
                            cash -= cost
                            trades_today["n"] += 1
                            pos = dict(i_entry=i + 1, t_entry=int(base.close_time[i + 1]), entry=fill, qty=dec.quantity, qty0=dec.quantity,
                                       cost=cost, stop=stop, tp1=tp1, tp2=tp2, tp1_done=False, peak=fill, trailing=False,
                                       pnl=0.0, score=comp.score)

        equity.append(cash + (pos["qty"] * float(base.close[i]) if pos else 0.0))
        times.append(t_i)

    # backtest sonunda açık pozisyon varsa son kapanıştan kapat (rapora dahil)
    if pos and times:
        close_part(pos, 1.0, float(base.close[hi - 1]), "MARKET", "BACKTEST_END", times[-1])
        equity[-1] = cash

    res = BTResult(trades, equity, times, initial)
    res.metrics = compute_metrics(res, base, lo, hi)
    return res


def compute_metrics(res: BTResult, base: Candles, lo: int, hi: int) -> dict:
    pnls = np.array([t.pnl for t in res.trades])
    n = len(pnls)
    eq = np.array(res.equity) if res.equity else np.array([res.initial])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    gp, gl = float(wins.sum()), float(-losses.sum())
    peak = np.maximum.accumulate(eq)
    mdd = float(((peak - eq) / peak).max() * 100)
    rets = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0.0])
    step_ms = int(np.median(np.diff(base.close_time))) if len(base) > 1 else 900_000
    per_year = 365 * DAY_MS / step_ms
    sharpe = float(rets.mean() / rets.std() * math.sqrt(per_year)) if rets.std() > 0 else None
    buy_hold = float((base.close[hi - 1] / base.open[lo] - 1) * 100) if hi > lo else None
    avg_win = float(wins.mean()) if len(wins) else None
    avg_loss = float(losses.mean()) if len(losses) else None
    days = (res.times[-1] - res.times[0]) / DAY_MS if len(res.times) > 1 else 0
    return {
        "trades": n,
        "net_return_pct": float((eq[-1] / res.initial - 1) * 100),
        "net_pnl": float(eq[-1] - res.initial),
        "win_rate": float(len(wins) / n * 100) if n else None,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "risk_reward": float(avg_win / -avg_loss) if avg_win and avg_loss else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "expectancy": float(pnls.mean()) if n else None,
        "max_drawdown_pct": mdd,
        "sharpe_like": sharpe,
        "buy_and_hold_pct": buy_hold,
        "days": round(days, 1),
        "by_reason": {r: int(sum(1 for t in res.trades if t.reason == r)) for r in {t.reason for t in res.trades}},
    }


@dataclass
class WalkForwardResult:
    chosen_threshold: float
    train: BTResult
    test: BTResult
    train_grid: dict[float, dict]


def walk_forward(candles: dict[str, Candles], s: TradingSettings, split: float = 0.6,
                 thresholds: tuple[float, ...] = (60, 65, 70, 75, 80), base_tf: str = "15m") -> WalkForwardResult:
    """Eşik değeri YALNIZCA eğitim diliminde seçilir; test dilimi seçim sırasında hiç kullanılmaz."""
    base = candles[base_tf]
    first_ok = int(np.searchsorted(base.close_time, candles["4h"].close_time[min(WARMUP_4H, len(candles["4h"]) - 1)], side="left"))
    cut_idx = first_ok + int((len(base) - first_ok) * split)
    cut_ms = int(base.close_time[cut_idx])
    grid: dict[float, dict] = {}
    best_thr, best_score = thresholds[0], -1e18
    prep = prepare(candles)
    for thr in thresholds:
        r = simulate(candles, s.model_copy(update={"buy_score_threshold": thr}), base_tf, end_ms=cut_ms, prep=prep)
        grid[thr] = r.metrics
        # ölçüt: net getiri - maksimum düşüş cezası (yalnızca kazanç oranına bakılmaz); az işlem varsa güvenilmez
        score = r.metrics["net_return_pct"] - 0.5 * r.metrics["max_drawdown_pct"] if r.metrics["trades"] >= 5 else -1e9 + r.metrics["trades"]
        if score > best_score:
            best_thr, best_score = thr, score
    chosen = s.model_copy(update={"buy_score_threshold": best_thr})
    train = simulate(candles, chosen, base_tf, end_ms=cut_ms, prep=prep)
    test = simulate(candles, chosen, base_tf, start_ms=cut_ms, prep=prep)
    return WalkForwardResult(best_thr, train, test, grid)
