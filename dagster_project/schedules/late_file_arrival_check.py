"""Daily check: has SG-SUB's journal file for the just-completed month landed by the cutoff
day? If not, emails directly via ingestion.alerting (not the run-failure sensor) -- a late file
is a business-process notice, not a pipeline malfunction, so it's kept semantically separate
from dagster_project/sensors/failure_alert_sensor.py's "something broke" alerts. This job itself
still succeeds either way; sending the alert is the point, not a failure state.

Not deduped: if the file is still missing, this fires again every day from the cutoff day
onward -- an intentional "keeps nagging until resolved" pattern, not a bug.
"""

import os
from datetime import datetime, timezone

import dagster as dg

from ingestion.alerting import send_alert_email
from ingestion.object_store import landing_path

ENTITY_ID = "SG-SUB"
DOCTYPE = "journals"
CUTOFF_DAY = 5  # alert if the previous month's file hasn't landed by this day of the month


def _previous_period(today) -> str:
    year, month = today.year, today.month
    if month == 1:
        year, month = year - 1, 12
    else:
        month -= 1
    return f"{year:04d}-{month:02d}"


def _file_has_arrived(watch_dir: str, period: str) -> bool:
    if not os.path.isdir(watch_dir):
        return False
    return any(
        period in name and os.path.isfile(os.path.join(watch_dir, name))
        for name in os.listdir(watch_dir)
    )


@dg.op
def check_late_file_arrival_op(context: dg.OpExecutionContext) -> None:
    today = datetime.now(timezone.utc)
    if today.day < CUTOFF_DAY:
        context.log.info(f"Before cutoff day {CUTOFF_DAY} of the month; nothing to check yet.")
        return

    period = _previous_period(today)
    watch_dir = landing_path(ENTITY_ID, DOCTYPE)

    if _file_has_arrived(watch_dir, period):
        context.log.info(f"{ENTITY_ID} {DOCTYPE} file for {period} found in {watch_dir}.")
        return

    send_alert_email(
        subject=f"Late file arrival: {ENTITY_ID} {DOCTYPE} for {period}",
        body=(
            f"No {DOCTYPE} file for {ENTITY_ID}, period {period}, has been found in "
            f"{watch_dir} as of {today.date()} (cutoff: day {CUTOFF_DAY} of the month)."
        ),
    )
    context.log.warning(f"Sent late-file alert for {ENTITY_ID} {period}.")


@dg.job
def check_late_file_arrival_job() -> None:
    check_late_file_arrival_op()


late_file_arrival_schedule = dg.ScheduleDefinition(
    name="late_file_arrival_check",
    job=check_late_file_arrival_job,
    cron_schedule="0 9 * * *",  # daily at 09:00
    default_status=dg.DefaultScheduleStatus.STOPPED,  # needs SMTP creds first, see .env.example
)
