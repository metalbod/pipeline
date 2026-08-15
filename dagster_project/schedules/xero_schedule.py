import dagster as dg

from dagster_project.assets.xero_assets import (
    xero_accounts_bronze,
    xero_aged_payables_bronze,
    xero_aged_receivables_bronze,
    xero_budget_bronze,
    xero_journals_bronze,
)

xero_daily_job = dg.define_asset_job(
    name="xero_daily_ingest",
    selection=dg.AssetSelection.assets(
        xero_accounts_bronze,
        xero_journals_bronze,
        xero_aged_receivables_bronze,
        xero_aged_payables_bronze,
        xero_budget_bronze,
    ),
)

xero_daily_schedule = dg.ScheduleDefinition(
    name="xero_daily_schedule",
    job=xero_daily_job,
    # Hourly, not daily -- ARCHITECTURE.md §5's "daily incremental pulls" was the Phase 1
    # floor, not a ceiling; hourly gets MY-PARENT's cash/revenue charts meaningfully closer to
    # same-day without over-polling a low-volume API. SG-SUB stays file-upload/monthly --
    # structural, since it has no API to poll more often than a human uploads a file.
    cron_schedule="0 * * * *",
    default_status=dg.DefaultScheduleStatus.STOPPED,  # start paused; no live credentials yet
)
