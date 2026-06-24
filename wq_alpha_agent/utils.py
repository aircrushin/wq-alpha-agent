"""Shared utilities: logging setup, JSONL helpers, rate limiters."""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def setup_logger(
    name: str = "wq_alpha_agent",
    level: int = logging.INFO,
    log_dir: Optional[Path] = None,
) -> logging.Logger:
    """Create a logger with console and optional file output.

    Args:
        name: Logger name.
        level: Log level.
        log_dir: Directory for log files. If None, no file logging.

    Returns:
        Configured logger.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # File handler
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"wq_agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
        logger.info("Log file: %s", log_path)

    return logger


def utc_timestamp() -> str:
    """ISO 8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def write_jsonl(path: Path, event: Dict[str, Any]) -> None:
    """Append a structured event to a JSONL evidence log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": utc_timestamp(), **event}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def rate_limited_sleep(seconds: float = 2.0) -> None:
    """Sleep to respect BRAIN API rate limits."""
    time.sleep(seconds)


def safe_float(value: Any) -> float:
    """Safely convert a value to float, returning 0.0 on failure."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def safe_int(value: Any) -> int:
    """Safely convert a value to int, returning 0 on failure."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def truncate_expression(expr: str, max_len: int = 120) -> str:
    """Truncate a long expression for display."""
    expr = expr.replace("\n", " ").strip()
    if len(expr) > max_len:
        return expr[: max_len - 3] + "..."
    return expr


def format_metrics_table(metrics_list: list[dict]) -> str:
    """Format a list of metric dicts as a readable table."""
    if not metrics_list:
        return "No metrics to display."

    header = f"{'Name':<30} {'Sharpe':>8} {'Fitness':>8} {'Turnover':>9} {'Grade':>8}"
    sep = "-" * len(header)
    rows = [header, sep]

    for m in metrics_list:
        rows.append(
            f"{m.get('name', '?')[:30]:<30} "
            f"{m.get('sharpe', 0):>8.2f} "
            f"{m.get('fitness', 0):>8.2f} "
            f"{m.get('turnover', 0):>9.4f} "
            f"{str(m.get('grade', '?')):>8}"
        )

    return "\n".join(rows)
