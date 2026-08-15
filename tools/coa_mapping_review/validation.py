"""Pure validation functions for the reviewed batch, mirroring the dbt_utils.unique_combination_
of_columns test on (entity_id, local_account_code, effective_from) that already gates coa_mapping
(dbt_project/models/silver/properties.yml). No Streamlit/DuckDB dependency -- unit-testable on
their own, and this is a client-side mirror of that check, not a replacement for `dbt test`.

Only rows the caller has already filtered to decision == "Approve" should be passed in -- rejected
rows are excluded from the batch before it ever reaches these functions.
"""

import csv
from pathlib import Path

SEED_COA_MAPPING_PATH = (
    Path(__file__).resolve().parents[2] / "dbt_project" / "seeds" / "seed_coa_mapping.csv"
)

REQUIRED_FIELDS = ["entity_id", "local_account_code", "group_standard_account_code", "effective_from"]

BatchKey = tuple[str, str, str]


def read_existing_keys(seed_path: Path = SEED_COA_MAPPING_PATH) -> set[BatchKey]:
    """Reads (entity_id, local_account_code, effective_from) straight off disk -- not via DuckDB,
    which could be stale relative to a mapping written earlier in the same review session."""
    if not seed_path.exists():
        return set()
    with seed_path.open(newline="") as f:
        reader = csv.DictReader(f)
        return {
            (row["entity_id"], row["local_account_code"], row["effective_from"]) for row in reader
        }


def _row_key(row: dict) -> BatchKey:
    return (row.get("entity_id", ""), row.get("local_account_code", ""), row.get("effective_from", ""))


def find_missing_required_fields(batch_rows: list[dict]) -> dict[int, str]:
    errors: dict[int, str] = {}
    for i, row in enumerate(batch_rows):
        missing = [f for f in REQUIRED_FIELDS if not row.get(f)]
        if missing:
            errors[i] = f"Missing required field(s): {', '.join(missing)}."
    return errors


def find_invalid_group_standard_codes(batch_rows: list[dict], valid_codes: set[str]) -> dict[int, str]:
    errors: dict[int, str] = {}
    for i, row in enumerate(batch_rows):
        code = row.get("group_standard_account_code", "")
        if not code:
            continue  # already covered by find_missing_required_fields
        if code not in valid_codes:
            errors[i] = f"'{code}' is not a valid group-standard account code."
    return errors


def find_duplicate_keys(batch_rows: list[dict], existing_keys: set[BatchKey]) -> dict[int, str]:
    """Flags a row if its key collides with a row already in seed_coa_mapping.csv, or with an
    earlier row in this same batch (the first occurrence is left unflagged)."""
    errors: dict[int, str] = {}
    seen_in_batch: set[BatchKey] = set()
    for i, row in enumerate(batch_rows):
        key = _row_key(row)
        if not all(key):
            continue  # incomplete key, already covered by find_missing_required_fields
        if key in existing_keys:
            errors[i] = f"Duplicate of an existing mapping already in seed_coa_mapping.csv: {key}."
        elif key in seen_in_batch:
            errors[i] = f"Duplicate of another row in this batch: {key}."
        else:
            seen_in_batch.add(key)
    return errors


def validate_batch(
    batch_rows: list[dict], existing_keys: set[BatchKey], valid_group_standard_codes: set[str]
) -> dict[int, list[str]]:
    """Runs all checks. Returns {row_index: [messages]} for any row with a problem; an empty dict
    means the batch is clean and Confirm can be enabled."""
    all_errors: dict[int, list[str]] = {}
    for i, msg in find_missing_required_fields(batch_rows).items():
        all_errors.setdefault(i, []).append(msg)
    for i, msg in find_invalid_group_standard_codes(batch_rows, valid_group_standard_codes).items():
        all_errors.setdefault(i, []).append(msg)
    for i, msg in find_duplicate_keys(batch_rows, existing_keys).items():
        all_errors.setdefault(i, []).append(msg)
    return all_errors
