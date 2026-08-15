from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from dagster_project.schedules.late_file_arrival_check import check_late_file_arrival_job

LATE_DAY = datetime(2026, 8, 5, tzinfo=timezone.utc)  # on cutoff day, checking 2026-07
EARLY_DAY = datetime(2026, 8, 1, tzinfo=timezone.utc)  # before cutoff day


@pytest.fixture(autouse=True)
def _smtp_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "alerts@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "test-password")
    monkeypatch.setenv("ALERT_EMAIL_TO", "kenneth.yong@mandrill.com.my")
    monkeypatch.setenv("OBJECT_STORE_ROOT", str(tmp_path))


def _mock_smtp():
    patcher = patch("ingestion.alerting.smtplib.SMTP")
    mock_smtp_cls = patcher.start()
    mock_server = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_server
    return patcher, mock_server


def test_fires_alert_when_file_missing_past_cutoff():
    patcher, mock_server = _mock_smtp()
    try:
        with patch(
            "dagster_project.schedules.late_file_arrival_check.datetime"
        ) as mock_datetime:
            mock_datetime.now.return_value = LATE_DAY
            result = check_late_file_arrival_job.execute_in_process()
    finally:
        patcher.stop()

    assert result.success
    mock_server.sendmail.assert_called_once()
    args = mock_server.sendmail.call_args[0]
    assert "2026-07" in args[2]
    assert "SG-SUB" in args[2]


def test_no_alert_when_file_present(tmp_path):
    watch_dir = tmp_path / "landing" / "SG-SUB" / "journals"
    watch_dir.mkdir(parents=True)
    (watch_dir / "SG-SUB_journals_2026-07_20260803T101500.xlsx").write_text("stub")

    patcher, mock_server = _mock_smtp()
    try:
        with patch(
            "dagster_project.schedules.late_file_arrival_check.datetime"
        ) as mock_datetime:
            mock_datetime.now.return_value = LATE_DAY
            result = check_late_file_arrival_job.execute_in_process()
    finally:
        patcher.stop()

    assert result.success
    mock_server.sendmail.assert_not_called()


def test_no_alert_before_cutoff_day():
    patcher, mock_server = _mock_smtp()
    try:
        with patch(
            "dagster_project.schedules.late_file_arrival_check.datetime"
        ) as mock_datetime:
            mock_datetime.now.return_value = EARLY_DAY
            result = check_late_file_arrival_job.execute_in_process()
    finally:
        patcher.stop()

    assert result.success
    mock_server.sendmail.assert_not_called()
