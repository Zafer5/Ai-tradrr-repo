"""Botun ana yöneticisi: tarama -> analiz -> risk kontrolü -> (paper) emir -> pozisyon izleme.

Güvenlik ilkeleri:
* Alım kararı her zaman ``risk.manager.evaluate_entry`` içinden geçer.
* Piyasa verisi alınamıyorsa veya fiyat akışı kesikse YENİ alım yapılmaz (güvenli mod).
* Açık pozisyonların stop/hedef kontrolü acil durdurma ve güvenli modda da çalışmaya devam eder.
* Aynı coine aynı anda ikinci emir verilmez (kilit + açık pozisyon kontrolü).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import timedelta

from sqlalchemy import delete, select

from ..analysis.engine import TIMEFRAMES, Analysis, PlanParams, analyze_symbol, build_plan
from ..exchange.binance import BinanceClient
from ..exchange.stream import PriceFeed
from ..exchange.types import Candles
from ..kv import kv_get, kv_set
from ..market.scanner import Candidate, ScanResult, scan
from ..models import AnalysisLog, EquitySnapshot, LogEntry, utcnow
from ..risk.manager import EntryRequest, SystemFlags, evaluate_entry
from ..trading_settings import SettingsStore, TradingSettings
from .exits import ExitAction, PosState, evaluate_exit
from .service import TradingService

log = logging.getLogger("app.bot")
STATE_KEY = "bot_state"
CANDLE_TTL = {"5m": 45, "15m": 120, "1h": 420, "4h": 1200}
STALE_FEED_SEC = 60


class BotRunner:
    def __init__(self, db, store: SettingsStore, client: BinanceClient, feed: PriceFeed, service: TradingService):
        self.db, self.store, self.client, self.feed, self.service = db, store, client, feed, service
        self.enabled = False
        self.emergency = False
        self.emergency_reason = ""
        self.symbols: dict = {}
        self._symbols_at = 0.0
        self.scan_result: ScanResult | None = None
        self.analyses: dict[str, Analysis] = {}
        self.last_scan_ok_at = 0.0
        self.last_scan_error: str | None = None
        self.scan_errors = 0
        self.scan_duration = 0.0
        self.safe_reason: str | None = None
        self.in_flight: set[str] = set()
        self.trade_lock = asyncio.Lock()
        self.decisions: deque = deque(maxlen=150)
        self.started_at = time.time()
        self._candles: dict[tuple[str, str], tuple[float, Candles]] = {}
        self._logged_at: dict[str, float] = {}
        self._tasks: list[asyncio.Task] = []
        self._warned_stale = False

    # ------------------------------------------------------------------ yaşam döngüsü
    async def load_state(self) -> None:
        async with self.db.session() as ses:
            st = await kv_get(ses, STATE_KEY, {})
        self.enabled = bool(st.get("enabled", False))
        self.emergency = bool(st.get("emergency", False))
        self.emergency_reason = st.get("emergency_reason", "")
        if self.emergency:
            self.enabled = False

    async def _save_state(self) -> None:
        async with self.db.session() as ses:
            await kv_set(ses, STATE_KEY, {"enabled": self.enabled, "emergency": self.emergency, "emergency_reason": self.emergency_reason})
            await ses.commit()

    async def start(self) -> None:
        await self.load_state()
        await self.service.ensure_account()
        self.feed.start()
        self._tasks = [
            asyncio.create_task(self._scan_loop(), name="scan"),
            asyncio.create_task(self._monitor_loop(), name="monitor"),
            asyncio.create_task(self._housekeeping_loop(), name="housekeeping"),
        ]
        log.info("Bot servisi başladı (bot %s, acil durdurma %s)", "AÇIK" if self.enabled else "KAPALI", "AKTİF" if self.emergency else "yok")

    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.feed.stop()

    # ------------------------------------------------------------------ panel komutları
    async def set_enabled(self, value: bool) -> None:
        if value and self.emergency:
            raise ValueError("Acil durdurma aktif. Önce 'Acil durdurmayı kaldır' işlemini yapın.")
        self.enabled = value
        await self._save_state()
        log.info("Bot %s", "AÇILDI" if value else "KAPATILDI")

    async def emergency_stop(self, close_positions: bool) -> int:
        self.emergency, self.enabled = True, False
        self.emergency_reason = f"Elle tetiklendi ({time.strftime('%d.%m.%Y %H:%M:%S')})"
        await self._save_state()
        log.error("ACİL DURDURMA tetiklendi (pozisyonları kapat: %s)", close_positions)
        closed = 0
        if close_positions:
            s = await self.store.get()
            async with self.trade_lock:
                closed = await self.service.close_all(dict(self.feed.prices), "EMERGENCY", s)
        return closed

    async def clear_emergency(self) -> None:
        self.emergency, self.emergency_reason = False, ""
        await self._save_state()
        log.warning("Acil durdurma kaldırıldı (bot kapalı; elle başlatın)")

    # ------------------------------------------------------------------ veri
    async def get_candles(self, symbol: str) -> dict[str, Candles]:
        async def one(tf: str) -> Candles:
            key = (symbol, tf)
            cached = self._candles.get(key)
            if cached and time.time() - cached[0] < CANDLE_TTL[tf]:
                return cached[1]
            c = await self.client.klines(symbol, tf, 300)
            self._candles[key] = (time.time(), c)
            return c

        return dict(zip(TIMEFRAMES, await asyncio.gather(*(one(tf) for tf in TIMEFRAMES))))

    # ------------------------------------------------------------------ tarama döngüsü
    async def _scan_loop(self) -> None:
        while True:
            s = await self.store.get()
            try:
                await self.scan_cycle(s)
                self.scan_errors, self.last_scan_error = 0, None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.scan_errors += 1
                self.last_scan_error = f"{type(e).__name__}: {e}"[:300]
                log.error("Tarama hatası (%d. ardışık): %s", self.scan_errors, self.last_scan_error)
            await asyncio.sleep(s.scan_interval_sec if self.scan_errors == 0 else min(s.scan_interval_sec, 30))

    async def scan_cycle(self, s: TradingSettings) -> None:
        t0 = time.time()
        if not self.symbols or time.time() - self._symbols_at > 3600:
            self.symbols = await self.client.exchange_info()
            self._symbols_at = time.time()
        tickers = await self.client.tickers_24h()
        res = scan(self.symbols, tickers, s)
        plan = PlanParams.from_settings(s)
        sem = asyncio.Semaphore(8)

        async def one(c: Candidate) -> Analysis:
            async with sem:
                candles = await self.get_candles(c.symbol)
            return await asyncio.to_thread(analyze_symbol, c.symbol, candles, None, plan, c.spread_pct, c.quote_volume)

        results = await asyncio.gather(*(one(c) for c in res.candidates), return_exceptions=True)
        analyses: dict[str, Analysis] = {}
        failed = 0
        for c, r in zip(res.candidates, results):
            if isinstance(r, Exception):
                failed += 1
                log.warning("%s analiz edilemedi: %s", c.symbol, r)
            else:
                analyses[c.symbol] = r
        if res.candidates and not analyses:
            raise RuntimeError("Hiçbir coin için mum verisi alınamadı")

        self.scan_result, self.analyses = res, analyses
        self.last_scan_ok_at, self.scan_duration = time.time(), time.time() - t0
        eligible = sum(1 for a in analyses.values() if a.eligible)
        log.info("Tarama tamam: %d USDT paritesi, %d filtreyi geçti, %d takipte, %d analiz edilebilir (%.1f sn)%s",
                 res.total_pairs, res.passed_filters, len(res.candidates), eligible, self.scan_duration,
                 f", {failed} hata" if failed else "")
        await self._log_analyses(analyses)
        if self.enabled and not self.emergency:
            await self.try_entries(s)

    # ------------------------------------------------------------------ alım
    def _record(self, a: Analysis, approved: bool, reasons: list[str]) -> None:
        self.decisions.appendleft({"ts": time.time(), "symbol": a.symbol, "score": a.score, "approved": approved, "reasons": reasons})

    async def try_entries(self, s: TradingSettings) -> None:
        ranked = sorted((a for a in self.analyses.values() if a.eligible and a.score >= s.buy_score_threshold), key=lambda a: -a.score)
        for a in ranked:
            async with self.trade_lock:
                if not self.enabled or self.emergency:
                    return
                await self._consider_entry(a, s)

    async def _consider_entry(self, a: Analysis, s: TradingSettings) -> None:
        flags = SystemFlags(self.emergency, self.safe_reason)
        try:
            bid, ask = await self.client.book_ticker(a.symbol)
        except Exception as e:  # API hatası => emir yok
            self._record(a, False, [f"Güncel fiyat alınamadı: {e}"])
            log.warning("%s için güncel fiyat alınamadı, alım atlandı: %s", a.symbol, e)
            return
        spread = (ask - bid) / ((ask + bid) / 2) * 100 if bid > 0 and ask > 0 else None
        if ask <= 0 or a.price <= 0 or abs(ask / a.price - 1) > 0.01:
            self._record(a, False, ["Güncel fiyat analiz fiyatından %1'den fazla saptı; analiz eskimiş"])
            return
        atr_abs = a.atr_pct / 100 * a.price
        stop, tp1, tp2 = build_plan(ask, atr_abs, PlanParams.from_settings(s))
        acct = await self.service.snapshot(dict(self.feed.prices), self.in_flight, s.cooldown_minutes)
        req = EntryRequest(a.symbol, a.score, a.risk, a.eligible, spread, ask * (1 + s.slippage_pct / 100), stop, tp1, tp2)
        dec = evaluate_entry(req, acct, flags, s, self.symbols.get(a.symbol))
        self._record(a, dec.approved, dec.reasons)
        if not dec.approved:
            return
        self.in_flight.add(a.symbol)
        try:
            await self.service.open_position(a.symbol, ask, dec, stop, tp1, tp2, a.score, a.risk, " ".join(a.rationale), s)
        finally:
            self.in_flight.discard(a.symbol)

    # ------------------------------------------------------------------ pozisyon izleme
    async def _monitor_loop(self) -> None:
        while True:
            try:
                await self.monitor_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Pozisyon izleme hatası")
            await asyncio.sleep(2)

    def _update_safe_mode(self, has_positions: bool) -> None:
        reasons = []
        if self.scan_errors >= 3:
            reasons.append(f"piyasa verisi alınamıyor ({self.last_scan_error})")
        grace = time.time() - self.started_at < STALE_FEED_SEC
        if (self.enabled or has_positions) and not grace and self.feed.age > STALE_FEED_SEC:
            reasons.append("canlı fiyat akışı kesik")
        new = "; ".join(reasons) or None
        if new != self.safe_reason:
            (log.error if new else log.info)("Güvenli mod %s", f"AKTİF: {new}" if new else "sona erdi")
        self.safe_reason = new

    async def monitor_once(self) -> None:
        s = await self.store.get()
        positions = await self.service.open_positions()
        self._update_safe_mode(bool(positions))
        if not positions:
            return
        if self.feed.age > STALE_FEED_SEC:
            if not self._warned_stale:
                log.error("Fiyat akışı %d sn'den eski: açık pozisyonlar için stop kontrolü yapılamıyor!", STALE_FEED_SEC)
                self._warned_stale = True
            return
        self._warned_stale = False
        for p in positions:
            price = self.feed.get(p.symbol)
            if price is None:
                continue
            ev = evaluate_exit(PosState(p.entry_price, p.quantity, p.stop_price, p.tp1_price, p.tp2_price, p.tp1_done, p.peak_price, p.trailing_active), price, s)
            if ev.peak != p.peak_price or ev.trailing_active != p.trailing_active:
                await self.service.update_position_state(p.id, ev.peak, ev.trailing_active)
            if ev.action:
                async with self.trade_lock:
                    await self.service.execute_exit(p.id, ev.action, s)

    async def close_position_manually(self, position_id: int) -> bool:
        s = await self.store.get()
        positions = {p.id: p for p in await self.service.open_positions()}
        p = positions.get(position_id)
        price = self.feed.get(p.symbol) if p else None
        if not p or not price:
            return False
        async with self.trade_lock:
            return await self.service.execute_exit(p.id, ExitAction(1.0, "MANUAL", "MARKET", price), s) is not None

    # ------------------------------------------------------------------ bakım
    async def _log_analyses(self, analyses: dict[str, Analysis]) -> None:
        now = time.time()
        rows = []
        for a in analyses.values():
            if not a.eligible or a.score < 50 or now - self._logged_at.get(a.symbol, 0) < 900:
                continue
            self._logged_at[a.symbol] = now
            rows.append(AnalysisLog(symbol=a.symbol, price=a.price, score=a.score, label=a.label, risk=a.risk,
                                    detail={"trend": a.trend, "stop": a.stop, "tp1": a.tp1, "tp2": a.tp2,
                                            "tf": {k: v["score"] for k, v in a.tf.items()}}))
        if rows:
            async with self.db.session() as ses:
                ses.add_all(rows)
                await ses.commit()

    async def _housekeeping_loop(self) -> None:
        last_prune = 0.0
        while True:
            await asyncio.sleep(60)
            try:
                prices = dict(self.feed.prices)
                equity, cash, _ = await self.service.equity(prices)
                await self.service.roll_day(equity)  # gece yarısı (İstanbul) gün başı özkaynağı kaydedilir
                async with self.db.session() as ses:
                    ses.add(EquitySnapshot(equity=equity, cash=cash))
                    await ses.commit()
                await self._update_outcomes(prices)
                if time.time() - last_prune > 86400:
                    last_prune = time.time()
                    cut = utcnow() - timedelta(days=14)
                    async with self.db.session() as ses:
                        await ses.execute(delete(LogEntry).where(LogEntry.ts < cut))
                        await ses.execute(delete(EquitySnapshot).where(EquitySnapshot.ts < utcnow() - timedelta(days=60)))
                        await ses.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Bakım görevi hatası")

    async def _update_outcomes(self, prices: dict[str, float]) -> None:
        """AI kararlarının sonrasındaki 1sa/4sa getirilerini ölçer (yalnızca ölçüm; strateji otomatik değişmez)."""
        if self.feed.age > 60:
            return
        now = utcnow()
        async with self.db.session() as ses:
            rows = (await ses.execute(select(AnalysisLog).where(
                AnalysisLog.ret_1h_pct.is_(None), AnalysisLog.ts <= now - timedelta(hours=1), AnalysisLog.ts > now - timedelta(hours=2)
            ).limit(300))).scalars().all()
            for r in rows:
                if r.symbol in prices:
                    r.ret_1h_pct = (prices[r.symbol] / r.price - 1) * 100
            rows = (await ses.execute(select(AnalysisLog).where(
                AnalysisLog.ret_4h_pct.is_(None), AnalysisLog.ts <= now - timedelta(hours=4), AnalysisLog.ts > now - timedelta(hours=6)
            ).limit(300))).scalars().all()
            for r in rows:
                if r.symbol in prices:
                    r.ret_4h_pct = (prices[r.symbol] / r.price - 1) * 100
            await ses.commit()
