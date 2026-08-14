import json
from pathlib import Path

import pandera.polars as pa
import polars as pl
import pytest

from data_quality.pandera_schemas.xero_accounts_schema import XeroAccountsSchema
from data_quality.pandera_schemas.xero_journal_lines_schema import XeroJournalLinesSchema
from ingestion.api_connectors.xero import normalize

FIXTURES = Path(__file__).parent.parent.parent / "ingestion/api_connectors/xero/fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_normalized_accounts_pass_schema():
    table = normalize.normalize_accounts(_fixture("accounts.json")["Accounts"], "MY-PARENT", "b1")
    XeroAccountsSchema.validate(pl.from_arrow(table))


def test_normalized_journal_lines_pass_schema():
    table = normalize.normalize_journals(_fixture("journals.json")["Journals"], "MY-PARENT", "b1")
    XeroJournalLinesSchema.validate(pl.from_arrow(table))


def test_journal_lines_schema_rejects_negative_amount():
    table = normalize.normalize_journals(_fixture("journals.json")["Journals"], "MY-PARENT", "b1")
    df = pl.from_arrow(table)
    bad = df.with_row_index("_i").with_columns(
        pl.when(pl.col("_i") == 0).then(-1.0).otherwise(pl.col("debit_amount")).alias("debit_amount")
    ).drop("_i")
    with pytest.raises(pa.errors.SchemaError):
        XeroJournalLinesSchema.validate(bad)
