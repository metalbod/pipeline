"""Xero Accounting API connector: fetches Accounts (local COA) and Journals (system-generated
GL, already balanced double-entry). See ARCHITECTURE.md §5 for the ingestion pattern.

`client` is dependency-injected everywhere so tests substitute a respx-mocked httpx.Client
instead of hitting the network -- see test_connector.py. Production callers get a real client
from client.build_xero_client().
"""

from typing import Optional

import httpx

JOURNALS_PAGE_SIZE = 100


def fetch_accounts(client: httpx.Client) -> list[dict]:
    """GET /Accounts -- the entity's local chart of accounts."""
    response = client.get("/Accounts")
    response.raise_for_status()
    return response.json()["Accounts"]


def fetch_journals_page(client: httpx.Client, since_journal_number: Optional[int] = None) -> list[dict]:
    """GET /Journals?offset= -- one page (up to 100) of system-generated journals, offset-based
    incremental pull per ARCHITECTURE.md §5."""
    params = {}
    if since_journal_number is not None:
        params["offset"] = since_journal_number
    response = client.get("/Journals", params=params)
    response.raise_for_status()
    return response.json()["Journals"]


def fetch_all_journals(client: httpx.Client, since_journal_number: Optional[int] = None) -> list[dict]:
    """Pages through /Journals until a short page signals the end."""
    all_journals: list[dict] = []
    cursor = since_journal_number
    while True:
        page = fetch_journals_page(client, cursor)
        if not page:
            break
        all_journals.extend(page)
        cursor = page[-1]["JournalNumber"]
        if len(page) < JOURNALS_PAGE_SIZE:
            break
    return all_journals
