from unittest.mock import MagicMock, patch

import pytest

from ingestion.alerting import AlertingConfigError, send_alert_email


@pytest.fixture(autouse=True)
def _smtp_env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "alerts@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "test-password")
    monkeypatch.setenv("ALERT_EMAIL_TO", "kenneth.yong@mandrill.com.my")


def test_send_alert_email_actually_sends():
    with patch("ingestion.alerting.smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        send_alert_email("Test Subject", "Test body")

        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("alerts@example.com", "test-password")
        mock_server.sendmail.assert_called_once()

        args = mock_server.sendmail.call_args[0]
        assert args[0] == "alerts@example.com"
        assert args[1] == ["kenneth.yong@mandrill.com.my"]
        assert "Test Subject" in args[2]
        assert "Test body" in args[2]


def test_send_alert_email_raises_clear_error_when_config_missing(monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    with pytest.raises(AlertingConfigError, match="SMTP_PASSWORD"):
        send_alert_email("Subject", "Body")
