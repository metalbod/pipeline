"""Normalizes raw Xero payloads into the common Bronze schema that both the Xero and file
connectors converge on (ARCHITECTURE.md §5: 'both paths converge into the same Bronze
schema-per-domain, which is what makes a single Silver transformation layer viable').
"""

from datetime import datetime, timezone

import pyarrow as pa

from ingestion.bronze_schemas import ACCOUNTS_SCHEMA, JOURNAL_LINES_SCHEMA

# Xero Journals are always in the organisation's base/functional currency by API design -- the
# `currency` column is left null in normalize_journals() below rather than guessed; Silver
# assigns it from dim_entity.functional_currency.


def _xero_datetime(value: str) -> datetime:
    """Xero's Accounting API returns dates as either the legacy .NET '/Date(ms+tz)/' format
    or ISO 8601, depending on endpoint/Accept header -- handle both defensively."""
    if value.startswith("/Date("):
        millis = int(value[6:].split("+")[0].split(")")[0])
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize_accounts(raw_accounts: list[dict], entity_id: str, batch_id: str) -> pa.Table:
    now = datetime.now(timezone.utc)
    rows = [
        {
            "_ingested_at": now,
            "_source_system": "xero",
            "_source_file_or_endpoint": "Accounts",
            "_batch_id": batch_id,
            "entity_id": entity_id,
            "local_account_code": a["Code"],
            "local_account_name": a["Name"],
            "local_account_type": a.get("Type"),
        }
        for a in raw_accounts
    ]
    return pa.Table.from_pylist(rows, schema=ACCOUNTS_SCHEMA)


def normalize_journals(raw_journals: list[dict], entity_id: str, batch_id: str) -> pa.Table:
    now = datetime.now(timezone.utc)
    rows = []
    for journal in raw_journals:
        journal_id = journal["JournalID"]
        posted_at = _xero_datetime(journal["JournalDate"]).date()
        source_updated_at = _xero_datetime(journal["CreatedDateUTC"])
        for i, line in enumerate(journal.get("JournalLines", [])):
            net = line.get("NetAmount", 0.0)
            rows.append(
                {
                    "_ingested_at": now,
                    "_source_system": "xero",
                    "_source_file_or_endpoint": "Journals",
                    "_batch_id": batch_id,
                    "entity_id": entity_id,
                    "source_record_id": journal_id,
                    "journal_id": journal_id,
                    "line_no": i,
                    "account_code": line.get("AccountCode"),
                    "account_name": line.get("AccountName"),
                    # Xero convention: positive NetAmount is a debit, negative is a credit.
                    "debit_amount": net if net > 0 else 0.0,
                    "credit_amount": -net if net < 0 else 0.0,
                    "currency": None,
                    "description": line.get("Description"),
                    "posted_at": posted_at,
                    "source_updated_at": source_updated_at,
                }
            )
    return pa.Table.from_pylist(rows, schema=JOURNAL_LINES_SCHEMA)
