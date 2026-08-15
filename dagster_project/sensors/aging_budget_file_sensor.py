"""Watches storage/landing/SG-SUB/{ar_aging,ap_aging,budget}/ for new uploads -- SG-SUB only,
since MY-PARENT gets this data from Xero's Reports API instead (see xero_assets.py). Same
"month-end files don't arrive on a schedule the pipeline controls" reasoning as
sg_sub_journal_file_sensor.
"""

import json
from pathlib import Path

import dagster as dg

from dagster_project.assets.file_assets import (
    AgingFileUploadConfig,
    BudgetFileUploadConfig,
    file_upload_aging_bronze,
    file_upload_budget_bronze,
)
from ingestion.object_store import landing_path

ENTITY_ID = "SG-SUB"
AGING_DOCTYPES = ["ar_aging", "ap_aging"]
BUDGET_DOCTYPE = "budget"


def _candidate_files(doctype: str) -> list[Path]:
    watch_dir = Path(landing_path(ENTITY_ID, doctype))
    if not watch_dir.exists():
        return []
    return [f for f in watch_dir.iterdir() if f.is_file() and f.parent.name != "_quarantine"]


@dg.sensor(
    target=file_upload_aging_bronze,
    minimum_interval_seconds=30,
    default_status=dg.DefaultSensorStatus.RUNNING,
    description="Watches storage/landing/SG-SUB/{ar_aging,ap_aging}/ for new uploads.",
)
def sg_sub_aging_file_sensor(context: dg.SensorEvaluationContext):
    seen = set(json.loads(context.cursor)) if context.cursor else set()
    candidate_files = [(doctype, f) for doctype in AGING_DOCTYPES for f in _candidate_files(doctype)]
    new_files = [(doctype, f) for doctype, f in candidate_files if str(f) not in seen]

    if not new_files:
        return dg.SkipReason("No new files.")

    run_requests = [
        dg.RunRequest(
            run_key=str(f),
            run_config=dg.RunConfig(
                ops={
                    file_upload_aging_bronze.op.name: AgingFileUploadConfig(
                        file_path=str(f), entity_id=ENTITY_ID, doctype=doctype
                    )
                }
            ),
        )
        for doctype, f in new_files
    ]

    seen |= {str(f) for _doctype, f in new_files}
    context.update_cursor(json.dumps(sorted(seen)))
    return run_requests


@dg.sensor(
    target=file_upload_budget_bronze,
    minimum_interval_seconds=30,
    default_status=dg.DefaultSensorStatus.RUNNING,
    description="Watches storage/landing/SG-SUB/budget/ for new uploads.",
)
def sg_sub_budget_file_sensor(context: dg.SensorEvaluationContext):
    seen = set(json.loads(context.cursor)) if context.cursor else set()
    new_files = [f for f in _candidate_files(BUDGET_DOCTYPE) if str(f) not in seen]

    if not new_files:
        return dg.SkipReason("No new files.")

    run_requests = [
        dg.RunRequest(
            run_key=str(f),
            run_config=dg.RunConfig(
                ops={
                    file_upload_budget_bronze.op.name: BudgetFileUploadConfig(
                        file_path=str(f), entity_id=ENTITY_ID
                    )
                }
            ),
        )
        for f in new_files
    ]

    seen |= {str(f) for f in new_files}
    context.update_cursor(json.dumps(sorted(seen)))
    return run_requests
