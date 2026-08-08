import time

import pytest
from fastapi.testclient import TestClient

from helpers import make_ohlcv
from tradeadvisor.api.app import create_app
from tradeadvisor.config import Settings
from tradeadvisor.data.service import MarketDataService
from tradeadvisor.data.store import CandleStore
from tradeadvisor.models import Candle
from tradeadvisor.timeframes import INTERVAL_MS


class FakeAdapter:
    """Serves deterministic synthetic candles ending at the last closed bar
    before 'now' — no network involved."""

    def __init__(self, seed: int = 7):
        now = int(time.time() * 1000)
        self.data: dict[str, list[Candle]] = {}
        for interval in ("15m", "1h", "4h", "1d", "1w"):
            step = INTERVAL_MS[interval]
            n = 600
            last_open = (now // step) * step - step  # last fully closed bar
            df = make_ohlcv(n, seed=seed, trend=0.05, interval_ms=step,
                            start_time=last_open - (n - 1) * step)
            self.data[interval] = [
                Candle(open_time=int(r.open_time), open=r.open, high=r.high,
                       low=r.low, close=r.close, volume=r.volume,
                       close_time=int(r.close_time))
                for r in df.itertuples(index=False)
            ]

    def fetch_klines(self, symbol, interval, start_ms=None, end_ms=None, limit=1000):
        return self.fetch_klines_range(symbol, interval, start_ms or 0, end_ms)[:limit]

    def fetch_klines_range(self, symbol, interval, start_ms, end_ms=None):
        return [
            c for c in self.data[interval]
            if c.open_time >= start_ms and (end_ms is None or c.open_time <= end_ms)
        ]

    def list_symbols(self, quote="USDT"):
        return ["TESTUSDT"]


@pytest.fixture
def client(tmp_path):
    fake = FakeAdapter()
    service = MarketDataService({"spot": fake, "futures": fake}, CandleStore(tmp_path / "t.db"))
    app = create_app(settings=Settings(db_path=tmp_path / "t.db"), service=service)
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_symbols(client):
    resp = client.get("/api/symbols")
    assert resp.status_code == 200
    assert resp.json() == ["TESTUSDT"]


def test_klines_shape(client):
    resp = client.get("/api/klines", params={"symbol": "TESTUSDT", "interval": "1h", "limit": 300})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["candles"]) == 300
    assert {"time", "open", "high", "low", "close"} <= set(body["candles"][0])
    assert set(body["overlays"]) == {"ema20", "ema50", "ema200", "bb_upper", "bb_lower"}
    assert len(body["volume"]) == 300


def test_analyze_endpoint(client):
    resp = client.post("/api/analyze", json={
        "symbol": "TESTUSDT", "entry_timeframe": "1h",
        "account_size": 5000, "risk_pct": 1.0,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["direction"] in ("long", "short", "no_trade")
    assert len(body["rules"]) == 11
    assert body["symbol"] == "TESTUSDT"
    assert body["market"] == "spot"
    if body["direction"] == "long":
        assert body["stop_loss"] is not None
        assert body["position"]["account_size"] == 5000


def test_analyze_futures_market(client):
    resp = client.post("/api/analyze", json={
        "symbol": "TESTUSDT", "entry_timeframe": "1h", "market": "futures",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["market"] == "futures"
    if body["direction"] != "no_trade":
        assert body["position"]["leverage"] is not None


def test_analyze_rejects_bad_timeframe(client):
    resp = client.post("/api/analyze", json={"symbol": "TESTUSDT", "entry_timeframe": "3m"})
    assert resp.status_code == 422


def test_analyze_rejects_bad_market(client):
    resp = client.post("/api/analyze", json={"symbol": "TESTUSDT", "market": "margin"})
    assert resp.status_code == 422


def test_dashboard_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Trade Advisor" in resp.text
