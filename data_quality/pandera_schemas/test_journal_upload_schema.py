import datetime

import polars as pl
import pandera.polars as pa
import pytest

from data_quality.pandera_schemas.journal_upload_schema import JournalUploadSchema


def _valid_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "journal_id": ["J1", "J1"],
            "line_no": [0, 1],
            "account_code": ["610", "200"],
            "account_name": ["Accounts Receivable", "Sales"],
            "debit_amount": [100.0, 0.0],
            "credit_amount": [0.0, 100.0],
            "currency": ["SGD", "SGD"],
            "description": ["Invoice 1", "Invoice 1"],
            "posted_at": [datetime.date(2026, 7, 1), datetime.date(2026, 7, 1)],
        }
    )


def test_valid_journal_upload_passes():
    validated = JournalUploadSchema.validate(_valid_df())
    assert validated.shape == (2, 9)


def test_negative_amount_rejected():
    df = _valid_df().with_columns(pl.Series("debit_amount", [-100.0, 0.0]))
    with pytest.raises(pa.errors.SchemaError):
        JournalUploadSchema.validate(df)


def test_both_debit_and_credit_nonzero_rejected():
    df = _valid_df().with_columns(pl.Series("credit_amount", [50.0, 100.0]))
    with pytest.raises(pa.errors.SchemaError):
        JournalUploadSchema.validate(df)


def test_neither_debit_nor_credit_set_rejected():
    df = _valid_df().with_columns(pl.Series("debit_amount", [0.0, 0.0]))
    with pytest.raises(pa.errors.SchemaError):
        JournalUploadSchema.validate(df)


def test_invalid_currency_length_rejected():
    df = _valid_df().with_columns(pl.Series("currency", ["S", "SGD"]))
    with pytest.raises(pa.errors.SchemaError):
        JournalUploadSchema.validate(df)


def test_null_required_field_rejected():
    df = _valid_df().with_columns(pl.Series("account_code", ["610", None]))
    with pytest.raises(pa.errors.SchemaError):
        JournalUploadSchema.validate(df)


def test_unexpected_extra_column_rejected():
    df = _valid_df().with_columns(pl.lit("x").alias("unexpected_column"))
    with pytest.raises(pa.errors.SchemaError):
        JournalUploadSchema.validate(df)
