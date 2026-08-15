"""Creates the database/schema/table shells in OpenMetadata that the dbt ingestion then enriches
with lineage, docs, and test results.

Why this exists: OpenMetadata's dbt ingestion attaches metadata onto *existing* table entities
-- it doesn't create them from scratch (that's normally a live database connector's job, run
before dbt ingestion). Our DuckDB connector situation is unofficial-and-incompatible (see
duckdb_connector_spike.md), so this script does the connector's minimal job -- create real table
shells with real columns -- directly from dbt's own catalog.json, which already has full column
metadata for every model. Run once before the first dbt ingestion, and again if new
models/tables are added; re-running is idempotent (OpenMetadata's PUT-based create-or-update
semantics).

Usage: python ops/openmetadata/create_table_shells.py
Requires OPENMETADATA_BASE_URL, OPENMETADATA_JWT_TOKEN, DBT_TARGET_DIR in the environment.
"""

import json
import os

import httpx

SERVICE_NAME = "finance_platform_duckdb"
DATABASE_NAME = "warehouse"

# DuckDB catalog.json type strings -> OpenMetadata column dataType enum values.
TYPE_MAP = {
    "VARCHAR": "VARCHAR",
    "TIMESTAMP WITH TIME ZONE": "TIMESTAMPZ",
    "TIMESTAMP": "TIMESTAMP",
    "DATE": "DATE",
    "BOOLEAN": "BOOLEAN",
    "INTEGER": "INT",
    "BIGINT": "BIGINT",
    "DOUBLE": "DOUBLE",
    "FLOAT": "FLOAT",
}


def map_type(duckdb_type: str) -> str:
    if duckdb_type.startswith("DECIMAL"):
        return "DECIMAL"
    return TYPE_MAP.get(duckdb_type, "VARCHAR")


def main():
    base_url = os.environ["OPENMETADATA_BASE_URL"]
    token = os.environ["OPENMETADATA_JWT_TOKEN"]
    target_dir = os.environ["DBT_TARGET_DIR"]

    client = httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30.0,
    )

    catalog = json.load(open(os.path.join(target_dir, "catalog.json")))
    nodes = catalog["nodes"]

    # PUT, not POST: OpenMetadata's create-or-update semantics live on PUT (matches by name),
    # so re-running this script is idempotent -- POST is create-only and 409s on a second run.
    resp = client.put(
        "/v1/databases",
        json={"name": DATABASE_NAME, "service": SERVICE_NAME},
    )
    resp.raise_for_status()
    print(f"database: {DATABASE_NAME}")

    schemas_seen = set()
    for node in nodes.values():
        schema = node["metadata"]["schema"]
        if schema in schemas_seen:
            continue
        schemas_seen.add(schema)
        resp = client.put(
            "/v1/databaseSchemas",
            json={"name": schema, "database": f"{SERVICE_NAME}.{DATABASE_NAME}"},
        )
        resp.raise_for_status()
        print(f"  schema: {schema}")

    for node in nodes.values():
        meta = node["metadata"]
        schema = meta["schema"]
        table_name = meta["name"]
        columns = []
        for col in sorted(node["columns"].values(), key=lambda c: c["index"]):
            data_type = map_type(col["type"])
            column = {"name": col["name"], "dataType": data_type, "ordinalPosition": col["index"]}
            if data_type in ("VARCHAR", "CHAR", "BINARY", "VARBINARY"):
                # DuckDB VARCHAR is unbounded; OpenMetadata requires a length regardless.
                column["dataLength"] = 65535
            columns.append(column)
        resp = client.put(
            "/v1/tables",
            json={
                "name": table_name,
                "databaseSchema": f"{SERVICE_NAME}.{DATABASE_NAME}.{schema}",
                "columns": columns,
            },
        )
        if resp.status_code >= 400:
            print(f"  FAILED {schema}.{table_name}: {resp.status_code} {resp.text[:200]}")
        else:
            print(f"  table: {schema}.{table_name} ({len(columns)} columns)")

    client.close()
    print("Done.")


if __name__ == "__main__":
    main()
