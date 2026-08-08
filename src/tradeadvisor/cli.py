"""Command-line interface: tadvisor fetch / analyze / backtest / serve."""

from datetime import datetime, timezone

import typer

from tradeadvisor.config import get_settings
from tradeadvisor.models import BacktestReport, Recommendation
from tradeadvisor.runtime import analyze_symbol, build_service, load_backtest_frames
from tradeadvisor.signals.engine import SignalEngine
from tradeadvisor.timeframes import ENTRY_TIMEFRAMES

app = typer.Typer(help="Rule-based crypto trade advisory tool (decision support, not financial advice).")


def _parse_date(value: str) -> int:
    dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


@app.command()
def fetch(
    symbol: str = typer.Argument(..., help="e.g. BTCUSDT"),
    timeframes: list[str] = typer.Option(["15m", "1h", "4h", "1d"], "--tf"),
    bars: int = typer.Option(1500, help="bars per timeframe to backfill"),
    market: str = typer.Option("spot", help="spot or futures"),
):
    """Backfill the local candle cache for a symbol."""
    service = build_service()
    for tf in timeframes:
        df = service.get(symbol, tf, lookback_bars=bars, market=market)
        typer.echo(f"{symbol.upper()} {tf}: {len(df)} candles cached "
                   f"({_fmt_ts(int(df['open_time'].iloc[0]))} .. {_fmt_ts(int(df['close_time'].iloc[-1]))})"
                   if len(df) else f"{symbol.upper()} {tf}: no data")


def _print_recommendation(rec: Recommendation, raw: bool = False):
    typer.echo("")
    typer.echo(f"=== {rec.symbol}  [{rec.entry_timeframe} {rec.market.upper()}]  "
               f"as of {rec.data_as_of:%Y-%m-%d %H:%M UTC} ===")
    badge = {"long": "LONG", "short": "SHORT", "no_trade": "NO TRADE"}[rec.direction]
    typer.echo(f"Direction : {badge}   (score {rec.score_total:+.1f}, confidence {rec.confidence}/100)")
    typer.echo(f"Holding   : {rec.holding_period}")
    if rec.entry_zone:
        typer.echo(f"Entry zone: {rec.entry_zone[0]:.6g} .. {rec.entry_zone[1]:.6g}")
    if rec.stop_loss is not None:
        typer.echo(f"Stop loss : {rec.stop_loss:.6g}")
    if rec.take_profits:
        for i, t in enumerate(rec.take_profits, 1):
            typer.echo(f"TP{i}       : {t.price:.6g}  ({t.r_multiple:.1f}R, close {t.close_pct:.0f}%)")
    if rec.position:
        p = rec.position
        extra = ""
        if p.leverage is not None and p.leverage > 1:
            extra = f", needs ~{p.leverage:.1f}x leverage"
        elif p.size_capped:
            extra = ", size capped (spot, no leverage)"
        typer.echo(f"Position  : {p.quantity:.6g} units (~{p.notional:,.2f} notional), "
                   f"risking {p.risk_amount:,.2f} of {p.account_size:,.0f}{extra}")
    typer.echo("")
    typer.echo("Reasoning:")
    for r in rec.rules:
        typer.echo(f"  [{r.timeframe:>3}] {r.name:<22} {r.contribution:+6.1f}  {r.detail}")
    if raw and rec.levels:
        typer.echo("")
        typer.echo("Levels:")
        for lv in rec.levels[:10]:
            typer.echo(f"  {lv.kind:<10} {lv.price:.6g}  (strength {lv.strength})")
    if raw and rec.fibonacci:
        fib = rec.fibonacci
        typer.echo("")
        typer.echo(f"Fibonacci ({'up' if fib.leg_up else 'down'}-leg "
                   f"{fib.leg_low:.6g} .. {fib.leg_high:.6g}):")
        for f in fib.levels:
            typer.echo(f"  {f.kind:<12} {f.ratio:>5.3f}  {f.price:.6g}")
    if rec.warnings:
        typer.echo("")
        for w in rec.warnings:
            typer.echo(f"  ! {w}")


@app.command()
def analyze(
    symbol: str = typer.Argument(..., help="e.g. BTCUSDT"),
    tf: str = typer.Option("1h", help=f"entry timeframe: {', '.join(ENTRY_TIMEFRAMES)}"),
    market: str = typer.Option("spot", help="spot or futures"),
    account: float = typer.Option(None, help="account size in quote currency"),
    risk: float = typer.Option(None, help="risk per trade in % of account"),
    raw: bool = typer.Option(False, help="also print detected S/R and fibonacci levels"),
):
    """Analyze a symbol and print a trade recommendation."""
    settings = get_settings()
    if tf not in ENTRY_TIMEFRAMES:
        raise typer.BadParameter(f"tf must be one of {ENTRY_TIMEFRAMES}")
    if market not in ("spot", "futures"):
        raise typer.BadParameter("market must be 'spot' or 'futures'")
    service = build_service(settings)
    rec = analyze_symbol(
        service, SignalEngine(), symbol, tf,
        account_size=account or settings.default_account_size,
        risk_pct=risk or settings.default_risk_pct,
        market=market,
    )
    _print_recommendation(rec, raw=raw)


def _print_report(rep: BacktestReport):
    typer.echo("")
    typer.echo(f"=== Backtest {rep.symbol} [{rep.entry_timeframe} {rep.market.upper()}] "
               f"{_fmt_ts(rep.start)} .. {_fmt_ts(rep.end)} ({rep.bars} bars) ===")
    typer.echo(f"Trades       : {rep.trade_count}  ({rep.wins} wins / {rep.losses} losses)")
    if rep.win_rate is not None:
        typer.echo(f"Win rate     : {rep.win_rate:.1f}%")
    if rep.profit_factor is not None:
        typer.echo(f"Profit factor: {rep.profit_factor:.2f}")
    if rep.expectancy_r is not None:
        typer.echo(f"Expectancy   : {rep.expectancy_r:+.2f}R per trade")
    typer.echo(f"Max drawdown : {rep.max_drawdown_pct:.1f}%")
    typer.echo(f"Equity       : {rep.initial_equity:,.2f} -> {rep.final_equity:,.2f}")
    typer.echo(f"Exposure     : {rep.exposure_pct:.1f}% of bars in a position")
    for w in rep.warnings:
        typer.echo(f"  ! {w}")


@app.command()
def backtest(
    symbol: str = typer.Argument(..., help="e.g. BTCUSDT"),
    tf: str = typer.Option("1h", help=f"entry timeframe: {', '.join(ENTRY_TIMEFRAMES)}"),
    market: str = typer.Option("spot", help="spot (long-only) or futures (long+short)"),
    start: str = typer.Option("2024-01-01", help="YYYY-MM-DD (UTC)"),
    end: str = typer.Option(None, help="YYYY-MM-DD (UTC), default now"),
    account: float = typer.Option(None),
    risk: float = typer.Option(None),
):
    """Replay history through the signal engine and print performance stats."""
    from tradeadvisor.backtest.runner import BacktestConfig, run_backtest

    settings = get_settings()
    if tf not in ENTRY_TIMEFRAMES:
        raise typer.BadParameter(f"tf must be one of {ENTRY_TIMEFRAMES}")
    if market not in ("spot", "futures"):
        raise typer.BadParameter("market must be 'spot' or 'futures'")
    start_ms = _parse_date(start)
    end_ms = _parse_date(end) if end else None
    service = build_service(settings)
    typer.echo("Syncing candles...")
    frames = load_backtest_frames(service, symbol, tf, start_ms, end_ms, market=market)
    typer.echo(f"Running backtest over {len(frames['entry'])} {tf} bars (incl. warmup)...")
    cfg = BacktestConfig(
        account_size=account or settings.default_account_size,
        risk_pct=risk or settings.default_risk_pct,
        fee_pct=settings.fee_pct,
        slippage_pct=settings.slippage_pct,
        market=market,
    )
    rep = run_backtest(symbol, tf, frames, cfg, start_ms=start_ms, end_ms=end_ms)
    _print_report(rep)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
):
    """Start the API + web dashboard."""
    import uvicorn

    from tradeadvisor.api.app import create_app

    typer.echo(f"Dashboard: http://{host}:{port}")
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    app()
