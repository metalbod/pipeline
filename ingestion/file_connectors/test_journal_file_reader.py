from pathlib import Path

import polars as pl
import pytest

from ingestion.file_connectors import journal_file_reader as reader

VALID_TEMPLATE = Path(__file__).parent / "templates" / "journal_upload_template.csv"


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_ROOT", str(tmp_path / "storage"))


def _valid_df() -> pl.DataFrame:
    return pl.read_csv(VALID_TEMPLATE, try_parse_dates=True)


def test_process_upload_csv_happy_path(tmp_path):
    upload = tmp_path / "SG-SUB_journals_2026-07_20260814T120000Z.csv"
    upload.write_bytes(VALID_TEMPLATE.read_bytes())

    result = reader.process_upload(str(upload), "SG-SUB")

    assert result["journal_lines_row_count"] == 4
    assert result["accounts_row_count"] == 4  # distinct account_code values: 610, 200, 400, 800


def test_process_upload_xlsx_happy_path(tmp_path):
    upload = tmp_path / "SG-SUB_journals_2026-07_20260814T120000Z.xlsx"
    _valid_df().write_excel(upload)

    result = reader.process_upload(str(upload), "SG-SUB")

    assert result["journal_lines_row_count"] == 4


def test_process_upload_quarantines_invalid_file(tmp_path):
    bad_df = _valid_df().with_columns(pl.Series("debit_amount", [-1500.0, 0.0, 320.75, 0.0]))
    upload = tmp_path / "SG-SUB_journals_2026-07_bad.csv"
    bad_df.write_csv(upload)

    with pytest.raises(reader.JournalFileValidationError):
        reader.process_upload(str(upload), "SG-SUB")

    assert not upload.exists()  # moved, not copied
    quarantine_dir = Path(reader.landing_path("SG-SUB", reader.DOCTYPE)) / "_quarantine"
    assert (quarantine_dir / upload.name).exists()


def test_process_upload_derives_local_accounts_from_journal_lines(tmp_path):
    upload = tmp_path / "SG-SUB_journals_2026-07_20260814T120000Z.csv"
    upload.write_bytes(VALID_TEMPLATE.read_bytes())

    result = reader.process_upload(str(upload), "SG-SUB")

    from ingestion.delta_writer import read_bronze

    accounts = read_bronze("accounts").to_pylist()
    codes = {a["local_account_code"] for a in accounts}
    assert codes == {"610", "200", "400", "800"}
    assert result["accounts_row_count"] == 4
