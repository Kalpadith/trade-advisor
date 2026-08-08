"""Wiring helpers shared by the CLI and the API: build the service stack and
load the multi-timeframe frames the engine needs."""

import pandas as pd

from tradeadvisor.config import Settings, get_settings
from tradeadvisor.data.binance import BinanceAdapter
from tradeadvisor.data.service import MarketDataService
from tradeadvisor.data.store import CandleStore
from tradeadvisor.models import Recommendation
from tradeadvisor.signals.engine import SignalEngine
from tradeadvisor.timeframes import TF_CONFIG

ENTRY_LOOKBACK = 500
HIGHER_LOOKBACK = 400  # enough for EMA200 + slack on bias/context frames


def build_service(settings: Settings | None = None) -> MarketDataService:
    settings = settings or get_settings()
    adapters = {
        "spot": BinanceAdapter(
            base_url=settings.binance_base_url,
            fallback_base_urls=settings.fallback_base_urls,
            market="spot",
        ),
        "futures": BinanceAdapter(
            base_url=settings.binance_futures_base_url,
            market="futures",
        ),
    }
    store = CandleStore(settings.db_path)
    return MarketDataService(adapters, store)


def _role_timeframes(entry_tf: str) -> dict[str, str]:
    roles = TF_CONFIG[entry_tf]
    return {"entry": entry_tf, "context": roles.context, "bias": roles.bias}


def load_frames(
    service: MarketDataService, symbol: str, entry_tf: str, market: str = "spot"
) -> dict[str, pd.DataFrame]:
    """Fetch the entry/context/bias frames, reusing one DataFrame when two
    roles share a timeframe (identity is meaningful downstream)."""
    frames: dict[str, pd.DataFrame] = {}
    by_tf: dict[str, pd.DataFrame] = {}
    for role, tf in _role_timeframes(entry_tf).items():
        if tf not in by_tf:
            lookback = ENTRY_LOOKBACK if role == "entry" else HIGHER_LOOKBACK
            by_tf[tf] = service.get(symbol, tf, lookback_bars=lookback, market=market)
        frames[role] = by_tf[tf]
    return frames


def load_backtest_frames(
    service: MarketDataService,
    symbol: str,
    entry_tf: str,
    start_ms: int,
    end_ms: int | None = None,
    warmup_bars: int = 250,
    market: str = "spot",
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    by_tf: dict[str, pd.DataFrame] = {}
    for role, tf in _role_timeframes(entry_tf).items():
        if tf not in by_tf:
            by_tf[tf] = service.get_range(
                symbol, tf, start_ms, end_ms, warmup_bars=warmup_bars, market=market
            )
        frames[role] = by_tf[tf]
    return frames


def analyze_symbol(
    service: MarketDataService,
    engine: SignalEngine,
    symbol: str,
    entry_tf: str,
    account_size: float,
    risk_pct: float,
    market: str = "spot",
) -> Recommendation:
    frames = load_frames(service, symbol, entry_tf, market=market)
    return engine.analyze(
        symbol,
        entry_tf,
        frames["entry"],
        frames["context"],
        frames["bias"],
        account_size=account_size,
        risk_pct=risk_pct,
        market=market,
    )
