#!/usr/bin/env python3
"""Verify the status of submitted alphas on WorldQuant BRAIN.

Usage:
    python scripts/verify_status.py MPpxAmgL KPbLeq3p
    python scripts/verify_status.py --input ids.txt
    python scripts/verify_status.py --all --active-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wq_alpha_agent.auth import create_session, logout
from wq_alpha_agent.simulate import fetch_alpha_details


def main():
    parser = argparse.ArgumentParser(
        description="Verify WorldQuant BRAIN alpha submission status."
    )
    parser.add_argument(
        "alpha_ids", nargs="*",
        help="Alpha IDs to verify.",
    )
    parser.add_argument(
        "--input", "-i",
        default=None,
        help="File with one alpha ID per line.",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Save verification results to JSON file.",
    )
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Only show ACTIVE alphas.",
    )
    args = parser.parse_args()

    alpha_ids: List[str] = list(args.alpha_ids)

    if args.input:
        input_path = Path(args.input)
        if input_path.exists():
            alpha_ids.extend(
                line.strip() for line in input_path.read_text().splitlines()
                if line.strip() and not line.strip().startswith("#")
            )

    if not alpha_ids:
        print("No alpha IDs provided. Pass IDs as arguments or use --input.")
        return 1

    try:
        session = create_session()
    except Exception as exc:
        print(f"Authentication failed: {exc}")
        return 1

    results = []
    try:
        for alpha_id in alpha_ids:
            try:
                details = fetch_alpha_details(session, alpha_id, max_attempts=3, retry_delay=4)
                is_metrics = details.get("is") or {}
                os_metrics = details.get("os") or {}
                checks = is_metrics.get("checks") or []

                result = {
                    "alpha_id": alpha_id,
                    "status": details.get("status"),
                    "grade": details.get("grade"),
                    "sharpe": is_metrics.get("sharpe"),
                    "fitness": is_metrics.get("fitness"),
                    "turnover": is_metrics.get("turnover"),
                    "returns": is_metrics.get("returns"),
                    "drawdown": is_metrics.get("drawdown"),
                    "margin": is_metrics.get("margin"),
                    "self_correlation": is_metrics.get("selfCorrelation"),
                    "os_sharpe": os_metrics.get("sharpe"),
                    "os_fitness": os_metrics.get("fitness"),
                    "checks": [
                        {"name": c.get("name"), "result": c.get("result"),
                         "value": c.get("value"), "limit": c.get("limit")}
                        for c in checks
                    ],
                }

                if not args.active_only or result["status"] == "ACTIVE":
                    results.append(result)
                    status_icon = "✅" if result["status"] == "ACTIVE" else "⏳"
                    print(
                        f"{status_icon} {alpha_id}: status={result['status']}, "
                        f"grade={result['grade']}, Sharpe={result['sharpe']}, "
                        f"Fitness={result['fitness']}, TO={result['turnover']}"
                    )

            except Exception as exc:
                print(f"❌ {alpha_id}: ERROR - {exc}")
                results.append({"alpha_id": alpha_id, "error": str(exc)})

    finally:
        try:
            logout(session)
        except Exception:
            pass

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nResults saved to: {output_path}")

    # Summary
    active = [r for r in results if r.get("status") == "ACTIVE"]
    unsubmitted = [r for r in results if r.get("status") == "UNSUBMITTED"]
    errors = [r for r in results if "error" in r]
    print(f"\nSummary: {len(results)} checked | {len(active)} ACTIVE | {len(unsubmitted)} UNSUBMITTED | {len(errors)} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
