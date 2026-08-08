"""Swing point detection and support/resistance clustering.

A swing high at bar i requires the k bars on each side to be lower, so a swing
only exists once k bars have printed after it. `find_swings` computed on a
prefix therefore never sees unconfirmed swings (lookahead-safe by
construction); when computed once on full history, `confirmed_pos` lets the
backtester filter to what was visible at each decision bar."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tradeadvisor.models import Level


@dataclass
class Swings:
    pos: np.ndarray            # integer bar positions
    price: np.ndarray
    kind: np.ndarray           # "H" or "L"
    time: np.ndarray           # open_time ms
    confirmed_pos: np.ndarray  # pos + k: first bar at which the swing is known

    def visible(self, upto_pos: int) -> "Swings":
        m = self.confirmed_pos <= upto_pos
        return Swings(self.pos[m], self.price[m], self.kind[m], self.time[m], self.confirmed_pos[m])

    def __len__(self) -> int:
        return len(self.pos)


def find_swings(df: pd.DataFrame, k: int = 3) -> Swings:
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    times = df["open_time"].to_numpy()
    n = len(df)
    win = 2 * k + 1

    pos_list: list[int] = []
    price_list: list[float] = []
    kind_list: list[str] = []

    if n >= win:
        hs = pd.Series(high)
        ls = pd.Series(low)
        roll_max = hs.rolling(win, center=True).max().to_numpy()
        roll_min = ls.rolling(win, center=True).min().to_numpy()
        for i in range(k, n - k):
            if high[i] == roll_max[i]:
                pos_list.append(i)
                price_list.append(float(high[i]))
                kind_list.append("H")
            if low[i] == roll_min[i]:
                pos_list.append(i)
                price_list.append(float(low[i]))
                kind_list.append("L")

    pos = np.array(pos_list, dtype=np.int64)
    order = np.argsort(pos, kind="stable")
    pos = pos[order]
    return Swings(
        pos=pos,
        price=np.array(price_list, dtype=np.float64)[order],
        kind=np.array(kind_list, dtype="U1")[order],
        time=times[pos] if len(pos) else np.array([], dtype=np.int64),
        confirmed_pos=pos + k,
    )


def cluster_levels(
    swings: Swings,
    last_close: float,
    atr: float,
    max_swings: int = 40,
    tol_atr: float = 0.5,
) -> list[Level]:
    """Merge the most recent swings into price zones. A level is a support if
    it sits below the current close, resistance if above."""
    if len(swings) == 0 or not np.isfinite(atr) or atr <= 0:
        return []
    take = min(len(swings), max_swings)
    prices = swings.price[-take:]
    times = swings.time[-take:]

    order = np.argsort(prices)
    prices, times = prices[order], times[order]
    tol = tol_atr * atr

    levels: list[Level] = []
    cluster_p: list[float] = [float(prices[0])]
    cluster_t: list[int] = [int(times[0])]
    for p, t in zip(prices[1:], times[1:]):
        if p - np.mean(cluster_p) <= tol:
            cluster_p.append(float(p))
            cluster_t.append(int(t))
        else:
            levels.append(_make_level(cluster_p, cluster_t, last_close))
            cluster_p, cluster_t = [float(p)], [int(t)]
    levels.append(_make_level(cluster_p, cluster_t, last_close))
    levels.sort(key=lambda lv: (-lv.strength, -lv.last_touch))
    return levels


def _make_level(prices: list[float], times: list[int], last_close: float) -> Level:
    price = float(np.mean(prices))
    return Level(
        price=price,
        kind="support" if price <= last_close else "resistance",
        strength=len(prices),
        last_touch=max(times),
    )


def nearest_level(levels: list[Level], price: float, kind: str, below: bool) -> Level | None:
    """Closest level of `kind` strictly below (or above) `price`."""
    candidates = [
        lv for lv in levels
        if lv.kind == kind and ((lv.price <= price) if below else (lv.price >= price))
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda lv: abs(lv.price - price))


def nearest_swing_price(swings: Swings, price: float, kind: str, below: bool) -> float | None:
    """Closest raw swing price of kind 'H'/'L' below or above `price`."""
    m = swings.kind == kind
    vals = swings.price[m]
    vals = vals[vals <= price] if below else vals[vals >= price]
    if len(vals) == 0:
        return None
    return float(vals[np.argmin(np.abs(vals - price))])


def floor_pivots(prev_high: float, prev_low: float, prev_close: float) -> dict[str, float]:
    p = (prev_high + prev_low + prev_close) / 3.0
    return {
        "P": p,
        "R1": 2 * p - prev_low,
        "S1": 2 * p - prev_high,
        "R2": p + (prev_high - prev_low),
        "S2": p - (prev_high - prev_low),
        "R3": prev_high + 2 * (p - prev_low),
        "S3": prev_low - 2 * (prev_high - p),
    }
