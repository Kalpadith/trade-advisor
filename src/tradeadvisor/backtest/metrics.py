"""Backtest performance metrics."""

from tradeadvisor.models import EquityPoint, TradeRecord


def max_drawdown_pct(equity: list[float]) -> float:
    peak = float("-inf")
    dd = 0.0
    for e in equity:
        peak = max(peak, e)
        if peak > 0:
            dd = max(dd, (peak - e) / peak)
    return dd * 100.0


def summarize(trades: list[TradeRecord], curve: list[EquityPoint]) -> dict:
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in losses)
    return {
        "trade_count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades) * 100.0) if trades else None,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "expectancy_r": (sum(t.pnl_r for t in trades) / len(trades)) if trades else None,
        "avg_win": (gross_win / len(wins)) if wins else None,
        "avg_loss": (-gross_loss / len(losses)) if losses else None,
        "max_drawdown_pct": max_drawdown_pct([p.equity for p in curve]),
    }
