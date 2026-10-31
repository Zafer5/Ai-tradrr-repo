"""Veritabanı tabloları (SQLAlchemy 2.0)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class KV(Base):
    """Basit anahtar-değer deposu (ayarlar, bot durumu, sanal hesap, gün başı bakiye)."""

    __tablename__ = "kv"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Position(Base):
    """Bir alım-satım döngüsü (alımdan tam çıkışa kadar)."""

    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    mode: Mapped[str] = mapped_column(String(12), default="paper")
    status: Mapped[str] = mapped_column(String(8), default="OPEN", index=True)  # OPEN | CLOSED

    entry_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)  # kalan miktar
    initial_quantity: Mapped[float] = mapped_column(Float)
    cost_total: Mapped[float] = mapped_column(Float)  # alım bedeli + alım komisyonu
    stop_price: Mapped[float] = mapped_column(Float)
    tp1_price: Mapped[float] = mapped_column(Float)
    tp2_price: Mapped[float] = mapped_column(Float)
    tp1_done: Mapped[bool] = mapped_column(Boolean, default=False)
    peak_price: Mapped[float] = mapped_column(Float)
    trailing_active: Mapped[bool] = mapped_column(Boolean, default=False)

    est_fees: Mapped[float] = mapped_column(Float, default=0.0)  # tahmini toplam komisyon (gidiş-dönüş)
    fees_total: Mapped[float] = mapped_column(Float, default=0.0)  # gerçekleşen komisyon
    proceeds_total: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)  # net (komisyon dahil)

    score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(12), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Order(Base):
    """Gerçekleşen her dolum (alış / satış)."""

    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    mode: Mapped[str] = mapped_column(String(12), default="paper")
    side: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    order_type: Mapped[str] = mapped_column(String(12))  # MARKET | LIMIT
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AnalysisLog(Base):
    """AI kararlarının kaydı - sonradan sonuçlarını ölçmek için (kendi kendine strateji DEĞİŞTİRMEZ)."""

    __tablename__ = "analysis_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    price: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(32))
    risk: Mapped[str] = mapped_column(String(12))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ret_1h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    ret_4h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)


class LogEntry(Base):
    __tablename__ = "logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(10), index=True)
    source: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)


class ApiCredential(Base):
    """Şifreli API anahtarları. Düz metin ASLA saklanmaz, ASLA frontend'e gönderilmez."""

    __tablename__ = "api_credentials"
    env: Mapped[str] = mapped_column(String(12), primary_key=True)  # testnet | live
    api_key_enc: Mapped[str] = mapped_column(Text)
    api_secret_enc: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(24))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)


class Holding(Base):
    """Kullanıcının MEVCUT coinleri (elle girilmiş veya Binance'ten salt okunur çekilmiş).
    Bu kayıtlar paper trading hesabından AYRIDIR. Gerçek hesapta emir gönderilmez; yönetim 'gölge' (sanal) yapılır."""

    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset: Mapped[str] = mapped_column(String(16), unique=True)  # BTC
    symbol: Mapped[str] = mapped_column(String(24))  # BTCUSDT
    quantity: Mapped[float] = mapped_column(Float)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)  # USDT başına
    cost_known: Mapped[bool] = mapped_column(Boolean, default=False)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    fees_paid: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(12), default="manual")  # manual | binance
    managed: Mapped[bool] = mapped_column(Boolean, default=True)  # False = işlem dışı bırak
    peak_price: Mapped[float] = mapped_column(Float, default=0.0)
    trailing_active: Mapped[bool] = mapped_column(Boolean, default=False)
    tp_done: Mapped[bool] = mapped_column(Boolean, default=False)  # hedefte kısmi satış yapıldı (tekrarlanmaz)
    note: Mapped[str] = mapped_column(String(200), default="")
    last_decision: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PortfolioAction(Base):
    """Portföy yöneticisinin önerileri / gölge işlemleri."""

    __tablename__ = "portfolio_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    asset: Mapped[str] = mapped_column(String(16), index=True)
    action: Mapped[str] = mapped_column(String(16))  # TAKE_PROFIT | TRAIL_EXIT | REDUCE_RISK | STOP
    mode: Mapped[str] = mapped_column(String(10))  # oneri | golge
    fraction: Mapped[float] = mapped_column(Float, default=0.0)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    level: Mapped[str] = mapped_column(String(8), default="info")  # info | good | warn | bad
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
