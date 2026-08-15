from pathlib import Path

import polars as pl
import pytest

from ingestion.file_connectors import budget_file_reader as reader

VALID_TEMPLATE = Path(__file__).parent / "templates" / "budget_upload_template.csv"


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_ROOT", str(tmp_path / "storage"))


def _valid_df() -> pl.DataFrame:
    return pl.read_csv(VALID_TEMPLATE)


def test_process_upload_csv_happy_path(tmp_path):
    upload = tmp_path / "SG-SUB_budget_2026-07_20260814T120000Z.csv"
    upload.write_bytes(VALID_TEMPLATE.read_bytes())

    result = reader.process_upload(str(upload), "SG-SUB")

    assert result["row_count"] == 2

    from ingestion.delta_writer import read_bronze

    rows = read_bronze("budget").to_pylist()
    sales = next(r for r in rows if r["account_code"] == "200")
    assert sales["budgeted_amount"] == 1800.0


def test_process_upload_quarantines_invalid_file(tmp_path):
    bad_df = _valid_df().drop("currency")
    upload = tmp_path / "SG-SUB_budget_2026-07_bad.csv"
    bad_df.write_csv(upload)

    with pytest.raises(reader.BudgetFileValidationError):
        reader.process_upload(str(upload), "SG-SUB")

    assert not upload.exists()
    quarantine_dir = Path(reader.landing_path("SG-SUB", reader.DOCTYPE)) / "_quarantine"
    assert (quarantine_dir / upload.name).exists()
