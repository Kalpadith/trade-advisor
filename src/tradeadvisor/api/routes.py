import math
from datetime import datetime, timezone
from typing import Literal

import httpx
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from tradeadvisor import __version__
from tradeadvisor.data.binance import GeoBlockedError
from tradeadvisor.indicators.patterns import (
    BEARISH_PATTERNS,
    BULLISH_PATTERNS,
    PATTERN_LABELS,
)
from tradeadvisor.models import BacktestReport, Recommendation
from tradeadvisor.runtime import analyze_symbol, load_backtest_frames
from tradeadvisor.timeframes import ENTRY_TIMEFRAMES, INTERVAL_MS

router = APIRouter()

MAX_BACKTEST_BARS = 20_000
OVERLAY_COLUMNS = ["ema20", "ema50", "ema200", "bb_upper", "bb_lower"]


class AnalyzeRequest(BaseModel):
    symbol: str
    entry_timeframe: str = "1h"
    market: Literal["spot", "futures"] = "spot"
    account_size: float = Field(gt=0, default=10_000.0)
    risk_pct: float = Field(gt=0, le=10, default=1.0)


class BacktestRequest(BaseModel):
    symbol: str
    entry_timeframe: str = "1h"
    market: Literal["spot", "futures"] = "spot"
    start: str = "2024-01-01"  # YYYY-MM-DD UTC
    end: str | None = None
    account_size: float = Field(gt=0, default=10_000.0)
    risk_pct: float = Field(gt=0, le=10, default=1.0)


def _parse_date(value: str) -> int:
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(422, f"invalid date '{value}', expected YYYY-MM-DD")
    return int(dt.timestamp() * 1000)


def _check_tf(tf: str):
    if tf not in ENTRY_TIMEFRAMES:
        raise HTTPException(422, f"entry_timeframe must be one of {ENTRY_TIMEFRAMES}")


def _translate_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, GeoBlockedError):
        return HTTPException(502, str(exc))
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 400:
        return HTTPException(404, "unknown symbol (Binance rejected the request)")
    if isinstance(exc, httpx.HTTPError):
        return HTTPException(502, f"exchange request failed: {exc}")
    raise exc


@router.get("/health")
def health(request: Request):
    db_ok = True
    try:
        request.app.state.service.store.count("BTCUSDT", "1h")
    except Exception:
        db_ok = False
    return {"status": "ok", "db_ok": db_ok, "version": __version__}


@router.get("/api/symbols")
async def symbols(
    request: Request,
    quote: str = "USDT",
    market: Literal["spot", "futures"] = "spot",
):
    try:
        adapter = request.app.state.service.adapter_for(market)
        return await run_in_threadpool(adapter.list_symbols, quote)
    except Exception as exc:
        raise _translate_errors(exc)


@router.get("/api/klines")
async def klines(
    request: Request,
    symbol: str,
    interval: str = Query("1h"),
    limit: int = Query(300, ge=50, le=1000),
    market: Literal["spot", "futures"] = "spot",
):
    if interval not in INTERVAL_MS:
        raise HTTPException(422, f"interval must be one of {list(INTERVAL_MS)}")

    def _work():
        service = request.app.state.service
        engine = request.app.state.engine
        df = service.get(symbol, interval, lookback_bars=limit, market=market)
        if df.empty:
            raise HTTPException(404, "no candles for this symbol/interval")
        return engine.prepare_entry(df)

    try:
        df = await run_in_threadpool(_work)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_errors(exc)

    times = (df["open_time"] // 1000).astype(int).tolist()
    candles = [
        {"time": t, "open": o, "high": h, "low": l, "close": c}
        for t, o, h, l, c in zip(times, df["open"], df["high"], df["low"], df["close"])
    ]
    volume = [
        {"time": t, "value": v, "color": "#26a69a55" if c >= o else "#ef535055"}
        for t, v, o, c in zip(times, df["volume"], df["open"], df["close"])
    ]
    overlays = {}
    for col in OVERLAY_COLUMNS:
        overlays[col] = [
            {"time": t, "value": float(v)}
            for t, v in zip(times, df[col])
            if v is not None and not (isinstance(v, float) and math.isnan(v))
        ]
    markers = []
    for t, row in zip(times, df[BULLISH_PATTERNS + BEARISH_PATTERNS].itertuples(index=False)):
        row_d = row._asdict()
        for col in BULLISH_PATTERNS:
            if row_d.get(col):
                markers.append({"time": t, "position": "belowBar", "color": "#26a69a",
                                "shape": "arrowUp", "text": PATTERN_LABELS[col][:12]})
        for col in BEARISH_PATTERNS:
            if row_d.get(col):
                markers.append({"time": t, "position": "aboveBar", "color": "#ef5350",
                                "shape": "arrowDown", "text": PATTERN_LABELS[col][:12]})
    return {"symbol": symbol.upper(), "interval": interval,
            "candles": candles, "volume": volume, "overlays": overlays, "markers": markers}


@router.post("/api/analyze", response_model=Recommendation)
async def analyze(request: Request, body: AnalyzeRequest):
    _check_tf(body.entry_timeframe)
    try:
        return await run_in_threadpool(
            analyze_symbol,
            request.app.state.service,
            request.app.state.engine,
            body.symbol,
            body.entry_timeframe,
            body.account_size,
            body.risk_pct,
            body.market,
        )
    except Exception as exc:
        raise _translate_errors(exc)


@router.post("/api/backtest", response_model=BacktestReport)
async def backtest(request: Request, body: BacktestRequest):
    from tradeadvisor.backtest.runner import BacktestConfig, run_backtest

    _check_tf(body.entry_timeframe)
    start_ms = _parse_date(body.start)
    end_ms = _parse_date(body.end) if body.end else None
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    span = (end_ms or now_ms) - start_ms
    if span <= 0:
        raise HTTPException(422, "end must be after start")
    if span // INTERVAL_MS[body.entry_timeframe] > MAX_BACKTEST_BARS:
        raise HTTPException(422, f"range too large: max {MAX_BACKTEST_BARS} {body.entry_timeframe} bars per backtest")

    settings = request.app.state.settings

    def _work() -> BacktestReport:
        frames = load_backtest_frames(
            request.app.state.service, body.symbol, body.entry_timeframe,
            start_ms, end_ms, market=body.market,
        )
        cfg = BacktestConfig(
            account_size=body.account_size,
            risk_pct=body.risk_pct,
            fee_pct=settings.fee_pct,
            slippage_pct=settings.slippage_pct,
            market=body.market,
        )
        return run_backtest(body.symbol, body.entry_timeframe, frames, cfg,
                            start_ms=start_ms, end_ms=end_ms)

    try:
        return await run_in_threadpool(_work)
    except Exception as exc:
        raise _translate_errors(exc)
