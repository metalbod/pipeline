"""Common Bronze schemas that every connector (Xero, file uploads, future sources) converges
on -- ARCHITECTURE.md §5: 'both paths converge into the same Bronze schema-per-domain, which
is what makes a single Silver transformation layer viable regardless of source.'
"""

import pyarrow as pa

ACCOUNTS_SCHEMA = pa.schema(
    [
        ("_ingested_at", pa.timestamp("us", tz="UTC")),
        ("_source_system", pa.string()),
        ("_source_file_or_endpoint", pa.string()),
        ("_batch_id", pa.string()),
        ("entity_id", pa.string()),
        ("local_account_code", pa.string()),
        ("local_account_name", pa.string()),
        ("local_account_type", pa.string()),
    ]
)

JOURNAL_LINES_SCHEMA = pa.schema(
    [
        ("_ingested_at", pa.timestamp("us", tz="UTC")),
        ("_source_system", pa.string()),
        ("_source_file_or_endpoint", pa.string()),
        ("_batch_id", pa.string()),
        ("entity_id", pa.string()),
        ("source_record_id", pa.string()),
        ("journal_id", pa.string()),
        ("line_no", pa.int64()),
        ("account_code", pa.string()),
        ("account_name", pa.string()),
        ("debit_amount", pa.float64()),
        ("credit_amount", pa.float64()),
        ("currency", pa.string()),
        ("description", pa.string()),
        ("posted_at", pa.date32()),
        ("source_updated_at", pa.timestamp("us", tz="UTC")),
    ]
)

# Finance-entered estimate, not live CRM data -- see ingestion/file_connectors/pipeline_file_reader.py.
PIPELINE_SNAPSHOT_SCHEMA = pa.schema(
    [
        ("_ingested_at", pa.timestamp("us", tz="UTC")),
        ("_source_system", pa.string()),
        ("_source_file_or_endpoint", pa.string()),
        ("_batch_id", pa.string()),
        ("entity_id", pa.string()),
        ("period", pa.string()),
        ("pipeline_stage", pa.string()),
        ("deal_count", pa.int64()),
        ("total_contract_value", pa.float64()),
        ("currency", pa.string()),
    ]
)

# Shared by both AR and AP aging -- one open-item grain, converged from Xero's
# AgedReceivablesByContact/AgedPayablesByContact reports and SG-SUB's aging file uploads, same
# "both paths converge into the same Bronze schema-per-domain" principle as accounts/journal_lines.
AGING_SCHEMA = pa.schema(
    [
        ("_ingested_at", pa.timestamp("us", tz="UTC")),
        ("_source_system", pa.string()),
        ("_source_file_or_endpoint", pa.string()),
        ("_batch_id", pa.string()),
        ("entity_id", pa.string()),
        ("source_record_id", pa.string()),
        ("contact_name", pa.string()),
        ("invoice_date", pa.date32()),
        ("due_date", pa.date32()),
        ("amount_outstanding", pa.float64()),
        ("currency", pa.string()),
    ]
)

BUDGET_SCHEMA = pa.schema(
    [
        ("_ingested_at", pa.timestamp("us", tz="UTC")),
        ("_source_system", pa.string()),
        ("_source_file_or_endpoint", pa.string()),
        ("_batch_id", pa.string()),
        ("entity_id", pa.string()),
        ("account_code", pa.string()),
        ("account_name", pa.string()),
        ("period", pa.string()),
        ("budgeted_amount", pa.float64()),
        ("currency", pa.string()),
    ]
)
