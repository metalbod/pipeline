"""Budget Excel/CSV file connector (SG-SUB and future entities). `account_code` flows through
the existing coa_mapping table in Silver (not re-derived here) so budgeted amounts land on the
same group_standard_code as actuals -- see dbt_project/models/silver/stg_budget.sql.

Template: landing/{entity_id}/budget/{entity_id}_budget_{period}_{received_at}.xlsx (or .csv),
columns: account_code, account_name, period, budgeted_amount, currency.

Same validate -> quarantine-on-failure -> archive -> append-to-Bronze pattern as
journal_file_reader.py -- see that module's header for the ARCHITECTURE.md §5 rationale.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from data_quality.pandera_schemas.budget_upload_schema import BudgetUploadSchema
from ingestion.bronze_schemas import BUDGET_SCHEMA
from ingestion.delta_writer import archive_raw_file_upload, new_batch_id, write_bronze
from ingestion.object_store import landing_path

DOCTYPE = "budget"

_STRING_COLUMNS = {"account_code", "account_name", "period", "currency"}


class BudgetFileValidationError(Exception):
    """Raised when an uploaded budget file fails the Pandera schema. The file is quarantined,
    not silently dropped -- see quarantine_file()."""


def _read_budget_file(file_path: Path) -> pl.DataFrame:
    overrides = {col: pl.Utf8 for col in _STRING_COLUMNS}
    if file_path.suffix.lower() == ".csv":
        df = pl.read_csv(file_path, schema_overrides=overrides)
    else:
        df = pl.read_excel(file_path, schema_overrides=overrides)
    # xlsx round-trips whole-number decimals as an integer cell type -- cast explicitly.
    return df.with_columns(pl.col("budgeted_amount").cast(pl.Float64))


def quarantine_file(entity_id: str, file_path: Path) -> Path:
    quarantine_dir = Path(landing_path(entity_id, DOCTYPE)) / "_quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    dest = quarantine_dir / file_path.name
    shutil.move(str(file_path), str(dest))
    return dest


def _normalize_budget(df: pl.DataFrame, entity_id: str, batch_id: str, source_file: str) -> pl.DataFrame:
    now = datetime.now(timezone.utc)
    return df.with_columns(
        pl.lit(now).alias("_ingested_at"),
        pl.lit("file_upload").alias("_source_system"),
        pl.lit(source_file).alias("_source_file_or_endpoint"),
        pl.lit(batch_id).alias("_batch_id"),
        pl.lit(entity_id).alias("entity_id"),
    ).select([f.name for f in BUDGET_SCHEMA])


def process_upload(file_path: str, entity_id: str) -> dict:
    """Validates, archives, normalizes, and appends one uploaded budget file to Bronze.

    On Pandera failure, quarantines the file and raises BudgetFileValidationError -- callers
    (the Dagster sensor/asset) should let this propagate as a run failure + alert, not swallow it.
    """
    path = Path(file_path)
    raw_bytes = path.read_bytes()

    try:
        df = _read_budget_file(path)
        BudgetUploadSchema.validate(df)
    except Exception as exc:
        quarantined_to = quarantine_file(entity_id, path)
        raise BudgetFileValidationError(
            f"{path.name} failed validation and was quarantined to {quarantined_to}: {exc}"
        ) from exc

    batch_id = new_batch_id()
    archive_raw_file_upload(entity_id, DOCTYPE, path.name, raw_bytes)

    budget_df = _normalize_budget(df, entity_id, batch_id, path.name)
    budget_path = write_bronze("budget", budget_df.to_arrow().cast(BUDGET_SCHEMA))

    return {
        "batch_id": batch_id,
        "row_count": budget_df.height,
        "path": budget_path,
    }
