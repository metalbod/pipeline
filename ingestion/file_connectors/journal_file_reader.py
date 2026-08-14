"""Excel/CSV journal-entry file connector (SG-SUB and future entities).

Template: landing/{entity_id}/journals/{entity_id}_journals_{period}_{received_at}.xlsx (or
.csv), columns: journal_id, line_no, account_code, account_name, debit_amount, credit_amount,
currency, description, posted_at.

Validated against JournalUploadSchema *before* acceptance -- ARCHITECTURE.md §5: quarantine and
alert on files that fail validation, never silently drop rows. The original file is versioned
into Bronze on success (delta_writer.archive_raw_file_upload) so "what changed since last
month's upload" is always answerable.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from data_quality.pandera_schemas.journal_upload_schema import JournalUploadSchema
from ingestion.bronze_schemas import ACCOUNTS_SCHEMA, JOURNAL_LINES_SCHEMA
from ingestion.delta_writer import archive_raw_file_upload, new_batch_id, write_bronze
from ingestion.object_store import landing_path

DOCTYPE = "journals"


class JournalFileValidationError(Exception):
    """Raised when an uploaded journal file fails the Pandera schema. The file is quarantined,
    not silently dropped -- see quarantine_file()."""


# Account/journal codes are often numeric-looking ("610") but must stay strings -- letting
# polars infer their dtype would silently turn "0610" into 610 and lose leading zeros.
_STRING_COLUMNS = {"journal_id", "account_code", "account_name", "currency", "description"}


def _read_journal_file(file_path: Path) -> pl.DataFrame:
    overrides = {col: pl.Utf8 for col in _STRING_COLUMNS}
    if file_path.suffix.lower() == ".csv":
        df = pl.read_csv(file_path, schema_overrides=overrides, try_parse_dates=True)
    else:
        df = pl.read_excel(file_path, schema_overrides=overrides)
    if df.schema.get("posted_at") != pl.Date:
        df = df.with_columns(pl.col("posted_at").str.to_date())
    return df


def quarantine_file(entity_id: str, file_path: Path) -> Path:
    quarantine_dir = Path(landing_path(entity_id, DOCTYPE)) / "_quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    dest = quarantine_dir / file_path.name
    shutil.move(str(file_path), str(dest))
    return dest


def _normalize_journal_lines(df: pl.DataFrame, entity_id: str, batch_id: str, source_file: str) -> pl.DataFrame:
    now = datetime.now(timezone.utc)
    return df.with_columns(
        pl.lit(now).alias("_ingested_at"),
        pl.lit("file_upload").alias("_source_system"),
        pl.lit(source_file).alias("_source_file_or_endpoint"),
        pl.lit(batch_id).alias("_batch_id"),
        pl.lit(entity_id).alias("entity_id"),
        (pl.lit(entity_id) + ":" + pl.col("journal_id") + ":" + pl.col("line_no").cast(pl.Utf8)).alias(
            "source_record_id"
        ),
        pl.lit(now).alias("source_updated_at"),
    ).select([f.name for f in JOURNAL_LINES_SCHEMA])


def _derive_local_accounts(df: pl.DataFrame, entity_id: str, batch_id: str, source_file: str) -> pl.DataFrame:
    """SG-SUB has no separate COA export in Phase 1's scope -- its local COA for the mapping
    step is derived from the distinct accounts seen in ingested journal files."""
    now = datetime.now(timezone.utc)
    return (
        df.select("account_code", "account_name")
        .unique()
        .rename({"account_code": "local_account_code", "account_name": "local_account_name"})
        .with_columns(
            pl.lit(now).alias("_ingested_at"),
            pl.lit("file_upload").alias("_source_system"),
            pl.lit(source_file).alias("_source_file_or_endpoint"),
            pl.lit(batch_id).alias("_batch_id"),
            pl.lit(entity_id).alias("entity_id"),
            pl.lit(None, dtype=pl.Utf8).alias("local_account_type"),
        )
        .select([f.name for f in ACCOUNTS_SCHEMA])
    )


def process_upload(file_path: str, entity_id: str) -> dict:
    """Validates, archives, normalizes, and appends one uploaded journal file to Bronze.

    On Pandera failure, quarantines the file and raises JournalFileValidationError -- callers
    (the Dagster sensor/asset) should let this propagate as a run failure + alert, not swallow it.
    """
    path = Path(file_path)
    raw_bytes = path.read_bytes()

    try:
        df = _read_journal_file(path)
        JournalUploadSchema.validate(df)
    except Exception as exc:
        # Broad on purpose: a file that can't even be parsed (merged header cells, wrong sheet
        # shape, ...) is exactly the "notoriously inconsistent Excel upload" case
        # ARCHITECTURE.md §5 says to quarantine, not crash the pipeline on.
        quarantined_to = quarantine_file(entity_id, path)
        raise JournalFileValidationError(
            f"{path.name} failed validation and was quarantined to {quarantined_to}: {exc}"
        ) from exc

    batch_id = new_batch_id()
    archive_raw_file_upload(entity_id, DOCTYPE, path.name, raw_bytes)

    journal_lines_df = _normalize_journal_lines(df, entity_id, batch_id, path.name)
    accounts_df = _derive_local_accounts(df, entity_id, batch_id, path.name)

    journal_lines_path = write_bronze("journal_lines", journal_lines_df.to_arrow().cast(JOURNAL_LINES_SCHEMA))
    accounts_path = write_bronze("accounts", accounts_df.to_arrow().cast(ACCOUNTS_SCHEMA))

    return {
        "batch_id": batch_id,
        "journal_lines_row_count": journal_lines_df.height,
        "accounts_row_count": accounts_df.height,
        "journal_lines_path": journal_lines_path,
        "accounts_path": accounts_path,
    }
