"""Local diversity gate — prevents submitting near-duplicate alpha expressions.

Fingerprints each alpha expression and compares against a protected list of
ACTIVE alphas using normalized skeletons, field overlap (Jaccard), operator
overlap, and family classification.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMMON_FIELDS: Set[str] = {
    "adv20", "assets", "cap", "close", "high", "industry",
    "low", "open", "returns", "subindustry", "volume", "vwap",
}

CONTROL_WORDS: Set[str] = {"if", "else", "nan", "true", "false"}

OPERATORS: Set[str] = {
    "abs", "group_mean", "group_neutralize", "group_rank", "group_zscore",
    "rank", "trade_when", "ts_backfill", "ts_delta", "ts_mean",
    "ts_median", "ts_rank", "ts_std_dev", "ts_sum", "ts_zscore", "vec_avg",
}

# Extensible family rules: family_name → {distinctive_field_ids}
FAMILY_RULES: Dict[str, Set[str]] = {
    "news_sentiment": {"nws12_afterhsz_sl"},
    "cashflow_roe_quality": {"cashflow_op", "return_equity"},
    "options_pcr_iv": {"pcr_oi_270", "implied_volatility_call_270", "implied_volatility_put_270"},
    "buyback_yield": {"fn_repurchased_shares_value_q"},
    "eps_profit_buzz": {"est_eps", "operating_income", "scl12_buzz"},
}


# ---------------------------------------------------------------------------
# Fingerprint model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AlphaFingerprint:
    """Immutable fingerprint of an alpha expression for diversity comparison."""

    alpha_id: Optional[str]
    name: str
    status: Optional[str]
    expression: str
    family: str
    fields: List[str]
    key_fields: List[str]
    operators: List[str]
    skeleton: str           # fully normalized with numbers → #
    field_skeleton: str     # fields → FIELD, variables → VAR
    metrics: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Expression parsing
# ---------------------------------------------------------------------------

def normalize_expression(expression: str) -> str:
    """Normalize an expression for structural comparison.

    - Collapses whitespace
    - Lowercases
    - Replaces numeric literals with ``#``
    """
    expr = re.sub(r"\s+", " ", expression.strip().lower())
    expr = re.sub(r"\b\d+(?:\.\d+)?\b", "#", expr)
    expr = re.sub(r"\s*([(),;+\-*/<>:=])\s*", r"\1", expr)
    return expr


def expression_identifiers(expression: str) -> List[str]:
    """Extract all identifiers (field names, operators, variables) from an expression."""
    return re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expression)


def local_variables(expression: str) -> Set[str]:
    """Detect local variable assignments like ``var = ...``."""
    return set(re.findall(r"(?:^|;)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=", expression))


def extract_fields(expression: str) -> List[str]:
    """Extract BRAIN data field names from an expression."""
    identifiers = set(expression_identifiers(expression))
    locals_ = local_variables(expression)
    return sorted(
        token
        for token in identifiers
        if token not in OPERATORS and token not in CONTROL_WORDS and token not in locals_
    )


def extract_operators(expression: str) -> List[str]:
    """Extract BRAIN operators used in an expression."""
    identifiers = expression_identifiers(expression)
    return sorted(token for token in set(identifiers) if token in OPERATORS)


def build_field_skeleton(expression: str) -> str:
    """Build a field-level skeleton: replace fields with FIELD, variables with VAR."""
    normalized = normalize_expression(expression)
    for variable in sorted(local_variables(expression), key=len, reverse=True):
        normalized = re.sub(rf"\b{re.escape(variable)}\b", "VAR", normalized)
    for field_name in sorted(extract_fields(expression), key=len, reverse=True):
        normalized = re.sub(rf"\b{re.escape(field_name)}\b", "FIELD", normalized)
    return normalized


def classify_family(fields: Set[str]) -> str:
    """Classify an alpha into a family based on its data fields.

    Extensible: add entries to ``FAMILY_RULES`` for new families.
    """
    scores = {
        family: len(fields & family_fields)
        for family, family_fields in FAMILY_RULES.items()
    }
    best_family, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score:
        return best_family
    non_common = sorted(fields - COMMON_FIELDS)
    if non_common:
        return "other:" + "+".join(non_common[:3])
    return "market_microstructure"


def key_fields_for_family(fields: Set[str], family: str) -> List[str]:
    """Return the distinctive (key) fields for a given family."""
    if family in FAMILY_RULES:
        keys = fields & FAMILY_RULES[family]
        if keys:
            return sorted(keys)
    return sorted(fields - COMMON_FIELDS)


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

def fingerprint_alpha(alpha: Dict[str, Any]) -> AlphaFingerprint:
    """Create an AlphaFingerprint from a dictionary representation.

    The dictionary can come from a batch config entry or a BRAIN API response.
    """
    expression = (
        alpha.get("expression")
        or (alpha.get("regular") or {}).get("code")
        or alpha.get("regular")
        or ""
    )
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError(
            f"Alpha {alpha.get('name') or alpha.get('alpha_id') or '<unnamed>'} has no expression"
        )

    fields = extract_fields(expression)
    field_set = set(fields)
    family = alpha.get("family") or classify_family(field_set)

    return AlphaFingerprint(
        alpha_id=alpha.get("alpha_id") or alpha.get("id"),
        name=alpha.get("name") or alpha.get("alpha_id") or "unnamed",
        status=alpha.get("status"),
        expression=expression,
        family=family,
        fields=fields,
        key_fields=key_fields_for_family(field_set, family),
        operators=extract_operators(expression),
        skeleton=normalize_expression(expression),
        field_skeleton=build_field_skeleton(expression),
        metrics=alpha.get("metrics") or {},
        settings=alpha.get("settings") or {},
    )


# ---------------------------------------------------------------------------
# Similarity metrics
# ---------------------------------------------------------------------------

def jaccard(left: Set[str], right: Set[str]) -> float:
    """Jaccard similarity between two sets."""
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def operator_overlap(left: List[str], right: List[str]) -> float:
    """Operator usage overlap (multi-set Jaccard)."""
    left_cnt = Counter(left)
    right_cnt = Counter(right)
    if not left_cnt and not right_cnt:
        return 1.0
    overlap = sum((left_cnt & right_cnt).values())
    total = sum((left_cnt | right_cnt).values())
    return overlap / total if total else 0.0


# ---------------------------------------------------------------------------
# Diversity evaluation
# ---------------------------------------------------------------------------

def evaluate_candidate(
    candidate: Dict[str, Any],
    protected: List[AlphaFingerprint],
) -> Tuple[bool, List[Dict[str, Any]], AlphaFingerprint]:
    """Check if a candidate alpha is too similar to any protected alpha.

    Args:
        candidate: Alpha dict (from batch config).
        protected: List of protected AlphaFingerprints (ACTIVE alphas).

    Returns:
        Tuple of (is_allowed, rejection_reasons, candidate_fingerprint).
    """
    candidate_fp = fingerprint_alpha(candidate)
    reasons: List[Dict[str, Any]] = []
    candidate_fields = set(candidate_fp.fields)
    candidate_key_fields = set(candidate_fp.key_fields)

    for active in protected:
        active_fields = set(active.fields)
        active_key_fields = set(active.key_fields)
        field_overlap = jaccard(candidate_fields, active_fields)
        key_overlap = jaccard(candidate_key_fields, active_key_fields)
        op_overlap = operator_overlap(candidate_fp.operators, active.operators)
        same_family = candidate_fp.family == active.family

        # Rule 1: Exact normalized expression match
        if candidate_fp.skeleton == active.skeleton:
            reasons.append({
                "rule": "exact_normalized_expression",
                "active_alpha_id": active.alpha_id,
                "active_family": active.family,
                "message": "Candidate normalizes to the same expression as a protected alpha.",
            })

        # Rule 2: Same field skeleton with high field overlap
        elif candidate_fp.field_skeleton == active.field_skeleton and field_overlap >= 0.7:
            reasons.append({
                "rule": "same_field_skeleton",
                "active_alpha_id": active.alpha_id,
                "active_family": active.family,
                "field_overlap": round(field_overlap, 4),
                "message": "Candidate has the same operator/field skeleton with only parameter or weight changes.",
            })

        # Rule 3: Same family with high key-field and operator overlap
        elif same_family and key_overlap >= 0.67 and field_overlap >= 0.5 and op_overlap >= 0.6:
            reasons.append({
                "rule": "same_family_key_fields",
                "active_alpha_id": active.alpha_id,
                "active_family": active.family,
                "field_overlap": round(field_overlap, 4),
                "key_field_overlap": round(key_overlap, 4),
                "operator_overlap": round(op_overlap, 4),
                "message": "Candidate reuses a protected family with high key-field and operator overlap.",
            })

    return (not reasons), reasons, candidate_fp


# ---------------------------------------------------------------------------
# Blacklist management
# ---------------------------------------------------------------------------

def load_blacklist(path: Path) -> List[AlphaFingerprint]:
    """Load a diversity blacklist from a JSON file.

    The file should contain a ``protected_alphas`` array of fingerprint dicts,
    or be a flat list of fingerprint dicts.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("protected_alphas", data)
    if isinstance(raw, list):
        return [AlphaFingerprint(**item) for item in raw]
    return []


def build_blacklist_from_active(
    active_alphas: List[Dict[str, Any]],
    self_correlation_max: float = 0.7,
) -> Dict[str, Any]:
    """Build a blacklist payload from a list of ACTIVE alpha records.

    Filters out alphas with high self-correlation (likely near-duplicates).
    """
    fingerprints = []
    for alpha in active_alphas:
        if alpha.get("status") != "ACTIVE":
            continue
        metrics = alpha.get("metrics") or alpha.get("is") or {}
        self_corr = metrics.get("selfCorrelation")
        if self_corr is not None and float(self_corr) > self_correlation_max:
            continue
        fingerprints.append(fingerprint_alpha(alpha))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "blocks": [
                "exact normalized expression",
                "same field skeleton with numeric/weight changes only",
                "same protected family with high key-field and operator overlap",
            ],
            "protected_self_correlation_max": self_correlation_max,
        },
        "protected_alphas": [asdict(fp) for fp in fingerprints],
    }


def filter_alpha_configs(
    alphas: List[Dict[str, Any]],
    protected: Optional[List[AlphaFingerprint]] = None,
    blacklist_path: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Filter a list of alpha configs through the diversity gate.

    Args:
        alphas: Alpha config dictionaries.
        protected: Pre-loaded protected fingerprints. If None, loads from blacklist_path.
        blacklist_path: Path to blacklist JSON. Used if protected is None.

    Returns:
        Tuple of (accepted_alphas, rejected_alphas_with_reasons).
    """
    if protected is None and blacklist_path is not None and blacklist_path.exists():
        protected = load_blacklist(blacklist_path)
    if protected is None:
        protected = []

    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for index, alpha in enumerate(alphas, start=1):
        allowed, reasons, candidate_fp = evaluate_candidate(alpha, protected)
        if allowed:
            accepted.append(alpha)
        else:
            rejected.append({
                "event": "diversity_gate_rejected",
                "name": alpha.get("name", f"alpha_{index}"),
                "index": index,
                "family": candidate_fp.family,
                "fields": candidate_fp.fields,
                "key_fields": candidate_fp.key_fields,
                "reasons": reasons,
            })

    return accepted, rejected
