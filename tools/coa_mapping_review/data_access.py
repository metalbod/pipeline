"""Read-only DuckDB access for the review UI's dropdowns (dim_account_group_standard, dim_entity).

Same connection pattern as dashboards/streamlit_app/app.py's get_connection()/load_df() -- this
tool never writes to the warehouse. The actual write path (write_path.py) goes straight to
dbt_project/seeds/seed_coa_mapping.csv on disk, not through DuckDB.
"""

import os

import duckdb
import polars as pl
import streamlit as st

DUCKDB_PATH = os.environ.get("DUCKDB_PATH", "./storage/warehouse.duckdb")


class WarehouseNotBuiltError(Exception):
    """Raised when a Silver table isn't in the warehouse yet -- surfaced as a clear instruction
    to run `dbt build`, not an opaque DuckDB traceback."""


@st.cache_resource
def get_connection():
    return duckdb.connect(DUCKDB_PATH, read_only=True)


def load_df(query: str, params: list | None = None) -> pl.DataFrame:
    try:
        return get_connection().execute(query, params or []).pl()
    except duckdb.Error as exc:
        raise WarehouseNotBuiltError(
            "Could not read from the warehouse -- run `dbt build` from dbt_project first "
            f"to populate it. ({exc})"
        ) from exc


def list_entities() -> pl.DataFrame:
    return load_df("select entity_id, entity_name from main_silver.dim_entity order by entity_id")


def list_group_standard_codes() -> pl.DataFrame:
    return load_df(
        "select group_standard_code, account_name from main_silver.dim_account_group_standard "
        "order by group_standard_code"
    )
