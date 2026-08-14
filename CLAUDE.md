# Project

Financial data platform: a medallion-architecture (Bronze/Silver/Gold) pipeline that consolidates
financial data from ERP/accounting APIs and Excel/CSV uploads across multiple subsidiaries into
business dashboards for the group's owners.

Full design: see `ARCHITECTURE.md` in this repo. Read it before starting any work — it is the
source of truth for the tech stack, data model, and phased roadmap.

# Stack

- Orchestration: Dagster (`dagster dev` to run the UI locally)
- Transformation: dbt-core on DuckDB (`dbt build`, `dbt test` from `/dbt_project`)
- Ingestion: Python (polars, httpx) — one connector per source system/file type
- Table format: Delta Lake (delta-rs) — confirmed in Phase 1; Bronze tables are appended via
  `deltalake.write_deltalake` and read by dbt-duckdb's `delta` plugin (`plugins: [{module: delta}]`
  in `profiles.yml`). Bronze dbt models over a Delta source must be `+materialized: table`, never
  `view` — the plugin registers an ephemeral in-process relation that a view's lazy re-query can't
  see from a fresh connection.
- Data quality: Pandera (dataframe contracts) + dbt tests (business rules)
- Dashboards: Streamlit (`/dashboards/streamlit_app`) + Superset/Metabase for self-serve

# Commands Claude can't guess

- `dagster dev` — start the orchestration UI locally
- `cd dbt_project && dbt build` — run all transformations
- `cd dbt_project && dbt test` — run all Silver/Gold data quality tests
- `pytest data_quality/` — run Pandera schema tests
- `pytest ingestion/` — run ingestion connector unit tests (mocked HTTP via `respx`, no live
  credentials needed)

# Non-negotiable rules

- Chart-of-accounts mappings are NEVER auto-applied to the production mapping table. Propose a
  mapping (see the `coa-mapper` subagent) but a human in Finance must approve it before it merges.
- Any change to `/dbt_project/models/silver` or `/gold` touching consolidation, elimination, FX
  translation, or COA logic must go through the `finance-reviewer` subagent before it's done.
- `Assets = Liabilities + Equity` is a hard invariant — never relax or skip this test to make a
  build pass.
- Bronze is append-only. Never mutate or delete Bronze data; corrections are new rows/versions.

# Workflow

- For anything touching consolidation or COA logic: explore -> plan (plan mode) -> implement ->
  adversarial review via `finance-reviewer`. Don't jump straight to code on these.
- Follow the phased roadmap in `ARCHITECTURE.md` (Implementation Roadmap section). Don't start
  Phase 2 (multi-subsidiary consolidation) work before Phase 1's single-entity vertical slice
  (one API connector + one file source -> Bronze -> Silver -> Gold -> a working dashboard) is
  built and passing its tests.

# Testing

- Every Silver/Gold dbt model needs a corresponding dbt test (see `dbt-test-writer` subagent).
- Every ingestion connector needs a Pandera schema.
- `dbt build && dbt test` must pass before any pipeline change is considered complete.
