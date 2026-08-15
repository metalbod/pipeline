"""Phase 2 dashboard: per-entity and consolidated balance sheet + P&L.

Queries Gold directly (ARCHITECTURE.md §3: "no ad hoc SQL against Silver from the BI layer").
Per-entity views show each entity in its own functional currency; the consolidated view shows
the group reporting currency (MYR) after FX translation and intercompany elimination.
"""

import os

import duckdb
import polars as pl
import streamlit as st

st.set_page_config(page_title="Finance Platform", layout="wide")

DUCKDB_PATH = os.environ.get("DUCKDB_PATH", "./storage/warehouse.duckdb")
CONSOLIDATED = "__CONSOLIDATED__"
GROUP_CURRENCY = "MYR"


@st.cache_resource
def get_connection():
    return duckdb.connect(DUCKDB_PATH, read_only=True)


def load_df(query: str, params: list | None = None) -> pl.DataFrame:
    return get_connection().execute(query, params or []).pl()


st.title("Finance Platform — Phase 2")
st.caption(
    "Per-entity statements are shown in each entity's own functional currency. The consolidated "
    "view aggregates both entities into the group reporting currency, with intercompany balances "
    "eliminated."
)

entities = load_df(
    "select entity_id, entity_name, functional_currency from main_silver.dim_entity order by entity_id"
)
if entities.is_empty():
    st.warning("No entities found in dim_entity — has `dbt build` been run?")
    st.stop()

entity_options = {"Group (Consolidated)": CONSOLIDATED}
entity_options.update(
    {f"{r['entity_id']} — {r['entity_name']}": r["entity_id"] for r in entities.iter_rows(named=True)}
)
entity_label = st.sidebar.selectbox("Entity", options=list(entity_options.keys()))
entity_id = entity_options[entity_label]
is_consolidated = entity_id == CONSOLIDATED
currency = (
    GROUP_CURRENCY
    if is_consolidated
    else entities.filter(pl.col("entity_id") == entity_id)["functional_currency"][0]
)

bs_table = "main_gold.rpt_balance_sheet_consolidated" if is_consolidated else "main_gold.rpt_balance_sheet"
pnl_table = "main_gold.rpt_profit_and_loss_consolidated" if is_consolidated else "main_gold.rpt_profit_and_loss"
entity_filter = "" if is_consolidated else "where entity_id = ?"
entity_params = [] if is_consolidated else [entity_id]

periods = load_df(
    f"select distinct fiscal_year, fiscal_period, period_start from {bs_table} "
    f"{entity_filter} order by period_start desc",
    entity_params,
)
if periods.is_empty():
    st.info(f"No Gold data yet for {entity_label}. Ingest and `dbt build` first.")
    st.stop()

period_options = {
    f"{r['fiscal_year']}-{r['fiscal_period']:02d}": (r["fiscal_year"], r["fiscal_period"])
    for r in periods.iter_rows(named=True)
}
period_label = st.sidebar.selectbox("Period", options=list(period_options.keys()))
fiscal_year, fiscal_period = period_options[period_label]

period_filter = "fiscal_year = ? and fiscal_period = ?"
period_params = [fiscal_year, fiscal_period]
bs_where = " and ".join(f for f in [entity_filter.replace("where ", ""), period_filter] if f)
pnl_where = bs_where

bs = load_df(
    f"select account_name, account_type, amount from {bs_table} "
    f"where {bs_where} order by account_type, account_name",
    entity_params + period_params,
)
pnl = load_df(
    f"select account_name, account_type, amount from {pnl_table} "
    f"where {pnl_where} order by account_type, account_name",
    entity_params + period_params,
)

col1, col2 = st.columns(2)

with col1:
    st.subheader(f"Balance Sheet — {period_label} ({currency})")
    for account_type in ["ASSET", "LIABILITY", "EQUITY"]:
        subset = bs.filter(pl.col("account_type") == account_type)
        if subset.is_empty():
            continue
        st.markdown(f"**{account_type.title()}s**")
        st.dataframe(subset.select("account_name", "amount"), hide_index=True, use_container_width=True)
        st.caption(f"Total: {subset['amount'].sum():,.2f} {currency}")

    total_assets = bs.filter(pl.col("account_type") == "ASSET")["amount"].sum()
    total_liab_equity = bs.filter(pl.col("account_type").is_in(["LIABILITY", "EQUITY"]))["amount"].sum()
    balanced = abs(total_assets - total_liab_equity) < 0.01
    st.metric("Assets = Liabilities + Equity", "Balanced" if balanced else "OUT OF BALANCE")

with col2:
    st.subheader(f"Profit & Loss — {period_label} ({currency})")
    for account_type in ["REVENUE", "EXPENSE"]:
        subset = pnl.filter(pl.col("account_type") == account_type)
        if subset.is_empty():
            continue
        st.markdown(f"**{account_type.title()}**")
        st.dataframe(subset.select("account_name", "amount"), hide_index=True, use_container_width=True)
        st.caption(f"Total: {subset['amount'].sum():,.2f} {currency}")

    revenue = pnl.filter(pl.col("account_type") == "REVENUE")["amount"].sum()
    expense = pnl.filter(pl.col("account_type") == "EXPENSE")["amount"].sum()
    st.metric("Net Income", f"{revenue - expense:,.2f} {currency}")
