"""Simulation engine for WorldQuant BRAIN alpha backtesting.

Handles: building simulation payloads, submitting simulations, polling for
completion, retrying on transient errors, and extracting metrics.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("wq_alpha_agent.simulate")

API_BASE = "https://api.worldquantbrain.com"

# Retryable error substrings for transient network issues
RETRYABLE_ERRORS = (
    "ProxyError",
    "RemoteDisconnected",
    "Max retries exceeded",
    "Connection aborted",
    "ConnectionError",
    "Timeout",
)


@dataclass
class SimulationSettings:
    """Standard BRAIN simulation settings."""

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
    max_trade: str = "OFF"
    max_position: str = "OFF"

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
        }


@dataclass
class AlphaMetrics:
    """Extracted IS/OS metrics from a completed simulation."""

    alpha_id: str
    status: str = "UNKNOWN"
    grade: Optional[str] = None
    sharpe: float = 0.0
    fitness: float = 0.0
    turnover: float = 0.0
    returns: float = 0.0
    drawdown: float = 0.0
    margin: float = 0.0
    ic_mean: float = 0.0
    os_sharpe: float = 0.0
    os_fitness: float = 0.0
    os_turnover: float = 0.0
    self_correlation: Optional[float] = None
    checks: List[Dict[str, Any]] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, alpha_id: str, data: Dict[str, Any]) -> "AlphaMetrics":
        """Parse an alpha detail API response into AlphaMetrics."""
        is_metrics = data.get("is") or {}
        os_metrics = data.get("os") or {}
        checks = is_metrics.get("checks") or []
        ic_data = is_metrics.get("ic") or {}

        def _safe_float(value: Any) -> float:
            if value is None:
                return 0.0
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        ic_mean = _safe_float(ic_data.get("mean")) if isinstance(ic_data, dict) else 0.0

        return cls(
            alpha_id=alpha_id,
            status=data.get("status", "UNKNOWN"),
            grade=data.get("grade"),
            sharpe=_safe_float(is_metrics.get("sharpe")),
            fitness=_safe_float(is_metrics.get("fitness")),
            turnover=_safe_float(is_metrics.get("turnover")),
            returns=_safe_float(is_metrics.get("returns")),
            drawdown=_safe_float(is_metrics.get("drawdown")),
            margin=_safe_float(is_metrics.get("margin")),
            ic_mean=_safe_float(ic_mean),
            os_sharpe=_safe_float(os_metrics.get("sharpe")),
            os_fitness=_safe_float(os_metrics.get("fitness")),
            os_turnover=_safe_float(os_metrics.get("turnover")),
            self_correlation=_safe_float(is_metrics.get("selfCorrelation")),
            checks=checks,
            raw_data=data,
        )

    def check_thresholds(
        self,
        min_sharpe: float = 1.25,
        min_fitness: float = 1.0,
        max_turnover: float = 0.7,
        min_ic: float = 0.0,
        required_grade: Optional[str] = None,
    ) -> tuple[bool, list[str]]:
        """Check if metrics pass quality thresholds.

        Returns:
            Tuple of (passed, list_of_failure_reasons).
        """
        reasons: list[str] = []

        if required_grade and self.grade != required_grade:
            reasons.append(f"Grade {self.grade} != {required_grade}")
        if self.sharpe < min_sharpe:
            reasons.append(f"Sharpe {self.sharpe:.4f} < {min_sharpe}")
        if self.fitness < min_fitness:
            reasons.append(f"Fitness {self.fitness:.4f} < {min_fitness}")
        if self.turnover > max_turnover:
            reasons.append(f"Turnover {self.turnover:.4f} > {max_turnover}")
        if abs(self.ic_mean) < min_ic:
            reasons.append(f"|IC Mean| {abs(self.ic_mean):.4f} < {min_ic}")

        return not reasons, reasons

    def failed_checks(self) -> List[Dict[str, Any]]:
        """Return list of failed platform checks."""
        return [c for c in self.checks if c.get("result") == "FAIL"]


def build_payload(
    expression: str,
    settings: Optional[SimulationSettings] = None,
    **overrides,
) -> Dict[str, Any]:
    """Build a BRAIN simulation API payload.

    Args:
        expression: The FastExpr alpha expression.
        settings: SimulationSettings object. Uses defaults if None.
        **overrides: Override any individual setting (e.g., decay=4).

    Returns:
        API payload dictionary.
    """
    if settings is None:
        settings = SimulationSettings()

    payload_settings = settings.to_dict()

    # Apply overrides
    override_map = {
        "instrument_type": "instrumentType",
        "region": "region",
        "universe": "universe",
        "delay": "delay",
        "decay": "decay",
        "neutralization": "neutralization",
        "truncation": "truncation",
        "pasteurization": "pasteurization",
        "unit_handling": "unitHandling",
        "nan_handling": "nanHandling",
        "language": "language",
        "visualization": "visualization",
    }
    for key, value in overrides.items():
        api_key = override_map.get(key, key)
        if api_key in payload_settings:
            payload_settings[api_key] = value

    return {
        "type": "REGULAR",
        "settings": payload_settings,
        "regular": expression,
    }


def simulate(
    session: requests.Session,
    expression: str,
    settings: Optional[SimulationSettings] = None,
    label: str = "",
    **overrides,
) -> str:
    """Submit a simulation and return the simulation ID.

    Args:
        session: Authenticated requests.Session.
        expression: FastExpr alpha expression.
        settings: Simulation settings.
        label: Human-readable label for logging.
        **overrides: Setting overrides.

    Returns:
        Simulation job ID from the Location header.

    Raises:
        RuntimeError: If simulation submission fails.
    """
    payload = build_payload(expression, settings, **overrides)
    prefix = f"[{label}] " if label else ""

    resp = session.post(f"{API_BASE}/simulations", json=payload)
    if resp.status_code != 201:
        raise RuntimeError(
            f"{prefix}Simulation submission failed: {resp.status_code} {resp.text[:500]}"
        )

    location = resp.headers.get("Location", "")
    sim_id = location.rstrip("/").split("/")[-1]
    logger.info("%sSimulation submitted: %s", prefix, sim_id)
    return sim_id


def poll_simulation(
    session: requests.Session,
    sim_id: str,
    label: str = "",
    poll_interval: int = 8,
    timeout: int = 600,
) -> Dict[str, Any]:
    """Poll a simulation until completion or timeout.

    Args:
        session: Authenticated requests.Session.
        sim_id: Simulation job ID.
        label: Label for logging.
        poll_interval: Seconds between polls.
        timeout: Maximum wait time in seconds.

    Returns:
        Simulation result dictionary with keys: status, alpha_id, sim_data.

    Raises:
        RuntimeError: On timeout or unrecoverable error.
    """
    prefix = f"[{label}] " if label else ""
    start = time.time()

    while time.time() - start < timeout:
        resp = session.get(f"{API_BASE}/simulations/{sim_id}")
        if resp.status_code != 200:
            logger.warning("%sPoll returned %d, retrying...", prefix, resp.status_code)
            time.sleep(poll_interval)
            continue

        data = resp.json()
        status = data.get("status", "UNKNOWN")
        logger.info("%sSimulation status: %s", prefix, status)

        if status == "COMPLETE":
            alpha_id = data.get("alpha")
            if not alpha_id:
                raise RuntimeError(f"{prefix}Simulation completed but no alpha_id in response: {data}")
            return {"status": "COMPLETE", "alpha_id": alpha_id, "sim_data": data}

        if status in ("ERROR", "FAILED"):
            return {"status": "ERROR", "sim_data": data}

        time.sleep(poll_interval)

    raise RuntimeError(f"{prefix}Simulation {sim_id} timed out after {timeout}s")


def fetch_alpha_details(
    session: requests.Session,
    alpha_id: str,
    label: str = "",
    max_attempts: int = 5,
    retry_delay: int = 8,
) -> Dict[str, Any]:
    """Fetch alpha details after simulation completes.

    BRAIN sometimes returns an alpha ID before the detail endpoint is ready,
    so this retries with backoff.

    Args:
        session: Authenticated requests.Session.
        alpha_id: Alpha ID.
        label: Label for logging.
        max_attempts: Maximum fetch attempts.
        retry_delay: Seconds between attempts.

    Returns:
        Alpha detail dictionary.

    Raises:
        RuntimeError: If details cannot be fetched after all attempts.
    """
    prefix = f"[{label}] " if label else ""

    for attempt in range(1, max_attempts + 1):
        resp = session.get(f"{API_BASE}/alphas/{alpha_id}")
        if resp.status_code == 200:
            return resp.json()

        logger.warning(
            "%sAlpha details attempt %d/%d returned %d. Sleeping %ds...",
            prefix, attempt, max_attempts, resp.status_code, retry_delay,
        )
        time.sleep(retry_delay)

    raise RuntimeError(f"{prefix}Failed to fetch alpha {alpha_id} details after {max_attempts} attempts")


def simulate_and_wait(
    session: requests.Session,
    expression: str,
    settings: Optional[SimulationSettings] = None,
    label: str = "",
    **overrides,
) -> AlphaMetrics:
    """Submit a simulation and wait for results.

    Convenience function that chains simulate → poll → fetch details → parse metrics.

    Args:
        session: Authenticated requests.Session.
        expression: FastExpr alpha expression.
        settings: Simulation settings.
        label: Label for logging.
        **overrides: Setting overrides.

    Returns:
        AlphaMetrics with full IS/OS data.
    """
    sim_id = simulate(session, expression, settings, label, **overrides)
    result = poll_simulation(session, sim_id, label)

    if result["status"] != "COMPLETE":
        raise RuntimeError(f"Simulation {sim_id} did not complete: {result['status']}")

    alpha_id = result["alpha_id"]
    details = fetch_alpha_details(session, alpha_id, label)
    return AlphaMetrics.from_api_response(alpha_id, details)


def validate_field(
    session: requests.Session,
    field_name: str,
    settings: Optional[SimulationSettings] = None,
    label: str = "",
) -> bool:
    """Quick-check if a data field exists by simulating ``rank(field_name)``.

    Args:
        session: Authenticated requests.Session.
        field_name: BRAIN data field ID to validate.
        settings: Simulation settings.
        label: Label for logging.

    Returns:
        True if the field is valid (simulation returns 201).
    """
    try:
        sim_id = simulate(session, f"rank({field_name})", settings, label)
        return True
    except RuntimeError:
        return False
