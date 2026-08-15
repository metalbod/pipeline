"""Bronze writer: appends normalized rows into a domain-level Delta table.

Bronze is append-only (CLAUDE.md) -- this module only ever appends. Corrections are new
rows/versions, never mutations. Each domain (e.g. "journal_lines", "accounts") gets one Delta
table that every source (Xero, file uploads, future connectors) appends into, matching
ARCHITECTURE.md §5's "both paths converge into the same Bronze schema-per-domain". The Delta
table's own version history plus the `_source_system`/`_batch_id` columns on every row are the
audit trail -- see the raw-dump helpers below for the separate as-received archival copy.
"""

import json
import os
import random
import time
import uuid
from datetime import datetime, timezone

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake
from deltalake.exceptions import DeltaError
from filelock import FileLock

from ingestion.object_store import bronze_api_path, bronze_delta_table_path, bronze_file_path

MAX_COMMIT_RETRIES = 5
LOCK_TIMEOUT_SECONDS = 30


def new_batch_id() -> str:
    return uuid.uuid4().hex


def write_bronze(domain: str, table: pa.Table, mode: str = "append") -> str:
    """Append `table` to the Bronze Delta table for `domain`. Returns the table path.

    Multiple ingestion sources can land near-simultaneously in practice (several file uploads
    processed at once, a scheduled API pull overlapping a sensor-triggered run) -- concurrent
    writers to the *same* domain's Delta table is a real, expected scenario, not an edge case.
    Delta Lake's own optimistic concurrency handles two processes racing at the storage-commit
    level, but under heavier simultaneous contention that surfaced as a hard crash of the
    writing process rather than a catchable conflict exception in testing -- not something a
    Python-level retry can recover from once the process is gone. A cross-process file lock
    scoped per domain (not global -- writes to different domains, e.g. journal_lines vs.
    accounts, still proceed in parallel) removes the race by construction instead of hoping
    retries paper over it. The retry loop stays as defense-in-depth for the ordinary,
    catchable DeltaError case.
    """
    path = bronze_delta_table_path(domain)
    os.makedirs(path, exist_ok=True)
    lock_path = path.rstrip("/\\") + ".lock"

    with FileLock(lock_path, timeout=LOCK_TIMEOUT_SECONDS):
        for attempt in range(MAX_COMMIT_RETRIES):
            try:
                write_deltalake(path, table, mode=mode)
                return path
            except DeltaError:
                if attempt == MAX_COMMIT_RETRIES - 1:
                    raise
                time.sleep(0.2 * (2**attempt) + random.uniform(0, 0.1))
    return path


def read_bronze(domain: str) -> pa.Table:
    path = bronze_delta_table_path(domain)
    return DeltaTable(path).to_pyarrow_table()


def archive_raw_api_response(
    source_system: str, entity_id: str, endpoint: str, batch_id: str, payload: object
) -> str:
    """Dumps the as-received API payload verbatim for replay/audit -- ARCHITECTURE.md §3:
    'any downstream bug can be replayed from the original data'. Never overwritten."""
    load_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dir_path = bronze_api_path(source_system, entity_id, endpoint, load_date)
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, f"{batch_id}.json")
    with open(file_path, "w") as f:
        json.dump(payload, f)
    return file_path


def archive_raw_file_upload(entity_id: str, doctype: str, received_filename: str, raw_bytes: bytes) -> str:
    """Versions the accepted upload file verbatim before any parsing -- never overwritten,
    so 'what changed since last month's upload' is always answerable (ARCHITECTURE.md §5)."""
    dir_path = bronze_file_path(entity_id, doctype)
    os.makedirs(dir_path, exist_ok=True)
    received_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem, ext = os.path.splitext(received_filename)
    file_path = os.path.join(dir_path, f"{stem}_{received_at}{ext}")
    with open(file_path, "wb") as f:
        f.write(raw_bytes)
    return file_path
