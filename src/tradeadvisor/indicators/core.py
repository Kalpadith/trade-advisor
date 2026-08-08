"""Indicator enrichment. Wraps the `ta` library behind one function so the
library can be swapped if a value ever diverges from the reference feed.
All indicators here are causal (rolling/recursive over past bars only), which
is what makes enrich-once-then-slice safe in the backtester."""

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import ADXIndicator, EMAIndicator, MACD
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator

INDICATOR_COLUMNS = [
    "ema20", "ema50", "ema200",
    "macd", "macd_signal", "macd_hist",
    "adx", "di_plus", "di_minus",
    "rsi14", "stoch_k", "stoch_d",
    "bb_upper", "bb_mid", "bb_lower", "bb_width",
    "atr14", "obv", "obv_slope", "vol_ma20", "vol_ratio",
]


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of the OHLCV frame with indicator columns appended.
    Early rows hold NaN until each indicator's warmup window is filled."""
    out = df.copy()
    close, high, low, volume = out["close"], out["high"], out["low"], out["volume"]
    n = len(out)

    out["ema20"] = EMAIndicator(close, 20).ema_indicator() if n >= 20 else np.nan
    out["ema50"] = EMAIndicator(close, 50).ema_indicator() if n >= 50 else np.nan
    out["ema200"] = EMAIndicator(close, 200).ema_indicator() if n >= 200 else np.nan

    if n >= 35:
        macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
        out["macd"] = macd.macd()
        out["macd_signal"] = macd.macd_signal()
        out["macd_hist"] = macd.macd_diff()
    else:
        out["macd"] = out["macd_signal"] = out["macd_hist"] = np.nan

    # ta's ADX implementation indexes into fixed offsets and misbehaves on
    # short inputs, so guard it explicitly.
    if n >= 45:
        adx = ADXIndicator(high, low, close, window=14)
        out["adx"] = adx.adx()
        out["di_plus"] = adx.adx_pos()
        out["di_minus"] = adx.adx_neg()
    else:
        out["adx"] = out["di_plus"] = out["di_minus"] = np.nan

    out["rsi14"] = RSIIndicator(close, 14).rsi() if n >= 15 else np.nan

    if n >= 20:
        stoch = StochasticOscillator(high, low, close, window=14, smooth_window=3)
        out["stoch_k"] = stoch.stoch()
        out["stoch_d"] = stoch.stoch_signal()
        bb = BollingerBands(close, window=20, window_dev=2)
        out["bb_upper"] = bb.bollinger_hband()
        out["bb_mid"] = bb.bollinger_mavg()
        out["bb_lower"] = bb.bollinger_lband()
        out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / out["bb_mid"]
        out["atr14"] = AverageTrueRange(high, low, close, window=14).average_true_range()
    else:
        out["stoch_k"] = out["stoch_d"] = np.nan
        out["bb_upper"] = out["bb_mid"] = out["bb_lower"] = out["bb_width"] = np.nan
        out["atr14"] = np.nan

    out["obv"] = OnBalanceVolumeIndicator(close, volume).on_balance_volume()
    out["obv_slope"] = (out["obv"] - out["obv"].shift(20)) / 20.0
    out["vol_ma20"] = volume.rolling(20).mean()
    out["vol_ratio"] = volume / out["vol_ma20"]

    return out
