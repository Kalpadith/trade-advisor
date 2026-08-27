"""Binance public REST adapter. Market data only - no API key, no trading."""

import logging
import time

import httpx

from tradeadvisor.models import Candle
from tradeadvisor.timeframes import INTERVAL_MS

log = logging.getLogger(__name__)

# klines request weight is 2; the per-IP budget is 6000/min. Back off well
# before the cap so a long backfill never trips a 429.
WEIGHT_SOFT_LIMIT = 5000
SYMBOLS_CACHE_TTL = 3600.0


class GeoBlockedError(RuntimeError):
    pass


class BannedError(RuntimeError):
    pass


class BinanceAdapter:
    def __init__(
        self,
        base_url: str = "https://api.binance.com",
        fallback_base_urls: list[str] | None = None,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
        market: str = "spot",
    ):
        self.market = market
        if market == "futures":
            self._klines_path = "/fapi/v1/klines"
            self._exchange_info_path = "/fapi/v1/exchangeInfo"
        else:
            self._klines_path = "/api/v3/klines"
            self._exchange_info_path = "/api/v3/exchangeInfo"
        self.base_url = base_url.rstrip("/")
        self.fallback_base_urls = [u.rstrip("/") for u in (fallback_base_urls or [])]
        self._client = client or httpx.Client(timeout=timeout)
        self._symbols_cache: tuple[float, list[str]] | None = None

    def _request(self, path: str, params: dict) -> httpx.Response:
        bases = [self.base_url] + [u for u in self.fallback_base_urls if u != self.base_url]
        last_error: Exception | None = None
        for base in bases:
            for attempt in range(3):
                try:
                    resp = self._client.get(base + path, params=params)
                except httpx.TransportError as exc:
                    last_error = exc
                    time.sleep(1.0 * (attempt + 1))
                    continue

                if resp.status_code == 451:
                    log.warning("%s is geo-blocked (451), trying next endpoint", base)
                    last_error = GeoBlockedError(
                        f"{base} returned 451 (geo-blocked). Set TADVISOR_BINANCE_BASE_URL "
                        "to a reachable endpoint, e.g. https://data-api.binance.vision"
                    )
                    break  # next base URL
                if resp.status_code == 418:
                    raise BannedError(
                        "Binance returned 418: this IP is temporarily auto-banned for "
                        "rate-limit abuse. Stop and wait before retrying."
                    )
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", 5)) + 1.0
                    log.warning("Rate limited (429), sleeping %.0fs", wait)
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    last_error = httpx.HTTPStatusError(
                        f"{resp.status_code} from {base}", request=resp.request, response=resp
                    )
                    time.sleep(1.0 * (attempt + 1))
                    continue

                resp.raise_for_status()

                # Promote a working fallback to primary for the rest of the session.
                if base != self.base_url:
                    log.info("Switching primary Binance endpoint to %s", base)
                    self.base_url = base

                used = resp.headers.get("X-MBX-USED-WEIGHT-1M")
                if used and int(used) > WEIGHT_SOFT_LIMIT:
                    log.info("Request weight %s near limit, pausing 10s", used)
                    time.sleep(10)
                return resp
        raise last_error or RuntimeError("all Binance endpoints failed")

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[Candle]:
        params: dict = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
        if start_ms is not None:
            params["startTime"] = int(start_ms)
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        rows = self._request(self._klines_path, params).json()
        return [
            Candle(
                open_time=int(r[0]),
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                volume=float(r[5]),
                close_time=int(r[6]),
            )
            for r in rows
        ]

    def fetch_klines_range(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int | None = None,
    ) -> list[Candle]:
        step = INTERVAL_MS[interval]
        out: list[Candle] = []
        cursor = int(start_ms)
        while True:
            page = self.fetch_klines(symbol, interval, start_ms=cursor, end_ms=end_ms)
            if not page:
                break
            out.extend(page)
            if len(page) < 1000:
                break
            cursor = page[-1].open_time + step
            if end_ms is not None and cursor > end_ms:
                break
        return out

    def list_symbols(self, quote: str = "USDT") -> list[str]:
        if self._symbols_cache and time.monotonic() - self._symbols_cache[0] < SYMBOLS_CACHE_TTL:
            return self._symbols_cache[1]
        info = self._request(self._exchange_info_path, {}).json()
        symbols = sorted(
            s["symbol"]
            for s in info.get("symbols", [])
            if s.get("status") == "TRADING"
            and s.get("quoteAsset") == quote
            # futures exchangeInfo lists delivery contracts too; keep perpetuals
            and s.get("contractType", "PERPETUAL") == "PERPETUAL"
        )
        self._symbols_cache = (time.monotonic(), symbols)
        return symbols
