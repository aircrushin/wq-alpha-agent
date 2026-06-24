#!/usr/bin/env python3
"""Search and discover WorldQuant BRAIN data fields.

Usage:
    python scripts/search_fields.py --search "operating_income"
    python scripts/search_fields.py --category fundamental --min-alpha-count 10
    python scripts/search_fields.py --fetch-all --save references/fields_usa_top3000_d1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wq_alpha_agent.auth import create_session, logout
from wq_alpha_agent.fields import (
    fetch_all_fields,
    load_local_fields,
    search_fields_api,
    search_local_fields,
    field_summary,
)


def main():
    parser = argparse.ArgumentParser(
        description="Search WorldQuant BRAIN data fields."
    )
    parser.add_argument("--search", "-s", default="", help="Keyword search term.")
    parser.add_argument("--category", "-c", default="", help="Category filter (fundamental, analyst, pv, news, option).")
    parser.add_argument("--dataset", default="", help="Dataset ID filter.")
    parser.add_argument("--min-coverage", type=float, default=0.0, help="Minimum data coverage (0-1).")
    parser.add_argument("--min-alpha-count", type=int, default=0, help="Minimum existing alpha count.")
    parser.add_argument("--sort-by", default="alphaCount", help="Sort field.")
    parser.add_argument("--limit", type=int, default=50, help="Max results.")
    parser.add_argument("--local-only", action="store_true", help="Search local cache only (no API call).")
    parser.add_argument("--fetch-all", action="store_true", help="Fetch all fields from API and cache locally.")
    parser.add_argument("--save", default=None, help="Save fetched fields to JSON file.")
    parser.add_argument("--summary", action="store_true", help="Show category/dataset summary.")
    parser.add_argument("--fields-path", default=None, help="Path to local fields JSON cache.")
    args = parser.parse_args()

    # Local-only search
    if args.local_only or (args.search or args.category) and not args.fetch_all:
        try:
            fields = load_local_fields(
                Path(args.fields_path) if args.fields_path else None
            )
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
            print("Use --fetch-all to download fields first, or provide --fields-path.")
            return 1

        results = search_local_fields(
            fields,
            keyword=args.search,
            category=args.category,
            dataset_id=args.dataset,
            min_coverage=args.min_coverage,
            min_alpha_count=args.min_alpha_count,
            sort_by=args.sort_by,
            limit=args.limit,
        )

        if args.summary:
            summary = field_summary(fields)
            print(json.dumps(summary, indent=2))
            return 0

        print(f"Found {len(results)} fields:")
        for f in results:
            cat = f.get("category", {}).get("name", "?")
            ds = f.get("dataset", {}).get("name", "?")
            cov = f.get("coverage", 0)
            ac = f.get("alphaCount", 0)
            desc = (f.get("description") or "")[:80]
            print(f"  {f['id']:<50} | {cat:<15} | cov={cov:.3f} | alphas={ac:>4} | {desc}")
        return 0

    # API-based search or fetch-all
    try:
        session = create_session()
    except Exception as exc:
        print(f"Authentication failed: {exc}")
        return 1

    try:
        if args.fetch_all:
            print("Fetching all fields (this may take a while)...")
            fields = fetch_all_fields(session)
            print(f"Fetched {len(fields)} fields.")

            if args.save:
                save_path = Path(args.save)
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_text(json.dumps(fields, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"Saved to {save_path}")

            if args.summary:
                summary = field_summary(fields)
                print(json.dumps(summary, indent=2))
        else:
            data = search_fields_api(
                session,
                search=args.search,
                category=args.category,
                limit=args.limit,
            )
            results = data.get("results", [])
            print(f"API returned {len(results)} results (total: {data.get('count', '?')}):")
            for f in results:
                print(f"  {f['id']:<50} | {f.get('category', {}).get('name', '?')}")
    finally:
        try:
            logout(session)
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
