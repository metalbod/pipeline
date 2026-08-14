# Solution Architecture: Financial Data Platform for Multi-Subsidiary Corporates

### Medallion Architecture on an Open-Source Python Stack, Built with Claude Code

Prepared for: Kenneth Yong — Platform Product Owner / Solution Architect
Date: 14 August 2026
Project: Data Engineering

---

## 1. Executive Summary

This document proposes a reference architecture for a data platform that ingests financial data — balance sheets, chart of accounts (COA), journal entries, and transaction ledgers — from a mix of APIs (ERP/accounting systems) and files (Excel/CSV extracts), and turns it into consolidated, trustworthy financial insights and dashboards for the owners of a large, multi-subsidiary corporate group.

The design rests on three decisions the request already fixes, plus the choices needed to make them concrete:

1. **Medallion architecture** (Bronze → Silver → Gold) as the data organizing principle, adapted to the specific pain points of multi-entity financial consolidation (chart-of-accounts mapping, intercompany eliminations, multi-currency translation, period close).
2. **Python, open source only** — a stack built from DuckDB, dbt-core, Dagster, Polars, Delta Lake/Apache Iceberg, Pandera, and Streamlit/Apache Superset, all runnable on a single VM or Kubernetes cluster with no proprietary licensing.
3. **Claude Code as the build-and-operate tool** — not just for writing the initial pipeline code, but as the standing engineering workflow for schema mapping, test generation, incident debugging, and ongoing maintenance as new subsidiaries and source systems are onboarded.

The rest of this document lays out the reference architecture, the technology choices and why, the financial data model, governance/security considerations for what is sensitive data, an implementation roadmap, and a concrete pattern for structuring the codebase so Claude Code is maximally effective on it.

---

## 2. Requirements Recap

| Dimension | Requirement |
|---|---|
| Architecture pattern | Medallion (Bronze / Silver / Gold) |
| Language/runtime | Python |
| Licensing | Open source only — no paid platform (Databricks/Snowflake/Fivetran, etc.) |
| Source systems | REST/SOAP APIs (accounting or ERP systems), plus manually supplied Excel/CSV files |
| Source data domains | Balance sheet, chart of accounts, journal entries, transaction/general ledger |
| Consumers | Business owners of a large corporate group with multiple subsidiaries |
| Output | Business insights and financial dashboards (consolidated and per-entity) |
| Build tool | Claude Code (agentic coding) |

Implicit requirements worth naming explicitly, because they shape the architecture more than the stated ones:

- **Multi-entity consolidation** is the hard part of this domain — not the plumbing. A chart of accounts that isn't standardized across subsidiaries will silently produce a wrong consolidated balance sheet. The Silver layer has to earn its keep here.
- **Auditability** — financial data attracts audit and compliance scrutiny. Every gold-layer number needs to be traceable back to a source journal line. Medallion architecture's layered lineage is a natural fit, but only if lineage is actually captured (see §7).
- **Mixed-cadence ingestion** — APIs typically update daily/intraday; Excel/CSV files are usually period-end manual drops (month-end journals, budget uploads). The pipeline has to tolerate both without becoming two separate systems.

---

## 3. Reference Architecture

```
                     ┌─────────────────────────────────────────────────────────┐
                     │                      ORCHESTRATION                      │
                     │                   Dagster (asset graph)                 │
                     └─────────────────────────────────────────────────────────┘
                                    │                      │
        ┌───────────────────────────┘                      └───────────────────────────┐
        ▼                                                                                ▼
┌───────────────────┐                                                         ┌────────────────────┐
│   API INGESTION    │                                                        │   FILE INGESTION    │
│  Python connectors  │                                                        │  watchdog / SFTP /  │
│  (requests/httpx),   │                                                       │  manual upload drop  │
│  Airbyte OSS for      │                                                      │  zone + openpyxl/    │
│  standard connectors   │                                                     │  polars readers      │
└───────────────────┘                                                         └────────────────────┘
        │                                                                                │
        └───────────────────────────┬───────────────────────────────────────────────────┘
                                     ▼
                     ┌─────────────────────────────────────────────────────────┐
                     │                     BRONZE (raw)                         │
                     │  Parquet on object storage (MinIO/S3), Delta Lake table   │
                     │  format. Append-only, schema-on-read, 1:1 with source.    │
                     │  Partitioned by entity_id / source_system / load_date.    │
                     └─────────────────────────────────────────────────────────┘
                                     │
                                     ▼   dbt-core + dbt-duckdb (or dbt-spark for scale)
                     ┌─────────────────────────────────────────────────────────┐
                     │                     SILVER (conformed)                   │
                     │  Cleaned, deduplicated, typed. COA mapped to group        │
                     │  standard chart. Multi-currency translated. Double-entry  │
                     │  validated. Slowly changing dimensions for entities/COA.  │
                     │  Data quality gates: Pandera schemas + dbt tests.         │
                     └─────────────────────────────────────────────────────────┘
                                     │
                                     ▼   dbt-core marts
                     ┌─────────────────────────────────────────────────────────┐
                     │                     GOLD (business marts)                │
                     │  Star schema: fact_journal_line, fact_balance,            │
                     │  dim_account, dim_entity, dim_period, dim_currency.        │
                     │  Consolidated + per-subsidiary balance sheet, P&L,         │
                     │  intercompany eliminations, KPI marts.                     │
                     └─────────────────────────────────────────────────────────┘
                                     │
                     ┌───────────────┴───────────────┐
                     ▼                                 ▼
          ┌────────────────────┐            ┌────────────────────────┐
          │  Streamlit / Dash    │            │   Apache Superset /      │
          │  bespoke exec         │           │   Metabase self-serve     │
          │  dashboards            │          │   BI for finance team      │
          └────────────────────┘            └────────────────────────┘

  Cross-cutting: data quality (Pandera/Great Expectations), catalog & lineage
  (OpenMetadata), secrets (Vault/SOPS), observability (Dagster UI + Prometheus/Grafana),
  version control + CI (git, GitHub Actions, Claude Code).
```

### Layer responsibilities

**Bronze (raw / landing).** Immutable, append-only copies of source data exactly as received: raw API JSON payloads and raw Excel/CSV files, converted to Parquet but not otherwise transformed. Every record carries `_ingested_at`, `_source_system`, `_source_file_or_endpoint`, and `_batch_id`. This layer exists so that any downstream bug can be replayed from the original data, and so auditors can be shown "this is exactly what the source system said on this date."

**Silver (cleaned / conformed).** This is where the actual financial engineering happens:
- Chart of accounts mapping: each subsidiary's local COA is mapped to a single group-standard COA via a maintained mapping table (see §6).
- Type and schema conformance (dates, decimals with correct precision for money, currency codes).
- Deduplication of journal entries (idempotent re-ingestion of the same file/API batch).
- Double-entry validation (debits = credits per journal batch) as an explicit, alertable check — not just a nice-to-have test.
- Multi-currency translation to a group reporting currency using an FX rate dimension.
- Slowly Changing Dimension (SCD Type 2) handling for entities and accounts, since subsidiaries get added/renamed/restructured over time.

**Gold (business marts).** Denormalized, dashboard-ready star schemas: a consolidated balance sheet mart, P&L mart, intercompany elimination mart, and KPI marts (working capital, liquidity ratios, DSO/DPO, entity-level and group-level). This is what Streamlit/Superset queries directly — no ad hoc SQL against Silver from the BI layer.

---

## 4. Technology Stack (Open Source, Python-First)

| Capability | Recommendation | Why |
|---|---|---|
| Orchestration | **Dagster** | Asset-based (not just task-based) orchestration maps naturally onto medallion layers — each Bronze/Silver/Gold table is a declared "software-defined asset" with explicit dependencies, so lineage is a first-class citizen, not bolted on. Has a free OSS edition, strong local dev experience, and native dbt integration. Prefect and Airflow are reasonable alternatives; Airflow is heavier and task-centric, Prefect is lighter but less opinionated about data assets. |
| API ingestion | **Python (`httpx`/`requests`) custom connectors**, with **Airbyte OSS** for any source that has a pre-built connector | Most accounting/ERP APIs (Xero, QuickBooks, NetSuite, SAP) are bespoke enough that a thin custom connector is more maintainable than fighting a generic tool; Airbyte is worth it only where a maintained connector already exists. |
| File ingestion | **`openpyxl`/`polars`/`pandas`** reading from a watched drop-zone (local folder, SFTP, or S3 prefix) | Polars is materially faster than pandas for large CSVs and has first-class Excel support via `polars.read_excel` (delegating to `openpyxl`/`fastexcel`); use pandas where a library (e.g. a bespoke Excel-with-macros template) only has pandas support. |
| Object storage | **MinIO** (self-hosted, S3-compatible) or cloud object storage if already available | Keeps the "open source only" constraint even if not fully self-hosted; MinIO gives an identical API to S3 so the same code runs on-prem or in any cloud later. |
| Table format | **Delta Lake (`delta-rs`/`deltalake` Python package)** or **Apache Iceberg (`pyiceberg`)** | ACID transactions, schema evolution, and time travel on top of Parquet — essential for a financial system where "what did the balance sheet say before that correction?" is a real question. Delta Lake has the simpler pure-Python path via `delta-rs`; Iceberg is the more vendor-neutral long-term bet if multi-engine access (Trino, Spark) is likely later. Either is a reasonable default; don't run both. |
| Transformation | **dbt-core** on **DuckDB** (`dbt-duckdb`) for Silver/Gold SQL transformations; **Polars** for pre-SQL cleansing that's awkward in SQL (e.g. messy Excel layouts, header detection) | DuckDB is the pragmatic choice for a single-node deployment processing what is, for even a large corporate group, a modest data volume (tens of millions of journal lines, not billions) — it's fast, embeddable, zero-ops, and reads Parquet/Delta directly. dbt gives version-controlled, tested, documented SQL transformations with built-in lineage graphs, which matters enormously for a finance audience that will ask "how was this number calculated." Migrate to `dbt-spark`/`dbt-databricks`-style engines only if volume genuinely outgrows a single node. |
| Data quality | **Pandera** for schema/dataframe-level contracts in Python code (e.g., "debit/credit columns must be non-negative decimals"); **dbt tests** (`not_null`, `relationships`, custom singular tests for debits=credits) at the SQL layer | Two layers by design: Pandera catches shape/type problems before data ever reaches Silver SQL models; dbt tests catch business-rule problems (referential integrity, balance rules) as the SQL is materialized. Great Expectations is a valid alternative to Pandera but is heavier to operate; Pandera's lighter-weight, type-hint-driven API fits a small platform team better. |
| Data catalog / lineage | **OpenMetadata** (optional but recommended once >1 team consumes the platform) | Auto-ingests lineage from dbt and Dagster, gives business users a searchable catalog of what "Gold.fct_balance_sheet" actually means. |
| Dashboards | **Streamlit** (or Plotly Dash) for curated executive dashboards; **Apache Superset** for self-serve exploration by the finance team | Streamlit/Dash for a small number of tightly designed views business owners open regularly (consolidated P&L, group balance sheet, entity drill-down); Superset for ad hoc slicing by finance analysts without needing developer involvement for every new chart. Metabase is a simpler, faster-to-stand-up alternative to Superset if the self-serve audience is small. |
| Secrets | **SOPS + age**, or **HashiCorp Vault OSS** | API keys for accounting systems and DB credentials must not sit in plaintext config, and financial data raises the bar on this from day one. |
| CI/CD & version control | **git + GitHub/GitLab Actions** | Runs dbt tests, Pandera checks, and (see §8) Claude Code–driven review on every pipeline change before it touches production data. |
| Observability | **Dagster UI** for pipeline runs/asset health; **Prometheus + Grafana** for infra metrics; structured logging via `structlog` | Dagster's asset catalog view doubles as a lightweight lineage/status dashboard for the platform team, distinct from the business-facing BI dashboards. |

This stack has no dependency on a paid vendor. It can run entirely on a single reasonably sized VM for a corporate group with a handful of subsidiaries, and scales out (swap DuckDB for a distributed engine, add Kubernetes for Dagster) only if and when volume demands it — avoid provisioning for a scale this workload is unlikely to need.

---

## 5. Ingestion Design: APIs and Files, One Pipeline

Both source types should land in the same Bronze structure so Silver doesn't need to know or care where data came from.

**API ingestion pattern:**
- One connector per source system, each a Dagster asset with its own schedule (daily incremental pulls using the source API's "modified since" or cursor-based pagination where available).
- Raw JSON responses persisted to Bronze as-received (e.g. `bronze/api/{source_system}/{entity_id}/{endpoint}/{load_date}/*.parquet` after a thin JSON→columnar conversion), so replays don't require re-calling the API.
- Idempotency via a `(source_system, entity_id, record_id, source_updated_at)` natural key so re-pulls don't duplicate.

**File ingestion pattern:**
- A defined drop zone per subsidiary/data type (e.g. `landing/{entity_id}/journals/`, `landing/{entity_id}/coa/`) that finance teams upload to (SFTP, a shared drive synced to object storage, or a simple internal upload portal).
- A Dagster sensor watches the drop zone and triggers ingestion on new files, rather than running on a fixed schedule — month-end files don't arrive on a schedule the pipeline controls.
- Because Excel files from finance teams are notoriously inconsistent (merged header cells, inserted subtotal rows, varying sheet names), the file ingestion asset should: (1) validate against an expected template with Pandera before accepting, (2) quarantine and alert on files that fail validation rather than silently dropping rows, and (3) version every accepted file into Bronze so a "what changed since last month's upload" diff is always possible.
- File naming/versioning convention (`{entity_id}_{doctype}_{period}_{received_at}.xlsx`) preserved into Bronze metadata for traceability.

Both paths converge into the same Bronze schema-per-domain (balance sheet, COA, journals, ledger), which is what makes a single Silver transformation layer viable regardless of source.

---

## 6. Financial Data Model

### 6.1 Chart of accounts standardization

The single highest-risk step in this whole pipeline. Recommended pattern:

- Maintain a **group-standard chart of accounts** as a governed table (`dim_account_group_standard`), owned by group finance, not derived automatically.
- Maintain a **mapping table** per subsidiary: `(entity_id, local_account_code, local_account_name) → group_standard_account_code`, version-controlled and effective-dated (accounts get remapped occasionally, e.g. after a restructuring).
- Unmapped local accounts should **fail loudly** in Silver (a dbt test that fails the run, or at minimum routes to a "needs mapping" exception mart) rather than being dropped or defaulted — an unmapped account silently excluded from a balance sheet is a worse failure mode than a broken pipeline run.
- Claude Code is a strong fit for the *initial* mapping exercise: given a subsidiary's local COA export and the group standard COA, it can propose a first-pass mapping (by name/code similarity and account type) for a human in finance to review and approve — turning a multi-day manual exercise into a review task. This should always remain human-approved, never auto-applied to production mappings.

### 6.2 Core Gold-layer star schema

```
dim_entity        (entity_id, entity_name, parent_entity_id, ownership_pct,
                    functional_currency, country, is_consolidated, effective_from/to)
dim_account       (account_key, group_standard_code, account_name, account_type
                    [asset/liability/equity/revenue/expense], account_subtype,
                    effective_from/to)   -- SCD Type 2
dim_period        (period_key, fiscal_year, fiscal_period, period_start, period_end,
                    is_closed)
dim_currency      (currency_code, currency_name)

fact_journal_line (journal_line_key, entity_id, account_key, period_key,
                    journal_id, line_no, debit_amount, credit_amount,
                    transaction_currency, functional_currency_amount,
                    group_currency_amount, fx_rate_used, source_system,
                    posted_at, is_intercompany, counterparty_entity_id)

fact_balance      (entity_id, account_key, period_key, opening_balance,
                    period_movement, closing_balance, group_currency_amount)

fact_intercompany_elimination (entity_id, counterparty_entity_id, account_key,
                    period_key, eliminated_amount)
```

`fact_journal_line` is the atomic, auditable grain — every consolidated number should be traceable to a `SUM()` over rows in this table. `fact_balance` is a derived, faster-to-query summary for dashboards (avoids re-aggregating millions of journal lines on every page load). Intercompany elimination is modeled explicitly rather than netted away silently, because business owners reviewing a consolidated balance sheet legitimately want to see what was eliminated and why.

### 6.3 Multi-subsidiary consolidation logic (Gold layer, dbt)

1. Translate each entity's local-currency balances to group currency using period-end (balance sheet) or period-average (P&L) FX rates from a maintained `dim_fx_rate` table.
2. Aggregate to group level by `group_standard_account_code` and `period_key`.
3. Apply intercompany eliminations (e.g. intercompany receivables/payables, intercompany revenue/COGS) via a rules table keyed on `(entity_id, counterparty_entity_id, account_type)`.
4. Apply minority-interest/ownership-percentage adjustments where a subsidiary isn't 100%-owned.
5. Produce the consolidated balance sheet and P&L marts, alongside the equivalent per-subsidiary (unconsolidated) marts, since owners will want both views.

This is genuinely one of the harder parts of financial data engineering — it's worth treating as its own dbt package with its own dedicated tests (e.g. "consolidated assets = consolidated liabilities + equity, always"), not an afterthought bolted onto Gold.

---

## 7. Data Quality, Lineage, and Governance

- **Double-entry integrity**: every ingested journal batch must balance (sum of debits = sum of credits); enforce as a hard gate in Silver, not a warning.
- **Balance sheet integrity**: `Assets = Liabilities + Equity` enforced as a Gold-layer dbt test on every entity and at group level, every run.
- **Completeness checks**: expected subsidiaries/periods present before a "period is closed" flag is set, so dashboards never show a partially-loaded month as final.
- **Lineage**: dbt's built-in DAG plus Dagster's asset lineage together give column-to-column and table-to-table lineage for free if the transformations are expressed as dbt models rather than ad hoc scripts — this is what will let the platform team answer "where did this number come from" during an audit without spelunking through code.
- **Access control**: financial data is sensitive; row-level security by entity (a regional controller sees their subsidiary, group finance/owners see everything) enforced at the Gold/BI layer, e.g. via Superset's row-level security or a dedicated read API in front of Gold tables.
- **Immutability & audit trail**: Bronze is append-only; Silver/Gold changes from corrections are versioned via the table format's time-travel (Delta/Iceberg), so "the balance sheet as it appeared before the restatement" is always recoverable — genuinely important for audit defensibility.
- **PII/sensitive data**: journal descriptions and vendor/customer names in ledgers can carry sensitive information; apply masking/redaction policy at Gold for any dashboard role that doesn't need it.

---

## 8. How to Use Claude Code to Build and Operate This

Claude Code is genuinely well-suited to this project, not just as a code generator but as the ongoing engineering workflow, if the repo is structured to take advantage of it.

**Repository structure that plays to Claude Code's strengths:**

```
/repo
  CLAUDE.md                     # commands, conventions Claude can't infer (see below)
  /ingestion
    /api_connectors/{system}/   # one connector per source system
    /file_connectors/
  /dbt_project
    /models/bronze/  /silver/  /gold/
    /tests/
  /dagster_project
    /assets/  /sensors/  /schedules/
  /data_quality
    /pandera_schemas/
  /dashboards
    /streamlit_app/
  .claude/
    /agents/                    # subagents (below)
    /skills/                    # reusable domain workflows (below)
  .github/workflows/            # CI: dbt test, pandera checks, adversarial review
```

**A `CLAUDE.md`** should capture what Claude can't infer from the code itself: how to run `dbt build` and `dagster dev` locally, the naming convention for Bronze/Silver/Gold tables, the rule that COA mappings are never auto-applied without human sign-off, and where the group-standard chart of accounts lives. Per the official guidance, keep it short — link to docs rather than duplicating them, and prune anything Claude already gets right without being told.

**Custom subagents worth defining** (`.claude/agents/`):
- A `coa-mapper` subagent, scoped to read-only tools, whose job is proposing chart-of-accounts mappings for human review (never to write directly to the production mapping table).
- A `dbt-test-writer` subagent for generating dbt tests and Pandera schemas from a model's intended business rules.
- A `finance-reviewer` subagent used as an adversarial reviewer on any change touching consolidation logic — a fresh-context review specifically checking that `Assets = Liabilities + Equity` still holds, that eliminations are still correct, and that no silent account was dropped.

**Custom skills worth defining** (`.claude/skills/`): a `new-subsidiary-onboarding` skill that walks through the steps of adding a new entity (COA mapping request, FX/currency setup, dbt model updates, dashboard entity filter) as a repeatable checklist Claude can execute against, since onboarding a newly acquired subsidiary is exactly the kind of recurring, well-defined workflow skills are built for.

**Workflow pattern for this specific project:**
1. **Explore → plan → implement** for anything touching consolidation or COA logic — these are exactly the "modifies multiple files, high cost of getting wrong" cases where plan mode earns its overhead.
2. **Give Claude a check it can run**: wire dbt tests and Pandera schemas in from day one so that "the pipeline works" has a concrete, automatable definition (`dbt build && dbt test` passing) rather than being eyeballed — this is what lets Claude Code iterate on a broken transformation autonomously instead of needing a human to notice each failure.
3. **Non-interactive mode (`claude -p`) in CI**: run a review pass on every PR touching `/dbt_project/models/gold` or `/silver`, since these are the highest-blast-radius changes (a bad Gold model reaches a business owner's dashboard directly).
4. **Subagents for investigation, not just implementation**: when a number looks wrong in a dashboard, "use a subagent to trace fct_balance_sheet.total_assets for entity X, period Y back through Gold → Silver → Bronze and report where it diverges from source" is a strong debugging pattern that keeps the main session's context clean.
5. **Adversarial review before anything ships to the Gold layer**: a fresh-context subagent reviewing a diff against `Assets = Liabilities + Equity` and elimination correctness catches the class of error that's easy to introduce and expensive to miss in a financial system.

---

## 9. Implementation Roadmap

**Phase 0 — Foundations (2–3 weeks).** Stand up Dagster, DuckDB/dbt-core, MinIO, git repo with the structure above; define `dim_entity`, `dim_account_group_standard`, and the COA mapping table for 1–2 pilot subsidiaries.

**Phase 1 — Single-entity, single-source MVP (3–4 weeks).** One API connector + one Excel/CSV ingestion path → Bronze → Silver (with double-entry validation) → Gold (unconsolidated balance sheet + P&L for one subsidiary) → a first Streamlit dashboard. This proves the full vertical slice and the Claude Code workflow before scaling out.

**Phase 2 — Multi-subsidiary consolidation (4–6 weeks).** Onboard remaining subsidiaries, build out FX translation, intercompany elimination rules, ownership/minority-interest handling, and the consolidated marts. This is the phase most worth budgeting extra review time for.

**Phase 3 — Governance & self-serve (3–4 weeks).** Row-level security, OpenMetadata catalog, Superset/Metabase for finance self-serve, alerting on data quality failures and late file arrivals.

**Phase 4 — Insights layer (ongoing).** KPI marts (liquidity, working capital, DSO/DPO, entity benchmarking), trend/variance dashboards, and — if wanted later — a natural-language query layer over Gold tables (a good fit for a small Claude Agent SDK–based application once the Gold schema is stable).

---

## 10. Key Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Inconsistent/free-form Excel uploads from subsidiaries break ingestion silently | Strict template validation with Pandera at the ingestion boundary; quarantine + alert, never silently drop rows. |
| Chart-of-accounts drift across subsidiaries produces a wrong consolidated number | Governed, effective-dated mapping table; hard-fail on unmapped accounts; Claude-assisted first-pass mapping always human-approved. |
| Single-node DuckDB/dbt setup doesn't scale as more subsidiaries/history are added | Architecture is designed to swap the execution engine (DuckDB → Spark/Trino) without changing the dbt model layer or the Bronze/Silver/Gold contract — revisit only when volume actually demands it. |
| Financial data sensitivity vs. broad dashboard access | Row-level security by entity from day one; audit logging on Gold-table access; secrets never in plaintext. |
| "It matched last month" regressions in consolidation logic | Adversarial subagent review gate in CI on any change to `/silver` or `/gold` consolidation models; balance-sheet-equation test on every run. |

---

## Sources consulted

- [Claude Code best practices](https://code.claude.com/docs/en/best-practices)
- [awesome-claude-code-subagents — data-engineer](https://github.com/VoltAgent/awesome-claude-code-subagents/blob/main/categories/05-data-ai/data-engineer.md)
- [Medallion Architecture Guide (2026)](https://datadef.io/guides/en/medallion-architecture)
- [The Medallion Architecture Explained: Bronze, Silver, Gold with dbt](https://modeldock.run/blog/medallion-architecture-dbt)
- [Data Quality Frameworks: Great Expectations vs dbt Tests vs Soda Core](https://pipecode.ai/blogs/data-quality-frameworks-great-expectations-vs-dbt-tests-vs-soda-core)
- [Data validation in Python: Pandera and Great Expectations](https://endjin.com/blog/a-look-into-pandera-and-great-expectations-for-data-validation)
- [The Data Warehouse Toolkit — General Ledger / Accounting chapter](https://subscription.packtpub.com/book/data/9781118530801/14/ch14lvl1sec66/general-ledger-data)
- [Strategic Chart of Accounts Design — Deloitte](https://www.deloitte.com/us/en/services/consulting/articles/chart-of-accounts-design.html)
