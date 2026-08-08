import numpy as np

from helpers import df_from_rows, make_ohlcv
from tradeadvisor.indicators.levels import cluster_levels, find_swings


def _zigzag(n_cycles: int = 6, period: int = 10):
    """Triangle wave: swing highs at the peaks, lows at the troughs."""
    rows = []
    for cycle in range(n_cycles):
        for step in range(period):
            up = step < period // 2
            base = 100 + (step if up else period - step)
            rows.append((base, base + 0.4, base - 0.4, base + (0.2 if up else -0.2)))
    return df_from_rows(rows)


def test_swings_detected_on_zigzag():
    df = _zigzag()
    swings = find_swings(df, k=3)
    assert (swings.kind == "H").sum() >= 4
    assert (swings.kind == "L").sum() >= 4


def test_no_swing_in_last_k_bars():
    """A swing needs k later bars to confirm, so the final k positions can
    never hold a swing — the structural lookahead guard."""
    df = make_ohlcv(300, seed=11)
    k = 3
    swings = find_swings(df, k=k)
    assert len(swings) > 0
    assert swings.pos.max() <= len(df) - 1 - k
    assert (swings.confirmed_pos == swings.pos + k).all()


def test_visible_filter():
    df = make_ohlcv(300, seed=12)
    swings = find_swings(df, k=3)
    cut = 150
    vis = swings.visible(cut)
    assert (vis.confirmed_pos <= cut).all()
    assert len(vis) < len(swings)


def test_cluster_merges_nearby_swings():
    df = _zigzag()
    swings = find_swings(df, k=3)
    levels = cluster_levels(swings, last_close=103.0, atr=1.0)
    assert levels, "expected at least one level"
    # the zigzag repeats the same peaks/troughs, so clusters must have touches
    assert max(lv.strength for lv in levels) >= 2
    for lv in levels:
        assert lv.kind == ("support" if lv.price <= 103.0 else "resistance")


def test_cluster_handles_no_swings():
    df = make_ohlcv(10, seed=13)
    swings = find_swings(df, k=3)
    assert cluster_levels(swings, 100.0, float("nan")) == []
