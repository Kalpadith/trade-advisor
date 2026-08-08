import random

import pytest

from helpers import make_frames, make_ohlcv
from tradeadvisor.indicators.levels import find_swings
from tradeadvisor.signals.engine import SignalEngine


def test_strong_uptrend_is_not_shorted():
    frames = make_frames(seed=7, trend=0.15)
    rec = SignalEngine().analyze(
        "TESTUSDT", "1h", frames["entry"], frames["context"], frames["bias"]
    )
    assert rec.direction in ("long", "no_trade")
    assert rec.score_total > 0
    assert len(rec.rules) == 11
    assert any("decision support" in w for w in rec.warnings)


def test_plan_geometry_when_directional():
    """Find a seed that produces a tradeable long and check plan invariants."""
    engine = SignalEngine()
    rec = None
    for seed in range(30):
        frames = make_frames(seed=seed, trend=0.15)
        candidate = engine.analyze(
            "TESTUSDT", "1h", frames["entry"], frames["context"], frames["bias"]
        )
        if candidate.direction == "long":
            rec = candidate
            break
    assert rec is not None, "no seed produced a long recommendation"
    lo, hi = rec.entry_zone
    mid = (lo + hi) / 2
    assert lo <= hi
    assert rec.stop_loss < lo, "stop must sit below the entry zone for a long"
    tps = [t.price for t in rec.take_profits]
    assert all(tp > mid for tp in tps)
    assert tps == sorted(tps), "take profits must be ascending for a long"
    r = mid - rec.stop_loss
    assert rec.take_profits[0].r_multiple == pytest.approx((tps[0] - mid) / r, abs=1e-6)
    pos = rec.position
    assert pos.risk_amount == pytest.approx(pos.account_size * pos.risk_pct / 100)
    assert pos.quantity == pytest.approx(pos.risk_amount / r, rel=1e-6)


def test_flat_market_mostly_abstains():
    frames = make_frames(seed=21, trend=0.0)
    rec = SignalEngine().analyze(
        "TESTUSDT", "1h", frames["entry"], frames["context"], frames["bias"]
    )
    assert abs(rec.score_total) <= 100


def test_lookahead_guard_prefix_vs_full_slice():
    """THE critical test: analyzing a prefix directly must equal analyzing
    full-history-enriched data sliced to the same prefix (the backtester's
    fast path). Any difference means future bars leaked into the past."""
    frames = make_frames(seed=5, trend=0.05)
    engine = SignalEngine()

    entry_full = engine.prepare_entry(frames["entry"])
    ctx_prep = engine.prepare_higher(frames["context"])
    bias_prep = engine.prepare_higher(frames["bias"])
    swings_full = find_swings(entry_full)

    rng = random.Random(0)
    for _ in range(12):
        t = rng.randint(300, len(frames["entry"]) - 10)
        live = engine.analyze(
            "TESTUSDT", "1h",
            frames["entry"].iloc[:t], frames["context"], frames["bias"],
        )
        fast = engine.analyze(
            "TESTUSDT", "1h",
            entry_full.iloc[:t], ctx_prep, bias_prep,
            prepared=True, swings=swings_full.visible(t - 1),
        )
        assert live.direction == fast.direction, f"direction diverged at t={t}"
        assert live.score_total == pytest.approx(fast.score_total, abs=1e-9), f"score diverged at t={t}"
        if live.stop_loss is None:
            assert fast.stop_loss is None
        else:
            assert live.stop_loss == pytest.approx(fast.stop_loss, abs=1e-9)
        live_levels = sorted(lv.price for lv in live.levels)
        fast_levels = sorted(lv.price for lv in fast.levels)
        assert live_levels == pytest.approx(fast_levels, abs=1e-9), f"levels diverged at t={t}"


def test_noise_after_cutoff_cannot_change_result():
    """Replacing every bar after t with garbage must not affect the analysis
    of data up to t."""
    frames = make_frames(seed=9, trend=0.05)
    engine = SignalEngine()
    entry = frames["entry"]
    t = 400

    clean = engine.analyze("TESTUSDT", "1h", entry.iloc[:t], frames["context"], frames["bias"])
    noised = entry.copy()
    noised.iloc[t:, noised.columns.get_indexer(["open", "high", "low", "close"])] = 9999.0
    dirty = engine.analyze("TESTUSDT", "1h", noised.iloc[:t], frames["context"], frames["bias"])

    assert clean.direction == dirty.direction
    assert clean.score_total == dirty.score_total
    assert clean.stop_loss == dirty.stop_loss
