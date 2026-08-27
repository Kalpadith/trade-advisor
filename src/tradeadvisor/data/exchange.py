"""Exchange adapter protocol. Only Binance is implemented in v1, but any
exchange that can serve OHLCV candles can be plugged in behind this interface."""

from typing import Protocol

from tradeadvisor.models import Candle


class ExchangeAdapter(Protocol):
    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[Candle]:
        """Fetch a single page of klines."""
        ...

    def fetch_klines_range(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int | None = None,
    ) -> list[Candle]:
        """Fetch a full time range, paginating as needed."""
        ...

    def list_symbols(self, quote: str = "USDT") -> list[str]:
        ...
