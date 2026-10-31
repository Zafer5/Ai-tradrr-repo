"""Uygulama ayarları (.env dosyasından okunur)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    trading_mode: str = "paper"
    panel_username: str = "admin"
    panel_password: str = ""
    starting_balance: float = 1000.0
    binance_rest_url: str = "https://api.binance.com"
    binance_ws_url: str = "wss://stream.binance.com:9443"
    database_url: str = "sqlite+aiosqlite:///./data/trader.db"

    def validate_safety(self) -> None:
        if self.trading_mode not in ("paper",):
            raise RuntimeError(
                f"TRADING_MODE='{self.trading_mode}' desteklenmiyor. Bu sürüm yalnızca "
                "'paper' (sanal işlem) modunda çalışır. Gerçek para modu kapalıdır."
            )
        if len(self.panel_password) < 10:
            raise RuntimeError(
                "PANEL_PASSWORD .env dosyasında en az 10 karakter olacak şekilde ayarlanmalı."
            )


settings = Settings()
