from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TADVISOR_", extra="ignore")

    binance_base_url: str = "https://api.binance.com"
    # Tried in order when the primary endpoint is geo-blocked (HTTP 451).
    fallback_base_urls: list[str] = [
        "https://data-api.binance.vision",
        "https://api1.binance.com",
        "https://api4.binance.com",
    ]
    db_path: Path = Path("data/market.db")
    default_account_size: float = 10_000.0
    default_risk_pct: float = 1.0
    fee_pct: float = 0.1
    slippage_pct: float = 0.05


@lru_cache
def get_settings() -> Settings:
    return Settings()
