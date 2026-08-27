"""Individual scoring rules. Each rule inspects the last closed bar(s) of an
enriched frame and returns a RuleResult with score in [-1, +1] (positive =
bullish) plus a human-readable detail line. Weights are deliberately coarse
round numbers - precision here would be false precision."""

import pandas as pd

from tradeadvisor.indicators.fibonacci import GOLDEN_POCKET, FibLevels
from tradeadvisor.indicators.patterns import (
    BEARISH_PATTERNS,
    BULLISH_PATTERNS,
    PATTERN_LABELS,
)
from tradeadvisor.models import Level, RuleResult


def _r(name: str, tf: str, score: float, weight: float, detail: str) -> RuleResult:
    return RuleResult(
        name=name, timeframe=tf, score=score, weight=weight,
        contribution=score * weight, detail=detail,
    )


def _isnan(*values) -> bool:
    return any(pd.isna(v) for v in values)


# ---------------------------------------------------------------- bias TF ---

def rule_ema_stack(df: pd.DataFrame, tf: str, weight: float = 15) -> RuleResult:
    row = df.iloc[-1]
    c, e20, e50, e200 = row["close"], row["ema20"], row["ema50"], row["ema200"]
    if _isnan(c, e20, e50, e200):
        return _r("ema_stack", tf, 0, weight, "insufficient history for EMA 20/50/200")
    if c > e20 > e50 > e200:
        return _r("ema_stack", tf, 1, weight, f"full bullish EMA stack (close {c:.6g} > EMA20 > EMA50 > EMA200)")
    if c < e20 < e50 < e200:
        return _r("ema_stack", tf, -1, weight, f"full bearish EMA stack (close {c:.6g} < EMA20 < EMA50 < EMA200)")
    if c > e50 and e50 > e200:
        return _r("ema_stack", tf, 0.5, weight, "close above EMA50 and EMA50 above EMA200 (bullish lean)")
    if c < e50 and e50 < e200:
        return _r("ema_stack", tf, -0.5, weight, "close below EMA50 and EMA50 below EMA200 (bearish lean)")
    return _r("ema_stack", tf, 0, weight, "EMAs mixed / crossing - no clear trend structure")


def rule_macd_momentum(df: pd.DataFrame, tf: str, weight: float = 10) -> RuleResult:
    if len(df) < 2:
        return _r("macd_momentum", tf, 0, weight, "insufficient history for MACD")
    hist, prev = df["macd_hist"].iloc[-1], df["macd_hist"].iloc[-2]
    if _isnan(hist, prev):
        return _r("macd_momentum", tf, 0, weight, "insufficient history for MACD")
    if hist > 0:
        if hist > prev:
            return _r("macd_momentum", tf, 1, weight, f"MACD histogram positive and rising ({hist:.4g})")
        return _r("macd_momentum", tf, 0.5, weight, f"MACD histogram positive but fading ({hist:.4g})")
    if hist < 0:
        if hist < prev:
            return _r("macd_momentum", tf, -1, weight, f"MACD histogram negative and falling ({hist:.4g})")
        return _r("macd_momentum", tf, -0.5, weight, f"MACD histogram negative but recovering ({hist:.4g})")
    return _r("macd_momentum", tf, 0, weight, "MACD histogram flat")


def rule_adx_regime(
    df: pd.DataFrame, tf: str, weight: float = 15, adx_min: float = 20.0
) -> tuple[RuleResult, list[str]]:
    row = df.iloc[-1]
    adx, dip, dim = row["adx"], row["di_plus"], row["di_minus"]
    if _isnan(adx, dip, dim):
        return _r("adx_regime", tf, 0, weight, "insufficient history for ADX"), []
    if adx < adx_min:
        warn = f"choppy market: ADX {adx:.1f} < {adx_min:g} on {tf}"
        return _r("adx_regime", tf, 0, weight, f"ADX {adx:.1f} < {adx_min:g} - no trend to trade"), [warn]
    direction = 1 if dip > dim else -1
    strength = 1.0 if adx >= adx_min + 5 else 0.5
    side = "DI+ leads" if direction > 0 else "DI- leads"
    return _r("adx_regime", tf, direction * strength, weight,
              f"ADX {adx:.1f} trending, {side} ({dip:.1f} vs {dim:.1f})"), []


# ------------------------------------------------------------- context TF ---

def rule_price_vs_ema50(df: pd.DataFrame, tf: str, weight: float = 10) -> RuleResult:
    row = df.iloc[-1]
    c, e50 = row["close"], row["ema50"]
    if _isnan(c, e50):
        return _r("price_vs_ema50", tf, 0, weight, "insufficient history for EMA50")
    if abs(c - e50) / c < 0.0025:
        return _r("price_vs_ema50", tf, 0, weight, "price sitting on EMA50 - undecided")
    if c > e50:
        return _r("price_vs_ema50", tf, 1, weight, f"price above EMA50 ({c:.6g} > {e50:.6g})")
    return _r("price_vs_ema50", tf, -1, weight, f"price below EMA50 ({c:.6g} < {e50:.6g})")


def rule_rsi_regime(df: pd.DataFrame, tf: str, weight: float = 10) -> RuleResult:
    rsi = df["rsi14"].iloc[-1]
    if _isnan(rsi):
        return _r("rsi_regime", tf, 0, weight, "insufficient history for RSI")
    if rsi > 60:
        return _r("rsi_regime", tf, 1, weight, f"RSI {rsi:.1f} in bullish regime (>60)")
    if rsi > 55:
        return _r("rsi_regime", tf, 0.5, weight, f"RSI {rsi:.1f} leaning bullish")
    if rsi < 40:
        return _r("rsi_regime", tf, -1, weight, f"RSI {rsi:.1f} in bearish regime (<40)")
    if rsi < 45:
        return _r("rsi_regime", tf, -0.5, weight, f"RSI {rsi:.1f} leaning bearish")
    return _r("rsi_regime", tf, 0, weight, f"RSI {rsi:.1f} neutral (45-55)")


# --------------------------------------------------------------- entry TF ---

def rule_rsi_pullback(df: pd.DataFrame, tf: str, bias_sign: int, weight: float = 10) -> RuleResult:
    if bias_sign == 0:
        return _r("rsi_pullback", tf, 0, weight, "no higher-timeframe bias - pullback rule inactive")
    if len(df) < 2:
        return _r("rsi_pullback", tf, 0, weight, "insufficient history for RSI")
    rsi, prev = df["rsi14"].iloc[-1], df["rsi14"].iloc[-2]
    if _isnan(rsi, prev):
        return _r("rsi_pullback", tf, 0, weight, "insufficient history for RSI")
    if bias_sign > 0:
        if prev < 45 and rsi > prev:
            return _r("rsi_pullback", tf, 1, weight, f"RSI pullback turning up in uptrend ({prev:.1f} -> {rsi:.1f})")
        if rsi < 50 and rsi > prev:
            return _r("rsi_pullback", tf, 0.5, weight, f"RSI recovering below 50 ({rsi:.1f})")
        if rsi > 70:
            return _r("rsi_pullback", tf, -0.5, weight, f"RSI {rsi:.1f} overbought - chasing an extended move")
        return _r("rsi_pullback", tf, 0, weight, f"RSI {rsi:.1f} - no pullback entry setup")
    else:
        if prev > 55 and rsi < prev:
            return _r("rsi_pullback", tf, -1, weight, f"RSI rally turning down in downtrend ({prev:.1f} -> {rsi:.1f})")
        if rsi > 50 and rsi < prev:
            return _r("rsi_pullback", tf, -0.5, weight, f"RSI rolling over above 50 ({rsi:.1f})")
        if rsi < 30:
            return _r("rsi_pullback", tf, 0.5, weight, f"RSI {rsi:.1f} oversold - chasing an extended move")
        return _r("rsi_pullback", tf, 0, weight, f"RSI {rsi:.1f} - no pullback entry setup")


def rule_stoch_cross(df: pd.DataFrame, tf: str, bias_sign: int, weight: float = 7) -> RuleResult:
    if bias_sign == 0:
        return _r("stoch_cross", tf, 0, weight, "no higher-timeframe bias - stochastic rule inactive")
    if len(df) < 2:
        return _r("stoch_cross", tf, 0, weight, "insufficient history for stochastic")
    k, d = df["stoch_k"].iloc[-1], df["stoch_d"].iloc[-1]
    kp, dp = df["stoch_k"].iloc[-2], df["stoch_d"].iloc[-2]
    if _isnan(k, d, kp, dp):
        return _r("stoch_cross", tf, 0, weight, "insufficient history for stochastic")
    cross_up = k > d and kp <= dp
    cross_down = k < d and kp >= dp
    if bias_sign > 0 and cross_up:
        if kp < 25:
            return _r("stoch_cross", tf, 1, weight, f"stochastic bullish cross out of oversold (K {kp:.0f} -> {k:.0f})")
        if k < 50:
            return _r("stoch_cross", tf, 0.5, weight, f"stochastic bullish cross below midline (K {k:.0f})")
    if bias_sign < 0 and cross_down:
        if kp > 75:
            return _r("stoch_cross", tf, -1, weight, f"stochastic bearish cross out of overbought (K {kp:.0f} -> {k:.0f})")
        if k > 50:
            return _r("stoch_cross", tf, -0.5, weight, f"stochastic bearish cross above midline (K {k:.0f})")
    return _r("stoch_cross", tf, 0, weight, "no stochastic trigger")


def rule_sr_proximity(df: pd.DataFrame, tf: str, bias_sign: int, levels: list[Level], weight: float = 10) -> RuleResult:
    if bias_sign == 0:
        return _r("sr_proximity", tf, 0, weight, "no higher-timeframe bias - S/R rule inactive")
    row = df.iloc[-1]
    close, atr = row["close"], row["atr14"]
    if _isnan(close, atr) or not levels:
        return _r("sr_proximity", tf, 0, weight, "no ATR or no detected levels")
    tol = 0.5 * atr
    sup_near = any(lv.kind == "support" and 0 <= close - lv.price <= tol for lv in levels)
    res_near = any(lv.kind == "resistance" and 0 <= lv.price - close <= tol for lv in levels)
    if bias_sign > 0:
        score = (1.0 if sup_near else 0.0) + (-0.5 if res_near else 0.0)
        if sup_near and res_near:
            detail = "price squeezed between nearby support and resistance"
        elif sup_near:
            detail = "price sitting on support - favorable long location"
        elif res_near:
            detail = "resistance directly overhead - poor long location"
        else:
            detail = "price in open space - no nearby level"
    else:
        score = (-1.0 if res_near else 0.0) + (0.5 if sup_near else 0.0)
        if sup_near and res_near:
            detail = "price squeezed between nearby support and resistance"
        elif res_near:
            detail = "price pressing under resistance - favorable short location"
        elif sup_near:
            detail = "support directly below - poor short location"
        else:
            detail = "price in open space - no nearby level"
    return _r("sr_proximity", tf, max(-1.0, min(1.0, score)), weight, detail)


def rule_candle_confirmation(df: pd.DataFrame, tf: str, bias_sign: int, weight: float = 8) -> RuleResult:
    if bias_sign == 0:
        return _r("candle_confirmation", tf, 0, weight, "no higher-timeframe bias - candle rule inactive")
    row = df.iloc[-1]
    bullish = [PATTERN_LABELS[p] for p in BULLISH_PATTERNS if bool(row.get(p, False))]
    bearish = [PATTERN_LABELS[p] for p in BEARISH_PATTERNS if bool(row.get(p, False))]
    doji = bool(row.get("pat_doji", False))
    if bias_sign > 0:
        if bullish:
            return _r("candle_confirmation", tf, 1, weight, f"bullish confirmation candle: {', '.join(bullish)}")
        if bearish:
            return _r("candle_confirmation", tf, -0.5, weight, f"bearish candle against long idea: {', '.join(bearish)}")
    else:
        if bearish:
            return _r("candle_confirmation", tf, -1, weight, f"bearish confirmation candle: {', '.join(bearish)}")
        if bullish:
            return _r("candle_confirmation", tf, 0.5, weight, f"bullish candle against short idea: {', '.join(bullish)}")
    if doji:
        return _r("candle_confirmation", tf, 0, weight, "doji - indecision, no confirmation")
    return _r("candle_confirmation", tf, 0, weight, "no notable candle pattern")


def rule_fib_confluence(
    df: pd.DataFrame, tf: str, bias_sign: int, fib: FibLevels | None, weight: float = 8
) -> RuleResult:
    """Reward pullbacks into the golden pocket (50-61.8% retracement) of the
    most recent swing leg in the trend direction; penalize retracements so
    deep (beyond 78.6%) that the leg itself is in doubt."""
    if bias_sign == 0:
        return _r("fib_confluence", tf, 0, weight, "no higher-timeframe bias - fibonacci rule inactive")
    if fib is None:
        return _r("fib_confluence", tf, 0, weight, "no clear swing leg to measure fibonacci from")
    row = df.iloc[-1]
    close, atr = row["close"], row["atr14"]
    if _isnan(close, atr) or atr <= 0:
        return _r("fib_confluence", tf, 0, weight, "no ATR for fibonacci proximity")

    leg_matches_bias = (fib.up and bias_sign > 0) or (not fib.up and bias_sign < 0)
    if not leg_matches_bias:
        return _r("fib_confluence", tf, 0, weight,
                  f"most recent leg points {'up' if fib.up else 'down'}, against the bias - no fib setup")

    tol = 0.5 * atr
    span = fib.leg_high - fib.leg_low
    # how far price has retraced the leg (0 = leg end, 1 = leg start)
    retraced = (fib.leg_high - close) / span if fib.up else (close - fib.leg_low) / span

    if retraced > 0.786 + tol / span:
        return _r("fib_confluence", tf, -0.5 * bias_sign, weight,
                  f"retraced {retraced * 100:.0f}% of the leg (beyond 78.6%) - leg validity in doubt")

    gp_lo, gp_hi = (fib.retracement(GOLDEN_POCKET[1]), fib.retracement(GOLDEN_POCKET[0]))
    lo, hi = min(gp_lo, gp_hi), max(gp_lo, gp_hi)
    if lo - tol <= close <= hi + tol:
        return _r("fib_confluence", tf, 1.0 * bias_sign, weight,
                  f"price in the golden pocket (50-61.8% retracement at {lo:.6g}..{hi:.6g})")
    r382 = fib.retracement(0.382)
    if abs(close - r382) <= tol:
        return _r("fib_confluence", tf, 0.7 * bias_sign, weight,
                  f"price at the 38.2% retracement ({r382:.6g}) - shallow pullback")
    return _r("fib_confluence", tf, 0, weight,
              f"retraced {max(retraced, 0) * 100:.0f}% - not at a fibonacci confluence")


def rule_volume_confirmation(df: pd.DataFrame, tf: str, bias_sign: int, weight: float = 5) -> RuleResult:
    if bias_sign == 0:
        return _r("volume_confirmation", tf, 0, weight, "no higher-timeframe bias - volume rule inactive")
    row = df.iloc[-1]
    ratio = row["vol_ratio"]
    if _isnan(ratio):
        return _r("volume_confirmation", tf, 0, weight, "insufficient history for volume MA")
    candle_sign = 1 if row["close"] > row["open"] else -1
    if ratio > 1.2 and candle_sign == bias_sign:
        magnitude = 1.0 if ratio > 1.5 else 0.6
        return _r("volume_confirmation", tf, bias_sign * magnitude, weight,
                  f"volume {ratio:.1f}x average on a candle in trend direction")
    return _r("volume_confirmation", tf, 0, weight, f"volume {ratio:.1f}x average - no confirmation")
