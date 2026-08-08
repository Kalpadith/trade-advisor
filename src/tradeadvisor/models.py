"""Pydantic domain models shared by the engine, backtester, CLI and API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Direction = Literal["long", "short", "no_trade"]
MarketType = Literal["spot", "futures"]


class Candle(BaseModel):
    open_time: int  # ms epoch UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int  # ms epoch UTC


class Level(BaseModel):
    price: float
    kind: Literal["support", "resistance"]
    strength: int          # number of swing touches in the cluster
    last_touch: int        # ms epoch of most recent touch


class RuleResult(BaseModel):
    name: str
    timeframe: str
    score: float           # -1.0 .. +1.0 (positive = bullish)
    weight: float
    contribution: float    # score * weight
    detail: str


class Target(BaseModel):
    price: float
    r_multiple: float
    close_pct: float       # % of position to close at this target


class PositionSuggestion(BaseModel):
    quantity: float
    notional: float
    risk_amount: float
    account_size: float
    risk_pct: float
    # futures: leverage needed to hold the full risk-based size (1.0 = none).
    # spot: always None; size is capped at the account instead (size_capped).
    leverage: float | None = None
    size_capped: bool = False


class FibLevel(BaseModel):
    ratio: float
    price: float
    kind: Literal["retracement", "extension"]


class FibonacciInfo(BaseModel):
    leg_up: bool           # True when the measured leg runs low -> high
    leg_high: float
    leg_low: float
    levels: list[FibLevel]


class Recommendation(BaseModel):
    symbol: str
    generated_at: datetime
    data_as_of: datetime   # close time of the last closed candle analyzed
    direction: Direction
    confidence: int        # 0-100
    market: MarketType = "spot"
    entry_timeframe: str
    holding_period: str
    entry_zone: tuple[float, float] | None = None
    stop_loss: float | None = None
    take_profits: list[Target] | None = None
    position: PositionSuggestion | None = None
    score_total: float
    rules: list[RuleResult]
    levels: list[Level] = []
    fibonacci: FibonacciInfo | None = None
    warnings: list[str] = []


class TradeRecord(BaseModel):
    direction: Literal["long", "short"]
    signal_time: int
    entry_time: int
    entry_price: float
    exit_time: int
    avg_exit_price: float
    quantity: float
    pnl: float             # net of fees/slippage, in quote currency
    pnl_r: float           # pnl / planned risk amount
    fees: float
    exit_reason: str       # "stop", "targets", "breakeven", "end_of_data"


class EquityPoint(BaseModel):
    time: int
    equity: float


class BacktestReport(BaseModel):
    symbol: str
    entry_timeframe: str
    market: MarketType = "spot"
    start: int
    end: int
    bars: int
    trade_count: int
    wins: int
    losses: int
    win_rate: float | None = None
    profit_factor: float | None = None
    expectancy_r: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None
    max_drawdown_pct: float
    initial_equity: float
    final_equity: float
    exposure_pct: float
    equity_curve: list[EquityPoint]
    trades: list[TradeRecord]
    warnings: list[str] = []
