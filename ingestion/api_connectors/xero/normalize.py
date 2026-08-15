"""Normalizes raw Xero payloads into the common Bronze schema that both the Xero and file
connectors converge on (ARCHITECTURE.md §5: 'both paths converge into the same Bronze
schema-per-domain, which is what makes a single Silver transformation layer viable').
"""

from datetime import datetime, timezone

import pyarrow as pa

from ingestion.bronze_schemas import ACCOUNTS_SCHEMA, AGING_SCHEMA, BUDGET_SCHEMA, JOURNAL_LINES_SCHEMA

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


def _report_sections(raw_report: dict):
    """Yields (contact/account title, invoice/budget Rows) for each real Section in a Xero
    Reports-API response -- skips the trailing 'Totals' section every Xero report ends with,
    which isn't a real contact/account and would otherwise be misparsed as one."""
    report = raw_report["Reports"][0]
    for row in report["Rows"]:
        if row.get("RowType") == "Section" and row.get("Title") != "Totals":
            yield row["Title"], row.get("Rows", [])


def _aging_rows(raw_report: dict, entity_id: str, batch_id: str, endpoint: str) -> pa.Table:
    """Shared parser for AgedReceivablesByContact/AgedPayablesByContact -- same nested
    Rows/Cells shape either way, just a different endpoint name and Bronze domain. Xero's
    Reports API is positional, not keyed: Cells[0]=Reference/invoice number, [1]=Date,
    [2]=Due Date, [3]=Total -- the real invoice UUID (when present) rides in Cells[3]'s
    Attributes rather than as its own cell."""
    now = datetime.now(timezone.utc)
    rows = []
    for contact_name, invoice_rows in _report_sections(raw_report):
        for r in invoice_rows:
            cells = r["Cells"]
            reference = cells[0]["Value"]
            total_cell = cells[3]
            invoice_id = next(
                (a["Value"] for a in total_cell.get("Attributes", []) if a.get("Id") == "invoiceID"),
                reference,
            )
            rows.append(
                {
                    "_ingested_at": now,
                    "_source_system": "xero",
                    "_source_file_or_endpoint": endpoint,
                    "_batch_id": batch_id,
                    "entity_id": entity_id,
                    "source_record_id": invoice_id,
                    "contact_name": contact_name,
                    "invoice_date": datetime.fromisoformat(cells[1]["Value"]).date(),
                    "due_date": datetime.fromisoformat(cells[2]["Value"]).date(),
                    "amount_outstanding": float(total_cell["Value"]),
                    "currency": None,  # Xero reports are in the org's base currency; Silver
                    # assigns it from dim_entity.functional_currency, same as normalize_journals.
                }
            )
    return pa.Table.from_pylist(rows, schema=AGING_SCHEMA)


def normalize_aged_receivables(raw_report: dict, entity_id: str, batch_id: str) -> pa.Table:
    return _aging_rows(raw_report, entity_id, batch_id, "Reports/AgedReceivablesByContact")


def normalize_aged_payables(raw_report: dict, entity_id: str, batch_id: str) -> pa.Table:
    return _aging_rows(raw_report, entity_id, batch_id, "Reports/AgedPayablesByContact")


def normalize_budget_summary(raw_report: dict, entity_id: str, batch_id: str, period: str) -> pa.Table:
    """`period` ('YYYY-MM') is passed in rather than parsed from the report, since
    BudgetSummary's period columns are formatted as human-readable month labels ('Jul-26') --
    the caller already knows which period it requested the report for."""
    now = datetime.now(timezone.utc)
    rows = []
    for _section_title, account_rows in _report_sections(raw_report):
        for r in account_rows:
            cells = r["Cells"]
            account_cell = cells[0]
            account_code = next(
                (a["Value"] for a in account_cell.get("Attributes", []) if a.get("Id") == "account"),
                None,
            )
            rows.append(
                {
                    "_ingested_at": now,
                    "_source_system": "xero",
                    "_source_file_or_endpoint": "Reports/BudgetSummary",
                    "_batch_id": batch_id,
                    "entity_id": entity_id,
                    "account_code": account_code,
                    "account_name": account_cell["Value"],
                    "period": period,
                    "budgeted_amount": float(cells[1]["Value"]),
                    "currency": None,
                }
            )
    return pa.Table.from_pylist(rows, schema=BUDGET_SCHEMA)
