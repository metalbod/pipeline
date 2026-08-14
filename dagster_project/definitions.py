from dagster import Definitions
from dagster_dbt import DbtCliResource

from .assets import dbt_project, finance_platform_dbt_assets

defs = Definitions(
    assets=[finance_platform_dbt_assets],
    resources={
        "dbt": DbtCliResource(project_dir=dbt_project),
    },
)
