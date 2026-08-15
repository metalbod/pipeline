from dagster import Definitions
from dagster_dbt import DbtCliResource

from . import schedules, sensors
from .assets import (
    dbt_project,
    file_upload_journal_bronze,
    finance_platform_dbt_assets,
    openmetadata_dbt_catalog_sync,
    xero_accounts_bronze,
    xero_journals_bronze,
)
from .resources import XeroClientResource

defs = Definitions(
    assets=[
        finance_platform_dbt_assets,
        xero_accounts_bronze,
        xero_journals_bronze,
        file_upload_journal_bronze,
        openmetadata_dbt_catalog_sync,
    ],
    sensors=[sensors.sg_sub_journal_file_sensor, sensors.email_on_run_failure],
    schedules=[schedules.xero_daily_schedule, schedules.late_file_arrival_schedule],
    resources={
        "dbt": DbtCliResource(project_dir=dbt_project),
        "xero": XeroClientResource(),
    },
)
