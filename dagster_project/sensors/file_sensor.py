import json
from pathlib import Path

import dagster as dg

from dagster_project.assets.file_assets import JournalFileUploadConfig, file_upload_journal_bronze
from ingestion.object_store import landing_path

ENTITY_ID = "SG-SUB"
DOCTYPE = "journals"


def _watch_dir() -> Path:
    return Path(landing_path(ENTITY_ID, DOCTYPE))


@dg.sensor(
    target=file_upload_journal_bronze,
    minimum_interval_seconds=30,
    default_status=dg.DefaultSensorStatus.RUNNING,
    description="Watches storage/landing/SG-SUB/journals/ for new uploads -- month-end files "
    "don't arrive on a schedule the pipeline controls (ARCHITECTURE.md §5).",
)
def sg_sub_journal_file_sensor(context: dg.SensorEvaluationContext):
    watch_dir = _watch_dir()
    if not watch_dir.exists():
        return dg.SkipReason(f"{watch_dir} does not exist yet.")

    seen = set(json.loads(context.cursor)) if context.cursor else set()
    candidate_files = [
        f for f in watch_dir.iterdir() if f.is_file() and f.parent.name != "_quarantine"
    ]
    new_files = [f for f in candidate_files if f.name not in seen]

    if not new_files:
        return dg.SkipReason("No new files.")

    run_requests = [
        dg.RunRequest(
            run_key=f.name,
            run_config=dg.RunConfig(
                ops={
                    file_upload_journal_bronze.op.name: JournalFileUploadConfig(
                        file_path=str(f), entity_id=ENTITY_ID
                    )
                }
            ),
        )
        for f in new_files
    ]

    seen |= {f.name for f in new_files}
    context.update_cursor(json.dumps(sorted(seen)))
    return run_requests
