import dagster as dg

from ingestion.file_connectors.journal_file_reader import process_upload


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
