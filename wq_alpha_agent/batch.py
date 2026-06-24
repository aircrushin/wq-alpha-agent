"""Batch orchestration — the main pipeline for multi-alpha research sessions."""

from __future__ import annotations

import json
import logging
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from .diversity import filter_alpha_configs
from .simulate import (
    AlphaMetrics,
    SimulationSettings,
    fetch_alpha_details,
    poll_simulation,
    simulate,
)
from .submit import submit_with_full_verification

logger = logging.getLogger("wq_alpha_agent.batch")


def utc_timestamp() -> str:
    """ISO 8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, event: Dict[str, Any]) -> None:
    """Append a structured event to a JSONL evidence log file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": utc_timestamp(), **event}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def load_batch_config(path: Path) -> Dict[str, Any]:
    """Load and validate a batch configuration JSON file.

    Expected structure::

        {
            "defaults": {...},
            "alphas": [
                {"name": "...", "expression": "...", ...},
                ...
            ]
        }
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object.")
    if not isinstance(data.get("alphas"), list) or not data["alphas"]:
        raise ValueError("Config must include a non-empty 'alphas' array.")

    data.setdefault("defaults", {})
    return data


def merge_alpha_config(
    defaults: Dict[str, Any],
    alpha: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge an individual alpha config with batch defaults.

    Alpha-level keys override defaults. ``expression`` is required.
    """
    merged = deepcopy(defaults)
    merged.update(alpha)
    if "expression" not in merged:
        raise ValueError(f"Alpha '{alpha.get('name', 'unnamed')}' is missing 'expression'.")
    return merged


def apply_diversity_gate(
    alphas: List[Dict[str, Any]],
    blacklist_path: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Filter alpha configs through the local diversity gate.

    Returns:
        Tuple of (accepted, rejected_with_reasons).
    """
    return filter_alpha_configs(alphas, blacklist_path=blacklist_path)


def check_quality_thresholds(
    metrics: AlphaMetrics,
    min_sharpe: float = 1.25,
    min_fitness: float = 1.0,
    max_turnover: float = 0.7,
    min_ic: float = 0.0,
    required_grade: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """Check if alpha metrics pass configured quality thresholds."""
    return metrics.check_thresholds(
        min_sharpe=min_sharpe,
        min_fitness=min_fitness,
        max_turnover=max_turnover,
        min_ic=min_ic,
        required_grade=required_grade,
    )


def should_auto_submit(
    threshold_passed: bool,
    submission_mode: str = "qualified_only",
) -> bool:
    """Determine whether to attempt auto-submission.

    Args:
        threshold_passed: Whether quality thresholds were met.
        submission_mode: 'always' (submit regardless) or 'qualified_only'
            (only submit if thresholds pass).
    """
    if submission_mode == "always":
        return True
    return threshold_passed


async def run_single_alpha(
    session: requests.Session,
    config: Dict[str, Any],
    settings: Optional[SimulationSettings] = None,
    evidence_path: Optional[Path] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run the full pipeline for a single alpha: simulate → check → optionally submit.

    Args:
        session: Authenticated requests.Session.
        config: Merged alpha config with expression, thresholds, etc.
        settings: SimulationSettings. Built from config if None.
        evidence_path: Optional JSONL evidence log path.
        dry_run: If True, skip submission even if auto_submit is enabled.

    Returns:
        Complete result dictionary with metrics, threshold check, and submission status.
    """
    alpha_name = config.get("name", "unnamed")
    expression = config["expression"]

    if evidence_path:
        append_jsonl(evidence_path, {
            "event": "alpha_start",
            "name": alpha_name,
            "config": config,
        })

    # Build settings from config
    if settings is None:
        settings = SimulationSettings(
            instrument_type=config.get("instrumentType", "EQUITY"),
            region=config.get("region", "USA"),
            universe=config.get("universe", "TOP3000"),
            delay=config.get("delay", 1),
            decay=config.get("decay", 0),
            neutralization=config.get("neutralization", "SUBINDUSTRY"),
            truncation=config.get("truncation", 0.08),
            pasteurization=config.get("pasteurization", "ON"),
            unit_handling=config.get("unitHandling", "VERIFY"),
            nan_handling=config.get("nanHandling", "ON"),
            language=config.get("language", "FASTEXPR"),
        )

    # Step 1: Simulate
    logger.info("Simulating alpha: %s", alpha_name)
    try:
        sim_id = simulate(session, expression, settings, label=alpha_name)
        sim_result = poll_simulation(session, sim_id, label=alpha_name)

        if sim_result["status"] != "COMPLETE":
            return {
                "name": alpha_name,
                "alpha_id": None,
                "error": f"Simulation did not complete: {sim_result['status']}",
                "sim_result": sim_result,
                "submitted": False,
            }

        alpha_id = sim_result["alpha_id"]
        details = fetch_alpha_details(session, alpha_id, label=alpha_name)
        metrics = AlphaMetrics.from_api_response(alpha_id, details)

        if evidence_path:
            append_jsonl(evidence_path, {
                "event": "simulation_complete",
                "name": alpha_name,
                "alpha_id": alpha_id,
                "metrics": {
                    "sharpe": metrics.sharpe,
                    "fitness": metrics.fitness,
                    "turnover": metrics.turnover,
                    "returns": metrics.returns,
                    "drawdown": metrics.drawdown,
                    "grade": metrics.grade,
                },
            })

    except Exception as exc:
        logger.exception("Simulation failed for %s", alpha_name)
        return {
            "name": alpha_name,
            "alpha_id": None,
            "error": str(exc),
            "submitted": False,
        }

    # Step 2: Check thresholds
    threshold_passed, threshold_reasons = check_quality_thresholds(
        metrics,
        min_sharpe=config.get("min_sharpe", 1.25),
        min_fitness=config.get("min_fitness", 1.0),
        max_turnover=config.get("max_turnover", 0.7),
        min_ic=config.get("min_ic", 0.0),
        required_grade=config.get("required_grade"),
    )

    logger.info(
        "%s: Sharpe=%.4f Fitness=%.4f TO=%.4f Grade=%s | Thresholds=%s",
        alpha_name, metrics.sharpe, metrics.fitness, metrics.turnover,
        metrics.grade, "PASS" if threshold_passed else f"FAIL: {'; '.join(threshold_reasons)}",
    )

    # Step 3: Optionally submit
    submitted = False
    submit_result = None
    auto_submit = config.get("auto_submit", False) and not dry_run

    if auto_submit and should_auto_submit(threshold_passed, config.get("submission_mode", "qualified_only")):
        require_sc = config.get("require_self_correlation_pass", True)
        submit_result = submit_with_full_verification(
            session, alpha_id, label=alpha_name,
            require_self_correlation_pass=require_sc,
        )
        submitted = submit_result.get("submitted", False)

        if evidence_path:
            append_jsonl(evidence_path, {
                "event": "submission_result",
                "name": alpha_name,
                "alpha_id": alpha_id,
                "submitted": submitted,
                "result": submit_result,
            })

    result = {
        "name": alpha_name,
        "alpha_id": alpha_id,
        "metrics": {
            "sharpe": metrics.sharpe,
            "fitness": metrics.fitness,
            "turnover": metrics.turnover,
            "returns": metrics.returns,
            "drawdown": metrics.drawdown,
            "margin": metrics.margin,
            "grade": metrics.grade,
            "ic_mean": metrics.ic_mean,
        },
        "threshold_passed": threshold_passed,
        "threshold_reasons": threshold_reasons,
        "platform_failures": metrics.failed_checks(),
        "submitted": submitted,
        "submit_result": submit_result,
    }

    if evidence_path:
        append_jsonl(evidence_path, {"event": "alpha_result", "result": result})

    return result


def run_batch(
    session: requests.Session,
    config: Dict[str, Any],
    evidence_path: Optional[Path] = None,
    dry_run: bool = False,
    limit: Optional[int] = None,
    diversity_blacklist: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Run a full batch pipeline: diversity gate → simulate → threshold → submit.

    This is a synchronous (blocking) pipeline. Each alpha is processed
    sequentially with appropriate rate-limiting.

    Args:
        session: Authenticated requests.Session.
        config: Batch configuration dict.
        evidence_path: Optional JSONL evidence log path.
        dry_run: If True, skip submission.
        limit: Max number of alphas to process (after diversity gate).
        diversity_blacklist: Path to diversity blacklist JSON.

    Returns:
        List of per-alpha result dictionaries.
    """
    defaults = config.get("defaults", {})
    configured_alphas = config["alphas"]

    # Diversity gate
    accepted, rejected = apply_diversity_gate(configured_alphas, diversity_blacklist)
    if evidence_path:
        for rejection in rejected:
            append_jsonl(evidence_path, rejection)

    logger.info(
        "Diversity gate: accepted=%d rejected=%d (from %d total)",
        len(accepted), len(rejected), len(configured_alphas),
    )

    if limit:
        accepted = accepted[:limit]

    # Process each alpha
    results: List[Dict[str, Any]] = []
    total = len(accepted)

    for index, alpha in enumerate(accepted, start=1):
        merged = merge_alpha_config(defaults, alpha)
        logger.info("=== Alpha %d/%d: %s ===", index, total, merged.get("name", "unnamed"))

        try:
            import asyncio
            result = asyncio.run(
                run_single_alpha(session, merged, evidence_path=evidence_path, dry_run=dry_run)
            )
        except Exception as exc:
            logger.exception("Pipeline failure for %s", merged.get("name", "unnamed"))
            result = {
                "name": merged.get("name", f"alpha_{index}"),
                "alpha_id": None,
                "error": str(exc),
                "submitted": False,
            }

        results.append(result)

        # Rate limiting
        time.sleep(2)

    # Summary
    submitted_count = sum(1 for r in results if r.get("submitted"))
    logger.info("Batch complete: %d processed, %d submitted", len(results), submitted_count)

    if evidence_path:
        append_jsonl(evidence_path, {
            "event": "batch_summary",
            "total": len(results),
            "submitted": submitted_count,
            "rejected_by_diversity": len(rejected),
            "results": results,
        })

    return results


def print_batch_summary(results: List[Dict[str, Any]]) -> None:
    """Print a formatted batch summary to stdout."""
    print("\n" + "=" * 72)
    print("  BATCH SUMMARY")
    print("=" * 72)

    for r in results:
        m = r.get("metrics", {})
        status = "SUBMITTED" if r.get("submitted") else "SIMULATED"
        error = r.get("error")
        if error:
            status = f"ERROR: {error[:80]}"

        print(
            f"  {r['name']}: {status} | id={r.get('alpha_id', 'N/A')} | "
            f"Grade={m.get('grade', '?')} | Sharpe={m.get('sharpe', 0):.2f} | "
            f"Fitness={m.get('fitness', 0):.2f} | TO={m.get('turnover', 0):.3f}"
        )

        if r.get("threshold_reasons"):
            print(f"    thresholds: {'; '.join(r['threshold_reasons'])}")

    submitted = sum(1 for r in results if r.get("submitted"))
    print(f"\n  Total: {len(results)} | Submitted: {submitted}")
    print("=" * 72)
