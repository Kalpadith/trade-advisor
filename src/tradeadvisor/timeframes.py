"""Timeframe constants shared by the data layer and the signal engine."""

from dataclasses import dataclass

INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


@dataclass(frozen=True)
class TfRoles:
    bias: str      # higher timeframe that defines trend bias
    context: str   # intermediate timeframe for confirmation
    holding: str   # human-readable suggested holding period


TF_CONFIG: dict[str, TfRoles] = {
    "15m": TfRoles(bias="4h", context="1h", holding="a few hours to 1 day"),
    "1h": TfRoles(bias="1d", context="4h", holding="1-3 days"),
    "4h": TfRoles(bias="1d", context="1d", holding="3 days to 2 weeks"),
    "1d": TfRoles(bias="1w", context="1d", holding="1-8 weeks"),
}

ENTRY_TIMEFRAMES = list(TF_CONFIG.keys())
