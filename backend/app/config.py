"""Uygulama yapılandırması (ortam değişkenleri / .env).

Bu dosyadaki değerler SUNUCU tarafı ayarlarıdır. Alım-satım kuralları (risk, hedef vb.)
panelden değiştirilebilir ve veritabanında saklanır: bkz. ``trading_settings.py``.
"""
from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Bu sürümde gerçek para ile emir gönderme KOD DÜZEYİNDE kapalıdır.
# Aşama 3 yalnızca kullanıcı ayrıca onay verdikten sonra, bilinçli bir kod değişikliğiyle açılır.
LIVE_TRADING_AVAILABLE = False


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite+aiosqlite:///./data/ai_kripto_trader.db"
    data_dir: Path = Path("./data")

    # Binance (yalnızca genel piyasa verisi için kullanılır; API anahtarı gerektirmez)
    binance_rest_url: str = "https://api.binance.com"
    binance_ws_url: str = "wss://stream.binance.com:9443/ws"
    binance_testnet_rest_url: str = "https://testnet.binance.vision"

    # Panel girişi
    admin_password: str = ""
    secret_key: str = ""
    session_hours: int = 12
    cookie_secure: bool = False  # HTTPS arkasında true yapın

    frontend_dist: Path = Path("../frontend/dist")
    log_level: str = "INFO"
    enable_bot_runtime: bool = True  # testlerde kapatılır


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()


def resolve_secret_key(cfg: AppConfig) -> str:
    """SECRET_KEY verilmemişse data klasöründe bir kez üretilip saklanır (izin: 600)."""
    if cfg.secret_key and len(cfg.secret_key) >= 32:
        return cfg.secret_key
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.data_dir / "secret.key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_urlsafe(48)
    path.write_text(key)
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - Windows vb.
        pass
    return key
