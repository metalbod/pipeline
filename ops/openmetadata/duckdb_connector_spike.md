# DuckDB connector spike — result: not viable, not attempted further

Per the Phase 3 plan, `luatnc87/openmetadata-duckdb-connector` (the unofficial community DuckDB
connector) was spiked before deciding whether to build around it. **Verdict: incompatible with
our OpenMetadata version, and not a small gap** — the dbt-sourced catalog (models, lineage, test
results, docs) is the reliable path and stands on its own; this connector isn't wired into the
Dagster asset or docker-compose.

## What was checked

- The connector's own Dockerfile explicitly targets `openmetadata/ingestion:1.1.2`. We're running
  `1.12.0` — 11+ minor versions apart.
- No PyPI package; installation is "clone the repo, `pip install --no-deps .`" — no version
  pinning or compatibility declaration at all.
- Only 6 commits in the repo's history, no releases/tags — minimally maintained.
- Directly tested: cloned the repo and imported its core dependencies against our installed
  `openmetadata-ingestion` 1.12.14.2 package.
  - `from metadata.ingestion.api.source import Source, SourceStatus, InvalidSourceException`
    **fails** — `ModuleNotFoundError: No module named 'metadata.ingestion.api.source'`.
  - The entire module is gone in 1.12.x, not renamed: `metadata.ingestion.api` now exposes
    `closeable, common, delete, models, parser, status, step, steps, topology_runner` -- a
    different (Step/Topology-based) source architecture replaced the old `Source` base class
    entirely between 1.1.2 and 1.12.x.

## Why this isn't "just a patch"

The connector's `DuckDBConnector` class inherits from the old `Source` base class and implements
its interface (`prepare()`, `next_record()`, `get_status()`, etc.). Making it work against 1.12.x
means re-implementing it against the new Step/Topology framework, not fixing an import path —
effectively a rewrite of the connector's integration points, informed by 11+ versions of internal
API changes we haven't audited. That's out of proportion to what this connector would add on top
of the dbt-sourced catalog (live table browsing/sampling — a nice-to-have, not core value).

## What you get instead

The dbt ingestion path (`ops/openmetadata/dbt_ingestion.yaml`, wired into Dagster via
`openmetadata_dbt_catalog_sync`) is officially supported and unaffected by this — it covers
models, lineage, docs, and test results for every Bronze/Silver/Gold table, which is the bulk of
what a catalog is for here.

## If you want live DuckDB browsing later

Options, roughly in order of effort: (a) write a minimal custom connector against the *current*
Step/Topology API directly (a real but bounded project, informed by OpenMetadata's current
built-in connectors as reference implementations); (b) wait for an official or better-maintained
community connector; (c) accept the dbt-sourced catalog as sufficient, since it already covers
schema/lineage/tests/docs — the main thing live browsing adds is ad hoc data sampling.
