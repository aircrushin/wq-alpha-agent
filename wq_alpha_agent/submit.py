"""Alpha submission engine — pre-check, submit, and verify on WorldQuant BRAIN."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("wq_alpha_agent.submit")

API_BASE = "https://api.worldquantbrain.com"


def run_pre_submit_check(
    session: requests.Session,
    alpha_id: str,
    label: str = "",
) -> Dict[str, Any]:
    """Run the BRAIN pre-submit check for an alpha.

    Args:
        session: Authenticated requests.Session.
        alpha_id: Alpha ID to check.
        label: Label for logging.

    Returns:
        Check response with ``checks`` list and ``is`` metrics.
    """
    prefix = f"[{label}] " if label else ""
    url = f"{API_BASE}/alphas/{alpha_id}/check"
    resp = session.get(url)

    if resp.status_code != 200:
        raise RuntimeError(
            f"{prefix}Pre-submit check failed: {resp.status_code} {resp.text[:500]}"
        )

    data = resp.json()
    logger.info("%sPre-submit check completed for %s", prefix, alpha_id)
    return data


def get_check_failures(check_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract failed checks from a pre-submit check response."""
    is_metrics = check_data.get("is") or {}
    checks = is_metrics.get("checks") or []
    return [c for c in checks if c.get("result") == "FAIL"]


def get_check_by_name(check_data: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """Retrieve a specific check by name from check response."""
    is_metrics = check_data.get("is") or {}
    checks = is_metrics.get("checks") or []
    for check in checks:
        if check.get("name") == name:
            return check
    return None


def check_self_correlation(
    check_data: Dict[str, Any],
    require_pass: bool = True,
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """Specifically check the SELF_CORRELATION result.

    Returns:
        Tuple of (passed, check_dict_or_None).
    """
    sc = get_check_by_name(check_data, "SELF_CORRELATION")
    if sc is None:
        return not require_pass, None

    passed = sc.get("result") == "PASS"
    return passed or not require_pass, sc


def submit_alpha(
    session: requests.Session,
    alpha_id: str,
    label: str = "",
) -> Dict[str, Any]:
    """Submit an alpha to WorldQuant BRAIN.

    Note: A 201 response means the request was accepted, NOT that the alpha
    is ACTIVE. Always call ``verify_submission()`` afterward.

    Args:
        session: Authenticated requests.Session.
        alpha_id: Alpha ID to submit.
        label: Label for logging.

    Returns:
        Submission response metadata.

    Raises:
        RuntimeError: If submission request fails.
    """
    prefix = f"[{label}] " if label else ""
    url = f"{API_BASE}/alphas/{alpha_id}/submit"

    # Monkey-patch note: if using the wqb library, the submit URL may need
    # patching from http:// to https://. This function uses the direct REST
    # API with explicit https:// URLs, avoiding that bug.
    resp = session.post(url)

    if resp.status_code >= 400:
        error_text = resp.text[:500] if resp.text else f"status={resp.status_code}"
        raise RuntimeError(f"{prefix}Submission failed for {alpha_id}: {error_text}")

    logger.info("%sSubmitted alpha %s — status %d", prefix, alpha_id, resp.status_code)
    return {
        "submitted": True,
        "status_code": resp.status_code,
        "alpha_id": alpha_id,
    }


def verify_submission(
    session: requests.Session,
    alpha_id: str,
    label: str = "",
    max_attempts: int = 30,
    poll_interval: int = 10,
) -> Dict[str, Any]:
    """Verify that a submitted alpha has actually become ACTIVE.

    BRAIN may keep an alpha as UNSUBMITTED even after a 201 response if
    SELF_CORRELATION or other checks fail. This polls until the status
    is resolved.

    Args:
        session: Authenticated requests.Session.
        alpha_id: Alpha ID to verify.
        label: Label for logging.
        max_attempts: Maximum poll attempts.
        poll_interval: Seconds between polls.

    Returns:
        Dictionary with ``status``, ``alpha_data``, and ``verified`` keys.
    """
    prefix = f"[{label}] " if label else ""

    for attempt in range(1, max_attempts + 1):
        resp = session.get(f"{API_BASE}/alphas/{alpha_id}")
        if resp.status_code != 200:
            logger.warning("%sVerification poll %d returned %d", prefix, attempt, resp.status_code)
            time.sleep(poll_interval)
            continue

        alpha = resp.json()
        status = alpha.get("status")

        if status == "ACTIVE":
            logger.info("%sAlpha %s is ACTIVE — submission confirmed", prefix, alpha_id)
            return {"status": "ACTIVE", "alpha_data": alpha, "verified": True}

        # Check for SELF_CORRELATION failure
        checks = (alpha.get("is") or {}).get("checks") or []
        sc = next((c for c in checks if c.get("name") == "SELF_CORRELATION"), {})
        if sc.get("result") == "FAIL":
            logger.warning(
                "%sAlpha %s failed SELF_CORRELATION (value=%s, limit=%s)",
                prefix, alpha_id, sc.get("value"), sc.get("limit"),
            )
            return {
                "status": status,
                "alpha_data": alpha,
                "verified": False,
                "self_correlation_failed": True,
            }

        logger.info("%sAlpha %s status: %s (attempt %d/%d)", prefix, alpha_id, status, attempt, max_attempts)
        time.sleep(poll_interval)

    # Timed out
    resp = session.get(f"{API_BASE}/alphas/{alpha_id}")
    alpha = resp.json() if resp.status_code == 200 else {}
    return {"status": alpha.get("status", "UNKNOWN"), "alpha_data": alpha, "verified": False, "timed_out": True}


def submit_with_full_verification(
    session: requests.Session,
    alpha_id: str,
    label: str = "",
    require_self_correlation_pass: bool = True,
) -> Dict[str, Any]:
    """Full submission pipeline: pre-check → submit → verify.

    Args:
        session: Authenticated requests.Session.
        alpha_id: Alpha ID.
        label: Label for logging.
        require_self_correlation_pass: If True, fail if SELF_CORRELATION
            check fails during pre-submit check.

    Returns:
        Complete submission result with all steps documented.
    """
    prefix = f"[{label}] " if label else ""
    result = {"alpha_id": alpha_id, "submitted": False}

    # Step 1: Pre-submit check
    logger.info("%sRunning pre-submit check for %s", prefix, alpha_id)
    try:
        check_data = run_pre_submit_check(session, alpha_id, label)
        result["check_data"] = check_data
    except RuntimeError as exc:
        result["error"] = str(exc)
        result["stage"] = "pre_submit_check"
        return result

    # Step 2: Check for failures
    failures = get_check_failures(check_data)
    if require_self_correlation_pass:
        sc_passed, sc_check = check_self_correlation(check_data, require_pass=True)
        if not sc_passed and sc_check:
            failures.append({
                "name": "SELF_CORRELATION",
                "result": sc_check.get("result", "MISSING"),
                "value": sc_check.get("value"),
                "limit": sc_check.get("limit"),
            })

    if failures:
        fail_msg = "; ".join(
            f"{f.get('name')}={f.get('result')} (value={f.get('value')}, limit={f.get('limit')})"
            for f in failures
        )
        logger.warning("%sPre-submit check failed: %s", prefix, fail_msg)
        result["error"] = fail_msg
        result["stage"] = "pre_submit_check_failures"
        result["failures"] = failures
        return result

    # Step 3: Submit
    logger.info("%sAll checks passed. Submitting %s...", prefix, alpha_id)
    try:
        submit_result = submit_alpha(session, alpha_id, label)
        result.update(submit_result)
    except RuntimeError as exc:
        result["error"] = str(exc)
        result["stage"] = "submit"
        return result

    # Step 4: Verify
    logger.info("%sVerifying submission for %s...", prefix, alpha_id)
    verify_result = verify_submission(session, alpha_id, label)
    result["verification"] = verify_result
    result["submitted"] = verify_result.get("verified", False)

    if verify_result.get("verified"):
        logger.info("%sAlpha %s successfully submitted and ACTIVE!", prefix, alpha_id)
    elif verify_result.get("self_correlation_failed"):
        logger.warning("%sAlpha %s rejected: SELF_CORRELATION", prefix, alpha_id)

    return result
