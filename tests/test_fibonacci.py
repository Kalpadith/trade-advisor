import numpy as np
import pytest

from tradeadvisor.indicators.fibonacci import compute_fib
from tradeadvisor.indicators.levels import Swings


def make_swings(seq):
    """seq: list of (pos, price, kind)."""
    pos = np.array([s[0] for s in seq], dtype=np.int64)
    price = np.array([s[1] for s in seq], dtype=np.float64)
    kind = np.array([s[2] for s in seq], dtype="U1")
    return Swings(pos=pos, price=price, kind=kind,
                  time=pos * 1000, confirmed_pos=pos + 3)


def test_up_leg_retracements_and_extensions():
    swings = make_swings([(10, 100.0, "L"), (20, 105.0, "H"), (25, 102.0, "L"), (30, 110.0, "H")])
    fib = compute_fib(swings)
    assert fib is not None and fib.up
    assert fib.leg_low == 100.0 and fib.leg_high == 110.0
    assert fib.retracement(0.5) == pytest.approx(105.0)
    assert fib.retracement(0.618) == pytest.approx(110 - 0.618 * 10)
    assert fib.extensions[1.272] == pytest.approx(100 + 1.272 * 10)
    assert fib.extensions[1.618] == pytest.approx(100 + 1.618 * 10)


def test_down_leg_mirrors():
    swings = make_swings([(10, 110.0, "H"), (20, 100.0, "L")])
    fib = compute_fib(swings)
    assert fib is not None and not fib.up
    assert fib.retracement(0.5) == pytest.approx(105.0)
    assert fib.retracement(0.382) == pytest.approx(100 + 0.382 * 10)
    assert fib.extensions[1.272] == pytest.approx(110 - 1.272 * 10)


def test_insufficient_swings_returns_none():
    assert compute_fib(make_swings([(10, 100.0, "L")])) is None
    assert compute_fib(make_swings([(10, 100.0, "L"), (20, 102.0, "L")])) is None


def test_zero_span_returns_none():
    swings = make_swings([(10, 100.0, "L"), (20, 100.0, "H")])
    assert compute_fib(swings) is None
