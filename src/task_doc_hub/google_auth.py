"""Google auth via clasp token — reuses ~/.clasprc.json credentials."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CLASP_RC = Path.home() / ".clasprc.json"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_access_token() -> str:
    """Get a fresh access token by refreshing the clasp OAuth token.

    Raises RuntimeError if clasp credentials are missing or refresh fails.
    """
    if not CLASP_RC.exists():
        raise RuntimeError(
            "~/.clasprc.json not found. Run: npx @google/clasp login"
        )

    data = json.loads(CLASP_RC.read_text())
    default = data.get("tokens", {}).get("default", {})

    refresh_token = default.get("refresh_token")
    client_id = default.get("client_id")
    client_secret = default.get("client_secret")

    if not all([refresh_token, client_id, client_secret]):
        raise RuntimeError("Incomplete clasp credentials in ~/.clasprc.json")

    resp = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=10)

    if resp.status_code != 200:
        raise RuntimeError(f"Token refresh failed: {resp.text}")

    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("No access_token in refresh response")

    return token


def drive_headers() -> dict[str, str]:
    """Return Authorization headers for Drive API calls."""
    return {"Authorization": f"Bearer {get_access_token()}"}
