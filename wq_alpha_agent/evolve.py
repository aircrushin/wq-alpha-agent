"""Self-evolution engine — tracks alphas, computes correlations, generates lessons.

Turns each BRAIN interaction into reusable research rules by:
1. Fetching all user alphas from BRAIN
2. Comparing with a local snapshot (alpha_db.json)
3. Computing daily-return correlations against ACTIVE alphas
4. Generating human-readable lessons
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .auth import create_session
from .diversity import classify_family as _classify_family
from .simulate import API_BASE as _API_BASE

logger = logging.getLogger("wq_alpha_agent.evolve")


# ---------------------------------------------------------------------------
# PnL fetching
# ---------------------------------------------------------------------------

def fetch_pnl(session, alpha_id: str) -> List[float]:
    """Fetch cumulative PnL recordset for an alpha.

    Returns:
        List of cumulative PnL values (floats). Empty list on failure.
    """
    try:
        resp = session.get(f"{_API_BASE}/alphas/{alpha_id}/recordsets/pnl", timeout=(10, 60))
    except Exception:
        return []

    if resp.status_code != 200 or not resp.text.strip():
        return []

    try:
        data = resp.json()
    except Exception:
        return []

    schema = data.get("schema", {})
    props = schema.get("properties", [])

    if isinstance(props, list):
        date_idx = next((i for i, p in enumerate(props) if p.get("name", "").lower() == "date"), 0)
        pnl_idx = next(
            (i for i, p in enumerate(props)
             if p.get("name", "").lower() in ("pnl", "cum_pnl", "returns", "ret")),
            1,
        )
    else:
        date_idx = next((v["index"] for k, v in props.items() if k.lower() == "date"), 0)
        pnl_idx = next(
            (v["index"] for k, v in props.items()
             if k.lower() in ("pnl", "cum_pnl", "returns", "ret")),
            1,
        )

    records = sorted(data.get("records", []), key=lambda r: r[date_idx])
    out: List[float] = []
    for row in records:
        rec = row[0] if isinstance(row, list) and len(row) == 1 and isinstance(row[0], list) else row
        try:
            out.append(float(rec[pnl_idx]))
        except Exception:
            continue
    return out


def daily_returns(cum_pnl: List[float]) -> List[float]:
    """Convert cumulative PnL to daily returns."""
    return [cum_pnl[i + 1] - cum_pnl[i] for i in range(len(cum_pnl) - 1)]


# ---------------------------------------------------------------------------
# Alpha DB
# ---------------------------------------------------------------------------

def load_alpha_db(path: Path) -> Dict[str, Any]:
    """Load the local alpha snapshot database."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"alphas": {}, "last_update": None, "version": 1}


def save_alpha_db(db: Dict[str, Any], path: Path) -> None:
    """Save the alpha snapshot database."""
    path.write_text(json.dumps(db, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Fingerprint & classify
# ---------------------------------------------------------------------------

def compute_alpha_fingerprint(alpha: Dict[str, Any]) -> Dict[str, Any]:
    """Compute a stable fingerprint from a BRAIN alpha API response."""
    is_ = alpha.get("is", {}) if isinstance(alpha.get("is"), dict) else {}
    expr_obj = alpha.get("regular", alpha.get("expression", {}))
    expr = expr_obj.get("code") if isinstance(expr_obj, dict) else str(expr_obj)
    settings = alpha.get("settings", {})
    return {
        "status": alpha.get("status"),
        "expression": expr,
        "settings": settings,
        "sharpe": is_.get("sharpe"),
        "fitness": is_.get("fitness"),
        "returns": is_.get("returns"),
        "turnover": is_.get("turnover"),
        "drawdown": is_.get("drawdown"),
        "margin": is_.get("margin"),
        "long_count": is_.get("longCount"),
        "short_count": is_.get("shortCount"),
    }


def classify_alpha(expr: str) -> str:
    """Rough family classification based on expression tokens."""
    expr_lower = expr.lower()
    tokens = []
    if any(f in expr_lower for f in ["operating_income/equity", "oi/equity", "operating_income/sales"]):
        tokens.append("profitability")
    if any(f in expr_lower for f in ["est_eps", "est_fcf", "est_revenue", "est_ebitda", "est_ptp"]):
        tokens.append("analyst")
    if any(f in expr_lower for f in ["free_cash_flow", "cashflow_op", "cash_flow"]):
        tokens.append("cashflow")
    if any(f in expr_lower for f in ["close/open", "open/close", "vwap", "returns", "volume", "high + low"]):
        tokens.append("technical")
    if any(f in expr_lower for f in ["scl12_buzz", "scl12_sentiment", "sentiment"]):
        tokens.append("sentiment")
    if any(f in expr_lower for f in ["equity/assets", "liabilities/assets", "sales/assets"]):
        tokens.append("quality/leverage")
    return "+".join(tokens) if tokens else "other"


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------

def correlation_with_existing(
    new_pnl: List[float],
    db: Dict[str, Any],
    min_records: int = 50,
) -> List[Dict[str, Any]]:
    """Compute daily-return correlation of a new alpha against all ACTIVE alphas.

    IMPORTANT: Correlation must be computed on **daily returns**, not cumulative
    PnL. Cumulative PnL correlation is severely inflated and misleading.

    Args:
        new_pnl: Cumulative PnL of the new alpha.
        db: Alpha database dict.
        min_records: Minimum PnL length to compute correlation.

    Returns:
        List of correlation results, sorted by abs(corr) descending.
    """
    if len(new_pnl) < min_records + 1:
        return []

    new_ret = np.array(daily_returns(new_pnl))
    results: List[Dict[str, Any]] = []

    for old_id, old in db.get("alphas", {}).items():
        if old.get("status") != "ACTIVE" or not old.get("pnl"):
            continue
        old_ret = np.array(daily_returns(old["pnl"]))
        if len(new_ret) != len(old_ret):
            continue
        corr = float(np.corrcoef(new_ret, old_ret)[0, 1])
        results.append({
            "alpha_id": old_id,
            "corr": corr,
            "sharpe": old.get("sharpe"),
            "fitness": old.get("fitness"),
        })

    results.sort(key=lambda x: abs(x["corr"]), reverse=True)
    return results


# ---------------------------------------------------------------------------
# Lesson generation
# ---------------------------------------------------------------------------

def generate_lesson(fp: Dict[str, Any], top_corr: List[Dict[str, Any]]) -> str:
    """Generate a one-line lesson from an alpha's metrics and correlations."""
    family = classify_alpha(fp.get("expression", ""))

    if fp.get("fitness") is None:
        metric_note = "Simulation failed or data missing"
    elif fp["fitness"] >= 1.5 and fp.get("turnover") is not None and fp["turnover"] <= 0.15:
        metric_note = "High Fitness, low turnover — excellent candidate"
    elif fp["fitness"] >= 1.1 and fp.get("turnover") is not None and fp["turnover"] <= 0.20:
        metric_note = "Meets basic submission thresholds"
    elif fp.get("turnover") is not None and fp["turnover"] > 0.35:
        metric_note = "Turnover too high — increase decay or mix with stable signal"
    else:
        metric_note = "Metrics marginal — needs optimization"

    if not top_corr:
        corr_note = "No ACTIVE alphas to compare correlation"
    elif abs(top_corr[0]["corr"]) >= 0.7:
        corr_note = f"Highly correlated with {top_corr[0]['alpha_id']} ({top_corr[0]['corr']:.2f}) — change signal family"
    elif abs(top_corr[0]["corr"]) >= 0.5:
        corr_note = f"Moderately correlated with {top_corr[0]['alpha_id']} ({top_corr[0]['corr']:.2f}) — submit with caution"
    else:
        corr_note = f"Low correlation with existing ACTIVE ({top_corr[0]['corr']:.2f}) — good diversification value"

    return f"{metric_note}. {corr_note}."


# ---------------------------------------------------------------------------
# Fetch all alphas
# ---------------------------------------------------------------------------

def fetch_user_alphas(session, limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch all user alphas from BRAIN with pagination."""
    all_alphas: List[Dict[str, Any]] = []
    offset = 0
    while True:
        resp = session.get(
            f"{_API_BASE}/users/self/alphas",
            params={"limit": limit, "offset": offset},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch alphas: {resp.status_code} {resp.text[:500]}")
        data = resp.json()
        batch = data.get("results", data.get("alphas", []))
        if not batch:
            break
        all_alphas.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
        time.sleep(0.2)
    return all_alphas


# ---------------------------------------------------------------------------
# Evolution runner
# ---------------------------------------------------------------------------

def run_evolution(
    session,
    db_path: Path,
    apply: bool = False,
) -> str:
    """Run the self-evolution cycle.

    Fetches all alphas, compares with local snapshot, computes correlations,
    and generates a Markdown lesson snippet.

    Args:
        session: Authenticated requests.Session.
        db_path: Path to alpha_db.json.
        apply: If True, persist the snapshot. If False, preview only.

    Returns:
        Markdown snippet string.
    """
    db = load_alpha_db(db_path)
    known_ids = set(db.get("alphas", {}).keys())
    is_first_run = len(known_ids) == 0

    all_alphas = fetch_user_alphas(session)
    logger.info("Fetched %d alphas, %d known", len(all_alphas), len(known_ids))

    new_alphas: List[Dict[str, Any]] = []
    changed_alphas: List[tuple] = []

    for alpha in all_alphas:
        aid = alpha.get("id")
        if not aid:
            continue
        fp = compute_alpha_fingerprint(alpha)

        if aid not in known_ids:
            new_alphas.append(alpha)
        else:
            old = db["alphas"][aid]
            if old.get("status") != fp["status"] or old.get("sharpe") != fp["sharpe"]:
                changed_alphas.append((old, {**fp, "alpha_id": aid}))

    if is_first_run:
        # Bulk snapshot mode
        logger.info("First run — building bulk snapshot...")
        for idx, alpha in enumerate(all_alphas):
            aid = alpha.get("id")
            fp = compute_alpha_fingerprint(alpha)
            pnl = fetch_pnl(session, aid)
            db["alphas"][aid] = {**fp, "pnl": pnl}
            if idx % 10 == 0:
                logger.info("  PnL: %d/%d", idx + 1, len(all_alphas))
            time.sleep(0.3)

        snippet = _build_bulk_summary(all_alphas)

    else:
        # Incremental mode
        logger.info("Incremental: %d new, %d changed", len(new_alphas), len(changed_alphas))

        entries: List[Dict[str, Any]] = []
        for alpha in new_alphas:
            aid = alpha.get("id")
            fp = compute_alpha_fingerprint(alpha)
            pnl = fetch_pnl(session, aid)
            top_corr = correlation_with_existing(pnl, db)
            lesson = generate_lesson(fp, top_corr)
            entries.append({
                "alpha_id": aid,
                "status": fp["status"],
                "family": classify_alpha(fp.get("expression", "")),
                "sharpe": fp["sharpe"],
                "fitness": fp["fitness"],
                "turnover": fp["turnover"],
                "drawdown": fp["drawdown"],
                "expression": fp["expression"],
                "top_corr": top_corr[:3],
                "lesson": lesson,
            })
            if apply:
                db["alphas"][aid] = {**fp, "pnl": pnl}
            logger.info("  new: %s | Sharpe=%.2f Fitness=%.2f", aid, fp["sharpe"], fp["fitness"])
            time.sleep(0.3)

        for old, new in changed_alphas:
            aid = new["alpha_id"]
            entries.append({
                "alpha_id": aid,
                "event": "status_or_metric_changed",
                "old_status": old.get("status"),
                "new_status": new["status"],
                "sharpe": new["sharpe"],
                "fitness": new["fitness"],
                "turnover": new["turnover"],
                "lesson": f"Status changed from {old.get('status')} to {new['status']}.",
            })
            if apply:
                db["alphas"][aid] = new

        snippet = _build_incremental_report(entries)

    if apply:
        db["last_update"] = datetime.now(timezone.utc).isoformat()
        save_alpha_db(db, db_path)
        logger.info("Saved alpha_db.json: %d alphas tracked", len(db["alphas"]))

    return snippet


def _build_bulk_summary(alphas: List[Dict[str, Any]]) -> str:
    """Build a Markdown summary for the first (bulk) run."""
    from collections import Counter

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(alphas)
    active = [a for a in alphas if a.get("status") == "ACTIVE"]
    families = Counter(
        classify_alpha(a.get("regular", {}).get("code", "")) for a in alphas
    )

    top_active = sorted(
        active,
        key=lambda a: (a.get("is", {}).get("fitness") or 0),
        reverse=True,
    )[:5]

    lines = [
        f"\n### {now} — Bulk Initialization Snapshot\n",
        f"- Total alphas: {total} | ACTIVE: {len(active)}",
        f"- Signal family distribution: {dict(families.most_common(8))}",
        "",
        "**Top 5 ACTIVE by Fitness**:",
    ]

    for a in top_active:
        is_ = a.get("is", {})
        aid = a.get("id", "?")
        family = classify_alpha(a.get("regular", {}).get("code", ""))
        lines.append(
            f"- `{aid}` ({family}): Sharpe={is_.get('sharpe', 0):.2f}, "
            f"Fitness={is_.get('fitness', 0):.2f}, TO={is_.get('turnover', 0):.3f}"
        )

    failures = [a for a in alphas if a.get("is", {}).get("fitness") is not None
                and a.get("is", {}).get("fitness", 0) < 0.5]
    high_to = [a for a in alphas if a.get("is", {}).get("turnover") is not None
               and a.get("is", {}).get("turnover", 0) > 0.50]

    if failures:
        fail_families = Counter(
            classify_alpha(a.get("regular", {}).get("code", "")) for a in failures
        )
        lines.extend([
            "",
            f"**Low-Fitness signals (Fitness < 0.5, {len(failures)} total)**:",
            f"- Family distribution: {dict(fail_families.most_common(5))}",
        ])

    if high_to:
        to_families = Counter(
            classify_alpha(a.get("regular", {}).get("code", "")) for a in high_to
        )
        lines.extend([
            "",
            f"**High-Turnover signals (TO > 50%, {len(high_to)} total)**:",
            f"- Family distribution: {dict(to_families.most_common(5))}",
        ])

    lines.append("\n---\n")
    return "\n".join(lines)


def _build_incremental_report(entries: List[Dict[str, Any]]) -> str:
    """Build per-alpha Markdown for incremental updates."""
    if not entries:
        return ""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"\n### {now}\n"]

    for e in entries:
        if e.get("event") == "status_or_metric_changed":
            lines.append(
                f"- **{e['alpha_id']}** Status: {e['old_status']} → {e['new_status']}; "
                f"Sharpe={e['sharpe']}, Fitness={e['fitness']}, TO={e['turnover']}. "
                f"{e['lesson']}"
            )
        else:
            lines.append(
                f"- **{e['alpha_id']}** ({e['status']}, {e['family']}): "
                f"Sharpe={e['sharpe']}, Fitness={e['fitness']}, TO={e['turnover']}, DD={e['drawdown']}. "
                f"{e['lesson']}"
            )
            if e.get("top_corr"):
                corr_strs = [f"{c['alpha_id']}({c['corr']:+.2f})" for c in e["top_corr"]]
                lines.append(f"  - Correlations: {', '.join(corr_strs)}")
            expr = (e.get("expression") or "")[:120]
            if expr:
                lines.append(f"  - Expression: `{expr}`")

    lines.append("\n---\n")
    return "\n".join(lines)
