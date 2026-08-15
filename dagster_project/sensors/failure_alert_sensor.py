"""Email alert on any run failure -- covers every hard-fail dbt test from Phases 1-2
(double-entry, unmapped/dropped journal lines, per-entity and consolidated balance sheet
equation, intercompany elimination net-to-zero) since a failing dbt test fails the whole run.
Also covers ingestion failures (Xero, file upload) for the same reason -- any run failing in
this repository is worth knowing about, not just dbt's.

Uses dagster.make_email_on_run_failure_sensor (first-party) rather than a hand-rolled SMTP
integration. No `monitored_jobs`/`monitor_all_code_locations` set -- the factory's default
behavior when both are omitted is exactly what we want: alert on any job failing in this single
code location.

Starts STOPPED: no real SMTP credentials exist yet (see .env.example) -- same pattern as the
Xero schedule in Phase 1. Flip to RUNNING (in the Dagster UI, or default_status here) once SMTP
credentials are configured.
"""

import os

import dagster as dg

email_on_run_failure = dg.make_email_on_run_failure_sensor(
    email_from=os.environ.get("SMTP_USER", ""),
    email_password=os.environ.get("SMTP_PASSWORD", ""),
    email_to=[os.environ.get("ALERT_EMAIL_TO", "")],
    smtp_host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
    smtp_port=int(os.environ["SMTP_PORT"]) if os.environ.get("SMTP_PORT") else None,
    smtp_user=os.environ.get("SMTP_USER"),
    name="email_on_run_failure",
    default_status=dg.DefaultSensorStatus.STOPPED,
)
