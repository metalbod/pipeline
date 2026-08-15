from pathlib import Path

import polars as pl
import pytest

from ingestion.file_connectors import aging_file_reader as reader

AR_TEMPLATE = Path(__file__).parent / "templates" / "ar_aging_upload_template.csv"
AP_TEMPLATE = Path(__file__).parent / "templates" / "ap_aging_upload_template.csv"


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_ROOT", str(tmp_path / "storage"))


def test_process_upload_ar_happy_path(tmp_path):
    upload = tmp_path / "SG-SUB_ar_aging_2026-07_20260814T120000Z.csv"
    upload.write_bytes(AR_TEMPLATE.read_bytes())

    result = reader.process_upload(str(upload), "SG-SUB", "ar_aging")

    assert result["row_count"] == 1

    from ingestion.delta_writer import read_bronze

    rows = read_bronze("ar_aging").to_pylist()
    assert rows[0]["source_record_id"] == "INV-2001"
    assert rows[0]["amount_outstanding"] == 1500.0


def test_process_upload_ap_happy_path(tmp_path):
    upload = tmp_path / "SG-SUB_ap_aging_2026-07_20260814T120000Z.csv"
    upload.write_bytes(AP_TEMPLATE.read_bytes())

    result = reader.process_upload(str(upload), "SG-SUB", "ap_aging")

    assert result["row_count"] == 1

    from ingestion.delta_writer import read_bronze

    rows = read_bronze("ap_aging").to_pylist()
    assert rows[0]["contact_name"] == "Singapore Office Supplies Pte Ltd"


def test_process_upload_rejects_unknown_doctype(tmp_path):
    upload = tmp_path / "SG-SUB_ar_aging_2026-07_20260814T120000Z.csv"
    upload.write_bytes(AR_TEMPLATE.read_bytes())

    with pytest.raises(ValueError, match="doctype"):
        reader.process_upload(str(upload), "SG-SUB", "not_a_real_doctype")


def test_process_upload_quarantines_invalid_file(tmp_path):
    bad_df = pl.read_csv(AR_TEMPLATE, try_parse_dates=True).with_columns(
        pl.Series("amount_outstanding", [-1500.0])
    )
    upload = tmp_path / "SG-SUB_ar_aging_2026-07_bad.csv"
    bad_df.write_csv(upload)

    with pytest.raises(reader.AgingFileValidationError):
        reader.process_upload(str(upload), "SG-SUB", "ar_aging")

    assert not upload.exists()
    quarantine_dir = Path(reader.landing_path("SG-SUB", "ar_aging")) / "_quarantine"
    assert (quarantine_dir / upload.name).exists()
