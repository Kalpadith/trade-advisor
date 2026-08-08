"""Spot vs futures behaviour: shorting rules, sizing, backtest direction."""

import pytest

from helpers import make_frames
from tradeadvisor.backtest.runner import BacktestConfig, run_backtest
from tradeadvisor.signals.engine import SignalEngine


def _find_directional(direction: str, trend: float, market: str, risk_pct: float = 1.0):
    engine = SignalEngine()
    for seed in range(40):
        frames = make_frames(seed=seed, trend=trend)
        rec = engine.analyze(
            "TESTUSDT", "1h", frames["entry"], frames["context"], frames["bias"],
            market=market, risk_pct=risk_pct,
        )
        if rec.direction == direction:
            return rec, frames
    return None, None


def test_spot_short_signal_has_no_plan():
    rec, _ = _find_directional("short", trend=-0.15, market="spot")
    assert rec is not None, "no seed produced a short signal"
    assert rec.market == "spot"
    assert rec.entry_zone is None and rec.stop_loss is None and rec.position is None
    assert any("spot cannot short" in w for w in rec.warnings)


def test_futures_short_signal_has_full_plan():
    rec, _ = _find_directional("short", trend=-0.15, market="futures")
    assert rec is not None, "no seed produced a short signal"
    assert rec.market == "futures"
    lo, hi = rec.entry_zone
    mid = (lo + hi) / 2
    assert rec.stop_loss > hi, "stop must sit above the entry zone for a short"
    tps = [t.price for t in rec.take_profits]
    assert all(tp < mid for tp in tps)
    assert tps == sorted(tps, reverse=True)
    assert rec.position.leverage is not None and rec.position.leverage >= 1.0


def test_futures_reports_leverage_and_spot_caps_size():
    fut, frames = _find_directional("long", trend=0.15, market="futures", risk_pct=5.0)
    assert fut is not None, "no seed produced a long signal"
    engine = SignalEngine()
    spot = engine.analyze(
        "TESTUSDT", "1h", frames["entry"], frames["context"], frames["bias"],
        market="spot", risk_pct=5.0,
    )
    assert spot.direction == "long", "market must not change the signal itself"
    assert spot.score_total == fut.score_total

    if fut.position.leverage > 1.0:
        assert spot.position.size_capped
        assert spot.position.notional <= spot.position.account_size * 1.0001
        assert spot.position.risk_amount < fut.position.risk_amount
    else:
        assert not spot.position.size_capped
        assert spot.position.quantity == pytest.approx(fut.position.quantity)


def test_backtest_spot_is_long_only_futures_can_short():
    frames = make_frames(seed=15, trend=-0.12, n_entry=900)
    spot = run_backtest("TESTUSDT", "1h", frames, BacktestConfig(warmup_bars=250, market="spot"))
    fut = run_backtest("TESTUSDT", "1h", frames, BacktestConfig(warmup_bars=250, market="futures"))
    assert all(t.direction == "long" for t in spot.trades), "spot backtest must never short"
    assert any(t.direction == "short" for t in fut.trades), "futures backtest should short a downtrend"
    assert spot.market == "spot" and fut.market == "futures"
