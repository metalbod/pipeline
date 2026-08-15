"""Shared SMTP alerting utility. dagster.make_email_on_run_failure_sensor (used in
dagster_project/sensors/failure_alert_sensor.py) covers run failures directly; this covers
proactive checks that aren't themselves a failing run -- e.g. a file that simply hasn't arrived
yet (dagster_project/schedules/late_file_arrival_check.py).
"""

import os
import smtplib
from email.mime.text import MIMEText


class AlertingConfigError(RuntimeError):
    """Raised when required SMTP config is missing."""


def send_alert_email(subject: str, body: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT") or 587)
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    email_to = os.environ.get("ALERT_EMAIL_TO")

    missing = [
        name
        for name, value in [
            ("SMTP_USER", smtp_user),
            ("SMTP_PASSWORD", smtp_password),
            ("ALERT_EMAIL_TO", email_to),
        ]
        if not value
    ]
    if missing:
        raise AlertingConfigError(
            f"{', '.join(missing)} must be set in the environment (see .env.example) to send alerts."
        )

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = email_to

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [email_to], message.as_string())
