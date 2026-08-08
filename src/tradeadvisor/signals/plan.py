"""Turn a directional signal into a concrete trade plan: entry zone, ATR-based
stop, R-multiple take-profits and fixed-risk position sizing."""

from dataclasses import dataclass, field

import pandas as pd

from tradeadvisor.indicators.fibonacci import GOLDEN_POCKET, FibLevels
from tradeadvisor.indicators.levels import Swings, nearest_level, nearest_swing_price
from tradeadvisor.models import Level, PositionSuggestion, Target

STOP_ATR_MIN = 1.5
STOP_ATR_MAX = 3.0
ZONE_ATR_MAX = 0.5
SWING_BUFFER_ATR = 0.1


@dataclass
class TradePlan:
    entry_zone: tuple[float, float]
    stop_loss: float
    targets: list[Target]
    position: PositionSuggestion
    warnings: list[str] = field(default_factory=list)


def build_trade_plan(
    entry_df: pd.DataFrame,
    levels: list[Level],
    swings: Swings,
    direction: str,
    account_size: float,
    risk_pct: float,
    fib: FibLevels | None = None,
    market: str = "spot",
) -> tuple[TradePlan | None, list[str]]:
    """Returns (plan, warnings). plan is None when no sane plan exists, with
    the reason in warnings."""
    row = entry_df.iloc[-1]
    close = float(row["close"])
    atr = float(row["atr14"]) if pd.notna(row["atr14"]) else float("nan")
    if not (atr > 0):
        return None, ["cannot build a trade plan: ATR unavailable (insufficient history)"]

    sign = 1 if direction == "long" else -1

    # --- entry zone: from current close back to the nearer of the EMA20
    # pullback and the nearest level, capped at 0.5 ATR wide.
    candidates: list[float] = []
    ema20 = row["ema20"]
    if pd.notna(ema20) and sign * (close - float(ema20)) > 0:
        candidates.append(float(ema20))
    level_kind = "support" if sign > 0 else "resistance"
    lv = nearest_level(levels, close, level_kind, below=(sign > 0))
    if lv is not None:
        candidates.append(lv.price)
    # golden-pocket retracement is a valid pullback magnet when the measured
    # leg points the way we want to trade
    if fib is not None and ((fib.up and sign > 0) or (not fib.up and sign < 0)):
        gp = fib.retracement(GOLDEN_POCKET[0])  # 50% edge of the pocket
        if sign * (close - gp) > 0:
            candidates.append(gp)

    if candidates:
        target_edge = max(candidates) if sign > 0 else min(candidates)
    else:
        target_edge = close - sign * 0.25 * atr
    far_edge = close - sign * min(abs(close - target_edge), ZONE_ATR_MAX * atr)
    zone = (min(far_edge, close), max(far_edge, close))
    mid = (zone[0] + zone[1]) / 2

    # --- stop: at least 1.5 ATR from zone mid, pushed beyond the nearest
    # confirmed swing if one is close; if that requires > 3 ATR, walk away.
    dist = STOP_ATR_MIN * atr
    swing_kind = "L" if sign > 0 else "H"
    ref_price = zone[0] if sign > 0 else zone[1]
    swing = nearest_swing_price(swings, ref_price, swing_kind, below=(sign > 0))
    if swing is not None:
        beyond = sign * (mid - swing) + SWING_BUFFER_ATR * atr
        dist = max(dist, beyond)
    if dist > STOP_ATR_MAX * atr:
        return None, [
            f"no sane stop placement: protecting the nearest swing needs a stop "
            f"{dist / atr:.1f}x ATR away (max {STOP_ATR_MAX:.1f}x) - skip this trade"
        ]
    stop = mid - sign * dist

    # --- take profits: 1R / 2R, and 3R unless a strong level or a fibonacci
    # extension sits closer beyond TP2.
    r = dist
    tp1 = mid + sign * r
    tp2 = mid + sign * 2 * r
    tp3 = mid + sign * 3 * r
    tp3_candidates: list[float] = []
    opposing_kind = "resistance" if sign > 0 else "support"
    beyond_lv = nearest_level(levels, tp2, opposing_kind, below=(sign < 0))
    if beyond_lv is not None:
        tp3_candidates.append(beyond_lv.price)
    if fib is not None and ((fib.up and sign > 0) or (not fib.up and sign < 0)):
        tp3_candidates.extend(fib.extensions.values())
    for cand in tp3_candidates:
        if sign * (cand - tp2) > 0 and sign * (tp3 - cand) > 0:
            tp3 = cand
    targets = [
        Target(price=tp1, r_multiple=1.0, close_pct=50),
        Target(price=tp2, r_multiple=2.0, close_pct=30),
        Target(price=tp3, r_multiple=abs(tp3 - mid) / r, close_pct=20),
    ]

    # --- fixed-risk sizing, market-aware
    risk_amount = account_size * risk_pct / 100.0
    quantity = risk_amount / dist
    notional = quantity * mid
    warnings: list[str] = []
    leverage: float | None = None
    size_capped = False
    if market == "futures":
        leverage = max(1.0, notional / account_size)
        if leverage > 1.0:
            warnings.append(
                f"futures: full risk-based size needs ~{leverage:.1f}x leverage "
                f"({notional:,.2f} notional on a {account_size:,.0f} account) - "
                "higher leverage brings the liquidation price closer to entry"
            )
    else:  # spot: no leverage exists, cap the size at the account
        if notional > account_size:
            size_capped = True
            quantity = account_size / mid
            notional = quantity * mid
            risk_amount = quantity * dist
            warnings.append(
                f"spot has no leverage: size capped at the full account; risk at the "
                f"stop falls to {risk_amount:,.2f} ({risk_amount / account_size * 100:.2f}% "
                "of account) instead of the requested risk"
            )

    position = PositionSuggestion(
        quantity=quantity,
        notional=notional,
        risk_amount=risk_amount,
        account_size=account_size,
        risk_pct=risk_pct,
        leverage=leverage,
        size_capped=size_capped,
    )
    return TradePlan(entry_zone=zone, stop_loss=stop, targets=targets,
                     position=position, warnings=warnings), warnings
