"""AR/AP aging Excel/CSV file connector (SG-SUB and future entities). One module for both
doctypes -- `ar_aging` and `ap_aging` are the same shape and converge on the same Bronze
AGING_SCHEMA as Xero's Aged*ByContact reports (ingestion/api_connectors/xero/normalize.py).

Template: landing/{entity_id}/{doctype}/{entity_id}_{doctype}_{period}_{received_at}.xlsx (or
.csv), columns: invoice_id, contact_name, invoice_date, due_date, amount_outstanding, currency.

Same validate -> quarantine-on-failure -> archive -> append-to-Bronze pattern as
journal_file_reader.py -- see that module's header for the ARCHITECTURE.md §5 rationale.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from data_quality.pandera_schemas.aging_upload_schema import AgingUploadSchema
from ingestion.bronze_schemas import AGING_SCHEMA
from ingestion.delta_writer import archive_raw_file_upload, new_batch_id, write_bronze
from ingestion.object_store import landing_path

VALID_DOCTYPES = {"ar_aging", "ap_aging"}

_STRING_COLUMNS = {"invoice_id", "contact_name", "currency"}


class AgingFileValidationError(Exception):
    """Raised when an uploaded aging file fails the Pandera schema. The file is quarantined,
    not silently dropped -- see quarantine_file()."""


def _read_aging_file(file_path: Path) -> pl.DataFrame:
    overrides = {col: pl.Utf8 for col in _STRING_COLUMNS}
    if file_path.suffix.lower() == ".csv":
        df = pl.read_csv(file_path, schema_overrides=overrides, try_parse_dates=True)
    else:
        df = pl.read_excel(file_path, schema_overrides=overrides)
    for date_col in ("invoice_date", "due_date"):
        if df.schema.get(date_col) != pl.Date:
            df = df.with_columns(pl.col(date_col).str.to_date())
    # xlsx round-trips whole-number decimals as an integer cell type -- cast explicitly.
    return df.with_columns(pl.col("amount_outstanding").cast(pl.Float64))


def quarantine_file(entity_id: str, doctype: str, file_path: Path) -> Path:
    quarantine_dir = Path(landing_path(entity_id, doctype)) / "_quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    dest = quarantine_dir / file_path.name
    shutil.move(str(file_path), str(dest))
    return dest


def _normalize_aging(df: pl.DataFrame, entity_id: str, batch_id: str, source_file: str) -> pl.DataFrame:
    now = datetime.now(timezone.utc)
    return df.with_columns(
        pl.lit(now).alias("_ingested_at"),
        pl.lit("file_upload").alias("_source_system"),
        pl.lit(source_file).alias("_source_file_or_endpoint"),
        pl.lit(batch_id).alias("_batch_id"),
        pl.lit(entity_id).alias("entity_id"),
        pl.col("invoice_id").alias("source_record_id"),
    ).select([f.name for f in AGING_SCHEMA])


def process_upload(file_path: str, entity_id: str, doctype: str) -> dict:
    """Validates, archives, normalizes, and appends one uploaded aging file to Bronze.
    `doctype` must be 'ar_aging' or 'ap_aging' -- selects the landing/Bronze domain, the file
    contents and validation are identical either way.

    On Pandera failure, quarantines the file and raises AgingFileValidationError -- callers
    (the Dagster sensor/asset) should let this propagate as a run failure + alert, not swallow it.
    """
    if doctype not in VALID_DOCTYPES:
        raise ValueError(f"doctype must be one of {VALID_DOCTYPES}, got {doctype!r}")

    path = Path(file_path)
    raw_bytes = path.read_bytes()

    try:
        df = _read_aging_file(path)
        AgingUploadSchema.validate(df)
    except Exception as exc:
        quarantined_to = quarantine_file(entity_id, doctype, path)
        raise AgingFileValidationError(
            f"{path.name} failed validation and was quarantined to {quarantined_to}: {exc}"
        ) from exc

    batch_id = new_batch_id()
    archive_raw_file_upload(entity_id, doctype, path.name, raw_bytes)

    aging_df = _normalize_aging(df, entity_id, batch_id, path.name)
    aging_path = write_bronze(doctype, aging_df.to_arrow().cast(AGING_SCHEMA))

    return {
        "batch_id": batch_id,
        "row_count": aging_df.height,
        "path": aging_path,
    }
