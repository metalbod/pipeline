-- fct_journal_line's COA-mapping join is INNER on purpose: an unmapped local account must fail
-- the build loudly, not silently vanish (ARCHITECTURE.md §6.1). If the row counts diverge, some
-- stg_journal_lines row didn't survive the coa_mapping/dim_account_group_standard/dim_period
-- joins -- most likely an account with no approved mapping yet.
with stg_count as (
    select count(*) as cnt from {{ ref('stg_journal_lines') }}
),
fct_count as (
    select count(*) as cnt from {{ ref('fct_journal_line') }}
)

select stg_count.cnt as stg_rows, fct_count.cnt as fct_rows
from stg_count, fct_count
where stg_count.cnt != fct_count.cnt
