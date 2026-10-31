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
from ..analysis.regime import Regime, evaluate_regime
from ..exchange.binance import BinanceClient
from ..exchange.stream import PriceFeed
from ..exchange.types import Candles
from ..kv import kv_get, kv_set
from ..market.scanner import Candidate, ScanResult, scan
from ..notify import Notifier
from ..portfolio.manager import MarketView
from ..portfolio.service import PortfolioService
from ..models import AnalysisLog, EquitySnapshot, LogEntry, utcnow
from ..risk.manager import EntryRequest, SystemFlags, evaluate_entry
from ..trading_settings import SettingsStore, TradingSettings
from .exits import ExitAction, PosState, evaluate_exit
from .service import TradingService

log = logging.getLogger("app.bot")
STATE_KEY = "bot_state"
CANDLE_TTL = {"5m": 45, "15m": 120, "1h": 420, "4h": 1200, "1d": 3600}
LISTS_KEY = "coin_lists"
SHOCK_PAUSE_SEC = 45 * 60
STALE_FEED_SEC = 60


class BotRunner:
    def __init__(self, db, store: SettingsStore, client: BinanceClient, feed: PriceFeed, service: TradingService,
                 notifier: Notifier, portfolio: PortfolioService):
        self.db, self.store, self.client, self.feed, self.service = db, store, client, feed, service
        self.notifier, self.portfolio = notifier, portfolio
        self.regime: Regime | None = None
        self.shock_until = 0.0
        self._last_pf_eval = 0.0
        self._daily_report_date = ""
        self._loss_notified_date = ""
        self._was_safe = False
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
        await self.notifier.send("emergency", "ACİL DURDURMA", "Bot kapatıldı, yeni alım engellendi." + (" Açık pozisyonlar kapatılıyor." if close_positions else ""), "bad")
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
        lists = await self.coin_lists()
        res.candidates = [c for c in res.candidates if c.symbol not in lists["exclude"]]
        # takip listesi + portföydeki coinler de analiz edilir (tarayıcı elemiş olsa bile)
        held = await self.portfolio.symbols()
        have = {c.symbol for c in res.candidates}
        extra = []
        for sym in (set(lists["watch"]) | held) - have:
            tk, info = tickers.get(sym), self.symbols.get(sym)
            if tk and info and tk.last > 0:
                extra.append(Candidate(sym, info.base, tk.last, tk.quote_volume, tk.change_pct, tk.spread_pct or 0.0, tk.trades))
        plan = PlanParams.from_settings(s)
        sem = asyncio.Semaphore(8)
        await self._update_regime(s)

        async def one(c: Candidate) -> Analysis:
            async with sem:
                candles = await self.get_candles(c.symbol)
            return await asyncio.to_thread(analyze_symbol, c.symbol, candles, None, plan, c.spread_pct, c.quote_volume, c.change_pct)

        to_analyze = res.candidates + extra
        results = await asyncio.gather(*(one(c) for c in to_analyze), return_exceptions=True)
        analyses: dict[str, Analysis] = {}
        failed = 0
        for c, r in zip(to_analyze, results):
            if isinstance(r, Exception):
                failed += 1
                log.warning("%s analiz edilemedi: %s", c.symbol, r)
            else:
                r.held = c.symbol in held
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

    # ------------------------------------------------------------------ piyasa rejimi / listeler
    async def coin_lists(self) -> dict:
        async with self.db.session() as ses:
            d = await kv_get(ses, LISTS_KEY, {})
        return {"watch": d.get("watch", []), "exclude": d.get("exclude", [])}

    async def save_coin_lists(self, watch: list[str], exclude: list[str]) -> dict:
        clean = lambda xs: sorted({x.strip().upper() for x in xs if x.strip().isalnum()})  # noqa: E731
        d = {"watch": clean(watch), "exclude": clean(exclude)}
        async with self.db.session() as ses:
            await kv_set(ses, LISTS_KEY, d)
            await ses.commit()
        return d

    async def _update_regime(self, s: TradingSettings) -> None:
        """BTC yönü ve ani düşüş koruması. Veri alınamazsa rejim 'Bilinmiyor' kalır (alım engellenmez ama güvenli mod ayrıca çalışır)."""
        try:
            btc = await self.get_candles("BTCUSDT")
        except Exception as e:
            log.warning("BTC verisi alınamadı: %s", e)
            return
        r = evaluate_regime(btc, int(time.time() * 1000), s.market_shock_pct)
        if r.shock and time.time() >= self.shock_until:
            log.error("ANİ DÜŞÜŞ KORUMASI: %s — yeni alımlar %d dk durduruldu", r.shock_reason, SHOCK_PAUSE_SEC // 60)
            await self.notifier.send("shock", "Ani düşüş koruması devrede", f"{r.shock_reason}. Yeni alımlar {SHOCK_PAUSE_SEC // 60} dakika durduruldu.", "bad")
        if r.shock:
            self.shock_until = time.time() + SHOCK_PAUSE_SEC
        self.regime = r

    @property
    def shock_active(self) -> bool:
        return time.time() < self.shock_until

    def _flags(self, s: TradingSettings) -> SystemFlags:
        extra = 10.0 if (s.btc_filter_enabled and self.regime and self.regime.direction == "Düşüş") else 0.0
        shock = (self.regime.shock_reason or "BTC ani düşüş") if self.shock_active and self.regime else None
        return SystemFlags(self.emergency, self.safe_reason, shock, extra)

    def market_views(self) -> dict[str, MarketView]:
        shock = self.shock_active
        direction = self.regime.direction if self.regime else None
        return {sym: MarketView(a.score if a.eligible else None, a.trend if a.eligible else None, a.sell_fit if a.eligible else None,
                                a.downside_risk if a.eligible else None, a.risk if a.eligible else None, shock, direction)
                for sym, a in self.analyses.items()}

    # ------------------------------------------------------------------ alım
    def _record(self, a: Analysis, approved: bool, reasons: list[str]) -> None:
        self.decisions.appendleft({"ts": time.time(), "symbol": a.symbol, "score": a.score, "approved": approved, "reasons": reasons})

    async def try_entries(self, s: TradingSettings) -> None:
        held = await self.portfolio.symbols()
        lists = await self.coin_lists()
        ranked = sorted((a for a in self.analyses.values() if a.eligible and a.score >= s.buy_score_threshold), key=lambda a: -a.score)
        for a in ranked:
            if a.symbol in held:
                self._record(a, False, ["Bu coin mevcut portföyünüzde: yeni alım yapılmaz, ayrı yönetilir (mükerrer işlem engeli)"])
                continue
            if a.symbol in lists["exclude"]:
                continue
            async with self.trade_lock:
                if not self.enabled or self.emergency:
                    return
                await self._consider_entry(a, s)

    async def _consider_entry(self, a: Analysis, s: TradingSettings) -> None:
        flags = self._flags(s)
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
        req = EntryRequest(symbol=a.symbol, score=a.score, risk_level=a.risk, eligible=a.eligible, spread_pct=spread, change_pct=a.change_pct,
                          entry=ask * (1 + s.slippage_pct / 100), stop=stop, tp1=tp1, tp2=tp2)
        dec = evaluate_entry(req, acct, flags, s, self.symbols.get(a.symbol))
        self._record(a, dec.approved, dec.reasons)
        if not dec.approved:
            return
        self.in_flight.add(a.symbol)
        try:
            pos = await self.service.open_position(a.symbol, ask, dec, stop, tp1, tp2, a.score, a.risk, " ".join(a.rationale), s)
        finally:
            self.in_flight.discard(a.symbol)
        if pos:
            await self.notifier.send(
                "buy", f"ALIM (sanal): {a.symbol.replace('USDT', '')}",
                f"{pos.quantity:.6g} adet @ {pos.entry_price:.6g} (≈{pos.quantity * pos.entry_price:.2f} USDT)\nStop {stop:.6g} · Hedef1 {tp1:.6g} · Hedef2 {tp2:.6g}\n"
                f"Neden (AI puanı {a.score:.0f}, risk {a.risk}): {' '.join(a.rationale[:2])}\nGüvenli işlem: risk kontrolü onayladı, tahmini komisyon {pos.est_fees:.3f} USDT.", "info")

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
        await self._side_tasks(s)
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
                    after = await self.service.execute_exit(p.id, ev.action, s)
                if after:
                    await self._notify_exit(after, ev.action)

    async def _side_tasks(self, s: TradingSettings) -> None:
        """Bildirimler ve portföy değerlendirmesi (her ~10 sn)."""
        if self.safe_reason and not self._was_safe:
            await self.notifier.send("safe", "Güvenli mod: yeni alımlar durdu", self.safe_reason, "bad", "safe", 600)
        self._was_safe = bool(self.safe_reason)
        if time.time() - self._last_pf_eval < 10 or not self.feed.prices or self.feed.age > STALE_FEED_SEC:
            return
        self._last_pf_eval = time.time()
        snap = await self.service.snapshot(dict(self.feed.prices), set(), 0)
        from .service import today_str

        if snap.day_pnl_pct <= -s.daily_loss_limit_pct and self._loss_notified_date != today_str():
            self._loss_notified_date = today_str()
            await self.notifier.send("loss_limit", "Günlük zarar limiti aşıldı", f"Bugünkü sonuç %{snap.day_pnl_pct:.2f}. Gün sonuna kadar yeni alım yapılmayacak; açık pozisyonlar korunmaya devam ediyor.", "bad")
        await self.portfolio.evaluate_all(dict(self.feed.prices), self.market_views(), s)
        await self._maybe_daily_report()

    async def _maybe_daily_report(self) -> None:
        from datetime import datetime

        from .service import TZ, today_str

        now = datetime.now(TZ)
        if now.hour == 23 and now.minute >= 55 and self._daily_report_date != today_str():
            self._daily_report_date = today_str()
            from ..report import build_daily_report

            title, body = await build_daily_report(self.db, self.service, dict(self.feed.prices))
            await self.notifier.send("daily_report", title, body, "info")

    async def _notify_exit(self, pos, action: ExitAction) -> None:
        from .exits import REASON_TR

        why = REASON_TR.get(action.reason, action.reason)
        coin = pos.symbol.replace("USDT", "")
        if pos.status == "CLOSED":
            lvl = "good" if pos.realized_pnl > 0 else "bad"
            await self.notifier.send("sell", f"SATIŞ (sanal): {coin} — {why}", f"Pozisyon kapandı. Net sonuç (komisyon dahil): {pos.realized_pnl:+.3f} USDT\nNeden: {why}.", lvl)
            if action.reason == "STOP_LOSS":
                await self.notifier.send("stoploss", f"Zarar sınırına ulaşıldı: {coin}", f"Stop-loss çalıştı, kayıp {pos.realized_pnl:+.3f} USDT. Sermaye korunuyor.", "warn")
        else:
            await self.notifier.send("sell", f"KISMİ SATIŞ (sanal): {coin} — {why}", f"Pozisyonun bir kısmı satıldı, kalan {pos.quantity:.6g}. Stop başa baş üstüne çekildi. Şu ana kadar net {pos.realized_pnl:+.3f} USDT.", "good")

    async def close_position_manually(self, position_id: int) -> bool:
        s = await self.store.get()
        positions = {p.id: p for p in await self.service.open_positions()}
        p = positions.get(position_id)
        price = self.feed.get(p.symbol) if p else None
        if not p or not price:
            return False
        async with self.trade_lock:
            after = await self.service.execute_exit(p.id, ExitAction(1.0, "MANUAL", "MARKET", price), s)
        if after:
            await self._notify_exit(after, ExitAction(1.0, "MANUAL", "MARKET", price))
        return after is not None

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
