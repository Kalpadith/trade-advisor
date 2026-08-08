"""Candlestick pattern detection in pure pandas. Every pattern has an exact
arithmetic definition so each one is unit-testable, and all definitions only
reference the current and previous bars (causal)."""

import numpy as np
import pandas as pd

BULLISH_PATTERNS = [
    "pat_bull_engulf",
    "pat_hammer",
    "pat_morning_star",
    "pat_bull_harami",
    "pat_piercing_line",
    "pat_three_white_soldiers",
    "pat_tweezer_bottom",
]
BEARISH_PATTERNS = [
    "pat_bear_engulf",
    "pat_shooting_star",
    "pat_evening_star",
    "pat_bear_harami",
    "pat_dark_cloud_cover",
    "pat_three_black_crows",
    "pat_tweezer_top",
]
NEUTRAL_PATTERNS = ["pat_doji"]
PATTERN_COLUMNS = BULLISH_PATTERNS + BEARISH_PATTERNS + NEUTRAL_PATTERNS

PATTERN_LABELS = {
    "pat_bull_engulf": "bullish engulfing",
    "pat_bear_engulf": "bearish engulfing",
    "pat_hammer": "hammer",
    "pat_shooting_star": "shooting star",
    "pat_morning_star": "morning star",
    "pat_evening_star": "evening star",
    "pat_bull_harami": "bullish harami",
    "pat_bear_harami": "bearish harami",
    "pat_piercing_line": "piercing line",
    "pat_dark_cloud_cover": "dark cloud cover",
    "pat_three_white_soldiers": "three white soldiers",
    "pat_three_black_crows": "three black crows",
    "pat_tweezer_bottom": "tweezer bottom",
    "pat_tweezer_top": "tweezer top",
    "pat_doji": "doji",
}


def add_patterns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    o, h, l, c = out["open"], out["high"], out["low"], out["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    upper_wick = h - np.maximum(o, c)
    lower_wick = np.minimum(o, c) - l

    o1, c1, h1, l1 = o.shift(1), c.shift(1), h.shift(1), l.shift(1)
    body1 = (c1 - o1).abs()
    o2, c2 = o.shift(2), c.shift(2)
    body2 = (c2 - o2).abs()

    # trend filters: several reversal patterns only mean something after a leg
    down_leg = c1 < c.shift(6)
    up_leg = c1 > c.shift(6)

    # --- engulfing -------------------------------------------------------
    out["pat_bull_engulf"] = (
        (c1 < o1) & (c > o) & (c >= o1) & (o <= c1) & (body > body1)
    )
    out["pat_bear_engulf"] = (
        (c1 > o1) & (c < o) & (c <= o1) & (o >= c1) & (body > body1)
    )

    # --- doji ------------------------------------------------------------
    out["pat_doji"] = (body <= 0.1 * rng).fillna(False)

    # --- hammer family ---------------------------------------------------
    out["pat_hammer"] = (
        (lower_wick >= 2 * body) & (upper_wick <= body) & (body > 0) & down_leg
    )
    out["pat_shooting_star"] = (
        (upper_wick >= 2 * body) & (lower_wick <= body) & (body > 0) & up_leg
    )

    # --- stars (3-bar) ---------------------------------------------------
    mid2 = (o2 + c2) / 2
    out["pat_morning_star"] = (
        (c2 < o2) & (body1 < 0.3 * body2) & (c > o) & (c > mid2)
    )
    out["pat_evening_star"] = (
        (c2 > o2) & (body1 < 0.3 * body2) & (c < o) & (c < mid2)
    )

    # --- harami: small body fully inside the prior (large) opposite body -
    inside_prior_body = (np.maximum(o, c) <= np.maximum(o1, c1)) & (
        np.minimum(o, c) >= np.minimum(o1, c1)
    )
    out["pat_bull_harami"] = (
        (c1 < o1) & (c > o) & inside_prior_body & (body <= 0.6 * body1) & down_leg
    )
    out["pat_bear_harami"] = (
        (c1 > o1) & (c < o) & inside_prior_body & (body <= 0.6 * body1) & up_leg
    )

    # --- piercing line / dark cloud cover (2-bar, close beyond midpoint) -
    mid1 = (o1 + c1) / 2
    out["pat_piercing_line"] = (
        (c1 < o1) & (c > o) & (o < c1) & (c > mid1) & (c < o1) & down_leg
    )
    out["pat_dark_cloud_cover"] = (
        (c1 > o1) & (c < o) & (o > c1) & (c < mid1) & (c > o1) & up_leg
    )

    # --- three soldiers / crows: three consecutive strong closes ---------
    strong_bull = (c > o) & (body >= 0.6 * rng)
    strong_bear = (c < o) & (body >= 0.6 * rng)
    out["pat_three_white_soldiers"] = (
        strong_bull & strong_bull.shift(1, fill_value=False) & strong_bull.shift(2, fill_value=False)
        & (c > c1) & (c1 > c.shift(2))
    )
    out["pat_three_black_crows"] = (
        strong_bear & strong_bear.shift(1, fill_value=False) & strong_bear.shift(2, fill_value=False)
        & (c < c1) & (c1 < c.shift(2))
    )

    # --- tweezers: two bars sharing an extreme (within 10% of the range) -
    tol = 0.1 * rng
    out["pat_tweezer_bottom"] = (
        ((l - l1).abs() <= tol) & (c1 < o1) & (c > o) & down_leg
    )
    out["pat_tweezer_top"] = (
        ((h - h1).abs() <= tol) & (c1 > o1) & (c < o) & up_leg
    )

    for col in PATTERN_COLUMNS:
        out[col] = out[col].fillna(False).astype(bool)
    return out
