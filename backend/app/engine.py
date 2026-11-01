"""İşlem motoru: tarama -> analiz -> risk kontrolü -> sanal emir -> pozisyon takibi."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import math
import time
from collections import deque
from dataclasses import asdict, dataclass, field, fields, replace

from sqlalchemy import delete, func, select

from .analysis import TIMEFRAMES, Analysis, Analyzer, TargetSettings
from .db import Account, AnalysisRecord, Database, LogEntry, Position, SettingsRow, Trade, utcnow
from .exchanges.base import ExchangeError, MarketDataClient, PriceUpdate, SymbolInfo
from .exchanges.binance_trade import BinanceTrader, OrderUncertain
from .live import LiveExecutor
from .paper import PaperExecutor
from . import radar as radar_mod
from .risk import PortfolioState, RiskSettings, evaluate_buy, round_step
from .scanner import ScanFilters, ScanResult, scan

log = logging.getLogger("engine")


@dataclass
class TradeSettings:
    trailing_enabled: bool = True
    trailing_activation_pct: float = 1.0   # fiyat girişten bu kadar % yükselince iz süren stop devreye girer
    trailing_pct: float = 1.0              # en yüksek fiyattan bu kadar % düşerse sat
    scale_out_enabled: bool = True         # kademeli satış: hedefte bir kısmını sat
    scale_out_fraction: float = 0.5
    analysis_interval_sec: int = 300
    universe_refresh_sec: int = 1800
    position_check_sec: int = 5


@dataclass
class BotSettings:
    scan: ScanFilters = field(default_factory=ScanFilters)
    targets: TargetSettings = field(default_factory=TargetSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    trade: TradeSettings = field(default_factory=TradeSettings)

    def to_dict(self) -> dict:
        return {k: asdict(getattr(self, k)) for k in ("scan", "targets", "risk", "trade")}

    def update(self, data: dict) -> None:
        for group in ("scan", "targets", "risk", "trade"):
            obj = getattr(self, group)
            for f in fields(obj):
                if f.name in data.get(group, {}):
                    v = data[group][f.name]
                    cur = getattr(obj, f.name)
                    setattr(obj, f.name, type(cur)(v))
        self.validate()

    def validate(self) -> None:
        r = self.risk
        checks = [
            (0 < r.risk_per_trade_pct <= 5, "İşlem başına risk %0-5 arasında olmalı"),
            (0 < r.daily_loss_limit_pct <= 20, "Günlük zarar limiti %0-20 arasında olmalı"),
            (1 <= r.max_open_positions <= 20, "Açık pozisyon sayısı 1-20 arasında olmalı"),
            (0 < r.max_per_coin_pct <= 50, "Tek coin limiti %0-50 arasında olmalı"),
            (0 < r.max_total_exposure_pct <= 100, "Toplam maruziyet %0-100 arasında olmalı"),
            (0 <= r.min_score <= 100, "Puan eşiği 0-100 olmalı"),
            (0 <= r.fee_pct <= 1 and 0 <= r.slippage_pct <= 2, "Komisyon/kayma değerleri geçersiz"),
            (1 <= self.scan.max_coins <= 200, "Taranacak coin sayısı 1-200 olmalı"),
            (0 < self.trade.scale_out_fraction < 1, "Kademeli satış oranı 0-1 arasında olmalı"),
            (self.trade.analysis_interval_sec >= 60, "Analiz aralığı en az 60 sn olmalı"),
            (self.trade.position_check_sec >= 2, "Pozisyon kontrol aralığı en az 2 sn olmalı"),
        ]
        for ok, msg in checks:
            if not ok:
                raise ValueError(msg)


class _NoKeysExecutor(PaperExecutor):
    """Test/canlı modda API anahtarı yokken: hiçbir emir gönderilmez, sanal emir de yapılmaz."""

    async def buy(self, *a, **k):
        raise ExchangeError("API anahtarı kayıtlı değil")

    async def sell(self, *a, **k):
        raise ExchangeError("API anahtarı kayıtlı değil")


def today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


class Engine:
    def __init__(self, client: MarketDataClient, db: Database, starting_balance: float, stream=None,
                 mode: str = "paper", trader: BinanceTrader | None = None, max_order_usdt: float = 0.0, budget: float = 0.0):
        self.mode = mode
        self.trader = trader
        self.max_order_usdt = max_order_usdt   # canlı modda config'ten gelen, panelden aşılamayan üst sınır
        self.budget = budget
        self.exchange_check: dict | None = None
        self.frozen: set[str] = set()
        self.radar_items: list = []
        self.last_radar_at = 0.0
        self.trending: set[str] = set()
        self.client = client
        self.db = db
        self.starting_balance = starting_balance
        self.stream = stream
        self.analyzer = Analyzer()
        self.settings = BotSettings()
        self.executor = None  # aşağıda set_trader ile belirlenir
        self.set_trader(trader)
        self.universe: list[ScanResult] = []
        self.rejected_count = 0
        self.symbol_info: dict[str, SymbolInfo] = {}
        self.prices: dict[str, tuple[float, float]] = {}  # symbol -> (fiyat, zaman)
        self.latest: dict[str, Analysis] = {}
        self.running = False
        self.emergency_stop = False
        self.halted_reason: str | None = None
        self.last_universe_at = 0.0
        self.last_analysis_at = 0.0
        self.last_error: str | None = None
        self.decisions: deque = deque(maxlen=300)
        self.progress = {"done": 0, "total": 0, "active": False}
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []

    # ---------- kayıt ----------
    async def log(self, level: str, msg: str) -> None:
        getattr(log, level.lower(), log.info)(msg)
        async with self.db.session() as s:
            s.add(LogEntry(level=level.upper(), message=msg))
            await s.commit()

    def note(self, symbol: str, score: int | None, action: str, text: str) -> None:
        """Panelin 'Canlı' sekmesinde görünen karar kaydı."""
        self.decisions.appendleft({"at": time.time(), "symbol": symbol, "score": score, "action": action, "text": text})

    # ---------- başlangıç ----------
    async def init(self) -> None:
        await self.db.create_all()
        async with self.db.session() as s:
            acc = await s.get(Account, 1)
            if acc is None:
                acc = Account(id=1, mode=self.mode, starting_balance=self.starting_balance, cash=self.starting_balance,
                              day=today(), day_start_equity=self.starting_balance, peak_equity=self.starting_balance)
                s.add(acc)
            row = await s.get(SettingsRow, "bot")
            if row:
                try:
                    self.settings.update(row.value)
                except Exception as e:  # noqa: BLE001
                    log.warning("Kayıtlı ayarlar okunamadı, varsayılanlar kullanılıyor: %s", e)
            state = await s.get(SettingsRow, "state")
            if state:
                self.running = bool(state.value.get("running", False))
                self.emergency_stop = bool(state.value.get("emergency_stop", False))
            await s.commit()
        self._apply_exec_settings()

    def set_trader(self, trader: BinanceTrader | None) -> None:
        """Modu ve anahtarlara göre yürütücüyü seçer. Anahtar yoksa test/canlı modda emir gönderilemez."""
        self.trader = trader
        r = self.settings.risk
        if self.mode == "paper":
            self.executor = PaperExecutor(r.fee_pct, r.slippage_pct)
        elif trader is None:
            self.executor = _NoKeysExecutor(r.fee_pct, r.slippage_pct)
        else:
            self.executor = LiveExecutor(trader, self.mode, r.fee_pct, r.slippage_pct)

    def _apply_exec_settings(self) -> None:
        self.executor.fee = self.settings.risk.fee_pct / 100
        self.executor.slip = self.settings.risk.slippage_pct / 100

    @property
    def label(self) -> str:
        return {"paper": "SANAL", "testnet": "TESTNET", "live": "GERÇEK PARA"}.get(self.mode, self.mode.upper())

    async def save_settings(self, data: dict) -> None:
        new = BotSettings()
        new.update(self.settings.to_dict())
        new.update(data)
        self.settings = new
        self._apply_exec_settings()
        async with self.db.session() as s:
            await s.merge(SettingsRow(key="bot", value=self.settings.to_dict()))
            await s.commit()
        await self.log("INFO", "Ayarlar güncellendi")

    async def _save_state(self) -> None:
        async with self.db.session() as s:
            await s.merge(SettingsRow(key="state", value={"running": self.running, "emergency_stop": self.emergency_stop}))
            await s.commit()

    def start_background(self) -> None:
        self._tasks = [
            asyncio.create_task(self._loop("universe", self.refresh_universe, lambda: self.settings.trade.universe_refresh_sec)),
            asyncio.create_task(self._loop("analysis", self.analysis_cycle, lambda: self.settings.trade.analysis_interval_sec, delay=5)),
            asyncio.create_task(self._loop("radar", self.refresh_radar, lambda: 900, delay=20)),
            asyncio.create_task(self._loop("positions", self.manage_positions, lambda: self.settings.trade.position_check_sec, delay=3)),
        ]
        if self.stream:
            self.stream.start()

    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.stream:
            await self.stream.stop()

    async def _loop(self, name: str, fn, interval, delay: float = 0) -> None:
        await asyncio.sleep(delay)
        while True:
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{name}: {e}"
                await self.log("ERROR", f"{name} döngüsünde hata: {e}")
            await asyncio.sleep(interval())

    # ---------- fiyatlar ----------
    def on_price(self, u: PriceUpdate) -> None:
        self.prices[u.symbol] = (u.price, u.ts or time.time())

    async def current_price(self, symbol: str) -> float | None:
        p = self.prices.get(symbol)
        if p and time.time() - p[1] < 15:
            return p[0]
        try:
            b = await self.client.book_ticker(symbol)
            mid = (b.bid + b.ask) / 2
            self.prices[symbol] = (mid, time.time())
            return mid
        except ExchangeError as e:
            await self.log("WARNING", f"{symbol} fiyatı alınamadı: {e}")
            return None

    # ---------- tarama ----------
    async def refresh_universe(self) -> None:
        symbols, tickers, books = await asyncio.gather(self.client.symbols(), self.client.tickers_24h(), self.client.book_tickers())
        self.symbol_info = {s.symbol: s for s in symbols}
        self.universe, rejected = scan(symbols, tickers, books, self.settings.scan)
        self.rejected_count = len(rejected)
        self.last_universe_at = time.time()
        await self._update_stream()
        await self.log("INFO", f"Coin listesi güncellendi: {len(self.universe)} coin takipte, {len(rejected)} coin elendi")

    async def _update_stream(self) -> None:
        if not self.stream:
            return
        async with self.db.session() as s:
            open_syms = (await s.execute(select(Position.symbol).where(Position.status == "open"))).scalars().all()
        self.stream.set_symbols([u.symbol for u in self.universe] + list(open_syms))

    # ---------- radar ----------
    async def refresh_radar(self) -> None:
        symbols, tickers, books = await asyncio.gather(self.client.symbols(), self.client.tickers_24h(), self.client.book_tickers())
        self.symbol_info.update({x.symbol: x for x in symbols})
        trending = await radar_mod.fetch_trending()
        if trending:
            self.trending = trending
        self.radar_items = await radar_mod.scan_radar(self.client, symbols, tickers, books, self.trending)
        self.last_radar_at = time.time()
        new = [r for r in self.radar_items if r.age_days is not None and r.age_days < 30]
        await self.log("INFO", f"Radar güncellendi: {len(self.radar_items)} coin incelendi, {len(new)} yeni listelenen")

    # ---------- analiz ----------
    async def analyze_symbol(self, symbol: str) -> Analysis:
        results = await asyncio.gather(*(self.client.klines(symbol, tf, 250) for tf in TIMEFRAMES))
        return self.analyzer.analyze(symbol, dict(zip(TIMEFRAMES, results)), self.settings.targets)

    async def analysis_cycle(self) -> None:
        if not self.universe:
            return
        analyses: list[Analysis] = []
        coins = list(self.universe)
        if self.settings.scan.include_radar and self.radar_items:
            have = {u.symbol for u in coins}
            extra = [r for r in self.radar_items if r.symbol not in have and (r.age_days is None or r.age_days >= 40)
                     and r.score >= 50 and r.change_24h <= 25][: self.settings.scan.radar_extra]
            coins += [ScanResult(r.symbol, r.base, r.price, r.change_24h, r.quote_volume, 0.0, 0) for r in extra]
            if extra:
                self.note("-", None, "bilgi", "Radar'dan eklenen coinler: " + ", ".join(r.symbol for r in extra))
        self.progress = {"done": 0, "total": len(coins), "active": True}
        self.note("-", None, "bilgi", f"Analiz başladı: {len(coins)} coin incelenecek")
        try:
            for u in coins:
                try:
                    a = await self.analyze_symbol(u.symbol)
                except ExchangeError as e:
                    await self.log("WARNING", f"{u.symbol} analiz edilemedi: {e}")
                    self.progress["done"] += 1
                    continue
                self.latest[u.symbol] = a
                analyses.append(a)
                self.progress["done"] += 1
        finally:
            self.progress["active"] = False
        self.last_analysis_at = time.time()
        async with self.db.session() as s:
            for a in analyses:
                s.add(AnalysisRecord(symbol=a.symbol, score=a.score, data=a.to_dict()))
            cutoff = utcnow() - dt.timedelta(days=3)
            await s.execute(delete(AnalysisRecord).where(AnalysisRecord.created_at < cutoff))
            await s.execute(delete(LogEntry).where(LogEntry.created_at < utcnow() - dt.timedelta(days=14)))
            await s.commit()
        min_score = self.settings.risk.min_score
        candidates = sorted((a for a in analyses if a.score >= min_score), key=lambda a: a.score, reverse=True)
        best = max(analyses, key=lambda a: a.score, default=None)
        summary = f"Analiz bitti: {len(analyses)} coin, {len(candidates)} aday (eşik {min_score} puan)."
        if best:
            summary += f" En yüksek puan: {best.symbol} = {best.score}."
        if not candidates:
            summary += " Eşiği geçen coin yok, bu yüzden alım yapılmadı."
        self.note("-", None, "bilgi", summary)
        await self.log("INFO", f"Analiz tamamlandı: {len(analyses)} coin, {len(candidates)} aday")
        if not candidates:
            return
        if not self.running or self.emergency_stop:
            self.note("-", None, "bekle", "Bot kapalı olduğu için adaylara girilmedi. Başlatmak için Ana Sayfa'dan 'Botu başlat'a bas.")
            return
        for a in candidates:
            await self.try_open(a)

    # ---------- portföy ----------
    async def portfolio(self, s) -> tuple[Account, list[Position], PortfolioState]:
        acc = await s.get(Account, 1)
        positions = (await s.execute(select(Position).where(Position.status == "open"))).scalars().all()
        exposure = 0.0
        for p in positions:
            px = self.prices.get(p.symbol, (p.entry_price, 0))[0]
            exposure += p.quantity * px
        equity = acc.cash + exposure
        if acc.day != today():
            acc.day, acc.day_start_equity = today(), equity
        acc.peak_equity = max(acc.peak_equity, equity)
        state = PortfolioState(equity=equity, cash=acc.cash, day_start_equity=acc.day_start_equity,
                               open_symbols={p.symbol for p in positions}, open_exposure=exposure,
                               bot_running=self.running, emergency_stop=self.emergency_stop,
                               halted_reason=self.halted_reason)
        return acc, list(positions), state

    async def try_open(self, a: Analysis) -> None:
        async with self._lock:
            try:
                book = await self.client.book_ticker(a.symbol)
            except ExchangeError as e:
                await self.log("WARNING", f"{a.symbol}: güncel alış fiyatı alınamadı, işlem yapılmadı ({e})")
                self.note(a.symbol, a.score, "red", "Güncel fiyat alınamadı, işlem yapılmadı")
                return
            risk = self.settings.risk
            if self.max_order_usdt > 0:   # config'teki sınır panelden gevşetilemez
                cap = min(risk.max_order_usdt or self.max_order_usdt, self.max_order_usdt)
                risk = replace(risk, max_order_usdt=cap)
            async with self.db.session() as s:
                acc, _, state = await self.portfolio(s)
                info = self.symbol_info.get(a.symbol)
                d = evaluate_buy(a, state, info, book.ask, risk)
                if not d.approved:
                    await s.commit()
                    await self.log("INFO", f"{a.symbol} (puan {a.score}) alınmadı: {'; '.join(d.reasons)}")
                    self.note(a.symbol, a.score, "red", "Risk kontrolü onaylamadı: " + "; ".join(d.reasons))
                    return
                try:
                    if self.mode != "paper" and self.trader is not None:
                        free = await self.trader.free_balance("USDT")
                        if free < d.notional * 1.01:
                            raise ExchangeError(f"Borsadaki serbest USDT yetersiz ({free:.2f})")
                    fill = await self.executor.buy(a.symbol, book.ask, d.quantity, info)
                    if fill.notional + fill.fee_cash > acc.cash + 1e-9:
                        raise RuntimeError("Nakit yetersiz (doğrulama)")
                except OrderUncertain as e:
                    await self._halt(f"Emir sonucu belirsiz: {e}")
                    return
                except ExchangeError as e:
                    await self.log("WARNING", f"{a.symbol} alım emri reddedildi/başarısız: {e}")
                    self.note(a.symbol, a.score, "red", f"Emir gönderilemedi: {e}")
                    return
                except Exception as e:  # noqa: BLE001
                    self.halted_reason = f"Emir hatası: {e}"
                    await self.log("ERROR", f"{a.symbol} alım emrinde hata, yeni emirler durduruldu: {e}")
                    return
                await self.log("INFO", f"[{self.label}] ALIM GERÇEKLEŞTİ {a.symbol}: {fill.quantity:g} @ {fill.price:.6g}, tutar {fill.notional:.4f}, komisyon {fill.fee:.4f}")
                ratio_tp, ratio_sl = a.take_profit / a.price, a.stop_loss / a.price   # hedef/stop gerçek dolum fiyatına göre
                tp, sl = fill.price * ratio_tp, fill.price * ratio_sl
                acc.cash -= fill.notional + fill.fee_cash
                why = " | ".join(a.reasons[:6])
                pos = Position(symbol=a.symbol, mode=self.mode, quantity=fill.quantity, initial_quantity=fill.quantity,
                               entry_price=fill.price, cost_basis=fill.notional + fill.fee, take_profit=tp,
                               stop_loss=sl, initial_stop=sl, highest_price=fill.price, score=a.score,
                               reason=why, expected_fee=d.expected_fee, fees_paid=fill.fee)
                s.add(pos)
                await s.flush()
                s.add(Trade(position_id=pos.id, symbol=a.symbol, side="BUY", mode=self.mode, price=fill.price,
                            quantity=fill.quantity, notional=fill.notional, fee=fill.fee, note=f"Puan {a.score}"))
                await s.commit()
            await self._update_stream()
            self.note(a.symbol, a.score, "alım", f"{self.label} ALIM: {fill.quantity:g} adet @ {fill.price:.6g} ({fill.notional:.2f} USDT). Hedef {tp:.6g}, stop {sl:.6g}. Gerekçe: {why}")

    async def _halt(self, reason: str) -> None:
        self.halted_reason = reason
        self.running = False
        await self._save_state()
        await self.log("ERROR", f"BOT DURDURULDU: {reason}. Borsa hesabınızı elle kontrol edin.")
        self.note("-", None, "red", f"BOT DURDURULDU: {reason}")

    async def _sell(self, s, acc: Account, pos: Position, qty: float, bid: float, reason: str) -> float:
        info = self.symbol_info.get(pos.symbol)
        qty = min(pos.quantity, round_step(qty, info.step_size) if info else qty)
        if pos.quantity - qty < 1e-12 or (info and (pos.quantity - qty) * bid < max(info.min_notional, 5.0)):
            qty = pos.quantity  # kalan çok küçükse tamamını sat
        fill = await self.executor.sell(pos.symbol, bid, qty, info)
        qty = min(qty, fill.quantity) if fill.quantity > 0 else qty
        portion = qty / pos.quantity
        cost_part = pos.cost_basis * portion
        pnl = fill.notional - fill.fee - cost_part
        acc.cash += fill.notional - fill.fee_cash
        pos.quantity -= qty
        pos.cost_basis -= cost_part
        pos.realized_pnl += pnl
        pos.fees_paid += fill.fee
        if pos.quantity <= 1e-12:
            pos.quantity, pos.status, pos.closed_at, pos.exit_reason = 0.0, "closed", utcnow(), reason
        s.add(Trade(position_id=pos.id, symbol=pos.symbol, side="SELL", mode=self.mode, price=fill.price, quantity=qty,
                    notional=fill.notional, fee=fill.fee, pnl=pnl, note=reason))
        self.note(pos.symbol, None, "satış", f"{self.label} SATIŞ: {qty:g} adet @ {fill.price:.6g} ({reason}), net {pnl:+.2f} USDT")
        await self.log("INFO", f"[{self.label}] SATIŞ {pos.symbol}: {qty:g} @ {fill.price:.6g} ({reason}), net {pnl:+.2f} USDT")
        return pnl

    async def _try_sell(self, s, acc, pos, qty, bid, reason) -> bool:
        """Satışı dener. Borsa reddederse bir sonraki döngüde yeniden dener; sonuç belirsizse durdurur."""
        try:
            await self._sell(s, acc, pos, qty, bid, reason)
            return True
        except OrderUncertain as e:
            self.frozen.add(pos.symbol)
            await self._halt(f"{pos.symbol} satış sonucu belirsiz: {e}")
        except ExchangeError as e:
            await self.log("ERROR", f"{pos.symbol} SATIŞ BAŞARISIZ ({reason}): {e}. Yeniden denenecek.")
            self.note(pos.symbol, None, "red", f"Satış başarısız ({reason}): {e}")
        return False

    async def manage_positions(self) -> None:
        async with self._lock:
            async with self.db.session() as s:
                acc, positions, _ = await self.portfolio(s)
                t = self.settings.trade
                fee = self.settings.risk.fee_pct / 100
                for pos in positions:
                    if pos.symbol in self.frozen:
                        continue   # sonucu belirsiz emir var: elle kontrol edilene kadar dokunma
                    price = await self.current_price(pos.symbol)
                    if price is None:
                        continue
                    pos.highest_price = max(pos.highest_price, price)
                    if t.trailing_enabled and pos.highest_price >= pos.entry_price * (1 + t.trailing_activation_pct / 100):
                        pos.stop_loss = max(pos.stop_loss, pos.highest_price * (1 - t.trailing_pct / 100))
                    hit_stop = price <= pos.stop_loss
                    hit_tp = price >= pos.take_profit
                    if not (hit_stop or hit_tp):
                        continue
                    try:
                        book = await self.client.book_ticker(pos.symbol)
                    except ExchangeError as e:
                        await self.log("WARNING", f"{pos.symbol}: satış fiyatı alınamadı, beklemede ({e})")
                        continue
                    if hit_stop:
                        reason = "İz süren stop" if pos.stop_loss > pos.initial_stop else "Stop-loss"
                        await self._try_sell(s, acc, pos, pos.quantity, book.bid, reason)
                        continue
                    if self.executor.net_if_sold(book.bid, pos.quantity, pos.cost_basis) <= 0:
                        continue  # net kâr pozitif değilse hedefte satma
                    if t.scale_out_enabled and not pos.scaled_out:
                        ok = await self._try_sell(s, acc, pos, pos.quantity * t.scale_out_fraction, book.bid, "Kâr hedefi (kademeli)")
                        if ok and pos.status == "open":
                            pos.scaled_out = True
                            pos.stop_loss = max(pos.stop_loss, pos.entry_price * (1 + 2 * fee))  # başa baş
                            pos.take_profit = pos.take_profit + (pos.take_profit - pos.entry_price)
                    else:
                        await self._try_sell(s, acc, pos, pos.quantity, book.bid, "Kâr hedefi")
                await s.commit()

    async def close_position(self, position_id: int, reason: str = "Elle kapatıldı") -> bool:
        async with self._lock:
            async with self.db.session() as s:
                acc = await s.get(Account, 1)
                pos = await s.get(Position, position_id)
                if pos is None or pos.status != "open":
                    return False
                book = await self.client.book_ticker(pos.symbol)
                await self._try_sell(s, acc, pos, pos.quantity, book.bid, reason)
                await s.commit()
                return True

    async def close_all(self, reason: str) -> int:
        async with self.db.session() as s:
            ids = (await s.execute(select(Position.id).where(Position.status == "open"))).scalars().all()
        n = 0
        for i in ids:
            try:
                n += await self.close_position(i, reason)
            except ExchangeError as e:
                await self.log("ERROR", f"Pozisyon {i} kapatılamadı: {e}")
        return n

    # ---------- kontrol ----------
    async def verify_exchange(self) -> dict:
        """Testnet/canlı mod için borsa bağlantısını ve API anahtarı yetkilerini doğrular."""
        checks: list[dict] = []
        warnings: list[str] = []

        def add(text: str, ok: bool) -> None:
            checks.append({"text": text, "ok": ok})

        if self.mode == "paper":
            return {"ok": True, "mode": self.mode, "checks": [], "warnings": []}
        if self.trader is None:
            self.exchange_check = {"ok": False, "mode": self.mode, "warnings": [], "at": time.time(),
                                   "checks": [{"text": "API anahtarı kayıtlı değil (Bağlantılar sekmesinden girin)", "ok": False}]}
            return self.exchange_check
        try:
            acc = await self.trader.account()
            add("Borsa hesabına bağlanıldı", True)
            add("Hesapta alım-satım izni var", bool(acc.get("canTrade")))
            free = 0.0
            for b in acc.get("balances", []):
                if b["asset"] == "USDT":
                    free = float(b["free"])
            need = self.budget if self.mode == "live" else 0.0
            add(f"Serbest USDT ({free:.2f}) bot bütçesinden ({need:.2f}) az değil", free >= need)
            if self.mode == "live":
                r = await self.trader.api_restrictions()
                add("API anahtarında PARA ÇEKME izni KAPALI", r.get("enableWithdrawals") is False)
                add("API anahtarında Spot alım-satım izni açık", bool(r.get("enableSpotAndMarginTrading")))
                add("API anahtarında vadeli/kaldıraç izni kapalı", not r.get("enableFutures", False) and not r.get("enableMargin", False))
                if not r.get("ipRestrict"):
                    warnings.append("API anahtarına IP kısıtlaması konmamış. Binance'te anahtarı sadece bu bilgisayarın IP adresine kısıtlamanız önerilir.")
            # kayıtlı açık pozisyonlar borsadaki bakiyeyle uyumlu mu?
            async with self.db.session() as s:
                opens = (await s.execute(select(Position).where(Position.status == "open"))).scalars().all()
            bal = {b["asset"]: float(b["free"]) + float(b["locked"]) for b in acc.get("balances", [])}
            for p in opens:
                base = (self.symbol_info.get(p.symbol).base if p.symbol in self.symbol_info else p.symbol.removesuffix("USDT"))
                add(f"{p.symbol} pozisyonu borsadaki bakiyeyle uyumlu", bal.get(base, 0.0) >= p.quantity * 0.98)
        except ExchangeError as e:
            add(f"Borsa doğrulaması başarısız: {e}", False)
        ok = all(c["ok"] for c in checks)
        self.exchange_check = {"ok": ok, "mode": self.mode, "checks": checks, "warnings": warnings, "at": time.time()}
        return self.exchange_check

    async def set_running(self, on: bool, confirmed: bool = False) -> None:
        if on and self.emergency_stop:
            raise ValueError("Acil durdurma aktif. Önce acil durdurmayı kaldırın.")
        if on and self.mode == "live" and not confirmed:
            raise ValueError("Gerçek para modunda başlatmak için onay metnini yazmalısınız.")
        if on and self.mode != "paper":
            chk = await self.verify_exchange()
            if not chk["ok"]:
                bad = "; ".join(c["text"] for c in chk["checks"] if not c["ok"])
                raise ValueError(f"Güvenlik kontrolü başarısız, bot başlatılmadı: {bad}")
            if self.frozen:
                raise ValueError("Sonucu belirsiz kalan emir var. Borsa hesabınızı kontrol edip botu yeniden başlatın.")
        self.running = on
        if on:
            self.halted_reason = None
        await self._save_state()
        await self.log("INFO", "Bot başlatıldı" if on else "Bot durduruldu")
        if on and not self.universe:
            asyncio.create_task(self._safe(self.refresh_universe))

    async def _safe(self, fn) -> None:
        try:
            await fn()
        except Exception as e:  # noqa: BLE001
            await self.log("ERROR", f"Hata: {e}")

    async def set_emergency(self, on: bool, close_positions: bool = False) -> int:
        self.emergency_stop = on
        if on:
            self.running = False
        await self._save_state()
        await self.log("WARNING", "ACİL DURDURMA etkin" if on else "Acil durdurma kaldırıldı")
        if on and close_positions:
            return await self.close_all("Acil durdurma")
        return 0

    # ---------- raporlar ----------
    async def status(self) -> dict:
        async with self.db.session() as s:
            acc, positions, st = await self.portfolio(s)
            await s.commit()
            day_start = dt.datetime.strptime(today(), "%Y-%m-%d")
            today_trades = (await s.execute(select(func.count()).select_from(Trade).where(Trade.created_at >= day_start))).scalar()
            fees = (await s.execute(select(func.coalesce(func.sum(Trade.fee), 0.0)))).scalar()
            closed_count = (await s.execute(select(func.count()).select_from(Position).where(Position.status == "closed"))).scalar()
        top = sorted(self.latest.values(), key=lambda a: a.score, reverse=True)[:5]
        return {
            "mode": self.mode,
            "mode_label": self.label,
            "running": self.running,
            "emergency_stop": self.emergency_stop,
            "halted_reason": self.halted_reason,
            "equity": round(st.equity, 4),
            "cash": round(acc.cash, 4),
            "starting_balance": acc.starting_balance,
            "daily_pnl": round(st.equity - acc.day_start_equity, 4),
            "total_pnl": round(st.equity - acc.starting_balance, 4),
            "open_positions": len(positions),
            "open_exposure": round(st.open_exposure, 4),
            "closed_positions": closed_count,
            "tracked_coins": len(self.universe),
            "rejected_coins": self.rejected_count,
            "trades_today": today_trades,
            "total_fees": round(fees, 4),
            "ws_connected": bool(self.stream and self.stream.connected),
            "last_universe_at": self.last_universe_at,
            "last_analysis_at": self.last_analysis_at,
            "last_error": self.last_error,
            "top_opportunities": [{"symbol": a.symbol, "score": a.score, "label": a.label} for a in top],
        }

    async def report(self) -> dict:
        async with self.db.session() as s:
            closed = (await s.execute(select(Position).where(Position.status == "closed").order_by(Position.closed_at))).scalars().all()
            acc = await s.get(Account, 1)
        pnls = [p.realized_pnl for p in closed]
        wins = [x for x in pnls if x > 0]
        losses = [x for x in pnls if x <= 0]
        equity, peak, max_dd = acc.starting_balance, acc.starting_balance, 0.0
        daily: dict[str, float] = {}
        for p in closed:
            equity += p.realized_pnl
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak * 100 if peak else 0)
            d = p.closed_at.strftime("%Y-%m-%d")
            daily[d] = daily.get(d, 0.0) + p.realized_pnl
        gross_win, gross_loss = sum(wins), -sum(losses)
        return {
            "closed_trades": len(pnls),
            "net_pnl": round(sum(pnls), 4),
            "win_rate": round(len(wins) / len(pnls) * 100, 2) if pnls else None,
            "avg_win": round(gross_win / len(wins), 4) if wins else None,
            "avg_loss": round(-gross_loss / len(losses), 4) if losses else None,
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
            "max_drawdown_pct": round(max_dd, 3),
            "total_fees": round(sum(p.fees_paid for p in closed), 4),
            "daily": [{"day": k, "pnl": round(v, 4)} for k, v in sorted(daily.items())],
            "note": "Kazanç oranı tek başına başarı göstergesi değildir; net kâr, düşüş ve kâr faktörüne birlikte bakın.",
        }
