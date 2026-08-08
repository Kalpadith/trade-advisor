import numpy as np
import pandas as pd

from helpers import make_ohlcv
from tradeadvisor.indicators.core import INDICATOR_COLUMNS, enrich


def test_enrich_adds_all_columns():
    df = enrich(make_ohlcv(300))
    for col in INDICATOR_COLUMNS:
        assert col in df.columns


def test_property_bounds():
    df = enrich(make_ohlcv(300, seed=1))
    rsi = df["rsi14"].dropna()
    assert ((rsi >= 0) & (rsi <= 100)).all()
    stoch = df["stoch_k"].dropna()
    assert ((stoch >= 0) & (stoch <= 100)).all()
    assert (df["atr14"].dropna() >= 0).all()
    valid = df.dropna(subset=["bb_upper", "bb_mid", "bb_lower"])
    assert (valid["bb_lower"] <= valid["bb_mid"] + 1e-9).all()
    assert (valid["bb_mid"] <= valid["bb_upper"] + 1e-9).all()


def test_ema_matches_pandas_reference():
    df = make_ohlcv(300, seed=2)
    out = enrich(df)
    ref = df["close"].ewm(span=20, min_periods=20, adjust=False).mean()
    pd.testing.assert_series_equal(
        out["ema20"].dropna(), ref.dropna(), check_names=False, atol=1e-9, rtol=0
    )


def test_rsi_matches_wilder_reference():
    """ta's RSI uses Wilder smoothing (ewm alpha=1/n, adjust=False).
    Compare well past warmup where seeding differences have converged."""
    df = make_ohlcv(400, seed=3)
    out = enrich(df)
    delta = df["close"].diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    avg_up = up.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_down = down.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    ref = 100 - 100 / (1 + avg_up / avg_down)
    diff = (out["rsi14"] - ref).iloc[150:].abs()
    assert diff.max() < 0.5


def test_obv_increases_on_rising_market():
    n = 100
    df = make_ohlcv(n, seed=4, trend=5.0, volatility=0.01)  # closes strictly rising
    out = enrich(df)
    obv = out["obv"].to_numpy()
    assert (np.diff(obv) >= 0).all()
