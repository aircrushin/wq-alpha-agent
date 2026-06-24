#!/usr/bin/env python3
"""Self-evolution script — learn from BRAIN alpha data.

Fetches all alphas, compares with local snapshot, computes daily-return
correlations, and generates Markdown lesson snippets.

Usage:
    python scripts/evolve_skill.py              # Preview changes
    python scripts/evolve_skill.py --apply      # Apply to alpha_db.json
    python scripts/evolve_skill.py --output lessons.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wq_alpha_agent.auth import create_session, logout
from wq_alpha_agent.evolve import run_evolution

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "alpha_db.json"


def main():
    parser = argparse.ArgumentParser(
        description="Evolve the WQ Alpha Agent skill from empirical BRAIN data."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to alpha_db.json (default: preview only).",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="Path to alpha_db.json snapshot file.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write the generated Markdown snippet to a file.",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)

    try:
        session = create_session()
    except Exception as exc:
        print(f"Authentication failed: {exc}")
        return 1

    try:
        snippet = run_evolution(session, db_path, apply=args.apply)
    finally:
        try:
            logout(session)
        except Exception:
            pass

    if not snippet.strip():
        print("\nNo new empirical findings to record.")
        return 0

    print("\n" + "=" * 60)
    if args.apply:
        print("APPLIED — Lessons incorporated into alpha_db.json")
    else:
        print("PREVIEW — Use --apply to commit changes")
    print("=" * 60)
    print(snippet)
    print("=" * 60)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(snippet, encoding="utf-8")
        print(f"\nSnippet written to: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
