I want to build the financial data platform described in @ARCHITECTURE.md. Read it in full first.

Start with Phase 0 (Foundations) from the Implementation Roadmap section: set up the repo
structure described in the "How to Use Claude Code to Build and Operate This" section, initialize
a Dagster project and a dbt-core project on DuckDB, stand up local object storage (MinIO, or a
local filesystem stand-in for now if that's simpler to start), and create the `dim_entity` and
`dim_account_group_standard` tables plus an empty, effective-dated COA mapping table for the pilot
subsidiaries I'll specify.

Enter plan mode and propose a concrete, file-by-file plan for Phase 0 only. Confirm the plan with
me before implementing anything. Do not start Phase 1 work yet.
