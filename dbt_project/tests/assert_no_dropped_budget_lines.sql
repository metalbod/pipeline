-- stg_budget's coa_mapping/dim_account_group_standard joins are INNER on purpose (same
-- "fail loudly on an unmapped account" reasoning as fct_journal_line.sql), but unlike
-- fct_journal_line it had no drop-detection test of its own -- caught in finance-reviewer pass.
-- If the row counts diverge, some budget line's account_code has no active coa_mapping row.
with deduped_bronze as (
    select distinct _source_system, entity_id, account_code, period
    from {{ ref('bronze_budget') }}
),
bronze_count as (
    select count(*) as cnt from deduped_bronze
),
stg_count as (
    select count(*) as cnt from {{ ref('stg_budget') }}
)

select bronze_count.cnt as bronze_rows, stg_count.cnt as stg_rows
from bronze_count, stg_count
where bronze_count.cnt != stg_count.cnt
