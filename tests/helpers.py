"""Synthetic OHLCV generators used across the test suite."""

import numpy as np
import pandas as pd

HOUR_MS = 3_600_000
DEFAULT_START = 1_700_000_000_000  # 2023-11-14 UTC, fixed for determinism


def make_ohlcv(
    n: int = 400,
    seed: int = 42,
    trend: float = 0.0,
    volatility: float = 1.0,
    start_price: float = 100.0,
    interval_ms: int = HOUR_MS,
    start_time: int = DEFAULT_START,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(trend, volatility, n)
    closes = np.maximum(start_price + np.cumsum(steps), 1.0)
    opens = np.concatenate([[start_price], closes[:-1]])
    wick = np.abs(rng.normal(0, volatility * 0.5, n))
    highs = np.maximum(opens, closes) + wick
    lows = np.maximum(np.minimum(opens, closes) - wick, 0.5)
    volume = rng.lognormal(3, 0.5, n)
    open_time = start_time + np.arange(n, dtype=np.int64) * interval_ms

    df = pd.DataFrame({
        "open_time": open_time,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volume,
        "close_time": open_time + interval_ms - 1,
    })
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.index.name = "time"
    return df


def df_from_rows(rows: list[tuple[float, float, float, float]], interval_ms: int = HOUR_MS) -> pd.DataFrame:
    """Build a small frame from explicit (open, high, low, close) tuples."""
    open_time = DEFAULT_START + np.arange(len(rows), dtype=np.int64) * interval_ms
    o, h, l, c = zip(*rows)
    df = pd.DataFrame({
        "open_time": open_time,
        "open": o, "high": h, "low": l, "close": c,
        "volume": [100.0] * len(rows),
        "close_time": open_time + interval_ms - 1,
    })
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.index.name = "time"
    return df


def make_frames(seed: int = 7, trend: float = 0.05, n_entry: int = 500) -> dict[str, pd.DataFrame]:
    """Entry (1h) / context (4h) / bias (1d) frames with a shared drift."""
    return {
        "entry": make_ohlcv(n_entry, seed=seed, trend=trend, volatility=1.0, interval_ms=HOUR_MS),
        "context": make_ohlcv(350, seed=seed + 1, trend=trend * 4, volatility=2.0, interval_ms=4 * HOUR_MS),
        "bias": make_ohlcv(300, seed=seed + 2, trend=trend * 24, volatility=5.0, interval_ms=24 * HOUR_MS),
    }
