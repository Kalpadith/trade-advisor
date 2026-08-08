# Trade Advisor

Rule-based crypto trade advisory tool. Ask it about a coin and it fetches
live + historical Binance data, runs multi-timeframe technical analysis, and
produces a trade recommendation: direction (long / short / **no trade**),
suggested holding period, entry zone, stop loss, take-profit targets,
fixed-risk position size, a confidence score — and the full reasoning trail
showing which rules fired and what each contributed.

> **This is decision support, not financial advice.** No indicator system
> reliably predicts markets. What this tool gives you is consistency,
> risk discipline, and a backtester to falsify rule ideas before you trust
> them. "No trade" is a first-class answer. It never places orders.

## Setup

```powershell
cd trade-advisor
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Optionally copy `.env.example` to `.env` and adjust. If Binance returns
HTTP 451 (geo-blocked in your region), set:

```
TADVISOR_BINANCE_BASE_URL=https://data-api.binance.vision
```

(The tool also tries this mirror automatically as a fallback.)

## Usage

```powershell
# backfill the local candle cache (optional; analyze does this on demand)
tadvisor fetch BTCUSDT

# analyze: prints direction, entry zone, SL, TPs, sizing + reasoning
tadvisor analyze BTCUSDT --tf 1h --account 10000 --risk 1

# backtest the exact same engine over history
tadvisor backtest BTCUSDT --tf 4h --start 2026-01-01

# web dashboard (chart + recommendation card + backtest tab)
tadvisor serve            # -> http://127.0.0.1:8000
```

Entry timeframes: `15m`, `1h`, `4h`, `1d`. Each entry timeframe is judged
against a higher **bias** timeframe (trend) and a **context** timeframe
(confirmation): 15m→4h/1h, 1h→1d/4h, 4h→1d, 1d→1w.

## How a recommendation is produced

1. **Bias timeframe (weight 40):** EMA 20/50/200 stack, MACD histogram,
   ADX regime. ADX < 20 flags the market as choppy and can veto the trade.
2. **Context timeframe (weight 20):** price vs EMA50, RSI regime.
3. **Entry timeframe (weight 40):** RSI pullback in trend direction,
   stochastic cross, proximity to detected support/resistance, candlestick
   confirmation (engulfing, hammer, stars...), volume confirmation.

Total score ≥ +30 → long, ≤ −30 → short, otherwise no trade. The trade plan
uses an ATR-based stop (min 1.5×ATR, beyond the nearest confirmed swing,
max 3×ATR or the trade is skipped), take-profits at 1R/2R/3R (3R capped at
the next major level), and position size = account × risk% ÷ stop distance.

## Backtester honesty rules

- Same `SignalEngine.analyze()` as live — zero divergence by construction.
- Signals fire on closed candles only; fills happen next bar at the earliest.
- Swing points only become visible k bars after they form (no repainting).
- If a candle touches both stop and take-profit, the stop is counted (pessimistic).
- Every fill pays fees (0.1%) and slippage (0.05%) per side.

A test (`tests/test_signals.py::test_lookahead_guard_prefix_vs_full_slice`)
asserts that analyzing a data prefix directly is identical to the
backtester's enrich-once-then-slice fast path — the standard way lookahead
bugs sneak into backtests.

## Verifying against TradingView

Open the same symbol on TradingView with the **Binance** feed, add RSI(14),
EMA(20/50/200) and Bollinger(20,2), and compare with the chart overlays at
`http://127.0.0.1:8000` and the values cited in the reasoning trail. Values
should match to within rounding once ~200 bars of warmup exist. Detected
S/R levels should sit on visually obvious swing clusters.

## Tests

```powershell
pytest
```

## Project layout

```
src/tradeadvisor/
  data/        Binance adapter, SQLite candle cache, incremental sync
  indicators/  indicator enrichment, swing/S-R detection, candle patterns
  signals/     rules -> scoring -> trade plan -> SignalEngine
  backtest/    event-loop replay + metrics
  api/         FastAPI routes (health, symbols, klines, analyze, backtest)
web/           dashboard (vanilla JS + Lightweight Charts, no build step)
tests/         37 tests incl. the lookahead guard and pessimistic-fill rules
```
