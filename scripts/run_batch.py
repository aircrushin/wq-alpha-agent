#!/usr/bin/env python3
"""Run a batch configuration through the full alpha research pipeline.

Usage:
    python scripts/run_batch.py --config examples/example_quality.json
    python scripts/run_batch.py --config my_batch.json --dry-run --limit 3
    python scripts/run_batch.py --config my_batch.json --diversity-check-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wq_alpha_agent.auth import create_session, logout
from wq_alpha_agent.batch import (
    apply_diversity_gate,
    load_batch_config,
    print_batch_summary,
    run_batch,
)
from wq_alpha_agent.utils import setup_logger, write_jsonl


def main():
    parser = argparse.ArgumentParser(
        description="Run a WorldQuant alpha batch research session."
    )
    parser.add_argument(
        "--config", "-c",
        required=True,
        help="Path to batch config JSON file.",
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=None,
        help="Process only the first N alphas (after diversity gate).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate but never auto-submit.",
    )
    parser.add_argument(
        "--diversity-check-only",
        action="store_true",
        help="Only run the diversity gate; do not authenticate or simulate.",
    )
    parser.add_argument(
        "--blacklist",
        default=None,
        help="Path to diversity blacklist JSON.",
    )
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="Directory for log and evidence files.",
    )
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    logger = setup_logger("wq_batch", log_dir=log_dir)
    evidence_path = log_dir / f"batch_evidence_{Path(args.config).stem}.jsonl"

    # Load config
    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        return 1

    try:
        config = load_batch_config(config_path)
    except Exception as exc:
        logger.error("Failed to load config: %s", exc)
        return 1

    logger.info("Loaded %d alpha definitions from %s", len(config["alphas"]), config_path)

    # Diversity check only
    if args.diversity_check_only:
        blacklist_path = Path(args.blacklist) if args.blacklist else None
        accepted, rejected = apply_diversity_gate(config["alphas"], blacklist_path)
        print(f"\nDiversity Gate: accepted={len(accepted)}, rejected={len(rejected)}")
        for r in rejected:
            reason = r["reasons"][0]
            print(f"  REJECTED {r['name']}: {reason['rule']} vs {reason['active_alpha_id']}")
        for a in accepted:
            print(f"  ACCEPTED {a.get('name', 'unnamed')}")
        return 0

    # Full pipeline
    dry_run = args.dry_run
    blacklist_path = Path(args.blacklist) if args.blacklist else None

    try:
        session = create_session()
    except Exception as exc:
        logger.error("Authentication failed: %s", exc)
        return 1

    try:
        results = run_batch(
            session,
            config,
            evidence_path=evidence_path,
            dry_run=dry_run,
            limit=args.limit,
            diversity_blacklist=blacklist_path,
        )
    finally:
        try:
            logout(session)
        except Exception:
            pass

    print_batch_summary(results)

    submitted = sum(1 for r in results if r.get("submitted"))
    logger.info("Done: %d processed, %d submitted", len(results), submitted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
