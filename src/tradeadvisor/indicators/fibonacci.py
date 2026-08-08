"""Fibonacci retracement/extension levels off the most recent significant
swing leg. Built only from confirmed swings, so it inherits their
lookahead-safety: a leg endpoint is invisible until k bars confirm it."""

from dataclasses import dataclass

from tradeadvisor.indicators.levels import Swings

RETRACEMENT_RATIOS = [0.236, 0.382, 0.5, 0.618, 0.786]
EXTENSION_RATIOS = [1.272, 1.618]
GOLDEN_POCKET = (0.5, 0.618)
LEG_WINDOW_SWINGS = 12  # how many recent swings define the "current" leg


@dataclass
class FibLevels:
    up: bool               # True if the leg runs low -> high (an up-leg)
    leg_high: float
    leg_low: float
    retracements: dict[float, float]   # ratio -> price
    extensions: dict[float, float]     # ratio -> price (beyond the leg's end)

    def retracement(self, ratio: float) -> float:
        return self.retracements[ratio]


def compute_fib(swings: Swings) -> FibLevels | None:
    """Find the most recent leg: the latest confirmed swing marks its end,
    the opposite extreme among the preceding recent swings marks its start."""
    if len(swings) < 2:
        return None
    take = min(len(swings), LEG_WINDOW_SWINGS)
    kind = swings.kind[-take:]
    price = swings.price[-take:]

    high_mask = kind == "H"
    low_mask = kind == "L"
    if not high_mask.any() or not low_mask.any():
        return None

    last_high_idx = int(high_mask.nonzero()[0][-1])
    last_low_idx = int(low_mask.nonzero()[0][-1])

    if last_high_idx > last_low_idx:
        # up-leg ending at the most recent swing high
        up = True
        leg_high = float(price[last_high_idx])
        lows_before = price[:last_high_idx][low_mask[:last_high_idx]]
        if len(lows_before) == 0:
            return None
        leg_low = float(lows_before.min())
    else:
        # down-leg ending at the most recent swing low
        up = False
        leg_low = float(price[last_low_idx])
        highs_before = price[:last_low_idx][high_mask[:last_low_idx]]
        if len(highs_before) == 0:
            return None
        leg_high = float(highs_before.max())

    span = leg_high - leg_low
    if span <= 0:
        return None

    if up:
        retr = {r: leg_high - r * span for r in RETRACEMENT_RATIOS}
        ext = {e: leg_low + e * span for e in EXTENSION_RATIOS}
    else:
        retr = {r: leg_low + r * span for r in RETRACEMENT_RATIOS}
        ext = {e: leg_high - e * span for e in EXTENSION_RATIOS}

    return FibLevels(up=up, leg_high=leg_high, leg_low=leg_low,
                     retracements=retr, extensions=ext)
