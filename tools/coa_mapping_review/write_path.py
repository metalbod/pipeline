"""Appends approved mapping rows to dbt_project/seeds/seed_coa_mapping.csv -- the exact same file
a human edits by hand today. Never rewrites or reorders existing rows (append-only, matching this
file's established effective-dated correction convention and Bronze's append-only ethos
elsewhere in the repo). No git automation: `git add`/`commit`/`push` stays a separate, deliberate
human step afterward, same as this project's established pattern for tooling that touches
governed files.
"""

import csv
from datetime import datetime
from pathlib import Path

from filelock import FileLock

from tools.coa_mapping_review.validation import SEED_COA_MAPPING_PATH

COLUMNS = [
    "entity_id",
    "local_account_code",
    "local_account_name",
    "group_standard_account_code",
    "effective_from",
    "effective_to",
    "is_active",
    "approved_by",
    "approved_at",
]

LOCK_TIMEOUT_SECONDS = 30


def build_row(proposal_row: dict, approved_by: str, approved_at: datetime | None = None) -> dict:
    """Turns one Approve-decision UI row into a governed seed_coa_mapping.csv row. `effective_to`
    is always blank -- v1 only supports adding new mappings, not superseding an existing one
    (flagged as future work in the plan)."""
    ts = approved_at or datetime.now()
    return {
        "entity_id": proposal_row["entity_id"],
        "local_account_code": proposal_row["local_account_code"],
        "local_account_name": proposal_row["local_account_name"],
        "group_standard_account_code": proposal_row["group_standard_account_code"],
        "effective_from": proposal_row["effective_from"],
        "effective_to": "",
        "is_active": "true",
        "approved_by": approved_by,
        "approved_at": ts.isoformat(timespec="seconds"),
    }


def append_rows(rows: list[dict], seed_path: Path = SEED_COA_MAPPING_PATH) -> int:
    """Appends `rows` (already in COLUMNS shape, e.g. from build_row()) to the seed file. Returns
    the number of rows written. Locked so a second concurrent reviewer's confirm can't interleave
    a partial write -- same per-file-lock pattern as ingestion/delta_writer.py's write_bronze()."""
    if not rows:
        return 0

    lock_path = str(seed_path) + ".lock"
    with FileLock(lock_path, timeout=LOCK_TIMEOUT_SECONDS):
        file_exists = seed_path.exists()
        with seed_path.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            if not file_exists:
                writer.writeheader()
            for row in rows:
                writer.writerow({col: row.get(col, "") for col in COLUMNS})
    return len(rows)
