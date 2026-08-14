import dagster as dg

from dagster_project.assets.xero_assets import xero_accounts_bronze, xero_journals_bronze

xero_daily_job = dg.define_asset_job(
    name="xero_daily_ingest",
    selection=dg.AssetSelection.assets(xero_accounts_bronze, xero_journals_bronze),
)

xero_daily_schedule = dg.ScheduleDefinition(
    name="xero_daily_schedule",
    job=xero_daily_job,
    cron_schedule="0 2 * * *",  # 02:00 daily -- ARCHITECTURE.md §5's "daily incremental pulls"
    default_status=dg.DefaultScheduleStatus.STOPPED,  # start paused; no live credentials yet
)
