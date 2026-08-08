from tradeadvisor.data.store import CandleStore
from tradeadvisor.models import Candle


def _candles(n=10, start=1_700_000_000_000, step=3_600_000):
    return [
        Candle(
            open_time=start + i * step,
            open=100 + i, high=101 + i, low=99 + i, close=100.5 + i,
            volume=10.0,
            close_time=start + (i + 1) * step - 1,
        )
        for i in range(n)
    ]


def test_upsert_and_load_roundtrip(tmp_path):
    store = CandleStore(tmp_path / "test.db")
    candles = _candles(10)
    assert store.upsert("BTCUSDT", "1h", candles) == 10
    df = store.load("BTCUSDT", "1h")
    assert len(df) == 10
    assert list(df["open_time"]) == [c.open_time for c in candles]
    assert df.index.is_monotonic_increasing


def test_upsert_is_idempotent(tmp_path):
    store = CandleStore(tmp_path / "test.db")
    candles = _candles(10)
    store.upsert("BTCUSDT", "1h", candles)
    store.upsert("BTCUSDT", "1h", candles[5:])  # overlap
    assert store.count("BTCUSDT", "1h") == 10


def test_range_and_limit(tmp_path):
    store = CandleStore(tmp_path / "test.db")
    candles = _candles(20)
    store.upsert("ETHUSDT", "1h", candles)
    start = candles[5].open_time
    end = candles[14].open_time
    df = store.load("ETHUSDT", "1h", start_ms=start, end_ms=end)
    assert len(df) == 10
    tail = store.load("ETHUSDT", "1h", limit=7)
    assert len(tail) == 7
    assert int(tail["open_time"].iloc[-1]) == candles[-1].open_time


def test_edges(tmp_path):
    store = CandleStore(tmp_path / "test.db")
    assert store.latest_open_time("BTCUSDT", "1h") is None
    candles = _candles(5)
    store.upsert("BTCUSDT", "1h", candles)
    assert store.earliest_open_time("BTCUSDT", "1h") == candles[0].open_time
    assert store.latest_open_time("BTCUSDT", "1h") == candles[-1].open_time
    # intervals are isolated
    assert store.latest_open_time("BTCUSDT", "4h") is None
