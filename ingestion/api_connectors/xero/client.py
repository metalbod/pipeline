"""OAuth2 client for Xero's Accounting API.

Xero access tokens expire after 30 minutes; refresh tokens are single-use and rotate on every
exchange, so the newly-issued refresh token must be persisted back to disk immediately -- an
env var alone can't hold a value that changes on every run. See scripts/xero_oauth_bootstrap.py
for how the first refresh token gets here.
"""

import json
import os
import time
from pathlib import Path

import httpx

XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_API_BASE = "https://api.xero.com/api.xro/2.0"


class XeroConfigError(RuntimeError):
    """Raised when required Xero credentials/config are missing or invalid."""


def _token_file() -> Path:
    return Path(os.environ.get("XERO_TOKEN_FILE", ".secrets/xero_token.json"))


def _load_token_file() -> dict:
    path = _token_file()
    if not path.exists():
        raise XeroConfigError(
            f"No Xero token file at {path}. Run `python scripts/xero_oauth_bootstrap.py` once "
            "to complete the OAuth consent flow and obtain an initial refresh token."
        )
    return json.loads(path.read_text())


def save_token_file(data: dict) -> None:
    path = _token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise XeroConfigError(f"{name} must be set in the environment (see .env.example).")
    return value


def refresh_access_token(http_client: httpx.Client) -> dict:
    """Exchanges the current refresh token for a new access token, persisting the rotated
    refresh token Xero issues back to the token file."""
    client_id = _require_env("XERO_CLIENT_ID")
    client_secret = _require_env("XERO_CLIENT_SECRET")
    token_data = _load_token_file()

    response = http_client.post(
        XERO_TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": token_data["refresh_token"]},
        auth=(client_id, client_secret),
    )
    response.raise_for_status()
    new_token = response.json()
    save_token_file({"refresh_token": new_token["refresh_token"], "obtained_at": time.time()})
    return new_token


def build_xero_client() -> httpx.Client:
    """Builds a live httpx.Client with a fresh Xero access token + tenant header attached.

    Tests never call this -- they construct their own respx-mocked httpx.Client and inject it
    directly into connector.py's functions.
    """
    tenant_id = _require_env("XERO_TENANT_ID")

    with httpx.Client() as token_client:
        token = refresh_access_token(token_client)

    return httpx.Client(
        base_url=XERO_API_BASE,
        headers={
            "Authorization": f"Bearer {token['access_token']}",
            "Xero-tenant-id": tenant_id,
            "Accept": "application/json",
        },
        timeout=30.0,
    )
