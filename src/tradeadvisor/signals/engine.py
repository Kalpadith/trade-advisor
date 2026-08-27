"""SignalEngine - the single analysis entrypoint. The CLI, the API and the
backtester all call `analyze()`, which is what guarantees backtests measure
the same logic that produces live recommendations.

This module only receives DataFrames; it never touches HTTP or SQLite."""

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from tradeadvisor.indicators.core import enrich
from tradeadvisor.indicators.fibonacci import FibLevels, compute_fib
from tradeadvisor.indicators.levels import Swings, cluster_levels, find_swings
from tradeadvisor.indicators.patterns import add_patterns
from tradeadvisor.models import FibLevel, FibonacciInfo, Recommendation
from tradeadvisor.signals import rules as R
from tradeadvisor.signals.plan import build_trade_plan
from tradeadvisor.signals.scoring import score
from tradeadvisor.timeframes import TF_CONFIG

DISCLAIMER = "Rule-based decision support, not financial advice. Past performance does not guarantee future results."

# |bias + context subtotal| must reach this before entry-timing rules engage.
BIAS_DEADBAND = 10.0


@dataclass(frozen=True)
class EngineParams:
    """Tunable engine parameters. Defaults reproduce the original behaviour;
    per-timeframe profiles live in PARAMS_BY_TF."""

    entry_threshold: float = 30.0   # |score| needed to trade
    adx_min: float = 20.0           # bias-TF ADX below this = choppy
    choppy_override: float = 45.0   # |score| needed to trade through chop
    stop_atr_min: float = 1.5
    stop_atr_max: float = 3.0
    note: str | None = None         # appended to every recommendation's warnings


DEFAULT_PARAMS = EngineParams()

# Per-entry-timeframe tuned profiles (see scripts/sweep_15m.py). A timeframe
# without an entry here uses DEFAULT_PARAMS.
PARAMS_BY_TF: dict[str, EngineParams] = {
    # Tuned on BTC/ETH futures Jan-Apr 2026, validated May-Aug 2026 + SOL:
    # cut expectancy from -0.26R to -0.10R and max drawdown from ~75% to
    # ~17%, but 15m never reached positive expectancy - hence the note.
    "15m": EngineParams(
        entry_threshold=55,
        adx_min=25,
        stop_atr_min=2.5,
        stop_atr_max=4.0,
        note=(
            "15m profile: tuned on 2026 data, but even tuned, 15m expectancy "
            "stayed slightly negative in backtests - trade this timeframe with "
            "extra caution or prefer 4h/1d"
        ),
    ),
}


def params_for_timeframe(entry_tf: str) -> EngineParams:
    return PARAMS_BY_TF.get(entry_tf, DEFAULT_PARAMS)


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _fib_info(fib: FibLevels | None) -> FibonacciInfo | None:
    if fib is None:
        return None
    levels = [
        FibLevel(ratio=r, price=p, kind="retracement") for r, p in fib.retracements.items()
    ] + [
        FibLevel(ratio=r, price=p, kind="extension") for r, p in fib.extensions.items()
    ]
    return FibonacciInfo(leg_up=fib.up, leg_high=fib.leg_high, leg_low=fib.leg_low, levels=levels)


class SignalEngine:
    def __init__(self, params: EngineParams | None = None):
        # None = resolve per timeframe at analyze() time, so one engine
        # instance serves every timeframe with its tuned profile.
        self.params = params

    def prepare_entry(self, df: pd.DataFrame) -> pd.DataFrame:
        return add_patterns(enrich(df))

    def prepare_higher(self, df: pd.DataFrame) -> pd.DataFrame:
        return enrich(df)

    def analyze(
        self,
        symbol: str,
        entry_tf: str,
        entry_df: pd.DataFrame,
        context_df: pd.DataFrame,
        bias_df: pd.DataFrame,
        account_size: float = 10_000.0,
        risk_pct: float = 1.0,
        market: str = "spot",
        prepared: bool = False,
        swings: Swings | None = None,
    ) -> Recommendation:
        roles = TF_CONFIG[entry_tf]
        params = self.params or params_for_timeframe(entry_tf)
        if not prepared:
            entry_df = self.prepare_entry(entry_df)
            context_df = self.prepare_higher(context_df) if context_df is not entry_df else entry_df
            bias_df = self.prepare_higher(bias_df) if bias_df is not context_df else context_df
        if swings is None:
            swings = find_swings(entry_df)

        last = entry_df.iloc[-1]
        atr = float(last["atr14"]) if pd.notna(last["atr14"]) else math.nan
        levels = cluster_levels(swings, float(last["close"]), atr)
        fib = compute_fib(swings)

        warnings: list[str] = []

        adx_rule, adx_warnings = R.rule_adx_regime(bias_df, roles.bias, adx_min=params.adx_min)
        warnings.extend(adx_warnings)
        bias_rules = [
            R.rule_ema_stack(bias_df, roles.bias),
            R.rule_macd_momentum(bias_df, roles.bias),
            adx_rule,
        ]
        context_rules = [
            R.rule_price_vs_ema50(context_df, roles.context),
            R.rule_rsi_regime(context_df, roles.context),
        ]
        subtotal = sum(r.contribution for r in bias_rules + context_rules)
        bias_sign = 1 if subtotal >= BIAS_DEADBAND else (-1 if subtotal <= -BIAS_DEADBAND else 0)

        entry_rules = [
            R.rule_rsi_pullback(entry_df, entry_tf, bias_sign),
            R.rule_stoch_cross(entry_df, entry_tf, bias_sign),
            R.rule_sr_proximity(entry_df, entry_tf, bias_sign, levels),
            R.rule_fib_confluence(entry_df, entry_tf, bias_sign, fib),
            R.rule_candle_confirmation(entry_df, entry_tf, bias_sign),
            R.rule_volume_confirmation(entry_df, entry_tf, bias_sign),
        ]

        choppy = bool(adx_warnings)
        outcome = score(
            bias_rules, context_rules, entry_rules, choppy,
            entry_threshold=params.entry_threshold,
            choppy_override=params.choppy_override,
        )
        warnings.extend(outcome.warnings)
        direction = outcome.direction

        entry_zone = stop_loss = None
        targets = position = None
        if direction == "short" and market == "spot":
            # spot cannot short: keep the bearish read visible but plan nothing
            warnings.append(
                "bearish signal on the spot market: spot cannot short - stay out, "
                "or take profit on existing holdings; shorting requires futures"
            )
        elif direction != "no_trade":
            plan, plan_warnings = build_trade_plan(
                entry_df, levels, swings, direction, account_size, risk_pct,
                fib=fib, market=market,
                stop_atr_min=params.stop_atr_min,
                stop_atr_max=params.stop_atr_max,
            )
            if plan is None:
                direction = "no_trade"
                warnings.extend(plan_warnings)
            else:
                entry_zone = plan.entry_zone
                stop_loss = plan.stop_loss
                targets = plan.targets
                position = plan.position
                warnings.extend(plan.warnings)

        if params.note:
            warnings.append(params.note)
        warnings.append(DISCLAIMER)
        return Recommendation(
            symbol=symbol.upper(),
            generated_at=datetime.now(tz=timezone.utc),
            data_as_of=_ms_to_dt(int(last["close_time"])),
            direction=direction,
            confidence=outcome.confidence,
            market=market,  # type: ignore[arg-type]
            entry_timeframe=entry_tf,
            holding_period=roles.holding,
            entry_zone=entry_zone,
            stop_loss=stop_loss,
            take_profits=targets,
            position=position,
            score_total=outcome.total,
            rules=bias_rules + context_rules + entry_rules,
            levels=levels,
            fibonacci=_fib_info(fib),
            warnings=warnings,
        )
