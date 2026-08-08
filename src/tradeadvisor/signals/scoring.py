"""Combine rule results into a direction + confidence."""

from dataclasses import dataclass, field

from tradeadvisor.models import Direction, RuleResult

LONG_THRESHOLD = 30.0
SHORT_THRESHOLD = -30.0
CHOPPY_OVERRIDE = 45.0
DISAGREEMENT_PENALTY = 15


@dataclass
class ScoreOutcome:
    direction: Direction
    confidence: int
    total: float
    warnings: list[str] = field(default_factory=list)


def score(
    bias_rules: list[RuleResult],
    context_rules: list[RuleResult],
    entry_rules: list[RuleResult],
    choppy: bool,
) -> ScoreOutcome:
    bias_total = sum(r.contribution for r in bias_rules)
    entry_total = sum(r.contribution for r in entry_rules)
    total = bias_total + sum(r.contribution for r in context_rules) + entry_total

    warnings: list[str] = []
    if total >= LONG_THRESHOLD:
        direction: Direction = "long"
    elif total <= SHORT_THRESHOLD:
        direction = "short"
    else:
        direction = "no_trade"

    confidence = min(95, round(abs(total)))
    if bias_total * entry_total < 0:
        confidence = max(5, confidence - DISAGREEMENT_PENALTY)
        warnings.append("timeframe disagreement: entry timeframe conflicts with higher-timeframe bias")

    if choppy and direction != "no_trade" and abs(total) < CHOPPY_OVERRIDE:
        warnings.append("forced no-trade: trend strength (ADX) too weak to trust this signal")
        direction = "no_trade"

    return ScoreOutcome(direction=direction, confidence=confidence, total=total, warnings=warnings)
