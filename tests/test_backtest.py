import pytest

from helpers import make_frames
from tradeadvisor.backtest.metrics import max_drawdown_pct
from tradeadvisor.backtest.runner import (
    BacktestConfig,
    _Position,
    apply_bar_to_position,
    run_backtest,
)
from tradeadvisor.models import Target

CFG = BacktestConfig(slippage_pct=0.0, fee_pct=0.0)


def _long_position(stop=95.0):
    targets = [
        Target(price=105.0, r_multiple=1.0, close_pct=50),
        Target(price=110.0, r_multiple=2.0, close_pct=30),
        Target(price=115.0, r_multiple=3.0, close_pct=20),
    ]
    return _Position(
        direction="long", entry_price=100.0, quantity_total=1.0,
        quantity_remaining=1.0, stop=stop, targets=targets,
        hit=[False] * 3, risk_amount=5.0, signal_time=0, entry_time=1, fees=0.0,
    )


def test_pessimistic_rule_stop_beats_tp_in_same_bar():
    pos = _long_position()
    closed, reason = apply_bar_to_position(pos, o=100.0, h=116.0, low=94.0, cfg=CFG)
    assert closed and reason == "stop"
    assert pos.exit_fills == [(95.0, 1.0)]


def test_gap_through_stop_fills_at_open():
    pos = _long_position()
    closed, reason = apply_bar_to_position(pos, o=92.0, h=93.0, low=91.0, cfg=CFG)
    assert closed and reason == "stop"
    assert pos.exit_fills[0][0] == 92.0  # worse than the stop, as a gap would be


def test_tp1_scales_out_and_moves_stop_to_breakeven():
    pos = _long_position()
    closed, _ = apply_bar_to_position(pos, o=100.0, h=106.0, low=99.0, cfg=CFG)
    assert not closed
    assert pos.hit == [True, False, False]
    assert pos.quantity_remaining == pytest.approx(0.5)
    assert pos.stop == pytest.approx(100.0)  # breakeven
    closed, reason = apply_bar_to_position(pos, o=105.0, h=105.5, low=99.5, cfg=CFG)
    assert closed and reason == "breakeven"


def test_all_targets_close_the_trade():
    pos = _long_position()
    closed, reason = apply_bar_to_position(pos, o=104.0, h=120.0, low=103.0, cfg=CFG)
    assert closed and reason == "targets"
    assert pos.quantity_remaining == pytest.approx(0.0)


def test_max_drawdown():
    assert max_drawdown_pct([100, 120, 60, 90]) == pytest.approx(50.0)
    assert max_drawdown_pct([100, 110, 120]) == 0.0


def test_backtest_uptrend_produces_valid_long_trades():
    frames = make_frames(seed=7, trend=0.12, n_entry=900)
    report = run_backtest("TESTUSDT", "1h", frames, BacktestConfig(warmup_bars=250))
    assert report.bars > 0
    for t in report.trades:
        assert t.entry_time > t.signal_time, "fill must happen after the signal bar"
        assert t.exit_time >= t.entry_time
        assert t.direction == "long", "an uptrend should never trigger shorts"
    assert report.exposure_pct <= 100.0


def test_backtest_random_walk_expectancy_near_zero():
    frames = make_frames(seed=33, trend=0.0, n_entry=900)
    report = run_backtest("TESTUSDT", "1h", frames, BacktestConfig(warmup_bars=250))
    for t in report.trades:
        assert t.entry_time > t.signal_time
    if report.expectancy_r is not None:
        assert abs(report.expectancy_r) < 1.5
    # a coin-flip market must not produce a runaway equity curve
    assert 0.5 < report.final_equity / report.initial_equity < 1.5
