"""Runs OpenMetadata's dbt ingestion after each dbt build, so the catalog (models, lineage,
docs, test results) stays current automatically -- same "give the pipeline a check it can run"
pattern as everything else in this repo. Uses the officially-supported dbt manifest path, not
the unofficial DuckDB connector (see ops/openmetadata/duckdb_connector_spike.md).

Three steps, in order: `dbt docs generate` (produces catalog.json -- `dbt build` alone only
produces manifest.json/run_results.json), then create_table_shells.py (OpenMetadata's dbt
ingestion enriches *existing* tables, it doesn't create them -- this fills the gap a live
database connector would normally cover), then the actual dbt ingestion.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import dagster as dg

from dagster_project.assets.dbt_assets import dbt_project, finance_platform_dbt_assets

REPO_ROOT = Path(__file__).parent.parent.parent
OPS_DIR = REPO_ROOT / "ops" / "openmetadata"
INGESTION_TEMPLATE = OPS_DIR / "dbt_ingestion.yaml"

REQUIRED_ENV_VARS = ("OPENMETADATA_BASE_URL", "OPENMETADATA_JWT_TOKEN", "DBT_TARGET_DIR")


def _run(context: dg.AssetExecutionContext, cmd: list, **kwargs) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    context.log.info(result.stdout)
    if result.returncode != 0:
        context.log.error(result.stderr)
        raise dg.Failure(f"{' '.join(cmd)} failed (exit {result.returncode})")


@dg.asset(
    deps=[finance_platform_dbt_assets],
    group_name="catalog",
    description="Syncs the dbt manifest (models, lineage, docs, test results) into OpenMetadata.",
)
def openmetadata_dbt_catalog_sync(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    for var in REQUIRED_ENV_VARS:
        if not os.environ.get(var):
            raise dg.Failure(
                f"{var} must be set in the environment (see .env.example) to sync the "
                "OpenMetadata catalog."
            )

    _run(context, ["dbt", "docs", "generate"], cwd=dbt_project.project_dir)
    _run(context, ["python", str(OPS_DIR / "create_table_shells.py")], cwd=REPO_ROOT)

    rendered = os.path.expandvars(INGESTION_TEMPLATE.read_text())
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(rendered)
        rendered_path = f.name
    try:
        _run(context, ["metadata", "ingest", "-c", rendered_path], cwd=REPO_ROOT)
    finally:
        os.unlink(rendered_path)

    return dg.MaterializeResult()
