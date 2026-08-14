"""Orchestrates one Bronze ingestion run for Xero: fetch -> archive raw -> normalize -> append.

This connector is scoped to MY-PARENT, the pilot entity mapped to Xero for Phase 1
(ARCHITECTURE.md §9 / this session's kickoff).
"""

from typing import Optional

import httpx
import polars as pl

from data_quality.pandera_schemas.xero_accounts_schema import XeroAccountsSchema
from data_quality.pandera_schemas.xero_journal_lines_schema import XeroJournalLinesSchema
from ingestion.delta_writer import archive_raw_api_response, new_batch_id, write_bronze

from . import connector, normalize
from .client import build_xero_client

ENTITY_ID = "MY-PARENT"


def ingest_accounts(client: httpx.Client) -> dict:
    batch_id = new_batch_id()
    raw = connector.fetch_accounts(client)
    archive_raw_api_response("xero", ENTITY_ID, "Accounts", batch_id, raw)
    table = normalize.normalize_accounts(raw, ENTITY_ID, batch_id)
    XeroAccountsSchema.validate(pl.from_arrow(table))
    path = write_bronze("accounts", table)
    return {"batch_id": batch_id, "row_count": table.num_rows, "path": path}


def ingest_journals(client: httpx.Client, since_journal_number: Optional[int] = None) -> dict:
    batch_id = new_batch_id()
    raw = connector.fetch_all_journals(client, since_journal_number)
    archive_raw_api_response("xero", ENTITY_ID, "Journals", batch_id, raw)
    table = normalize.normalize_journals(raw, ENTITY_ID, batch_id)
    XeroJournalLinesSchema.validate(pl.from_arrow(table))
    path = write_bronze("journal_lines", table)
    return {"batch_id": batch_id, "row_count": table.num_rows, "path": path}


def run(since_journal_number: Optional[int] = None) -> dict:
    """Production entrypoint -- builds a live client from env credentials (XERO_CLIENT_ID,
    XERO_CLIENT_SECRET, XERO_TENANT_ID, and a bootstrapped token file). Tests call
    ingest_accounts/ingest_journals directly with a respx-mocked client instead."""
    with build_xero_client() as client:
        accounts_result = ingest_accounts(client)
        journals_result = ingest_journals(client, since_journal_number)
    return {"accounts": accounts_result, "journals": journals_result}
