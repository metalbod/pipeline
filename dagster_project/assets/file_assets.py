import dagster as dg

from ingestion.file_connectors.aging_file_reader import process_upload as process_aging_upload
from ingestion.file_connectors.budget_file_reader import process_upload as process_budget_upload
from ingestion.file_connectors.journal_file_reader import process_upload
from ingestion.file_connectors.pipeline_file_reader import process_upload as process_pipeline_upload


class JournalFileUploadConfig(dg.Config):
    file_path: str
    entity_id: str


@dg.asset(
    group_name="bronze_file_upload",
    description="Validates + lands one uploaded journal Excel/CSV file into Bronze (SG-SUB).",
)
def file_upload_journal_bronze(
    context: dg.AssetExecutionContext, config: JournalFileUploadConfig
) -> dg.MaterializeResult:
    result = process_upload(config.file_path, config.entity_id)
    return dg.MaterializeResult(
        metadata={
            "journal_lines_row_count": result["journal_lines_row_count"],
            "accounts_row_count": result["accounts_row_count"],
            "batch_id": result["batch_id"],
        }
    )


class PipelineFileUploadConfig(dg.Config):
    file_path: str
    entity_id: str


@dg.asset(
    group_name="bronze_file_upload",
    description="Validates + lands one uploaded sales-pipeline Excel/CSV file into Bronze. "
    "Finance-entered estimate, not live CRM data.",
)
def file_upload_pipeline_bronze(
    context: dg.AssetExecutionContext, config: PipelineFileUploadConfig
) -> dg.MaterializeResult:
    result = process_pipeline_upload(config.file_path, config.entity_id)
    return dg.MaterializeResult(
        metadata={
            "pipeline_snapshot_row_count": result["pipeline_snapshot_row_count"],
            "batch_id": result["batch_id"],
        }
    )


class AgingFileUploadConfig(dg.Config):
    file_path: str
    entity_id: str
    doctype: str


@dg.asset(
    group_name="bronze_file_upload",
    description="Validates + lands one uploaded AR/AP aging Excel/CSV file into Bronze (SG-SUB). "
    "doctype selects ar_aging vs ap_aging -- same shape either way.",
)
def file_upload_aging_bronze(
    context: dg.AssetExecutionContext, config: AgingFileUploadConfig
) -> dg.MaterializeResult:
    result = process_aging_upload(config.file_path, config.entity_id, config.doctype)
    return dg.MaterializeResult(
        metadata={
            "row_count": result["row_count"],
            "batch_id": result["batch_id"],
            "doctype": config.doctype,
        }
    )


class BudgetFileUploadConfig(dg.Config):
    file_path: str
    entity_id: str


@dg.asset(
    group_name="bronze_file_upload",
    description="Validates + lands one uploaded budget Excel/CSV file into Bronze (SG-SUB).",
)
def file_upload_budget_bronze(
    context: dg.AssetExecutionContext, config: BudgetFileUploadConfig
) -> dg.MaterializeResult:
    result = process_budget_upload(config.file_path, config.entity_id)
    return dg.MaterializeResult(
        metadata={
            "row_count": result["row_count"],
            "batch_id": result["batch_id"],
        }
    )
