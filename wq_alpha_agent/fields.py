"""Data field discovery and validation for WorldQuant BRAIN."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("wq_alpha_agent.fields")

API_BASE = "https://api.worldquantbrain.com"

# Default: local field cache for USA TOP3000 delay=1
DEFAULT_FIELDS_PATH = Path(__file__).resolve().parent.parent / "references" / "fields_usa_top3000_d1.json"


def search_fields_api(
    session: requests.Session,
    search: str = "",
    dataset_id: str = "",
    category: str = "",
    instrument_type: str = "EQUITY",
    region: str = "USA",
    universe: str = "TOP3000",
    delay: int = 1,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Search BRAIN data fields via the API.

    Args:
        session: Authenticated requests.Session.
        search: Free-text search term.
        dataset_id: Filter by dataset ID.
        category: Filter by category (e.g., 'fundamental', 'analyst', 'pv').
        instrument_type: Instrument type.
        region: Region code.
        universe: Universe code.
        delay: Data delay.
        limit: Results per page.
        offset: Pagination offset.

    Returns:
        API response dictionary with ``results`` array.
    """
    params = {
        "instrumentType": instrument_type,
        "region": region,
        "universe": universe,
        "delay": delay,
        "limit": limit,
        "offset": offset,
    }
    if search:
        params["search"] = search
    if dataset_id:
        params["dataset.id"] = dataset_id
    if category:
        params["category"] = category

    resp = session.get(f"{API_BASE}/data-fields", params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"Field search failed: {resp.status_code} {resp.text[:500]}")

    return resp.json()


def fetch_all_fields(
    session: requests.Session,
    **filters,
) -> List[Dict[str, Any]]:
    """Fetch ALL available data fields with pagination.

    Warning: This can be slow (4000+ fields). Cache the result locally.
    """
    all_fields = []
    offset = 0
    limit = 100

    while True:
        data = search_fields_api(session, limit=limit, offset=offset, **filters)
        results = data.get("results", [])
        if not results:
            break
        all_fields.extend(results)
        if len(results) < limit:
            break
        offset += limit
        time.sleep(0.3)  # rate limit

    return all_fields


def load_local_fields(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load locally cached field metadata.

    Args:
        path: Path to field JSON file. Defaults to USA TOP3000 delay=1 cache.

    Returns:
        List of field metadata dictionaries.
    """
    path = path or DEFAULT_FIELDS_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Local field cache not found at {path}. "
            "Run search_fields.py to download fields first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def search_local_fields(
    fields: List[Dict[str, Any]],
    keyword: str = "",
    category: str = "",
    dataset_id: str = "",
    min_coverage: float = 0.0,
    min_alpha_count: int = 0,
    sort_by: str = "alphaCount",
    reverse: bool = True,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Search and filter locally cached fields.

    Args:
        fields: List of field metadata dicts.
        keyword: Case-insensitive keyword search in id and description.
        category: Filter by category ID (e.g., 'fundamental', 'pv').
        dataset_id: Filter by dataset ID.
        min_coverage: Minimum coverage fraction (0-1).
        min_alpha_count: Minimum number of existing alphas using this field.
        sort_by: Field to sort by ('alphaCount', 'coverage', 'id').
        reverse: Sort descending.
        limit: Max results.

    Returns:
        Filtered and sorted field list.
    """
    keyword_lower = keyword.lower()

    filtered = []
    for f in fields:
        if category and f.get("category", {}).get("id") != category:
            continue
        if dataset_id and f.get("dataset", {}).get("id") != dataset_id:
            continue
        if min_coverage and (f.get("coverage") or 0) < min_coverage:
            continue
        if min_alpha_count and (f.get("alphaCount") or 0) < min_alpha_count:
            continue
        if keyword_lower:
            fid = f.get("id", "").lower()
            desc = (f.get("description") or "").lower()
            if keyword_lower not in fid and keyword_lower not in desc:
                continue
        filtered.append(f)

    filtered.sort(key=lambda f: f.get(sort_by, 0) or 0, reverse=reverse)
    return filtered[:limit]


def field_summary(fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate summary statistics for a field list."""
    from collections import Counter

    categories = Counter(
        f.get("category", {}).get("name", "unknown") for f in fields
    )
    datasets = Counter(
        f.get("dataset", {}).get("name", "unknown") for f in fields
    )
    total = len(fields)
    with_coverage = sum(1 for f in fields if (f.get("coverage") or 0) > 0)

    return {
        "total_fields": total,
        "fields_with_coverage": with_coverage,
        "categories": dict(categories.most_common()),
        "datasets": dict(datasets.most_common(10)),
    }
