"""Configuration helpers for alpha batch research."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BatchDefaults:
    """Default settings for a batch of alphas.

    Individual alpha entries can override any of these fields.
    """

    instrument_type: str = "EQUITY"
    region: str = "USA"
    universe: str = "TOP3000"
    delay: int = 1
    decay: int = 0
    neutralization: str = "SUBINDUSTRY"
    truncation: float = 0.08
    pasteurization: str = "ON"
    unit_handling: str = "VERIFY"
    nan_handling: str = "ON"
    language: str = "FASTEXPR"
    visualization: bool = False

    # Submission control
    auto_submit: bool = False
    submission_mode: str = "qualified_only"  # "always" or "qualified_only"
    require_self_correlation_pass: bool = True

    # Quality thresholds
    min_sharpe: float = 1.25
    min_fitness: float = 1.0
    max_turnover: float = 0.7
    min_ic: float = 0.0
    required_grade: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instrumentType": self.instrument_type,
            "region": self.region,
            "universe": self.universe,
            "delay": self.delay,
            "decay": self.decay,
            "neutralization": self.neutralization,
            "truncation": self.truncation,
            "pasteurization": self.pasteurization,
            "unitHandling": self.unit_handling,
            "nanHandling": self.nan_handling,
            "language": self.language,
            "visualization": self.visualization,
            "auto_submit": self.auto_submit,
            "submission_mode": self.submission_mode,
            "require_self_correlation_pass": self.require_self_correlation_pass,
            "min_sharpe": self.min_sharpe,
            "min_fitness": self.min_fitness,
            "max_turnover": self.max_turnover,
            "min_ic": self.min_ic,
            "required_grade": self.required_grade,
        }


# Recommended defaults by strategy type
STRATEGY_DEFAULTS = {
    "fundamental_quality": BatchDefaults(
        decay=0,
        neutralization="SUBINDUSTRY",
        min_sharpe=1.25,
        min_fitness=1.0,
        max_turnover=0.15,
    ),
    "analyst_expectation": BatchDefaults(
        decay=4,
        neutralization="INDUSTRY",
        min_sharpe=1.25,
        min_fitness=1.0,
        max_turnover=0.20,
    ),
    "technical_reversal": BatchDefaults(
        decay=12,
        neutralization="INDUSTRY",
        min_sharpe=1.25,
        min_fitness=1.0,
        max_turnover=0.35,
    ),
    "hybrid": BatchDefaults(
        decay=4,
        neutralization="INDUSTRY",
        min_sharpe=1.25,
        min_fitness=1.1,
        max_turnover=0.25,
    ),
    "sentiment": BatchDefaults(
        decay=4,
        neutralization="INDUSTRY",
        truncation=0.05,
        min_sharpe=1.3,
        min_fitness=1.0,
        max_turnover=0.30,
    ),
    "market_neutral": BatchDefaults(
        decay=0,
        neutralization="MARKET",
        min_sharpe=1.5,
        min_fitness=1.1,
        max_turnover=0.10,
    ),
}
