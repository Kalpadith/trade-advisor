"""Cache-aside market data service: serve candles from SQLite, fetching only
what is missing from the exchange. The still-forming candle is dropped here -
everything downstream sees closed candles only.

Holds one adapter per market ("spot", "futures"); every method takes the
market it should read from."""

import time

import pandas as pd

from tradeadvisor.data.exchange import ExchangeAdapter
from tradeadvisor.data.store import CandleStore
from tradeadvisor.models import Candle
from tradeadvisor.timeframes import INTERVAL_MS


def now_ms() -> int:
    return int(time.time() * 1000)


class MarketDataService:
    def __init__(
        self,
        adapters: ExchangeAdapter | dict[str, ExchangeAdapter],
        store: CandleStore,
    ):
        if not isinstance(adapters, dict):
            adapters = {"spot": adapters}
        self.adapters = adapters
        self.store = store

    @property
    def adapter(self) -> ExchangeAdapter:
        """Backwards-friendly handle to the spot adapter."""
        return self.adapters["spot"]

    def adapter_for(self, market: str) -> ExchangeAdapter:
        try:
            return self.adapters[market]
        except KeyError:
            raise ValueError(f"no adapter configured for market '{market}'") from None

    def _drop_forming(self, candles: list[Candle], now: int) -> list[Candle]:
        return [c for c in candles if c.close_time <= now]

    def _sync_range(self, symbol: str, interval: str, start_ms: int, end_ms: int, market: str) -> None:
        """Fetch whatever part of [start_ms, end_ms] the store does not cover.
        Only head/tail gaps are detected; interior gaps (exchange downtime)
        are tolerated by the indicator layer."""
        step = INTERVAL_MS[interval]
        now = now_ms()
        earliest = self.store.earliest_open_time(symbol, interval, market=market)
        latest = self.store.latest_open_time(symbol, interval, market=market)

        fetches: list[tuple[int, int]] = []
        if earliest is None or latest is None:
            fetches.append((start_ms, end_ms))
        else:
            if start_ms < earliest - step:
                fetches.append((start_ms, earliest - 1))
            if end_ms > latest + step - 1:
                fetches.append((latest + step, end_ms))

        adapter = self.adapter_for(market)
        for lo, hi in fetches:
            if lo >= hi or lo >= now:
                continue
            candles = adapter.fetch_klines_range(symbol, interval, start_ms=lo, end_ms=hi)
            candles = self._drop_forming(candles, now)
            self.store.upsert(symbol, interval, candles, market=market)

    def get(
        self, symbol: str, interval: str, lookback_bars: int = 500, market: str = "spot"
    ) -> pd.DataFrame:
        """Most recent `lookback_bars` closed candles, syncing the cache first."""
        now = now_ms()
        # +1 bar: the window from `now` includes the still-forming bar, which
        # is dropped, so an exact-lookback window would come up one short.
        start = now - (lookback_bars + 1) * INTERVAL_MS[interval]
        self._sync_range(symbol, interval, start, now, market)
        return self.store.load(symbol, interval, limit=lookback_bars, market=market)

    def get_range(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int | None = None,
        warmup_bars: int = 250,
        market: str = "spot",
    ) -> pd.DataFrame:
        """Candles covering [start - warmup, end], syncing the cache first.
        The warmup padding gives indicators (EMA200 etc.) room to converge
        before the requested window begins."""
        now = now_ms()
        end = min(end_ms, now) if end_ms is not None else now
        fetch_start = start_ms - warmup_bars * INTERVAL_MS[interval]
        self._sync_range(symbol, interval, fetch_start, end, market)
        return self.store.load(symbol, interval, start_ms=fetch_start, end_ms=end, market=market)
