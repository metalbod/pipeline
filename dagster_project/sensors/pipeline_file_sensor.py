"""Watches storage/landing/*/pipeline/ for new sales-pipeline uploads, across every entity --
unlike the journals sensor (SG-SUB only, since MY-PARENT's journals come from Xero), no entity
has a CRM integration, so any entity's Finance team may drop a pipeline file here.
"""

import json
from pathlib import Path

import dagster as dg

from dagster_project.assets.file_assets import PipelineFileUploadConfig, file_upload_pipeline_bronze
from ingestion.object_store import store_root

DOCTYPE = "pipeline"


def _landing_root() -> Path:
    return Path(store_root()) / "landing"


@dg.sensor(
    target=file_upload_pipeline_bronze,
    minimum_interval_seconds=30,
    default_status=dg.DefaultSensorStatus.RUNNING,
    description="Watches storage/landing/*/pipeline/ for new sales-pipeline uploads, any entity.",
)
def pipeline_file_sensor(context: dg.SensorEvaluationContext):
    landing_root = _landing_root()
    if not landing_root.exists():
        return dg.SkipReason(f"{landing_root} does not exist yet.")

    seen = set(json.loads(context.cursor)) if context.cursor else set()
    candidate_files = [
        f
        for entity_dir in landing_root.iterdir()
        if entity_dir.is_dir()
        for f in (entity_dir / DOCTYPE).glob("*")
        if f.is_file() and f.parent.name != "_quarantine"
    ]
    new_files = [f for f in candidate_files if str(f) not in seen]

    if not new_files:
        return dg.SkipReason("No new files.")

    run_requests = [
        dg.RunRequest(
            run_key=str(f),
            run_config=dg.RunConfig(
                ops={
                    file_upload_pipeline_bronze.op.name: PipelineFileUploadConfig(
                        file_path=str(f), entity_id=f.parent.parent.name
                    )
                }
            ),
        )
        for f in new_files
    ]

    seen |= {str(f) for f in new_files}
    context.update_cursor(json.dumps(sorted(seen)))
    return run_requests
