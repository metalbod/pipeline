#!/usr/bin/env python
"""One-time interactive Xero OAuth2 consent flow.

Run this yourself, locally, once you have a Xero Developer app (client ID/secret) and a
tenant to connect: `python scripts/xero_oauth_bootstrap.py`. It opens your browser for the
Xero consent screen, exchanges the authorization code for tokens, and writes the initial
refresh token to the path in XERO_TOKEN_FILE (default .secrets/xero_token.json, gitignored).

After this, ingestion/api_connectors/xero/client.py handles refreshing (and re-persisting the
rotated refresh token) on every run automatically -- you shouldn't need to run this again unless
the refresh token is revoked or expires from prolonged disuse (Xero: ~60 days unused).

Requires XERO_CLIENT_ID and XERO_CLIENT_SECRET in the environment, and that your Xero app's
configured redirect URI is http://localhost:8080/callback.
"""

import http.server
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser

import httpx

from ingestion.api_connectors.xero.client import XERO_TOKEN_URL, save_token_file

AUTHORIZE_URL = "https://login.xero.com/identity/connect/authorize"
REDIRECT_URI = "http://localhost:8080/callback"
SCOPES = "openid profile email accounting.transactions.read accounting.settings.read offline_access"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"Error: {name} must be set in the environment.", file=sys.stderr)
        sys.exit(1)
    return value


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    auth_code: str = ""
    expected_state: str = ""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if params.get("state", [""])[0] != self.expected_state:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"State mismatch -- aborting.")
            return
        _CallbackHandler.auth_code = params.get("code", [""])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Xero consent complete -- you can close this tab.")

    def log_message(self, *args):
        pass  # keep stdout clean


def main():
    client_id = _require_env("XERO_CLIENT_ID")
    client_secret = _require_env("XERO_CLIENT_SECRET")

    state = secrets.token_urlsafe(16)
    _CallbackHandler.expected_state = state
    auth_url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
        }
    )

    print(f"Opening {auth_url}\nComplete the consent screen in your browser...")
    webbrowser.open(auth_url)

    server = http.server.HTTPServer(("localhost", 8080), _CallbackHandler)
    server.handle_request()  # blocks for exactly one request

    if not _CallbackHandler.auth_code:
        print("No authorization code received -- aborting.", file=sys.stderr)
        sys.exit(1)

    response = httpx.post(
        XERO_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": _CallbackHandler.auth_code,
            "redirect_uri": REDIRECT_URI,
        },
        auth=(client_id, client_secret),
    )
    response.raise_for_status()
    token = response.json()
    save_token_file({"refresh_token": token["refresh_token"], "obtained_at": time.time()})
    print("Saved initial refresh token. XERO_TENANT_ID: run a GET /connections call "
          "against https://api.xero.com/connections with this token to find your tenant ID, "
          "then set XERO_TENANT_ID in your environment.")


if __name__ == "__main__":
    main()
