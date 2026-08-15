from pathlib import Path

from tools.coa_mapping_review import validation

SEED_HEADER = (
    "entity_id,local_account_code,local_account_name,group_standard_account_code,"
    "effective_from,effective_to,is_active,approved_by,approved_at\n"
)
EXISTING_ROW = (
    "MY-PARENT,090,Business Bank Account,GS-1000,2026-08-14,,true,Kenneth Yong,"
    "2026-08-14T00:00:00\n"
)


def _write_seed(tmp_path: Path) -> Path:
    seed_path = tmp_path / "seed_coa_mapping.csv"
    seed_path.write_text(SEED_HEADER + EXISTING_ROW)
    return seed_path


def test_read_existing_keys(tmp_path):
    seed_path = _write_seed(tmp_path)
    keys = validation.read_existing_keys(seed_path)
    assert keys == {("MY-PARENT", "090", "2026-08-14")}


def test_read_existing_keys_missing_file(tmp_path):
    assert validation.read_existing_keys(tmp_path / "does_not_exist.csv") == set()


def _row(**overrides):
    row = {
        "entity_id": "MY-SUB-01",
        "local_account_code": "610",
        "local_account_name": "Accounts Receivable",
        "group_standard_account_code": "GS-1100",
        "effective_from": "2026-08-15",
    }
    row.update(overrides)
    return row


def test_find_missing_required_fields():
    errors = validation.find_missing_required_fields([_row(entity_id="")])
    assert 0 in errors
    assert "entity_id" in errors[0]


def test_find_missing_required_fields_none_missing():
    assert validation.find_missing_required_fields([_row()]) == {}


def test_find_invalid_group_standard_codes():
    errors = validation.find_invalid_group_standard_codes(
        [_row(group_standard_account_code="GS-9999")], valid_codes={"GS-1000", "GS-1100"}
    )
    assert 0 in errors


def test_find_invalid_group_standard_codes_valid():
    errors = validation.find_invalid_group_standard_codes(
        [_row(group_standard_account_code="GS-1100")], valid_codes={"GS-1000", "GS-1100"}
    )
    assert errors == {}


def test_find_invalid_group_standard_codes_skips_blank():
    # blank codes are the required-field check's job, not this one's
    errors = validation.find_invalid_group_standard_codes(
        [_row(group_standard_account_code="")], valid_codes={"GS-1000"}
    )
    assert errors == {}


def test_find_duplicate_keys_against_existing_file(tmp_path):
    existing_keys = validation.read_existing_keys(_write_seed(tmp_path))
    errors = validation.find_duplicate_keys(
        [_row(entity_id="MY-PARENT", local_account_code="090", effective_from="2026-08-14")],
        existing_keys,
    )
    assert 0 in errors


def test_find_duplicate_keys_within_batch():
    dup_row = _row()
    errors = validation.find_duplicate_keys([dup_row, dict(dup_row)], existing_keys=set())
    assert 0 not in errors  # first occurrence is unflagged
    assert 1 in errors


def test_find_duplicate_keys_no_duplicates():
    row_a = _row(local_account_code="610")
    row_b = _row(local_account_code="800")
    assert validation.find_duplicate_keys([row_a, row_b], existing_keys=set()) == {}


def test_validate_batch_clean():
    errors = validation.validate_batch(
        [_row()], existing_keys=set(), valid_group_standard_codes={"GS-1100"}
    )
    assert errors == {}


def test_validate_batch_collects_multiple_problems():
    bad_row = _row(entity_id="", group_standard_account_code="GS-9999")
    errors = validation.validate_batch(
        [bad_row], existing_keys=set(), valid_group_standard_codes={"GS-1100"}
    )
    assert len(errors[0]) == 2
