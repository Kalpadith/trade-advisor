"""Candlestick pattern detection in pure pandas. Every pattern has an exact
arithmetic definition so each one is unit-testable, and all definitions only
reference the current and previous bars (causal)."""

import numpy as np
import pandas as pd

BULLISH_PATTERNS = ["pat_bull_engulf", "pat_hammer", "pat_morning_star"]
BEARISH_PATTERNS = ["pat_bear_engulf", "pat_shooting_star", "pat_evening_star"]
NEUTRAL_PATTERNS = ["pat_doji"]
PATTERN_COLUMNS = BULLISH_PATTERNS + BEARISH_PATTERNS + NEUTRAL_PATTERNS

PATTERN_LABELS = {
    "pat_bull_engulf": "bullish engulfing",
    "pat_bear_engulf": "bearish engulfing",
    "pat_hammer": "hammer",
    "pat_shooting_star": "shooting star",
    "pat_morning_star": "morning star",
    "pat_evening_star": "evening star",
    "pat_doji": "doji",
}


def add_patterns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    o, h, l, c = out["open"], out["high"], out["low"], out["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    upper_wick = h - np.maximum(o, c)
    lower_wick = np.minimum(o, c) - l

    prev_o, prev_c = o.shift(1), c.shift(1)
    prev_body = (prev_c - prev_o).abs()

    out["pat_bull_engulf"] = (
        (prev_c < prev_o) & (c > o)
        & (c >= prev_o) & (o <= prev_c)
        & (body > prev_body)
    )
    out["pat_bear_engulf"] = (
        (prev_c > prev_o) & (c < o)
        & (c <= prev_o) & (o >= prev_c)
        & (body > prev_body)
    )

    out["pat_doji"] = (body <= 0.1 * rng).fillna(False)

    # A hammer only means reversal after a down-leg (and mirror for the
    # shooting star), so gate on a 5-bar directional filter.
    down_leg = c.shift(1) < c.shift(6)
    up_leg = c.shift(1) > c.shift(6)
    out["pat_hammer"] = (
        (lower_wick >= 2 * body) & (upper_wick <= body) & (body > 0) & down_leg
    )
    out["pat_shooting_star"] = (
        (upper_wick >= 2 * body) & (lower_wick <= body) & (body > 0) & up_leg
    )

    o2, c2 = o.shift(2), c.shift(2)
    body2 = (c2 - o2).abs()
    body1 = (c.shift(1) - o.shift(1)).abs()
    mid2 = (o2 + c2) / 2
    out["pat_morning_star"] = (
        (c2 < o2) & (body1 < 0.3 * body2) & (c > o) & (c > mid2)
    )
    out["pat_evening_star"] = (
        (c2 > o2) & (body1 < 0.3 * body2) & (c < o) & (c < mid2)
    )

    for col in PATTERN_COLUMNS:
        out[col] = out[col].fillna(False).astype(bool)
    return out
