"""Registers the additional datasets needed for the CFO financial-health dashboard on top of
Phase 3's base setup (setup_superset.py): the Net Cash Balance and DSO/DPO-approximation charts
reuse the existing rpt_balance_sheet/rpt_profit_and_loss datasets, but FX volatility and the
daily cash/revenue movement charts need datasets that don't exist yet.

Follows the same idempotent, in-process (not REST) pattern as setup_superset.py, for the same
reason stated there: role/RLS/dataset-access management isn't exposed via Superset's REST API in
this version.

Two of these are virtual (SQL-defined) datasets rather than passthroughs of a physical table:
  - vw_working_capital: joins AR/AP balances (rpt_balance_sheet) against revenue/expense
    (rpt_profit_and_loss) to approximate DSO/DPO. This is a *balance-based approximation*. Real
    DSO/DPO needs invoice-level aging data (due dates, per-invoice status), which nothing in this
    platform ingests -- see the "not buildable" list from the CFO-dashboard feasibility research.
  - vw_daily_cash_movement / vw_daily_revenue: aggregate fct_journal_line (which does carry a
    daily posted_at, unlike the monthly-grain Gold reports) by day, filtered to Cash &
    Equivalents / REVENUE accounts respectively. "Daily" reflects the finest grain the schema
    supports, not live/real-time data -- ingestion itself is still monthly-batch (Xero syncs +
    monthly file uploads), so these charts will show whatever the last batch landed, in daily
    buckets, not same-day activity.

Invoke via: docker exec -i <superset-container> python /app/ops/build_cfo_dashboard.py
"""

from superset.app import create_app

DUCKDB_PATH_IN_CONTAINER = "/app/warehouse.duckdb"
DATABASE_NAME = "Finance Platform Warehouse"

GROUP_FINANCE_OWNER_ROLE = "Group Finance Owner"
REGIONAL_CONTROLLER_ROLE = "Regional Controller"

# (schema, table_name) for a physical dataset, or (None, table_name) + sql for a virtual one.
PHYSICAL_DATASETS = [
    ("main_silver", "dim_fx_rate"),
    # Added once real COGS/debt-facility data existed (Phase 5's 12-entity/12-month demo data)
    # -- held back at first build since a permanently-0%/empty chart would have been misleading.
    ("main_gold", "rpt_gross_margin"),
    ("main_gold", "rpt_covenant_headroom"),
]

VIRTUAL_DATASETS = {
    "vw_working_capital": """
SELECT
    bs.entity_id,
    bs.entity_name,
    bs.fiscal_year,
    bs.fiscal_period,
    bs.period_end,
    ar.amount AS ar_balance,
    ap.amount AS ap_balance,
    pl.revenue,
    pl.expense,
    ROUND(ar.amount / NULLIF(pl.revenue, 0) * EXTRACT(day FROM last_day(bs.period_end)), 1) AS dso_days_approx,
    ROUND(ap.amount / NULLIF(pl.expense, 0) * EXTRACT(day FROM last_day(bs.period_end)), 1) AS dpo_days_approx
FROM (SELECT DISTINCT entity_id, entity_name, fiscal_year, fiscal_period, period_end FROM main_gold.rpt_balance_sheet) bs
LEFT JOIN (SELECT entity_id, fiscal_year, fiscal_period, amount FROM main_gold.rpt_balance_sheet WHERE account_name = 'Accounts Receivable') ar
  ON ar.entity_id = bs.entity_id AND ar.fiscal_year = bs.fiscal_year AND ar.fiscal_period = bs.fiscal_period
LEFT JOIN (SELECT entity_id, fiscal_year, fiscal_period, amount FROM main_gold.rpt_balance_sheet WHERE account_name = 'Accounts Payable') ap
  ON ap.entity_id = bs.entity_id AND ap.fiscal_year = bs.fiscal_year AND ap.fiscal_period = bs.fiscal_period
LEFT JOIN (
    SELECT entity_id, fiscal_year, fiscal_period,
           SUM(CASE WHEN account_type = 'REVENUE' THEN amount ELSE 0 END) AS revenue,
           SUM(CASE WHEN account_type = 'EXPENSE' THEN amount ELSE 0 END) AS expense
    FROM main_gold.rpt_profit_and_loss
    GROUP BY 1,2,3
) pl ON pl.entity_id = bs.entity_id AND pl.fiscal_year = bs.fiscal_year AND pl.fiscal_period = bs.fiscal_period
""".strip(),
    "vw_daily_cash_movement": """
SELECT
    jl.entity_id,
    e.entity_name,
    jl.posted_at AS movement_date,
    SUM(jl.debit_amount - jl.credit_amount) AS net_cash_movement,
    e.functional_currency
FROM main_silver.fct_journal_line jl
JOIN main_silver.dim_account_group_standard ag ON ag.account_key = jl.account_key
JOIN main_silver.dim_entity e ON e.entity_id = jl.entity_id
WHERE ag.account_subtype = 'Cash & Equivalents'
GROUP BY 1, 2, 3, 5
""".strip(),
    "vw_daily_revenue": """
SELECT
    jl.entity_id,
    e.entity_name,
    jl.posted_at AS movement_date,
    SUM(jl.credit_amount - jl.debit_amount) AS revenue_amount,
    e.functional_currency
FROM main_silver.fct_journal_line jl
JOIN main_silver.dim_account_group_standard ag ON ag.account_key = jl.account_key
JOIN main_silver.dim_entity e ON e.entity_id = jl.entity_id
WHERE ag.account_type = 'REVENUE'
GROUP BY 1, 2, 3, 5
""".strip(),
}

# entity_id-bearing datasets that need the same per-entity RLS as the Phase 3 base datasets.
ENTITY_SCOPED_VIRTUAL_DATASETS = ["vw_working_capital", "vw_daily_cash_movement", "vw_daily_revenue"]
ENTITY_SCOPED_PHYSICAL_DATASETS = ["rpt_gross_margin", "rpt_covenant_headroom"]

RLS_CLAUSE_PER_ENTITY = (
    "entity_id in (select entity_id from main_silver.user_entity_access "
    "where username = '{{ current_username() }}')"
)


def get_or_create_dataset(db_session, SqlaTable, database, schema, table_name, sql=None):
    existing = (
        db_session.query(SqlaTable)
        .filter_by(database_id=database.id, schema=schema, table_name=table_name)
        .first()
    )
    if existing:
        print(f"dataset already exists: {table_name}")
        return existing
    dataset = SqlaTable(database=database, schema=schema, table_name=table_name, sql=sql)
    db_session.add(dataset)
    db_session.commit()
    dataset.fetch_metadata()
    db_session.commit()
    print(f"created dataset: {table_name}" + (" (virtual)" if sql else ""))
    return dataset


def grant_dataset_access(sm, db_session, role, dataset):
    view_menu_name = dataset.get_perm()
    pv = sm.find_permission_view_menu("datasource_access", view_menu_name)
    if pv is None:
        pv = sm.add_permission_view_menu("datasource_access", view_menu_name)
    if pv not in role.permissions:
        sm.add_permission_role(role, pv)
        print(f"  granted datasource_access on {view_menu_name} to {role.name}")
    else:
        print(f"  {role.name} already has datasource_access on {view_menu_name}")


def get_or_create_rls_filter(db_session, RowLevelSecurityFilter, name, tables, roles, clause):
    existing = db_session.query(RowLevelSecurityFilter).filter_by(name=name).first()
    if existing:
        existing.tables = tables
        existing.roles = roles
        existing.clause = clause
        db_session.commit()
        print(f"RLS filter already exists: {name} (re-asserted tables/roles/clause)")
        return existing
    rls = RowLevelSecurityFilter(name=name, filter_type="Regular", tables=tables, roles=roles, clause=clause)
    db_session.add(rls)
    db_session.commit()
    print(f"created RLS filter: {name}")
    return rls


def main():
    app = create_app()
    with app.app_context():
        from superset.extensions import db
        from superset.models.core import Database
        from superset.connectors.sqla.models import RowLevelSecurityFilter, SqlaTable

        sm = app.appbuilder.sm
        session = db.session

        database = (
            session.query(Database).filter_by(database_name=DATABASE_NAME).first()
        )
        if database is None:
            raise RuntimeError(
                f"{DATABASE_NAME!r} database connection not found -- run setup_superset.py first."
            )

        owner_role = sm.find_role(GROUP_FINANCE_OWNER_ROLE)
        controller_role = sm.find_role(REGIONAL_CONTROLLER_ROLE)
        if owner_role is None or controller_role is None:
            raise RuntimeError("roles not found -- run setup_superset.py first.")

        print("Creating datasets...")
        new_datasets = {}
        for schema, table in PHYSICAL_DATASETS:
            new_datasets[table] = get_or_create_dataset(session, SqlaTable, database, schema, table)
        for table, sql in VIRTUAL_DATASETS.items():
            new_datasets[table] = get_or_create_dataset(session, SqlaTable, database, None, table, sql=sql)

        print("Granting dataset access (both roles get all new datasets -- FX rates aren't")
        print("entity-scoped, and the entity-scoped ones are protected by RLS below instead)...")
        for ds in new_datasets.values():
            grant_dataset_access(sm, session, owner_role, ds)
            grant_dataset_access(sm, session, controller_role, ds)

        print("Creating RLS filters for entity-scoped datasets...")
        entity_scoped = [
            new_datasets[t]
            for t in ENTITY_SCOPED_VIRTUAL_DATASETS + ENTITY_SCOPED_PHYSICAL_DATASETS
        ]
        get_or_create_rls_filter(
            session,
            RowLevelSecurityFilter,
            name="Per-entity access (Regional Controller) - CFO dashboard",
            tables=entity_scoped,
            roles=[controller_role],
            clause=RLS_CLAUSE_PER_ENTITY,
        )

        print("\nDone. Dataset IDs:")
        for name, ds in new_datasets.items():
            print(f"  {name}: {ds.id}")


if __name__ == "__main__":
    main()
