-- fct_journal_line's COA-mapping, dim_account_group_standard, dim_period, and dim_fx_rate joins
-- are all INNER on purpose: an unmapped local account, or a currency/period with no approved FX
-- rate, must fail the build loudly, not silently vanish (ARCHITECTURE.md §6.1). If the row
-- counts diverge, some stg_journal_lines row didn't survive one of those joins -- most likely an
-- account with no approved mapping, or a missing FX rate for that currency/period.
--
-- Renamed from assert_no_unmapped_accounts.sql (Phase 1) -- Phase 2's dim_fx_rate join means
-- this check's scope is now broader than COA mapping alone, though the row-count-parity
-- mechanism itself is unchanged and already caught either failure mode for free.
with stg_count as (
    select count(*) as cnt from {{ ref('stg_journal_lines') }}
),
fct_count as (
    select count(*) as cnt from {{ ref('fct_journal_line') }}
)

select stg_count.cnt as stg_rows, fct_count.cnt as fct_rows
from stg_count, fct_count
where stg_count.cnt != fct_count.cnt
