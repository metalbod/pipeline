# CFO Financial Health Dashboard — Config

Single source of truth for the Claude-generated executive dashboard: every metric's
definition, format, chart type, and the exact SQL that pulls it from the Gold layer
(`main_gold`/`main_silver` schemas in `storage/warehouse.duckdb`). `generate.py` reads
this file, runs each `live`/`placeholder-empty` query, and renders one self-contained
HTML file. Nothing here is a separate access-control system — see "Roles & access scope"
below.

To change what's on the dashboard: edit this file, then re-run
`python dashboards/claude_html/generate.py`. No other file needs to change for a
metric tweak (wording, threshold, chart type). Only `generate.py` itself needs a change
if you introduce a new `Chart:` type it doesn't know how to render yet.

## Roles & access scope

The dashboard does **not** define its own roles — it reads the same
`main_silver.user_entity_access` + `main_silver.dim_entity` tables that already drive
Superset's row-level security (see `ops/superset/setup_superset.py`). One view is
generated per distinct `(role, entity_id)` row in `user_entity_access`:

- `GROUP_FINANCE_OWNER` (blank `entity_id`) → sees every row, including rows tagged
  `entity_id = 'GROUP'` (consolidated/group-level figures that aren't real entities).
- `REGIONAL_CONTROLLER` (a specific `entity_id`) → sees only rows whose `entity_id`
  is that controller's entity or a descendant of it in `dim_entity.parent_entity_id`.
  Never sees `'GROUP'`-tagged rows.

**Every `live`/`placeholder-empty` query below must return an `entity_id` column** —
a real `dim_entity.entity_id`, or the literal string `'GROUP'` for figures that are
inherently group-wide (consolidated totals, market data). That single column is what
the page's role switcher filters on.

Reminder from the plan this config implements: this is one shared HTML file with a
**client-side** role switcher, not per-session enforcement. Every viewer's browser
receives every entity's data regardless of which view they pick — the switcher changes
what's displayed, not what's downloaded. Treat "where this file is hosted / who it's
sent to" as the actual control point.

## Metric block format

Each metric is a `### Heading` under a `## Section` with these fields, then an optional
` ```sql ` block:

- `Status`: `live` (query runs, renders as a real chart) · `placeholder-empty` (query
  runs — kept for freshness/row-count transparency — but renders as an explicit
  "no data yet" card because the result is empty or would be misleading) ·
  `placeholder-no-source` (no query — nothing in the pipeline sources this yet)
- `Format`: `currency` · `percent` · `days` · `ratio` · `count` · `table`
- `Chart`: `bar` (categorical/grouped bar, also used for time series — see note below)
  · `stat` (KPI tiles, one per row) · `table` (raw rows) · `none` (placeholders only)
- `Definition`: one sentence, plain language
- `Note`: caveats — data cadence, why a metric is a placeholder, etc. Shown on the card.
- `XField` (bar charts only, optional): column to use as the x-axis category. Defaults
  to `entity_name` (one bar per entity) when omitted.
- `SeriesField` (bar charts only, optional): column to color/group bars by within each
  `XField` category (e.g. multiple entities sharing the same date). Omit for a plain
  one-bar-per-category chart with no legend.
- `LabelField` (stat charts only): comma-separated columns concatenated to form each
  tile's label.

Why `bar` and not `line` for daily trends: ingestion here is monthly-batch (Xero syncs
+ month-end file uploads), so a "daily" series is real days with real gaps between
batch-load dates, not a continuous signal — connecting them with a line would imply
continuity that isn't there. Bars per batch-load day are the honest rendering.

---

## 1. Cash & Liquidity Position (The Most Critical)

A CFO's primary rule is to ensure the organization never runs out of money.

### Net Cash Balance

- Status: live
- Format: currency
- Chart: bar
- Definition: Consolidated cash balance (GS-1000, Cash and Bank) by entity, plus the
  group-consolidated total.
- Note: "Consolidated" here means summed across subsidiaries in the Gold layer, not
  real-time — it reflects the most recent closed batch load, not a live bank feed.
  There's no per-bank-account dimension in the schema yet, only the GL cash balance.

```sql
select entity_id, entity_name, fiscal_year, fiscal_period, period_end, amount as value,
       functional_currency as currency
from main_gold.rpt_balance_sheet
where group_standard_code = 'GS-1000'

union all

select 'GROUP' as entity_id, 'Group Consolidated' as entity_name,
       fiscal_year, fiscal_period, period_end, amount as value,
       'MYR' as currency
from main_gold.rpt_balance_sheet_consolidated
where group_standard_code = 'GS-1000'

order by entity_id, fiscal_year, fiscal_period
```

### Daily Cash Burn Rate / Run Rate

- Status: live
- Format: currency
- Chart: bar
- XField: posted_at
- SeriesField: entity_name
- Definition: Net movement in cash & equivalents (GS-1000) per day, by entity —
  debits (cash in) minus credits (cash out).
- Note: Batch-cadence data, not a live feed — see the format note above. Days without
  a posted journal line simply don't appear rather than showing as zero.

```sql
select
    j.entity_id,
    e.entity_name,
    j.posted_at,
    sum(j.debit_amount - j.credit_amount) as value,
    e.functional_currency as currency
from main_silver.fct_journal_line j
join main_silver.dim_account_group_standard a on a.account_key = j.account_key
join main_silver.dim_entity e on e.entity_id = j.entity_id
where a.group_standard_code = 'GS-1000'
group by 1, 2, 3, 5
order by 1, 3
```

### Available Liquidity

- Status: placeholder-no-source
- Format: currency
- Chart: none
- Definition: Total liquidity capacity — cash-on-hand plus instantly accessible credit
  lines or revolving facilities.
- Note: Nothing in the pipeline ingests credit facility limits or drawn/undrawn amounts
  — `debt_covenants` only tracks covenant thresholds, not facility size. Needs a new
  Silver source (e.g. a facility ledger) before this can be built.

---

## 2. Working Capital Status

Tracks how efficiently the company's short-term assets and liabilities are circulating.

### Days Sales Outstanding (DSO)

- Status: live
- Format: days
- Chart: bar
- Definition: Average days to collect receivables — a rapid view of collections
  efficiency; a sudden spike indicates potential customer defaults or credit-policy
  issues.
- Note: `dso_days_true` (invoice-weighted, from AR aging) is null until enough aging
  history accumulates — the chart falls back to `dso_days_approx` (balance-based) in
  the meantime and labels which one it's showing.

```sql
select entity_id, entity_name, fiscal_year, fiscal_period, period_end,
       dso_days_approx, dso_days_true,
       coalesce(dso_days_true, dso_days_approx) as value
from main_gold.rpt_dso_dpo
order by entity_id, fiscal_year, fiscal_period
```

### Days Payable Outstanding (DPO)

- Status: live
- Format: days
- Chart: bar
- Definition: Average days to pay suppliers — monitors whether payment terms are being
  optimized without straining vendor relationships.
- Note: Same approx/true fallback as DSO above.

```sql
select entity_id, entity_name, fiscal_year, fiscal_period, period_end,
       dpo_days_approx, dpo_days_true,
       coalesce(dpo_days_true, dpo_days_approx) as value
from main_gold.rpt_dso_dpo
order by entity_id, fiscal_year, fiscal_period
```

### Top Overdue Receivables

- Status: live
- Format: table
- Chart: table
- Definition: Open AR invoices past due, ranked by amount outstanding — a high-level
  watchlist of large corporate accounts that are past due.

```sql
select entity_id, invoice_id, contact_name, invoice_date, due_date,
       days_overdue, aging_bucket, amount_outstanding, currency, overdue_rank
from main_gold.rpt_top_overdue_receivables
order by entity_id, overdue_rank
```

---

## 3. Revenue & Forward-Looking Pipeline

While backward-looking figures are managed monthly, forward-looking metrics flag
top-line issues early.

### Daily / Week-to-Date Revenue

- Status: live
- Format: currency
- Chart: bar
- XField: posted_at
- SeriesField: entity_name
- Definition: Revenue (GS-4000 and other REVENUE-type accounts) recognized per day, by
  entity.
- Note: Shown as a trend only, not "contrasted against the month's target" as originally
  scoped — `rpt_budget_variance` is monthly-grain, so a day/week-to-date-vs-prorated-target
  comparison would require inventing a proration assumption nothing else in the codebase
  makes. See Major Budget Variances below for the real (monthly) budget comparison.

```sql
select
    j.entity_id,
    e.entity_name,
    j.posted_at,
    sum(j.credit_amount - j.debit_amount) as value,
    e.functional_currency as currency
from main_silver.fct_journal_line j
join main_silver.dim_account_group_standard a on a.account_key = j.account_key
join main_silver.dim_entity e on e.entity_id = j.entity_id
where a.account_type = 'REVENUE'
group by 1, 2, 3, 5
order by 1, 3
```

### Sales Pipeline Velocity

- Status: live
- Format: currency
- Chart: bar
- XField: pipeline_stage
- SeriesField: entity_name
- Definition: Total contract value (TCV) and deal count by pipeline stage, per entity,
  with the period-over-period TCV change so a slowdown is visible directly.
- Note: Finance-entered pipeline estimate (monthly file upload), not live CRM data.

```sql
select entity_id, entity_name, fiscal_year, fiscal_period, period_end,
       pipeline_stage, deal_count, total_contract_value as value, currency,
       tcv_change_from_prior_period
from main_gold.rpt_sales_pipeline_velocity
order by entity_id, period_start, pipeline_stage
```

---

## 4. Operational Efficiencies & Budget Variances

CFOs want to see macro deviations from expected parameters without digging into
sub-ledgers.

### Gross Margin % Trends

- Status: placeholder-empty
- Format: percent
- Chart: none
- Definition: (Revenue − COGS) / Revenue, by entity and period — catches supply-chain
  price increases or competitive pricing pressure early.
- Note: The model runs but reads a flat 100% margin today because nothing has ever
  posted to the COGS account (GS-5100) in either source system — that's an absence of
  input data, not a bug. Showing 100% as a real number would be actively misleading, so
  this renders as a placeholder until Finance posts real COGS entries.

```sql
select entity_id, entity_name, fiscal_year, fiscal_period, period_end,
       revenue, cogs, gross_margin_pct as value
from main_gold.rpt_gross_margin
order by entity_id, fiscal_year, fiscal_period
```

### Major Budget Variances

- Status: live
- Format: percent
- Chart: bar
- XField: account_name
- SeriesField: entity_name
- Definition: Budgeted vs. actual by entity/account/period; flagged as a major variance
  when more than 15% off budget (a first-cut threshold, not an audited policy).

```sql
select b.entity_id, b.period, b.group_standard_code, b.account_name, b.account_type,
       b.budgeted_amount, b.actual_amount, b.variance_amount,
       b.variance_pct as value, b.is_major_variance,
       e.functional_currency as currency
from main_gold.rpt_budget_variance b
join main_silver.dim_entity e on e.entity_id = b.entity_id
order by b.entity_id, b.period, b.account_name
```

---

## 5. Strategic Risk Watchlist

Depending on the sector, external market triggers dictate capital safety.

### Macro Market Volatility — FX Exposure

- Status: live
- Format: ratio
- Chart: stat
- LabelField: currency_code, rate_type
- Definition: Current FX rate to group reporting currency (MYR) for each subsidiary's
  functional currency, at period-end and period-average.
- Note: Only one fiscal period (2026-07) has FX rates loaded so far, so this renders as
  current-rate tiles rather than a volatility trend — it becomes a real trend
  automatically once a second period's rates are loaded. The SGD rate is also flagged
  as a placeholder pending a Finance-provided rate (see `seed_dim_fx_rate.csv`).

```sql
select 'GROUP' as entity_id, currency_code, fiscal_year, fiscal_period, rate_type,
       rate_to_group_currency as value, source
from main_silver.dim_fx_rate
order by currency_code, fiscal_year, fiscal_period, rate_type
```

### Macro Market Volatility — Interest Rates & Commodities

- Status: placeholder-no-source
- Format: ratio
- Chart: none
- Definition: Exposure to shifting interest rates or commodity price fluctuations
  affecting raw input costs.
- Note: No market-data connector exists in this platform — would need a new external
  data source (e.g. a rates/commodities feed), genuinely out of scope for the pipeline
  as built today.

### Regulatory Capital / Covenants

- Status: placeholder-empty
- Format: percent
- Chart: none
- Definition: Actual debt-to-equity ratio vs. the covenant threshold, headroom %, and a
  breach flag, per debt facility.
- Note: The model runs but `debt_covenants` has zero rows — no real debt facility has
  been seeded yet. Renders empty until Finance provides real facility/covenant terms.

```sql
select entity_id, facility_name, covenant_type, threshold_value,
       fiscal_year, fiscal_period, external_debt, total_equity,
       actual_debt_to_equity_ratio as value, headroom_pct, is_breached
from main_gold.rpt_covenant_headroom
order by entity_id, fiscal_year, fiscal_period
```
