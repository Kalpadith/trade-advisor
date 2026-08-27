"""Parameter sweep for 15m futures trading.

Train window and validation window are strictly separated: pick the config on
TRAIN numbers only, then judge it once on VALID. Re-running this with configs
chosen from validation results is overfitting - don't.

Usage:
    python scripts/sweep_15m.py train    # sweep all configs on the train window
    python scripts/sweep_15m.py valid CONFIG [CONFIG...]   # validate chosen configs
"""

import sys
from datetime import datetime, timezone

from tradeadvisor.backtest.runner import BacktestConfig, run_backtest
from tradeadvisor.runtime import build_service, load_backtest_frames
from tradeadvisor.signals.engine import EngineParams, SignalEngine


def ms(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


TRAIN = (ms("2026-01-01"), ms("2026-05-01"))
VALID = (ms("2026-05-01"), None)
TRAIN_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
VALID_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]  # SOL never seen in training

# Binance USDT-M futures taker fee tier 0 is 0.045%; BTC/ETH books are deep,
# so slippage on small size is tight. The spot-taker default (0.1%/0.05%)
# would be the wrong cost model for 15m futures scalping.
FUTURES_COSTS = dict(fee_pct=0.045, slippage_pct=0.02)

CONFIGS: dict[str, tuple[EngineParams, dict]] = {
    "baseline":          (EngineParams(), {}),
    "T45":               (EngineParams(entry_threshold=45), {}),
    "T45_adx25":         (EngineParams(entry_threshold=45, adx_min=25), {}),
    "T45_stop2":         (EngineParams(entry_threshold=45, stop_atr_min=2.0), {}),
    "T45_adx25_stop2":   (EngineParams(entry_threshold=45, adx_min=25, stop_atr_min=2.0), {}),
    "T45_adx25_stop2_nobe": (
        EngineParams(entry_threshold=45, adx_min=25, stop_atr_min=2.0),
        {"breakeven_after_tp1": False},
    ),
    "T55_adx25_stop2":   (EngineParams(entry_threshold=55, adx_min=25, stop_atr_min=2.0), {}),
    "T65_adx25_stop2":   (EngineParams(entry_threshold=65, adx_min=25, stop_atr_min=2.0), {}),
    "T55_adx25_stop25":  (EngineParams(entry_threshold=55, adx_min=25, stop_atr_min=2.5, stop_atr_max=4.0), {}),
    "T65_adx25_stop25":  (EngineParams(entry_threshold=65, adx_min=25, stop_atr_min=2.5, stop_atr_max=4.0), {}),
}


def run(symbols: list[str], window, names: list[str]):
    service = build_service()
    frames_by_symbol = {}
    for sym in symbols:
        print(f"syncing {sym} 15m/1h/4h ...", flush=True)
        frames_by_symbol[sym] = load_backtest_frames(
            service, sym, "15m", TRAIN[0], None, market="futures"
        )

    header = f"{'config':22} {'symbol':9} {'trades':>6} {'win%':>6} {'PF':>6} {'expR':>7} {'dd%':>6} {'equity':>8}"
    print("\n" + header)
    print("-" * len(header))
    for name in names:
        params, bt_overrides = CONFIGS[name]
        totals = {"trades": 0, "wins": 0, "r": 0.0}
        for sym in symbols:
            cfg = BacktestConfig(market="futures", **FUTURES_COSTS, **bt_overrides)
            rep = run_backtest(
                sym, "15m", frames_by_symbol[sym], cfg,
                start_ms=window[0], end_ms=window[1],
                engine=SignalEngine(params),
            )
            pf = f"{rep.profit_factor:.2f}" if rep.profit_factor is not None else "-"
            wr = f"{rep.win_rate:.1f}" if rep.win_rate is not None else "-"
            er = f"{rep.expectancy_r:+.2f}" if rep.expectancy_r is not None else "-"
            print(f"{name:22} {sym:9} {rep.trade_count:>6} {wr:>6} {pf:>6} {er:>7} "
                  f"{rep.max_drawdown_pct:>6.1f} {rep.final_equity:>8,.0f}", flush=True)
            totals["trades"] += rep.trade_count
            totals["wins"] += rep.wins
            totals["r"] += sum(t.pnl_r for t in rep.trades)
        if totals["trades"]:
            print(f"{name:22} {'TOTAL':9} {totals['trades']:>6} "
                  f"{totals['wins'] / totals['trades'] * 100:>6.1f} {'':>6} "
                  f"{totals['r'] / totals['trades']:>+7.2f}", flush=True)
        print("-" * len(header), flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "train"
    if mode == "train":
        names = sys.argv[2:] or list(CONFIGS)
        run(TRAIN_SYMBOLS, TRAIN, names)
    elif mode == "valid":
        names = sys.argv[2:] or ["baseline"]
        run(VALID_SYMBOLS, VALID, names)
    else:
        sys.exit("usage: sweep_15m.py train | valid CONFIG...")
