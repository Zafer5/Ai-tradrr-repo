import pytest

from app.db import Database
from app.risk.manager import RiskDecision
from app.trading.exits import ExitAction
from app.trading.service import PaperBroker, TradingService
from app.trading_settings import SettingsStore, TradingSettings


@pytest.fixture
async def svc(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/p.db")
    await db.create_all()
    store = SettingsStore(db)
    s = TradingService(db, store)
    await s.ensure_account()
    yield s, store
    await db.dispose()


def test_broker_fill_model():
    s = TradingSettings()
    b = PaperBroker.buy(100.0, 2.0, s)
    assert b.price == pytest.approx(100.05) and b.fee == pytest.approx(100.05 * 2 * 0.001)
    m = PaperBroker.sell("MARKET", 100.0, 1.0, s)
    assert m.price == pytest.approx(99.95)
    l = PaperBroker.sell("LIMIT", 103.0, 1.0, s)
    assert l.price == 103.0 and l.fee == pytest.approx(0.103)


async def test_full_trade_cycle_pnl_and_cash_reconcile(svc):
    service, store = svc
    s = await store.get()
    dec = RiskDecision(True, ["ok"], quantity=0.5, notional=50.0)
    pos = await service.open_position("ABCUSDT", 100.0, dec, 98.5, 103.0, 106.0, 80.0, "Orta", "test", s)
    assert pos.entry_price == pytest.approx(100.05)
    cost = 0.5 * 100.05 + 0.5 * 100.05 * 0.001
    assert (await service.account())["cash"] == pytest.approx(1000 - cost)

    await service.execute_exit(pos.id, ExitAction(0.5, "TAKE_PROFIT_1", "LIMIT", 103.0), s)
    p = (await service.open_positions())[0]
    assert p.quantity == pytest.approx(0.25) and p.tp1_done and p.status == "OPEN"
    assert p.realized_pnl == pytest.approx(0.25 * 103 * (1 - 0.001) - cost * 0.5)

    await service.execute_exit(pos.id, ExitAction(1.0, "TAKE_PROFIT_2", "LIMIT", 106.0), s)
    assert await service.open_positions() == []
    acc = await service.account()
    total_pnl = acc["cash"] - 1000
    assert total_pnl > 0
    # nakit farkı == pozisyonun raporlanan net kâr/zararı (muhasebe tutarlılığı)
    from sqlalchemy import select

    from app.models import Position

    async with service.db.session() as ses:
        closed = (await ses.execute(select(Position))).scalar_one()
    assert closed.status == "CLOSED" and closed.close_reason == "TAKE_PROFIT_2"
    assert closed.realized_pnl == pytest.approx(total_pnl)
    assert closed.fees_total == pytest.approx(0.5 * 100.05 * 0.001 + 0.25 * 103 * 0.001 + 0.25 * 106 * 0.001)


async def test_stop_loss_realizes_a_loss_with_slippage_and_fees(svc):
    service, store = svc
    s = await store.get()
    pos = await service.open_position("ABCUSDT", 100.0, RiskDecision(True, [], quantity=1.0, notional=100), 98.5, 103, 106, 75, "Orta", "", s)
    await service.execute_exit(pos.id, ExitAction(1.0, "STOP_LOSS", "MARKET", 98.4), s)
    acc = await service.account()
    expected = 98.4 * 0.9995 * (1 - 0.001) - 100.05 * (1 + 0.001)
    assert acc["cash"] - 1000 == pytest.approx(expected)
    assert expected < 0


async def test_cannot_buy_with_insufficient_cash(svc):
    service, store = svc
    s = await store.get()
    pos = await service.open_position("ABCUSDT", 100.0, RiskDecision(True, [], quantity=50.0, notional=5000), 98, 103, 106, 80, "Orta", "", s)
    assert pos is None and (await service.account())["cash"] == 1000


async def test_equity_includes_open_positions_and_day_pnl(svc):
    service, store = svc
    s = await store.get()
    await service.open_position("ABCUSDT", 100.0, RiskDecision(True, [], quantity=1.0, notional=100), 98, 103, 106, 80, "Orta", "", s)
    eq, cash, val = await service.equity({"ABCUSDT": 110.0})
    assert val == pytest.approx(110.0) and eq == pytest.approx(cash + 110.0)
    snap = await service.snapshot({"ABCUSDT": 110.0}, set(), 60)
    assert snap.open_positions == {"ABCUSDT": pytest.approx(110.0)} and snap.trades_today == 1 and snap.day_pnl_pct > 0


async def test_cooldown_after_close(svc):
    service, store = svc
    s = await store.get()
    pos = await service.open_position("ABCUSDT", 100.0, RiskDecision(True, [], quantity=1.0, notional=100), 98, 103, 106, 80, "Orta", "", s)
    await service.execute_exit(pos.id, ExitAction(1.0, "MANUAL", "MARKET", 100.0), s)
    assert "ABCUSDT" in (await service.snapshot({}, set(), 60)).cooldown_symbols
    assert "ABCUSDT" not in (await service.snapshot({}, set(), 0)).cooldown_symbols
