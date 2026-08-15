"""Sales-pipeline Excel/CSV file connector. Finance-entered estimate of deal counts/contract
value moving through pipeline stages -- NOT live CRM data. No CRM system is integrated anywhere
in this platform (out of ARCHITECTURE.md §2's stated domains); this is the lightest-weight way to
get a directional pipeline-velocity signal without a new external integration.

Template: landing/{entity_id}/pipeline/{entity_id}_pipeline_{period}_{received_at}.xlsx (or
.csv), columns: period, pipeline_stage, deal_count, total_contract_value, currency.

Same validate -> quarantine-on-failure -> archive -> append-to-Bronze pattern as
journal_file_reader.py -- see that module's header for the ARCHITECTURE.md §5 rationale.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from data_quality.pandera_schemas.pipeline_upload_schema import PipelineUploadSchema
from ingestion.bronze_schemas import PIPELINE_SNAPSHOT_SCHEMA
from ingestion.delta_writer import archive_raw_file_upload, new_batch_id, write_bronze
from ingestion.object_store import landing_path

DOCTYPE = "pipeline"

_STRING_COLUMNS = {"period", "pipeline_stage", "currency"}


class PipelineFileValidationError(Exception):
    """Raised when an uploaded pipeline file fails the Pandera schema. The file is quarantined,
    not silently dropped -- see quarantine_file()."""


def _read_pipeline_file(file_path: Path) -> pl.DataFrame:
    overrides = {col: pl.Utf8 for col in _STRING_COLUMNS}
    if file_path.suffix.lower() == ".csv":
        df = pl.read_csv(file_path, schema_overrides=overrides)
    else:
        df = pl.read_excel(file_path, schema_overrides=overrides)
    # xlsx round-trips whole-number decimals (e.g. 25000.00) as an integer cell type -- cast
    # explicitly rather than relying on read-time type inference to guess "this is money".
    return df.with_columns(pl.col("total_contract_value").cast(pl.Float64))


def quarantine_file(entity_id: str, file_path: Path) -> Path:
    quarantine_dir = Path(landing_path(entity_id, DOCTYPE)) / "_quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    dest = quarantine_dir / file_path.name
    shutil.move(str(file_path), str(dest))
    return dest


def _normalize_pipeline_snapshot(df: pl.DataFrame, entity_id: str, batch_id: str, source_file: str) -> pl.DataFrame:
    now = datetime.now(timezone.utc)
    return df.with_columns(
        pl.lit(now).alias("_ingested_at"),
        pl.lit("file_upload").alias("_source_system"),
        pl.lit(source_file).alias("_source_file_or_endpoint"),
        pl.lit(batch_id).alias("_batch_id"),
        pl.lit(entity_id).alias("entity_id"),
    ).select([f.name for f in PIPELINE_SNAPSHOT_SCHEMA])


def process_upload(file_path: str, entity_id: str) -> dict:
    """Validates, archives, normalizes, and appends one uploaded pipeline file to Bronze.

    On Pandera failure, quarantines the file and raises PipelineFileValidationError -- callers
    (the Dagster sensor/asset) should let this propagate as a run failure + alert, not swallow it.
    """
    path = Path(file_path)
    raw_bytes = path.read_bytes()

    try:
        df = _read_pipeline_file(path)
        PipelineUploadSchema.validate(df)
    except Exception as exc:
        quarantined_to = quarantine_file(entity_id, path)
        raise PipelineFileValidationError(
            f"{path.name} failed validation and was quarantined to {quarantined_to}: {exc}"
        ) from exc

    batch_id = new_batch_id()
    archive_raw_file_upload(entity_id, DOCTYPE, path.name, raw_bytes)

    pipeline_df = _normalize_pipeline_snapshot(df, entity_id, batch_id, path.name)
    pipeline_path = write_bronze("pipeline_snapshot", pipeline_df.to_arrow().cast(PIPELINE_SNAPSHOT_SCHEMA))

    return {
        "batch_id": batch_id,
        "pipeline_snapshot_row_count": pipeline_df.height,
        "pipeline_snapshot_path": pipeline_path,
    }
