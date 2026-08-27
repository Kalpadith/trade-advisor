"""Event-loop backtester. Replays closed candles through the exact same
SignalEngine used for live analysis.

Execution model (deliberately conservative):
- A signal fires at the close of bar i; the earliest possible fill is bar i+1.
- Entries are limit orders at the entry-zone midpoint, valid for a few bars;
  if price never comes back, the trade is missed (as it would be live).
- If a candle touches both the stop and a take-profit, the stop is assumed to
  have been hit first (pessimistic intrabar rule).
- Every fill pays fees and slippage."""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tradeadvisor.backtest.metrics import summarize
from tradeadvisor.indicators.levels import find_swings
from tradeadvisor.models import BacktestReport, EquityPoint, Target, TradeRecord
from tradeadvisor.signals.engine import SignalEngine
from tradeadvisor.timeframes import TF_CONFIG


@dataclass
class BacktestConfig:
    account_size: float = 10_000.0
    risk_pct: float = 1.0
    fee_pct: float = 0.1        # per side, % of notional
    slippage_pct: float = 0.05  # per side, % of price
    entry_valid_bars: int = 5
    breakeven_after_tp1: bool = True
    warmup_bars: int = 250
    market: str = "spot"        # spot: long-only, size capped at equity


@dataclass
class _Pending:
    direction: str
    limit: float
    stop: float
    targets: list[Target]
    quantity: float
    risk_amount: float
    signal_time: int
    expires_pos: int


@dataclass
class _Position:
    direction: str
    entry_price: float
    quantity_total: float
    quantity_remaining: float
    stop: float
    targets: list[Target]
    hit: list[bool]
    risk_amount: float
    signal_time: int
    entry_time: int
    fees: float
    exit_fills: list[tuple[float, float]] = field(default_factory=list)  # (price, qty)


def _try_fill(p: _Pending, o: float, h: float, low: float) -> float | None:
    if p.direction == "long":
        if o <= p.limit:
            return o
        if low <= p.limit:
            return p.limit
    else:
        if o >= p.limit:
            return o
        if h >= p.limit:
            return p.limit
    return None


def apply_bar_to_position(
    pos: _Position, o: float, h: float, low: float, cfg: BacktestConfig,
    stop_only: bool = False,
) -> tuple[bool, str]:
    """Resolve one bar against an open position. Mutates pos. Returns
    (closed, reason). Pessimistic: the stop is checked before any target."""
    slip = cfg.slippage_pct / 100.0
    fee = cfg.fee_pct / 100.0
    sign = 1 if pos.direction == "long" else -1

    stop_hit = (low <= pos.stop) if sign > 0 else (h >= pos.stop)
    if stop_hit:
        raw = min(pos.stop, o) if sign > 0 else max(pos.stop, o)  # gaps fill worse
        px = raw * (1 - sign * slip)
        qty = pos.quantity_remaining
        pos.exit_fills.append((px, qty))
        pos.fees += px * qty * fee
        pos.quantity_remaining = 0.0
        reason = "breakeven" if abs(pos.stop - pos.entry_price) < 1e-12 else "stop"
        return True, reason

    if stop_only:
        return False, ""

    for i, t in enumerate(pos.targets):
        if pos.hit[i]:
            continue
        reached = (h >= t.price) if sign > 0 else (low <= t.price)
        if not reached:
            continue
        qty = min(pos.quantity_total * t.close_pct / 100.0, pos.quantity_remaining)
        px = t.price * (1 - sign * slip)
        pos.exit_fills.append((px, qty))
        pos.fees += px * qty * fee
        pos.quantity_remaining -= qty
        pos.hit[i] = True
        if i == 0 and cfg.breakeven_after_tp1:
            pos.stop = max(pos.stop, pos.entry_price) if sign > 0 else min(pos.stop, pos.entry_price)
    if pos.quantity_remaining <= 1e-12 or all(pos.hit):
        return True, "targets"
    return False, ""


def _close_position(pos: _Position, exit_time: int) -> TradeRecord:
    sign = 1 if pos.direction == "long" else -1
    exit_notional = sum(px * q for px, q in pos.exit_fills)
    qty = sum(q for _, q in pos.exit_fills)
    avg_exit = exit_notional / qty if qty > 0 else pos.entry_price
    gross = sign * (exit_notional - pos.entry_price * qty)
    pnl = gross - pos.fees
    return TradeRecord(
        direction=pos.direction,  # type: ignore[arg-type]
        signal_time=pos.signal_time,
        entry_time=pos.entry_time,
        entry_price=pos.entry_price,
        exit_time=exit_time,
        avg_exit_price=avg_exit,
        quantity=pos.quantity_total,
        pnl=pnl,
        pnl_r=pnl / pos.risk_amount if pos.risk_amount > 0 else 0.0,
        fees=pos.fees,
        exit_reason="",  # filled by caller
    )


def run_backtest(
    symbol: str,
    entry_tf: str,
    frames: dict[str, pd.DataFrame],  # role-keyed raw OHLCV: entry/context/bias
    config: BacktestConfig | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
    engine: SignalEngine | None = None,
) -> BacktestReport:
    cfg = config or BacktestConfig()
    engine = engine or SignalEngine()

    entry = engine.prepare_entry(frames["entry"])
    context = frames["context"]
    bias = frames["bias"]
    context = entry if context is frames["entry"] else engine.prepare_higher(context)
    bias = context if frames["bias"] is frames["context"] else (
        entry if frames["bias"] is frames["entry"] else engine.prepare_higher(bias)
    )

    if end_ms is not None:
        entry = entry[entry["close_time"] <= end_ms]
    n = len(entry)
    warnings: list[str] = []

    full_swings = find_swings(entry)
    opens = entry["open"].to_numpy()
    highs = entry["high"].to_numpy()
    lows = entry["low"].to_numpy()
    close_times = entry["close_time"].to_numpy()
    ctx_close_times = context["close_time"].to_numpy()
    bias_close_times = bias["close_time"].to_numpy()

    start_idx = cfg.warmup_bars
    if start_ms is not None:
        start_idx = max(start_idx, int(np.searchsorted(close_times, start_ms, side="left")))
    if start_idx >= n:
        warnings.append("not enough history after warmup - no bars were tested")
        start_idx = n

    equity = cfg.account_size
    trades: list[TradeRecord] = []
    curve: list[EquityPoint] = []
    if start_idx < n:
        curve.append(EquityPoint(time=int(close_times[start_idx]), equity=equity))
    pending: _Pending | None = None
    position: _Position | None = None
    bars_in_position = 0
    slip = cfg.slippage_pct / 100.0
    fee = cfg.fee_pct / 100.0

    for i in range(start_idx, n):
        o, h, low, ct = float(opens[i]), float(highs[i]), float(lows[i]), int(close_times[i])

        if position is not None:
            bars_in_position += 1
            closed, reason = apply_bar_to_position(position, o, h, low, cfg)
            if closed:
                trade = _close_position(position, ct)
                trade.exit_reason = reason
                trades.append(trade)
                equity += trade.pnl
                curve.append(EquityPoint(time=ct, equity=equity))
                position = None
        elif pending is not None:
            if i > pending.expires_pos:
                pending = None
            else:
                fill = _try_fill(pending, o, h, low)
                if fill is not None:
                    sign = 1 if pending.direction == "long" else -1
                    entry_px = fill * (1 + sign * slip)
                    position = _Position(
                        direction=pending.direction,
                        entry_price=entry_px,
                        quantity_total=pending.quantity,
                        quantity_remaining=pending.quantity,
                        stop=pending.stop,
                        targets=pending.targets,
                        hit=[False] * len(pending.targets),
                        risk_amount=pending.risk_amount,
                        signal_time=pending.signal_time,
                        entry_time=ct,
                        fees=entry_px * pending.quantity * fee,
                    )
                    pending = None
                    bars_in_position += 1
                    # pessimistic: the stop can be hit on the entry bar itself
                    closed, reason = apply_bar_to_position(position, o, h, low, cfg, stop_only=True)
                    if closed:
                        trade = _close_position(position, ct)
                        trade.exit_reason = reason
                        trades.append(trade)
                        equity += trade.pnl
                        curve.append(EquityPoint(time=ct, equity=equity))
                        position = None

        if position is None and pending is None and i < n - 1:
            ctx_idx = int(np.searchsorted(ctx_close_times, ct, side="right"))
            bias_idx = int(np.searchsorted(bias_close_times, ct, side="right"))
            if ctx_idx == 0 or bias_idx == 0:
                continue
            rec = engine.analyze(
                symbol,
                entry_tf,
                entry.iloc[: i + 1],
                context.iloc[:ctx_idx],
                bias.iloc[:bias_idx],
                account_size=equity,
                risk_pct=cfg.risk_pct,
                market=cfg.market,
                prepared=True,
                swings=full_swings.visible(i),
            )
            # in spot mode the engine returns shorts with no plan (stop_loss
            # is None), so this condition also enforces long-only on spot
            if rec.direction in ("long", "short") and rec.stop_loss is not None and rec.entry_zone:
                limit = (rec.entry_zone[0] + rec.entry_zone[1]) / 2
                dist = abs(limit - rec.stop_loss)
                if dist <= 0:
                    continue
                quantity = equity * cfg.risk_pct / 100.0 / dist
                if cfg.market == "spot":
                    quantity = min(quantity, equity / limit)  # no leverage on spot
                risk_amount = quantity * dist
                pending = _Pending(
                    direction=rec.direction,
                    limit=limit,
                    stop=rec.stop_loss,
                    targets=list(rec.take_profits or []),
                    quantity=quantity,
                    risk_amount=risk_amount,
                    signal_time=ct,
                    expires_pos=i + cfg.entry_valid_bars,
                )

    if position is not None and n > 0:
        # mark remaining inventory out at the final close
        last_close = float(entry["close"].iloc[-1])
        sign = 1 if position.direction == "long" else -1
        px = last_close * (1 - sign * slip)
        qty = position.quantity_remaining
        position.exit_fills.append((px, qty))
        position.fees += px * qty * fee
        position.quantity_remaining = 0.0
        trade = _close_position(position, int(close_times[-1]))
        trade.exit_reason = "end_of_data"
        trades.append(trade)
        equity += trade.pnl
        curve.append(EquityPoint(time=int(close_times[-1]), equity=equity))
        warnings.append("last position was still open at end of data and was marked out at the final close")

    stats = summarize(trades, curve)
    tested_bars = max(0, n - start_idx)
    return BacktestReport(
        symbol=symbol.upper(),
        entry_timeframe=entry_tf,
        market=cfg.market,  # type: ignore[arg-type]
        start=int(close_times[start_idx]) if start_idx < n else 0,
        end=int(close_times[-1]) if n else 0,
        bars=tested_bars,
        initial_equity=cfg.account_size,
        final_equity=equity,
        exposure_pct=(bars_in_position / tested_bars * 100.0) if tested_bars else 0.0,
        equity_curve=curve,
        trades=trades,
        warnings=warnings,
        **stats,
    )
