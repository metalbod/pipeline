"""Confirms email_on_run_failure actually fires: runs a real failing job against a temp
DagsterInstance, builds a genuine RunFailureSensorContext from its RUN_FAILURE event, and
invokes the sensor function -- only the SMTP transport is mocked (smtplib.SMTP_SSL, since the
sensor's default smtp_type is "SSL"), same "mock the wire, not our logic" pattern as
ingestion/test_alerting.py.
"""

import importlib
from unittest.mock import MagicMock, patch

import dagster as dg

import dagster_project.sensors.failure_alert_sensor as failure_alert_sensor_module


@dg.op
def failing_op():
    raise Exception("simulated dbt test failure for alert verification")


@dg.job
def failing_job():
    failing_op()


def test_email_on_run_failure_fires_for_a_real_failed_run(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "alerts@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "test-password")
    monkeypatch.setenv("ALERT_EMAIL_TO", "kenneth.yong@mandrill.com.my")

    # make_email_on_run_failure_sensor bakes credentials into the closure at module-import
    # time, and the module is typically already imported (with empty env) by the time a test
    # sets these -- reload so the sensor picks up the env vars set above, then reload again on
    # exit so the module doesn't keep test credentials baked in for the rest of the session.
    importlib.reload(failure_alert_sensor_module)
    email_on_run_failure = failure_alert_sensor_module.email_on_run_failure
    try:
        _run_test_body(email_on_run_failure)
    finally:
        monkeypatch.undo()
        importlib.reload(failure_alert_sensor_module)


def _run_test_body(email_on_run_failure):
    with dg.instance_for_test() as instance:
        result = failing_job.execute_in_process(instance=instance, raise_on_error=False)
        assert not result.success

        run = instance.get_run_by_id(result.run_id)
        [failure_entry] = instance.all_logs(run.run_id, of_type=dg.DagsterEventType.RUN_FAILURE)

        context = dg.build_run_status_sensor_context(
            sensor_name="email_on_run_failure",
            dagster_event=failure_entry.dagster_event,
            dagster_instance=instance,
            dagster_run=run,
        )

        with patch("dagster._utils.alert.smtplib.SMTP_SSL") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server

            email_on_run_failure(context)

            mock_smtp_cls.assert_called_once()
            mock_server.login.assert_called_once_with("alerts@example.com", "test-password")
            mock_server.sendmail.assert_called_once()

            args = mock_server.sendmail.call_args[0]
            assert args[0] == "alerts@example.com"
            assert args[1] == ["kenneth.yong@mandrill.com.my"]
            assert "failing_job" in args[2]
            assert "Steps failed" in args[2]
