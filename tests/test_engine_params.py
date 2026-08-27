"""EngineParams plumbing: thresholds and profiles actually change behaviour."""

from helpers import make_frames
from tradeadvisor.signals.engine import (
    DEFAULT_PARAMS,
    EngineParams,
    SignalEngine,
    params_for_timeframe,
)


def _analyze(engine, frames):
    return engine.analyze(
        "TESTUSDT", "1h", frames["entry"], frames["context"], frames["bias"],
        market="futures",
    )


def test_default_engine_matches_default_params():
    frames = make_frames(seed=7, trend=0.15)
    rec_none = _analyze(SignalEngine(), frames)
    rec_default = _analyze(SignalEngine(DEFAULT_PARAMS), frames)
    assert rec_none.direction == rec_default.direction
    assert rec_none.score_total == rec_default.score_total


def test_impossible_threshold_forces_no_trade():
    engine = SignalEngine(EngineParams(entry_threshold=10_000))
    for seed in (7, 15, 21):
        for trend in (0.15, -0.15):
            frames = make_frames(seed=seed, trend=trend)
            rec = _analyze(engine, frames)
            assert rec.direction == "no_trade"


def test_higher_threshold_only_removes_trades():
    """Raising the threshold must never create a trade the default rejected."""
    loose = SignalEngine(EngineParams(entry_threshold=30))
    strict = SignalEngine(EngineParams(entry_threshold=60))
    traded_loose = traded_strict = 0
    for seed in range(12):
        frames = make_frames(seed=seed, trend=0.12)
        rl = _analyze(loose, frames)
        rs = _analyze(strict, frames)
        assert rl.score_total == rs.score_total, "threshold must not change scoring"
        traded_loose += rl.direction != "no_trade"
        traded_strict += rs.direction != "no_trade"
        if rs.direction != "no_trade":
            assert rl.direction == rs.direction
    assert traded_strict <= traded_loose


def test_params_for_timeframe_falls_back_to_default():
    assert params_for_timeframe("1h") == DEFAULT_PARAMS
    assert params_for_timeframe("4h") == DEFAULT_PARAMS


def test_15m_uses_tuned_profile():
    p = params_for_timeframe("15m")
    assert p.entry_threshold == 55
    assert p.adx_min == 25
    assert p.stop_atr_min == 2.5
    assert p.note is not None


def test_15m_recommendation_carries_profile_note():
    frames = make_frames(seed=7, trend=0.15)
    rec = SignalEngine().analyze(
        "TESTUSDT", "15m", frames["entry"], frames["context"], frames["bias"],
        market="futures",
    )
    assert any("15m" in w and "caution" in w for w in rec.warnings)


def test_wider_stop_param_widens_stop():
    frames = make_frames(seed=7, trend=0.15)
    narrow = _analyze(SignalEngine(EngineParams(stop_atr_min=1.5)), frames)
    wide = _analyze(SignalEngine(EngineParams(stop_atr_min=2.5, stop_atr_max=4.0)), frames)
    if narrow.direction == "long" and wide.direction == "long":
        mid_n = sum(narrow.entry_zone) / 2
        mid_w = sum(wide.entry_zone) / 2
        assert (mid_w - wide.stop_loss) >= (mid_n - narrow.stop_loss)
