"""Authentication and session management for WorldQuant BRAIN API."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth

API_BASE = "https://api.worldquantbrain.com"

HEADERS = {
    "Accept": "application/json;version=2.0",
    "Content-Type": "application/json",
}

logger = logging.getLogger("wq_alpha_agent.auth")


def load_credentials(
    env_username: str = "WQ_BRAIN_USERNAME",
    env_password: str = "WQ_BRAIN_PASSWORD",
    credential_file: str = "credential.txt",
) -> Tuple[str, str]:
    """Load BRAIN credentials from environment or a local untracked file.

    Priority:
    1. Environment variables (WQ_BRAIN_USERNAME / WQ_BRAIN_PASSWORD)
    2. Local ``credential.txt`` (JSON array ``["username", "password"]``)

    Also checks legacy env vars (WQ_EMAIL / WQ_PASSWORD) for compatibility.

    Returns:
        Tuple of (username, password).
    """
    # Primary env vars
    env_user = os.getenv(env_username)
    env_password = os.getenv(env_password)
    if env_user and env_password:
        return env_user, env_password

    # Legacy env vars (compatibility with older setups)
    legacy_user = os.getenv("WQ_EMAIL")
    legacy_password = os.getenv("WQ_PASSWORD")
    if legacy_user and legacy_password:
        return legacy_user, legacy_password

    # Local credential file
    candidates = [
        Path(credential_file),
        Path.cwd() / credential_file,
        Path.home() / ".wq" / credential_file,
    ]
    for path in candidates:
        if path.exists():
            username, password = json.loads(path.read_text(encoding="utf-8"))
            return str(username), str(password)

    raise FileNotFoundError(
        "BRAIN credentials not found. Set WQ_BRAIN_USERNAME/WQ_BRAIN_PASSWORD "
        'environment variables, or create a credential.txt file with ["username", "password"].'
    )


def create_session(
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout: int = 10,
) -> requests.Session:
    """Create an authenticated requests.Session for the BRAIN API.

    Args:
        username: BRAIN username. If None, loaded from env/credential file.
        password: BRAIN password. If None, loaded from env/credential file.
        timeout: Connection timeout in seconds.

    Returns:
        Authenticated requests.Session.

    Raises:
        RuntimeError: If authentication fails.
    """
    if username is None or password is None:
        username, password = load_credentials()

    session = requests.Session()
    session.auth = HTTPBasicAuth(username, password)
    session.headers.update(HEADERS)

    resp = session.post(f"{API_BASE}/authentication", timeout=timeout)
    if resp.status_code != 201:
        raise RuntimeError(f"BRAIN authentication failed: {resp.status_code} {resp.text[:500]}")

    logger.info("Authenticated to WorldQuant BRAIN successfully.")
    return session


def create_session_with_retry(
    username: Optional[str] = None,
    password: Optional[str] = None,
    max_attempts: int = 3,
    **kwargs,
) -> requests.Session:
    """Create session with retry on transient auth failures."""
    for attempt in range(1, max_attempts + 1):
        try:
            return create_session(username=username, password=password, **kwargs)
        except RuntimeError as exc:
            if attempt == max_attempts:
                raise
            logger.warning("Auth attempt %d/%d failed: %s. Retrying...", attempt, max_attempts, exc)
    raise RuntimeError("Authentication failed after all retries.")


def logout(session: requests.Session) -> None:
    """Safely terminate a BRAIN session."""
    try:
        session.delete(f"{API_BASE}/authentication")
    except Exception:
        pass
