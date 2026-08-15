"""One-time idempotent Superset bootstrap for Phase 3: registers the Gold datasets, creates the
Group Finance Owner / Regional Controller roles with correct dataset access, adds Row Level
Security filters, and creates the two pilot user accounts.

Runs *inside* the Superset container (has Flask app context + direct model access) --
role/user/permission management isn't exposed via Superset's REST API in this version (confirmed
by probing /api/v1/security/roles/ and /api/v1/security/users/, both 404), so this uses
Superset's internal security manager directly, the same mechanism `superset fab create-admin`
itself uses. Dataset/database registration goes through the ORM session directly too, for a
single consistent approach rather than mixing REST calls and in-process calls.

Invoke via: docker exec -i <superset-container> python /app/ops/setup_superset.py
"""

import os
import secrets

from superset.app import create_app

DUCKDB_PATH_IN_CONTAINER = "/app/warehouse.duckdb"
DATABASE_NAME = "Finance Platform Warehouse"

PER_ENTITY_DATASETS = [
    ("main_gold", "rpt_balance_sheet"),
    ("main_gold", "rpt_profit_and_loss"),
]
CONSOLIDATED_DATASETS = [
    ("main_gold", "rpt_balance_sheet_consolidated"),
    ("main_gold", "rpt_profit_and_loss_consolidated"),
]

GROUP_FINANCE_OWNER_ROLE = "Group Finance Owner"
REGIONAL_CONTROLLER_ROLE = "Regional Controller"

PILOT_USERS = [
    # (username/email, first, last, role)
    ("kenneth.yong@mandrill.com.my", "Kenneth", "Yong", GROUP_FINANCE_OWNER_ROLE),
    ("metalbod@gmail.com", "SG", "Controller", REGIONAL_CONTROLLER_ROLE),
]

RLS_CLAUSE_PER_ENTITY = (
    "entity_id in (select entity_id from main_silver.user_entity_access "
    "where username = '{{ current_username() }}')"
)
# Zero-row clause for consolidated datasets: only true for users whose governed role is
# GROUP_FINANCE_OWNER. Same source of truth as the per-entity filter, not a separate hardcoded
# rule -- if a user's role in user_entity_access ever changes, this reflects it automatically.
RLS_CLAUSE_CONSOLIDATED_BLOCK = (
    "'GROUP_FINANCE_OWNER' in (select role from main_silver.user_entity_access "
    "where username = '{{ current_username() }}')"
)


def get_or_create_role(sm, db_session, name, base_role_name=None):
    """`base_role_name`, if given, seeds a newly-created role with that role's full permission
    set (e.g. Gamma's base API/UI access) before any dataset-specific grants are added on top.
    Without this, a role with only `datasource_access` permissions can't even call the list/read
    API endpoints needed to use those datasets at all -- confirmed by testing: both pilot users
    got a blanket 403 until their roles were seeded from Gamma."""
    role = sm.find_role(name)
    if role is None:
        role = sm.add_role(name)
        if base_role_name:
            base_role = sm.find_role(base_role_name)
            role.permissions = list(base_role.permissions)
            db_session.commit()
        print(f"created role: {name}" + (f" (seeded from {base_role_name})" if base_role_name else ""))
    else:
        print(f"role already exists: {name}")
    return role


def get_or_create_database(db_session, sqla_utils_Database, name, uri):
    existing = db_session.query(sqla_utils_Database).filter_by(database_name=name).first()
    if existing:
        print(f"database connection already exists: {name}")
        return existing
    database = sqla_utils_Database(database_name=name, sqlalchemy_uri=uri)
    db_session.add(database)
    db_session.commit()
    print(f"created database connection: {name}")
    return database


def get_or_create_dataset(db_session, SqlaTable, database, schema, table_name):
    existing = (
        db_session.query(SqlaTable)
        .filter_by(database_id=database.id, schema=schema, table_name=table_name)
        .first()
    )
    if existing:
        print(f"dataset already exists: {schema}.{table_name}")
        return existing
    dataset = SqlaTable(database=database, schema=schema, table_name=table_name)
    db_session.add(dataset)
    db_session.commit()
    dataset.fetch_metadata()
    db_session.commit()
    print(f"created dataset: {schema}.{table_name}")
    return dataset


def grant_dataset_access(sm, db_session, role, dataset):
    """Grants the FAB `datasource_access` permission for one dataset to one role -- this is
    what makes/keeps a dataset visible to the role at all, on top of any RLS row filter."""
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
        # Re-assert tables/roles/clause even for an existing filter -- roles referenced by ID
        # under the hood, so if a role gets deleted and recreated (e.g. after a permission-set
        # change), an existing filter silently keeps pointing at the dead role and stops
        # applying at all. Confirmed by testing: this exact scenario produced unfiltered query
        # results with no error anywhere.
        existing.tables = tables
        existing.roles = roles
        existing.clause = clause
        db_session.commit()
        print(f"RLS filter already exists: {name} (re-asserted tables/roles/clause)")
        return existing
    rls = RowLevelSecurityFilter(
        name=name,
        filter_type="Regular",
        tables=tables,
        roles=roles,
        clause=clause,
    )
    db_session.add(rls)
    db_session.commit()
    print(f"created RLS filter: {name}")
    return rls


def get_or_create_user(sm, db_session, username, first, last, email, role):
    existing = sm.find_user(username=username)
    if existing:
        if role not in existing.roles:
            # Re-assert the role even for an existing user -- keeps this script idempotent in
            # the face of a role being recreated (e.g. after a permission-set change), which
            # would otherwise silently leave the user with no role at all.
            existing.roles = [role]
            db_session.commit()
            print(f"user already exists: {username} (re-assigned role {role.name})")
        else:
            print(f"user already exists: {username}")
        return existing, None
    password = secrets.token_urlsafe(16)
    user = sm.add_user(
        username=username,
        first_name=first,
        last_name=last,
        email=email,
        role=role,
        password=password,
    )
    print(f"created user: {username}")
    return user, password


def main():
    app = create_app()
    with app.app_context():
        from superset.extensions import db
        from superset.models.core import Database
        from superset.connectors.sqla.models import RowLevelSecurityFilter, SqlaTable

        sm = app.appbuilder.sm
        session = db.session

        # duckdb-engine forwards URL query params through as DuckDB `SET <name> = <value>`
        # pragmas, not as duckdb.connect() kwargs -- `read_only` isn't a settable DuckDB pragma
        # (confirmed against duckdb_settings()), `access_mode=read_only` is the real one.
        database = get_or_create_database(
            session,
            Database,
            DATABASE_NAME,
            f"duckdb:///{DUCKDB_PATH_IN_CONTAINER}?access_mode=read_only",
        )

        per_entity_ds = [
            get_or_create_dataset(session, SqlaTable, database, schema, table)
            for schema, table in PER_ENTITY_DATASETS
        ]
        consolidated_ds = [
            get_or_create_dataset(session, SqlaTable, database, schema, table)
            for schema, table in CONSOLIDATED_DATASETS
        ]

        owner_role = get_or_create_role(sm, session, GROUP_FINANCE_OWNER_ROLE, base_role_name="Gamma")
        controller_role = get_or_create_role(sm, session, REGIONAL_CONTROLLER_ROLE, base_role_name="Gamma")

        print("Granting dataset access...")
        for ds in per_entity_ds + consolidated_ds:
            grant_dataset_access(sm, session, owner_role, ds)
        for ds in per_entity_ds:
            grant_dataset_access(sm, session, controller_role, ds)
        # Regional Controller intentionally does NOT get datasource_access on the consolidated
        # datasets -- no permission granted here at all. The zero-row RLS filter below is
        # defense in depth in case that ever changes, not the primary control.

        print("Creating RLS filters...")
        get_or_create_rls_filter(
            session,
            RowLevelSecurityFilter,
            name="Per-entity access (Regional Controller)",
            tables=per_entity_ds,
            roles=[controller_role],
            clause=RLS_CLAUSE_PER_ENTITY,
        )
        get_or_create_rls_filter(
            session,
            RowLevelSecurityFilter,
            name="Block consolidated for non-owners",
            tables=consolidated_ds,
            roles=[controller_role],
            clause=RLS_CLAUSE_CONSOLIDATED_BLOCK,
        )

        print("Creating pilot users...")
        credentials = []
        for username, first, last, role_name in PILOT_USERS:
            role = owner_role if role_name == GROUP_FINANCE_OWNER_ROLE else controller_role
            user, password = get_or_create_user(sm, session, username, first, last, username, role)
            if password:
                credentials.append((username, password))

        if credentials:
            print("\n=== New user credentials (relay securely, have them rotate) ===")
            for username, password in credentials:
                print(f"  {username}: {password}")
        print("\nDone.")


if __name__ == "__main__":
    main()
