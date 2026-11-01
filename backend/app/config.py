"""Uygulama ayarları (.env dosyasından okunur).

Üç çalışma modu vardır:
  paper   : sanal işlem (varsayılan, para riski yok)
  testnet : Binance Spot Testnet (sahte para, gerçek emir akışı denemesi)
  live    : GERÇEK PARA. Yalnızca LIVE_CONFIRM değeri tam olarak yazılırsa açılır.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict

LIVE_CONFIRM_TEXT = "GERCEK-PARA-RISKINI-KABUL-EDIYORUM"
TESTNET_REST = "https://testnet.binance.vision"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    trading_mode: str = "paper"
    live_confirm: str = ""
    panel_username: str = "admin"
    panel_password: str = ""
    starting_balance: float = 1000.0
    live_budget_usdt: float = 30.0        # botun gerçek hesapta kullanabileceği AZAMİ toplam tutar
    live_max_order_usdt: float = 10.0     # tek bir alımın azami tutarı
    binance_rest_url: str = "https://api.binance.com"
    binance_ws_url: str = "wss://stream.binance.com:9443"
    database_url: str = "sqlite+aiosqlite:///./data/trader.db"

    @property
    def is_live(self) -> bool:
        return self.trading_mode == "live"

    @property
    def db_url(self) -> str:
        """Her mod kendi veritabanını kullanır; sanal ve gerçek kayıtlar karışmaz."""
        if self.trading_mode != "paper" and "trader.db" in self.database_url:
            return self.database_url.replace("trader.db", f"trader_{self.trading_mode}.db")
        return self.database_url

    @property
    def effective_starting_balance(self) -> float:
        return self.live_budget_usdt if self.is_live else self.starting_balance

    def validate_safety(self) -> None:
        if self.trading_mode not in ("paper", "testnet", "live"):
            raise RuntimeError(f"TRADING_MODE='{self.trading_mode}' geçersiz. paper, testnet veya live olmalı.")
        if self.is_live and self.live_confirm != LIVE_CONFIRM_TEXT:
            raise RuntimeError(
                "Gerçek para modu için .env dosyasına şu satır da yazılmalı:\n"
                f"LIVE_CONFIRM={LIVE_CONFIRM_TEXT}\n"
                "Bu, gerçek para kaybedebileceğinizi kabul ettiğiniz anlamına gelir."
            )
        if self.is_live and not (1 <= self.live_budget_usdt <= 1000):
            raise RuntimeError("LIVE_BUDGET_USDT 1 ile 1000 arasında olmalı (güvenlik sınırı).")
        if self.is_live and not (1 <= self.live_max_order_usdt <= self.live_budget_usdt):
            raise RuntimeError("LIVE_MAX_ORDER_USDT 1 ile LIVE_BUDGET_USDT arasında olmalı.")
        if len(self.panel_password) < 10:
            raise RuntimeError(
                "PANEL_PASSWORD .env dosyasında en az 10 karakter olacak şekilde ayarlanmalı."
            )


settings = Settings()
