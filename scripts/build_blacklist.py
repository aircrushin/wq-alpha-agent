#!/usr/bin/env python3
"""Build or update the diversity blacklist from ACTIVE alpha fingerprints.

Usage:
    python scripts/build_blacklist.py --evidence active_verification.json
    python scripts/build_blacklist.py --from-braindb alpha_db.json
    python scripts/build_blacklist.py --self-correlation-max 0.6
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wq_alpha_agent.diversity import build_blacklist_from_active


def main():
    parser = argparse.ArgumentParser(
        description="Build diversity blacklist from ACTIVE alpha fingerprints."
    )
    parser.add_argument(
        "--evidence",
        default=None,
        help="Path to verification evidence JSON (list of alpha dicts).",
    )
    parser.add_argument(
        "--from-braindb",
        default=None,
        help="Path to alpha_db.json from evolve_skill.py.",
    )
    parser.add_argument(
        "--output", "-o",
        default="alpha_diversity_blacklist.json",
        help="Output path for the blacklist JSON.",
    )
    parser.add_argument(
        "--self-correlation-max",
        type=float,
        default=0.7,
        help="Maximum self-correlation for protected alphas.",
    )
    args = parser.parse_args()

    active_alphas = []

    if args.evidence:
        evidence_path = Path(args.evidence)
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
        # Support both list and wrapped object
        if isinstance(data, list):
            active_alphas = data
        elif isinstance(data, dict):
            active_alphas = data.get("alphas", data.get("protected_alphas", []))
        else:
            active_alphas = []

    elif args.from_braindb:
        db_path = Path(args.from_braindb)
        db = json.loads(db_path.read_text(encoding="utf-8"))
        for aid, record in db.get("alphas", {}).items():
            if record.get("status") == "ACTIVE":
                active_alphas.append({
                    "alpha_id": aid,
                    "name": aid,
                    "status": "ACTIVE",
                    "expression": record.get("expression", ""),
                    "metrics": record,
                    "settings": record.get("settings", {}),
                })

    else:
        print("Provide --evidence or --from-braindb to specify the alpha source.")
        return 1

    if not active_alphas:
        print("No ACTIVE alphas found in the source data.")
        return 1

    blacklist = build_blacklist_from_active(
        active_alphas,
        self_correlation_max=args.self_correlation_max,
    )

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(blacklist, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Blacklist written: {output_path}")
    print(f"  Protected alphas: {len(blacklist['protected_alphas'])}")
    print(f"  Self-correlation max: {args.self_correlation_max}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
